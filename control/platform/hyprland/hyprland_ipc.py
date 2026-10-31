"""
Native Arch Linux Hyprland Direct UNIX Domain Socket IPC Engine.
Provides sub-millisecond query and dispatch execution via:
  $XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket.sock (Request/Response)
  $XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock (Real-time Event Stream)

Includes automatic fallback to hyprctl subprocess if socket connection is unavailable.
"""

import os
import sys
import json
import socket
import subprocess
import threading
import time
from typing import Optional, Dict, Any, List, Callable


class HyprlandIPC:
    """
    Direct UNIX domain socket client for Hyprland compositor.
    """

    def __init__(self, signature: Optional[str] = None, runtime_dir: Optional[str] = None):
        self.signature = signature or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        self.runtime_dir = runtime_dir or os.environ.get(
            "XDG_RUNTIME_DIR",
            f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else "/tmp"
        )
        self._lock = threading.Lock()
        self._event_thread: Optional[threading.Thread] = None
        self._event_running = False
        self._event_listeners: List[Callable[[str, str], None]] = []
        self._active_window_cache: Optional[Dict[str, Any]] = None
        self._clients_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: float = 0.0

    @property
    def command_socket_path(self) -> str:
        """Path to request-response command socket."""
        sig = self.signature or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        return os.path.join(self.runtime_dir, "hypr", sig, ".socket.sock")

    @property
    def event_socket_path(self) -> str:
        """Path to real-time event streaming socket."""
        sig = self.signature or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        return os.path.join(self.runtime_dir, "hypr", sig, ".socket2.sock")

    def is_available(self) -> bool:
        """Checks if Hyprland IPC is available via socket or hyprctl."""
        if hasattr(socket, "AF_UNIX") and os.path.exists(self.command_socket_path):
            return True
        # Check hyprctl fallback
        try:
            res = subprocess.run(["hyprctl", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            return res.returncode == 0
        except Exception:
            return False

    def send_raw_command(self, cmd: str, timeout: float = 2.0) -> str:
        """
        Sends raw string command to Hyprland .socket.sock and reads response.
        Falls back to hyprctl if socket is not available.
        """
        sock_path = self.command_socket_path
        if hasattr(socket, "AF_UNIX") and os.path.exists(sock_path):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect(sock_path)
                    s.sendall(cmd.encode("utf-8"))
                    # Shutdown write end so Hyprland knows the request is complete
                    try:
                        s.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    data = []
                    while True:
                        chunk = s.recv(8192)
                        if not chunk:
                            break
                        data.append(chunk)
                    return b"".join(data).decode("utf-8", errors="replace")
            except Exception as e:
                sys.stderr.write(f"[HyprlandIPC] Socket communication error ({sock_path}): {e}. Falling back to hyprctl.\n")

        # Fallback to hyprctl
        return self._send_hyprctl(cmd)

    def _send_hyprctl(self, cmd: str) -> str:
        """Fallback command execution via hyprctl subprocess."""
        try:
            tokens = cmd.strip().split()
            if not tokens:
                return ""
            if tokens[0].startswith("j/"):
                subcmd = tokens[0][2:]
                args = ["hyprctl", "-j", subcmd] + tokens[1:]
            elif tokens[0] == "dispatch":
                args = ["hyprctl", "dispatch"] + tokens[1:]
            else:
                args = ["hyprctl"] + tokens

            proc = subprocess.run(args, capture_output=True, text=True, timeout=3.0)
            return proc.stdout
        except Exception as e:
            sys.stderr.write(f"[HyprlandIPC] hyprctl error for '{cmd}': {e}\n")
            return ""

    def query_json(self, query: str) -> Any:
        """
        Executes a JSON query command (e.g. 'clients', 'activewindow', 'monitors', 'workspaces')
        and returns parsed JSON data.
        """
        cmd = f"j/{query}" if not query.startswith("j/") else query
        raw = self.send_raw_command(cmd)
        if not raw.strip():
            return [] if query in ["clients", "monitors", "workspaces", "j/clients", "j/monitors", "j/workspaces"] else {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"[HyprlandIPC] Failed to decode JSON for '{cmd}': {exc}\nRaw: {raw[:200]}\n")
            return [] if "clients" in query or "monitors" in query or "workspaces" in query else {}

    def get_clients(self) -> List[Dict[str, Any]]:
        """Returns list of all active window clients."""
        return self.query_json("clients")

    def get_active_window(self) -> Optional[Dict[str, Any]]:
        """Returns currently focused active window info."""
        res = self.query_json("activewindow")
        if isinstance(res, dict) and res.get("address"):
            return res
        return None

    def get_monitors(self) -> List[Dict[str, Any]]:
        """Returns list of active monitors with geometry and scaling."""
        return self.query_json("monitors")

    def get_workspaces(self) -> List[Dict[str, Any]]:
        """Returns list of workspaces."""
        return self.query_json("workspaces")

    def get_active_workspace(self) -> Dict[str, Any]:
        """Returns currently active workspace."""
        return self.query_json("activeworkspace")

    def dispatch(self, dispatcher: str, *args: str) -> str:
        """
        Executes a Hyprland dispatcher command.
        Example: dispatch('focuswindow', 'address:0x1234')
                 dispatch('movecursor', '100', '200')
                 dispatch('exec', 'kitty')
        """
        arg_str = " ".join(args)
        cmd = f"dispatch {dispatcher} {arg_str}".strip()
        resp = self.send_raw_command(cmd)
        return resp.strip()

    def start_event_listener(self):
        """Starts real-time background listener on .socket2.sock."""
        if self._event_running or not hasattr(socket, "AF_UNIX"):
            return
        sock_path = self.event_socket_path
        if not os.path.exists(sock_path):
            return

        self._event_running = True
        self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._event_thread.start()

    def stop_event_listener(self):
        """Stops the background event listener."""
        self._event_running = False

    def add_event_listener(self, callback: Callable[[str, str], None]):
        """Registers a callback for Hyprland events: callback(event_name, event_data)."""
        self._event_listeners.append(callback)

    def _event_loop(self):
        sock_path = self.event_socket_path
        while self._event_running:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(5.0)
                    s.connect(sock_path)
                    buffer = ""
                    while self._event_running:
                        try:
                            data = s.recv(4096)
                            if not data:
                                break
                            buffer += data.decode("utf-8", errors="replace")
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if ">>" in line:
                                    event, payload = line.split(">>", 1)
                                    for listener in self._event_listeners:
                                        try:
                                            listener(event, payload)
                                        except Exception:
                                            pass
                        except socket.timeout:
                            continue
            except Exception:
                time.sleep(1.0)


# Default singleton instance
default_hyprland_ipc = HyprlandIPC()
HyprlandIPCClient = HyprlandIPC
