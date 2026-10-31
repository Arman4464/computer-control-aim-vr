"""
Native Linux Application Launcher for Hyprland (Arch Linux).
Launches applications via 'hyprctl dispatch exec' ensuring correct Wayland session inheritance,
resolves Linux desktop application binaries, and opens URLs/documents via xdg-open.
"""

import os
import sys
import time
import shutil
import subprocess
from typing import Optional, Dict, Any, List

from control.platform.base import BaseAppLauncher
from control.platform.hyprland.hyprland_ipc import HyprlandIPC, default_hyprland_ipc

KNOWN_LINUX_APPS = {
    "terminal": ["kitty", "alacritty", "foot", "wezterm", "gnome-terminal", "konsole", "xterm"],
    "kitty": ["kitty"],
    "alacritty": ["alacritty"],
    "foot": ["foot"],
    "wezterm": ["wezterm"],
    "browser": ["firefox", "google-chrome-stable", "chromium", "brave", "zen-browser"],
    "firefox": ["firefox"],
    "chrome": ["google-chrome-stable", "google-chrome", "chromium"],
    "chromium": ["chromium"],
    "brave": ["brave", "brave-browser"],
    "code": ["code", "codium", "code-oss"],
    "vscode": ["code", "codium", "code-oss"],
    "editor": ["nvim", "vim", "gedit", "kate", "nano"],
    "file_manager": ["thunar", "nautilus", "dolphin", "pcmanfm"],
    "files": ["thunar", "nautilus", "dolphin", "pcmanfm"],
    "dolphin": ["dolphin"],
    "thunar": ["thunar"],
    "nautilus": ["nautilus"],
    "audio": ["pavucontrol"],
    "pavucontrol": ["pavucontrol"],
    "media": ["mpv", "vlc"],
    "mpv": ["mpv"],
    "vlc": ["vlc"],
    "discord": ["discord", "vesktop", "webcord"],
    "obs": ["obs"],
}


class LinuxAppLauncher(BaseAppLauncher):
    """
    Arch Linux Hyprland Application Launcher.
    """

    def __init__(self, ipc: Optional[HyprlandIPC] = None, window_manager: Optional[Any] = None):
        self.ipc = ipc or default_hyprland_ipc
        self._window_manager = window_manager

    def _get_window_manager(self):
        if self._window_manager is not None:
            return self._window_manager
        try:
            from control.platform import get_platform_driver
            driver = get_platform_driver()
            return getattr(driver, "window_manager", None)
        except Exception:
            return None

    def resolve_binary(self, name: str) -> Optional[str]:
        """Resolves application name or alias to executable on system PATH."""
        clean = name.lower().strip()

        # Check alias table first
        if clean in KNOWN_LINUX_APPS:
            for candidate in KNOWN_LINUX_APPS[clean]:
                path = shutil.which(candidate)
                if path:
                    return path

        # Direct which lookup
        path = shutil.which(name)
        if path:
            return path

        # Check /usr/bin, /usr/local/bin, ~/.local/bin
        common_dirs = [
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
        ]
        for d in common_dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p

        return None

    def launch_app(self, name: str, args: Optional[str] = None, timeout: float = 3.5) -> Dict[str, Any]:
        """
        Launches application using Hyprland 'exec' dispatcher or subprocess.Popen,
        then polls up to timeout (default 3.5s) for the top-level application window
        to appear to prevent race conditions in fast subsequent DAG actions.
        """
        bin_path = self.resolve_binary(name)
        cmd_str = bin_path if bin_path else name
        if args:
            cmd_str += f" {args}"

        method = None
        pid = None

        # 1. Primary: hyprctl dispatch exec <command>
        try:
            resp = self.ipc.dispatch("exec", cmd_str)
            if "ok" in resp.lower() or resp == "":
                method = "hyprland_exec"
        except Exception as e:
            sys.stderr.write(f"[LinuxAppLauncher] hyprland exec failed: {e}. Falling back to Popen.\n")

        # 2. Fallback: subprocess.Popen
        if method is None:
            try:
                full_cmd = [bin_path or name]
                if args:
                    full_cmd.extend(args.split())
                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                method = "subprocess"
                pid = proc.pid
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to launch application '{name}': {str(e)}",
                }

        # 3. Window readiness polling (up to timeout, matching Windows launch_application)
        matched_win = None
        search_term = name.lower().strip()
        start_time = time.time()
        wm = self._get_window_manager()

        while time.time() - start_time < timeout:
            time.sleep(0.15)
            if wm:
                try:
                    # Check window list
                    windows = wm.list_windows()
                    for w in windows:
                        t = (w.get("title") or "").lower()
                        c = (w.get("class") or "").lower()
                        ic = (w.get("initial_class") or "").lower()
                        if search_term in t or search_term in c or search_term in ic:
                            matched_win = w
                            break
                        if pid and w.get("pid") == pid:
                            matched_win = w
                            break
                    if matched_win:
                        break

                    # Check active window
                    active = wm.get_active_window()
                    if active:
                        t = (active.get("title") or "").lower()
                        c = (active.get("class") or "").lower()
                        if search_term in t or search_term in c:
                            matched_win = active
                            break
                        if pid and active.get("pid") == pid:
                            matched_win = active
                            break
                except Exception:
                    pass
            if matched_win:
                break

        res: Dict[str, Any] = {
            "status": "launched",
            "app": name,
            "name": name,
            "command": cmd_str,
            "method": method,
        }
        if pid:
            res["pid"] = pid

        if matched_win:
            try:
                if wm:
                    wm.focus_window(matched_win.get("hwnd") or matched_win.get("address"))
            except Exception:
                pass
            res["window"] = {
                "title": matched_win.get("title", ""),
                "hwnd": matched_win.get("hwnd") or matched_win.get("address", ""),
                "address": matched_win.get("address", ""),
                "bounds": matched_win.get("bounds", [0, 0, 0, 0]),
            }
        else:
            res["note"] = f"Process started; window did not register within {timeout}s or runs without GUI window."

        return res

    def open_file_or_url(self, target: str) -> Dict[str, Any]:
        """
        Opens file or URL via xdg-open.
        """
        if shutil.which("xdg-open"):
            try:
                proc = subprocess.Popen(
                    ["xdg-open", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {"status": "opened", "target": target, "method": "xdg-open"}
            except Exception as e:
                return {"status": "error", "message": f"xdg-open error for '{target}': {str(e)}"}

        if target.startswith(("http://", "https://")):
            browser = self.resolve_binary("browser")
            if browser:
                try:
                    subprocess.Popen([browser, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    return {"status": "opened", "target": target, "method": f"browser_fallback:{browser}"}
                except Exception:
                    pass

        return {"status": "error", "message": "xdg-open not available on system."}

    # Backward-compatible alias
    launch = launch_app


# Default singleton instance
default_linux_app_launcher = LinuxAppLauncher()
