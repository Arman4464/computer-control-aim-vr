"""
FreeDesktop Notification Manager for Arch Linux Hyprland.
Dispatches native desktop notifications via notify-send and D-Bus.
"""

import sys
import shutil
import subprocess
from typing import Optional, Dict, Any

from control.platform.base import BaseNotifier


class LinuxNotifier(BaseNotifier):
    """
    FreeDesktop notification dispatcher using notify-send.
    """

    def send_notification(
        self,
        title: str,
        message: str,
        app_id: Optional[str] = None,
        sound: bool = True
    ) -> Dict[str, Any]:
        """
        Dispatches a notification to the FreeDesktop notification daemon (mako, dunst, swaync).
        """
        if not title and not message:
            return {"status": "error", "message": "Title or message must be provided."}

        clean_title = title or "AIM-VR Notification"
        clean_msg = message or ""
        app_name = app_id or "AIM-VR"

        if shutil.which("notify-send"):
            cmd = [
                "notify-send",
                "-a", app_name,
                "-i", "dialog-information",
                clean_title,
                clean_msg,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
                if proc.returncode == 0:
                    # Optional sound via canberra-gtk-play or paplay
                    if sound and shutil.which("canberra-gtk-play"):
                        try:
                            subprocess.Popen(["canberra-gtk-play", "-i", "message"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except Exception:
                            pass
                    return {"status": "success", "message": f"Notification '{clean_title}' dispatched successfully."}
                else:
                    return {"status": "error", "message": f"notify-send failed: {proc.stderr.strip()}"}
            except Exception as e:
                return {"status": "error", "message": f"Failed to run notify-send: {str(e)}"}

        sys.stderr.write(f"[LinuxNotifier] notify-send not found. Title: {clean_title}, Body: {clean_msg}\n")
        return {"status": "simulated", "message": f"Notification '{clean_title}' logged (notify-send not installed)."}


# Default singleton instance
default_linux_notifier = LinuxNotifier()
