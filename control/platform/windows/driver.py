"""
Windows Platform Driver (AIM-VR Win32 Native Implementation).
Wraps native Win32 User32, GDI32, Shell32, and COM subsystems behind the unified Platform Driver API.
"""

import sys
import os
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image

from control.platform.base import (
    BasePlatformDriver,
    BaseInputEngine,
    BaseWindowManager,
    BaseScreenCapture,
    BaseClipboard,
    BaseNotifier,
    BaseAppLauncher,
    BaseSafety,
)


class WindowsInputEngine(BaseInputEngine):
    """Win32 Input Engine wrapping MouseEngine and KeyboardEngine."""

    def __init__(self):
        self._mouse = None
        self._keyboard = None

    def _get_mouse(self):
        if self._mouse is None:
            from control.mouse_engine import default_mouse
            self._mouse = default_mouse
        return self._mouse

    def _get_keyboard(self):
        if self._keyboard is None:
            from control.keyboard_engine import default_keyboard
            self._keyboard = default_keyboard
        return self._keyboard

    def move_cursor(self, x: int, y: int) -> Tuple[int, int]:
        return self._get_mouse().move_cursor(x, y)

    def get_position(self) -> Tuple[int, int]:
        return self._get_mouse().get_position()

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> Tuple[int, int]:
        return self._get_mouse().click(x=x, y=y, button=button, clicks=clicks)

    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        return self._get_mouse().mouse_down(x=x, y=y, button=button)

    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        return self._get_mouse().mouse_up(x=x, y=y, button=button)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", duration: float = 0.5) -> Tuple[int, int]:
        return self._get_mouse().drag(start_x, start_y, end_x, end_y, button=button, duration=duration)

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self._get_mouse().scroll(clicks, x=x, y=y)

    def type_text(self, text: str, interval: float = 0.01) -> None:
        self._get_keyboard().type_text(text, interval=interval)

    def press_key(self, key: str) -> None:
        self._get_keyboard().press_key(key)

    def key_down(self, key: str) -> None:
        self._get_keyboard().key_down(key)

    def key_up(self, key: str) -> None:
        self._get_keyboard().key_up(key)

    def hotkey(self, *keys: str) -> None:
        self._get_keyboard().hotkey(*keys)


class WindowsWindowManager(BaseWindowManager):
    """Win32 Window Manager."""

    def __init__(self):
        self._wm = None

    def _get_wm(self):
        if self._wm is None:
            from control.window_manager import default_window_manager
            self._wm = default_window_manager
        return self._wm

    def get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        from control.mouse_engine import get_virtual_screen_bounds
        return get_virtual_screen_bounds()

    def list_monitors(self) -> List[Dict[str, Any]]:
        from perception.screen_capture import list_monitors
        return list_monitors()

    def list_windows(self) -> List[Dict[str, Any]]:
        from perception.screen_capture import list_visible_windows
        return list_visible_windows()

    def get_active_window(self) -> Optional[Dict[str, Any]]:
        from perception.screen_capture import get_foreground_window_info
        return get_foreground_window_info()

    def find_window(self, query: str) -> Optional[Dict[str, Any]]:
        from perception.screen_capture import find_window
        return find_window(query)

    def focus_window(self, identifier: Any) -> bool:
        from perception.screen_capture import focus_window
        return focus_window(identifier)

    def close_window(self, identifier: Any, force: bool = False) -> bool:
        from perception.screen_capture import close_window_safely
        return close_window_safely(identifier, force=force)

    def snap(self, target: str, position: str) -> Dict[str, Any]:
        return self._get_wm().snap(target, position)

    def set_state(self, target: str, state: str) -> Dict[str, Any]:
        return self._get_wm().set_state(target, state)

    def move_resize(self, target: str, x: int, y: int, width: int, height: int) -> Dict[str, Any]:
        return self._get_wm().move_resize(target, x, y, width, height)

    def get_window_bounds(self, identifier: Any) -> Optional[Tuple[int, int, int, int]]:
        from perception.screen_capture import get_window_extended_bounds, find_window
        if isinstance(identifier, int):
            return get_window_extended_bounds(identifier)
        win = find_window(str(identifier))
        if win and "hwnd" in win:
            return get_window_extended_bounds(win["hwnd"])
        return None


class WindowsScreenCapture(BaseScreenCapture):
    """Win32 GDI Screen Capture."""

    def __init__(self):
        self._manager = None

    def _get_manager(self):
        if self._manager is None:
            from perception.screen_capture import default_capture_manager
            self._manager = default_capture_manager
        return self._manager

    def capture_screen(self, max_dim: Optional[int] = None, quality: int = 80) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
        from perception.screen_capture import capture_screen
        return capture_screen(max_dim=max_dim, quality=quality)

    def capture_window(self, query: str, max_dim: Optional[int] = None, quality: int = 80) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int, int, int]]]:
        from perception.screen_capture import capture_window
        return capture_window(query, max_dim=max_dim, quality=quality)

    def get_raw_frame(self, target: Optional[str] = None) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
        return self._get_manager().get_raw_frame(target=target)


class WindowsClipboard(BaseClipboard):
    """Win32 Native Clipboard."""

    def __init__(self):
        self._cb = None

    def _get_cb(self):
        if self._cb is None:
            from control.clipboard import default_clipboard
            self._cb = default_clipboard
        return self._cb

    def get_text(self) -> str:
        return self._get_cb().get_text()

    def set_text(self, text: str) -> bool:
        return self._get_cb().set_text(text)

    def paste(self, text: Optional[str] = None, restore_clipboard: bool = False) -> bool:
        return self._get_cb().paste(text=text, restore_clipboard=restore_clipboard)


class WindowsNotifier(BaseNotifier):
    """Windows Action Center Toast Notifier."""

    def send_notification(self, title: str, message: str, app_id: Optional[str] = None, sound: bool = True) -> Dict[str, Any]:
        from control.notifications import send_toast_notification
        return send_toast_notification(title=title, message=message, app_id=app_id, sound=sound)


class WindowsAppLauncher(BaseAppLauncher):
    """Windows Application Launcher."""

    def launch_app(self, name: str, args: Optional[str] = None) -> Dict[str, Any]:
        from control.app_launcher import launch_application
        return launch_application(name, args=args)

    def open_file_or_url(self, target: str) -> Dict[str, Any]:
        from control.app_launcher import shell_execute
        return shell_execute(target)


class WindowsSafety(BaseSafety):
    """Win32 Safety checks."""

    def get_cursor_pos(self) -> Tuple[int, int]:
        from control.safety import get_physical_cursor_pos
        return get_physical_cursor_pos()

    def is_elevated(self) -> bool:
        from control.safety import is_process_elevated
        return is_process_elevated()

    def check_failsafe(self, pos: Optional[Tuple[int, int]] = None) -> None:
        from control.safety import default_governor
        default_governor.check_failsafe()

    def ensure_interactive_desktop(self) -> bool:
        from control.safety import ensure_interactive_desktop
        return ensure_interactive_desktop()


class WindowsPlatformDriver(BasePlatformDriver):
    """Native Windows Platform Driver."""

    name: str = "windows"

    def __init__(self):
        super().__init__()
        self.input = WindowsInputEngine()
        self.window_manager = WindowsWindowManager()
        self.capture = WindowsScreenCapture()
        self.clipboard = WindowsClipboard()
        self.notifier = WindowsNotifier()
        self.launcher = WindowsAppLauncher()
        self.safety = WindowsSafety()

    def is_available(self) -> bool:
        return sys.platform == "win32"
