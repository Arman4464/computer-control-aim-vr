"""
Native Linux Application Launcher for Hyprland (Arch Linux).
Launches applications via 'hyprctl dispatch exec' ensuring correct Wayland session inheritance,
resolves Linux desktop application binaries, and opens URLs/documents via xdg-open.
"""

import os
import sys
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

    def __init__(self, ipc: Optional[HyprlandIPC] = None):
        self.ipc = ipc or default_hyprland_ipc

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

    def launch_app(self, name: str, args: Optional[str] = None) -> Dict[str, Any]:
        """
        Launches application using Hyprland 'exec' dispatcher or subprocess.Popen.
        """
        bin_path = self.resolve_binary(name)
        cmd_str = bin_path if bin_path else name
        if args:
            cmd_str += f" {args}"

        # 1. Primary: hyprctl dispatch exec <command>
        try:
            resp = self.ipc.dispatch("exec", cmd_str)
            if "ok" in resp.lower() or resp == "":
                return {
                    "status": "launched",
                    "app": name,
                    "command": cmd_str,
                    "method": "hyprland_exec",
                }
        except Exception as e:
            sys.stderr.write(f"[LinuxAppLauncher] hyprland exec failed: {e}. Falling back to Popen.\n")

        # 2. Fallback: subprocess.Popen
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
            return {
                "status": "launched",
                "app": name,
                "pid": proc.pid,
                "command": cmd_str,
                "method": "subprocess",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to launch application '{name}': {str(e)}",
            }

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
