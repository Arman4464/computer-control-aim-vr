"""
Hyprland Platform Driver (Arch Linux Native Implementation).
Wires together low-level /dev/uinput input injection, UNIX domain socket IPC,
grim screencopy, wl-clipboard, FreeDesktop notifications, and native app launching.
"""

import os
import sys
import shutil
from typing import Optional, Tuple

from control.platform.base import BasePlatformDriver, BaseSafety
from control.platform.hyprland.hyprland_ipc import HyprlandIPC, default_hyprland_ipc
from control.platform.hyprland.uinput_engine import UInputEngine
from control.platform.hyprland.hyprland_window_manager import HyprlandWindowManager
from control.platform.hyprland.hyprland_capture import HyprlandScreenCapture
from control.platform.hyprland.linux_clipboard import LinuxClipboard
from control.platform.hyprland.linux_notifications import LinuxNotifier
from control.platform.hyprland.linux_app_launcher import LinuxAppLauncher
from control.platform.hyprland.linux_ocr import LinuxOcrEngine, default_linux_ocr


class HyprlandSafety(BaseSafety):
    """
    Linux / Hyprland safety governor checks.
    """

    def __init__(self, input_engine: UInputEngine, wm: HyprlandWindowManager):
        self.input_engine = input_engine
        self.wm = wm

    def get_cursor_pos(self) -> Tuple[int, int]:
        """Returns physical cursor position."""
        return self.input_engine.get_position()

    def is_elevated(self) -> bool:
        """Checks if process has root privileges."""
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False

    def check_failsafe(self, pos: Optional[Tuple[int, int]] = None) -> None:
        """
        Corner abort check ((0, 0) corner failsafe).
        """
        x, y = pos if pos is not None else self.get_cursor_pos()
        vx, vy, _, _ = self.wm.get_virtual_screen_bounds()

        is_primary_corner = (0 <= x <= 3 and 0 <= y <= 3)
        is_virtual_corner = (vx <= x <= vx + 3 and vy <= y <= vy + 3)

        if is_primary_corner or is_virtual_corner:
            from control.safety import FailsafeException
            raise FailsafeException(
                f"Failsafe triggered! Cursor at ({x}, {y}) near screen corner. Aborting computer control action."
            )

    def ensure_interactive_desktop(self) -> bool:
        """On Wayland, verifies active display session."""
        return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


class HyprlandPlatformDriver(BasePlatformDriver):
    """
    Native Arch Linux Hyprland Platform Driver.
    """

    name: str = "hyprland"

    def __init__(self, ipc: Optional[HyprlandIPC] = None):
        super().__init__()
        self.ipc = ipc or default_hyprland_ipc
        self.input = UInputEngine(ipc=self.ipc)
        self.window_manager = HyprlandWindowManager(ipc=self.ipc)
        self.capture = HyprlandScreenCapture(wm=self.window_manager, ipc=self.ipc)
        self.clipboard = LinuxClipboard(input_engine=self.input)
        self.notifier = LinuxNotifier()
        self.launcher = LinuxAppLauncher(ipc=self.ipc)
        self.safety = HyprlandSafety(input_engine=self.input, wm=self.window_manager)
        self.ocr = default_linux_ocr

    def is_available(self) -> bool:
        """Checks if Hyprland environment is active."""
        if not sys.platform.startswith("linux"):
            return False
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return True
        if os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "hyprland":
            return True
        if shutil.which("hyprctl"):
            return True
        return False
