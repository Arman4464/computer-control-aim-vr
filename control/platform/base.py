"""
Platform Abstraction Layer - Base Interfaces and Contracts.
Defines abstract interfaces for input injection, window management, screen capture,
clipboard interaction, desktop notifications, application launching, and safety.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image


class BaseInputEngine(ABC):
    """Abstract interface for mouse and keyboard input injection."""

    @abstractmethod
    def move_cursor(self, x: int, y: int) -> Tuple[int, int]:
        """Moves cursor to screen pixel position (x, y). Returns final position."""
        pass

    @abstractmethod
    def get_position(self) -> Tuple[int, int]:
        """Returns the current cursor screen position (x, y)."""
        pass

    @abstractmethod
    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> Tuple[int, int]:
        """Clicks specified mouse button at (x, y) or current pos. Returns final position."""
        pass

    @abstractmethod
    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        """Presses and holds the specified mouse button."""
        pass

    @abstractmethod
    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        """Releases the specified mouse button."""
        pass

    @abstractmethod
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", duration: float = 0.5) -> Tuple[int, int]:
        """Drags mouse from start to end coordinates."""
        pass

    @abstractmethod
    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Scrolls wheel vertically (positive=up, negative=down)."""
        pass

    @abstractmethod
    def type_text(self, text: str, interval: float = 0.01) -> None:
        """Types unicode string with delay between characters."""
        pass

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Presses and releases a single key."""
        pass

    @abstractmethod
    def key_down(self, key: str) -> None:
        """Presses and holds a single key."""
        pass

    @abstractmethod
    def key_up(self, key: str) -> None:
        """Releases a single key."""
        pass

    @abstractmethod
    def hotkey(self, *keys: str) -> None:
        """Executes hotkey combination pressed down in order and released in reverse."""
        pass


class BaseWindowManager(ABC):
    """Abstract interface for desktop window and workspace management."""

    @abstractmethod
    def get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """Returns global virtual screen bounds (left, top, width, height)."""
        pass

    @abstractmethod
    def list_monitors(self) -> List[Dict[str, Any]]:
        """Returns list of active monitors with geometry, scaling, and primary flag."""
        pass

    @abstractmethod
    def list_windows(self) -> List[Dict[str, Any]]:
        """Returns list of visible top-level windows."""
        pass

    @abstractmethod
    def get_active_window(self) -> Optional[Dict[str, Any]]:
        """Returns metadata for the currently active/focused window."""
        pass

    @abstractmethod
    def find_window(self, query: str) -> Optional[Dict[str, Any]]:
        """Finds window matching title, class, or identifier."""
        pass

    @abstractmethod
    def focus_window(self, identifier: Any) -> bool:
        """Brings the specified window into focus."""
        pass

    @abstractmethod
    def close_window(self, identifier: Any, force: bool = False) -> bool:
        """Closes the specified window."""
        pass

    @abstractmethod
    def snap(self, target: str, position: str) -> Dict[str, Any]:
        """Snaps window to specified monitor region (left, right, top, bottom, etc.)."""
        pass

    @abstractmethod
    def set_state(self, target: str, state: str) -> Dict[str, Any]:
        """Sets window state: 'maximize', 'minimize', 'restore'."""
        pass

    @abstractmethod
    def move_resize(self, target: str, x: int, y: int, width: int, height: int) -> Dict[str, Any]:
        """Sets explicit window pixel bounds."""
        pass

    @abstractmethod
    def get_window_bounds(self, identifier: Any) -> Optional[Tuple[int, int, int, int]]:
        """Returns bounding rectangle (left, top, width, height) of window."""
        pass


class BaseScreenCapture(ABC):
    """Abstract interface for screen capture."""

    @abstractmethod
    def capture_screen(self, max_dim: Optional[int] = None, quality: int = 80) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
        """Captures the full virtual desktop or primary screen. Returns (PIL.Image, (vx, vy, vw, vh))."""
        pass

    @abstractmethod
    def capture_window(self, query: str, max_dim: Optional[int] = None, quality: int = 80) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int, int, int]]]:
        """Captures specified target window. Returns (PIL.Image, bounds) or (None, None)."""
        pass

    @abstractmethod
    def get_raw_frame(self, target: Optional[str] = None) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
        """Returns unscaled PIL image and bounds for screenshot/SOM pipeline."""
        pass


class BaseClipboard(ABC):
    """Abstract interface for clipboard operations."""

    @abstractmethod
    def get_text(self) -> str:
        """Returns current clipboard text."""
        pass

    @abstractmethod
    def set_text(self, text: str) -> bool:
        """Copies text to clipboard."""
        pass

    @abstractmethod
    def paste(self, text: Optional[str] = None, restore_clipboard: bool = False) -> bool:
        """Pastes text via clipboard injection and synthetic Ctrl+V."""
        pass


class BaseNotifier(ABC):
    """Abstract interface for desktop notifications."""

    @abstractmethod
    def send_notification(self, title: str, message: str, app_id: Optional[str] = None, sound: bool = True) -> Dict[str, Any]:
        """Sends native desktop notification."""
        pass


class BaseAppLauncher(ABC):
    """Abstract interface for application launching."""

    @abstractmethod
    def launch_app(self, name: str, args: Optional[str] = None) -> Dict[str, Any]:
        """Launches application by binary name or known alias."""
        pass

    @abstractmethod
    def open_file_or_url(self, target: str) -> Dict[str, Any]:
        """Opens file or URL via default system handler."""
        pass


class BaseSafety(ABC):
    """Abstract interface for platform-specific safety checks."""

    @abstractmethod
    def get_cursor_pos(self) -> Tuple[int, int]:
        """Returns physical cursor position."""
        pass

    @abstractmethod
    def is_elevated(self) -> bool:
        """Returns True if running with admin/root privileges."""
        pass

    @abstractmethod
    def check_failsafe(self, pos: Optional[Tuple[int, int]] = None) -> None:
        """Checks if cursor is at failsafe corner and aborts if necessary."""
        pass

    @abstractmethod
    def ensure_interactive_desktop(self) -> bool:
        """Ensures process is attached to interactive user session."""
        pass


class BasePlatformDriver(ABC):
    """Root driver aggregating all platform-specific subsystems."""

    name: str = "base"

    def __init__(self):
        self.input: BaseInputEngine = None
        self.window_manager: BaseWindowManager = None
        self.capture: BaseScreenCapture = None
        self.clipboard: BaseClipboard = None
        self.notifier: BaseNotifier = None
        self.launcher: BaseAppLauncher = None
        self.safety: BaseSafety = None

    def get_platform_name(self) -> str:
        """Returns string identifier of the platform."""
        return self.name

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the current operating environment supports this driver."""
        pass

