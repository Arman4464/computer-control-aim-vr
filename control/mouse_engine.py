"""
High-Performance Win32 Mouse Engine with Multi-Monitor Virtual Screen
Coordinate Normalization and Per-Monitor DPI Awareness.
"""

import ctypes
from ctypes import wintypes
import time
import sys
import math
from control.safety import (
    default_governor,
    ensure_interactive_desktop,
    get_physical_cursor_pos,
    POINT
)

user32 = ctypes.windll.user32
shcore = getattr(ctypes.windll, "shcore", None)

# 64-bit / 32-bit safe ULONG_PTR
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR)
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]

class _INPUTunion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("u", _INPUTunion)
    ]

# Win32 Constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

# System Metrics constants
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
user32.mouse_event.restype = None

if hasattr(user32, "SetProcessDpiAwarenessContext"):
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL

if shcore and hasattr(shcore, "SetProcessDpiAwareness"):
    shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
    shcore.SetProcessDpiAwareness.restype = getattr(wintypes, "HRESULT", ctypes.HRESULT)


def init_dpi_awareness() -> str:
    """
    Initializes Per-Monitor DPI awareness to ensure SendInput and screen coordinates
    map 1:1 to physical display pixels without virtual scaling distortion.
    """
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            res = user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            if res:
                return "Per-Monitor DPI Aware V2"
    except Exception:
        pass

    try:
        if shcore and hasattr(shcore, "SetProcessDpiAwareness"):
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            res = shcore.SetProcessDpiAwareness(2)
            if res == 0:
                return "Per-Monitor DPI Aware V1"
    except Exception:
        pass

    try:
        if hasattr(user32, "SetProcessDPIAware"):
            res = user32.SetProcessDPIAware()
            if res:
                return "System DPI Aware"
    except Exception:
        pass

    return "Default DPI"


# Initialize DPI awareness upon module import
_dpi_mode = init_dpi_awareness()
sys.stderr.write(f"[MouseEngine] DPI Awareness initialized: {_dpi_mode}\n")


def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Returns (vx, vy, vw, vh) of the entire virtual desktop span across all monitors."""
    ensure_interactive_desktop()
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    vw = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return vx, vy, vw, vh


def to_virtual_normalized(pixel_x: int, pixel_y: int) -> tuple[int, int]:
    """
    Normalizes absolute pixel coordinates (pixel_x, pixel_y) into [0..65535]
    for MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK.
    Correctly accounts for negative offsets in multi-monitor layouts.
    """
    vx, vy, vw, vh = get_virtual_screen_bounds()
    if vw <= 1:
        norm_x = 0
    else:
        norm_x = int(round((pixel_x - vx) * 65535.0 / (vw - 1)))

    if vh <= 1:
        norm_y = 0
    else:
        norm_y = int(round((pixel_y - vy) * 65535.0 / (vh - 1)))

    norm_x = max(0, min(65535, norm_x))
    norm_y = max(0, min(65535, norm_y))
    return norm_x, norm_y


def convert_coords(x: float, y: float, coords_mode: str = "pixel") -> tuple[int, int]:
    """
    Converts input coordinates into absolute pixel coordinates.
    coords_mode: 'pixel' (raw display pixels) or 'normalized_1000' (0..1000 range).
    """
    vx, vy, vw, vh = get_virtual_screen_bounds()
    if coords_mode == "normalized_1000":
        abs_x = int(round(vx + (x / 1000.0) * (vw - 1)))
        abs_y = int(round(vy + (y / 1000.0) * (vh - 1)))
        return abs_x, abs_y
    return int(round(x)), int(round(y))


def _send_mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0):
    """Sends a raw MOUSEINPUT event via SendInput."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dx = dx
    inp.u.mi.dy = dy
    inp.u.mi.mouseData = data
    inp.u.mi.dwFlags = flags
    inp.u.mi.time = 0
    inp.u.mi.dwExtraInfo = 0

    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        # Fallback to user32.mouse_event to bypass background UIPI blocks
        user32.mouse_event(flags, dx, dy, data, 0)


class MouseEngine:
    """High-level mouse control interface."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def get_position(self) -> tuple[int, int]:
        """Returns current cursor position in screen pixels."""
        return get_physical_cursor_pos()

    def _raw_mouse_down(self, button: str = "left") -> None:
        btn = button.lower()
        if btn == "left":
            flags = MOUSEEVENTF_LEFTDOWN
        elif btn == "right":
            flags = MOUSEEVENTF_RIGHTDOWN
        elif btn == "middle":
            flags = MOUSEEVENTF_MIDDLEDOWN
        else:
            raise ValueError(f"Unknown mouse button: {button}")
        _send_mouse_event(flags)

    def _raw_mouse_up(self, button: str = "left") -> None:
        btn = button.lower()
        if btn == "left":
            flags = MOUSEEVENTF_LEFTUP
        elif btn == "right":
            flags = MOUSEEVENTF_RIGHTUP
        elif btn == "middle":
            flags = MOUSEEVENTF_MIDDLEUP
        else:
            raise ValueError(f"Unknown mouse button: {button}")
        _send_mouse_event(flags)

    def move(self, x: float, y: float, coords_mode: str = "pixel") -> tuple[int, int]:
        """Moves cursor to specified target coordinates."""
        self.governor.pre_action()
        target_x, target_y = convert_coords(x, y, coords_mode)
        norm_x, norm_y = to_virtual_normalized(target_x, target_y)

        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        _send_mouse_event(flags, norm_x, norm_y)

        # Fallback to SetCursorPos to ensure exact pixel accuracy
        user32.SetCursorPos(target_x, target_y)

        self.governor.post_action((target_x, target_y))
        return target_x, target_y

    def mouse_down(self, button: str = "left") -> None:
        """Presses and holds the specified mouse button ('left', 'right', 'middle')."""
        self.governor.pre_action()
        self._raw_mouse_down(button)
        self.governor.post_action()

    def mouse_up(self, button: str = "left") -> None:
        """Releases the specified mouse button ('left', 'right', 'middle')."""
        self.governor.pre_action()
        self._raw_mouse_up(button)
        self.governor.post_action()

    def hover(
        self,
        x: float,
        y: float,
        duration: float = 0.2,
        coords_mode: str = "pixel"
    ) -> tuple[int, int]:
        """
        Moves cursor to (x, y) and hovers there for duration seconds.
        Essential for activating flyout menus, tooltips, and hover UI states.
        """
        target_x, target_y = self.move(x, y, coords_mode)
        if duration > 0:
            time.sleep(duration)
        return target_x, target_y

    def click(
        self,
        x: float | None = None,
        y: float | None = None,
        button: str = "left",
        clicks: int = 1,
        coords_mode: str = "pixel"
    ) -> tuple[int, int]:
        """
        Clicks at target (x, y) or current position.
        Supports single, double, or triple clicks (e.g. for full paragraph/URL selection).
        """
        self.governor.pre_action()

        if x is not None and y is not None:
            target_x, target_y = convert_coords(x, y, coords_mode)
            norm_x, norm_y = to_virtual_normalized(target_x, target_y)
            _send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, norm_x, norm_y)
            user32.SetCursorPos(target_x, target_y)
            cur_x, cur_y = target_x, target_y
        else:
            cur_x, cur_y = self.get_position()

        # Auto-activate window under cursor if not current foreground to prevent WM_ACTIVATE swallowing
        try:
            ensure_interactive_desktop()
            pt = POINT(cur_x, cur_y)
            hwnd_target = user32.WindowFromPoint(pt)
            if hwnd_target:
                hwnd_root = user32.GetAncestor(hwnd_target, 2)  # GA_ROOT = 2
                hwnd_fg = user32.GetForegroundWindow()
                if hwnd_root and hwnd_root != hwnd_fg:
                    user32.SetForegroundWindow(hwnd_root)
                    time.sleep(0.02)
        except Exception:
            pass

        btn = button.lower()
        for i in range(clicks):
            if i > 0:
                time.sleep(0.04)  # Inter-click delay within Windows double-click window (<500ms)
            self._raw_mouse_down(btn)
            time.sleep(0.02)
            self._raw_mouse_up(btn)

        self.governor.post_action((cur_x, cur_y))
        return cur_x, cur_y

    def drag(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        duration: float = 0.3,
        steps: int = 15,
        button: str = "left",
        coords_mode: str = "pixel"
    ) -> None:
        """Performs a smooth drag from start to end coordinates."""
        self.governor.pre_action()

        s_x, s_y = convert_coords(start_x, start_y, coords_mode)
        e_x, e_y = convert_coords(end_x, end_y, coords_mode)

        # Move to start
        norm_sx, norm_sy = to_virtual_normalized(s_x, s_y)
        _send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, norm_sx, norm_sy)
        user32.SetCursorPos(s_x, s_y)
        time.sleep(0.03)

        self._raw_mouse_down(button)
        time.sleep(0.03)

        step_delay = duration / max(steps, 1)
        for i in range(1, steps + 1):
            self.governor.check_failsafe()
            t = i / steps
            # Smooth ease-in-out interpolation
            ease = 0.5 - 0.5 * math.cos(t * math.pi)
            interp_x = int(round(s_x + (e_x - s_x) * ease))
            interp_y = int(round(s_y + (e_y - s_y) * ease))
            norm_x, norm_y = to_virtual_normalized(interp_x, interp_y)
            _send_mouse_event(
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                norm_x,
                norm_y
            )
            time.sleep(step_delay)

        user32.SetCursorPos(e_x, e_y)
        self._raw_mouse_up(button)
        self.governor.post_action((e_x, e_y))

    def scroll(self, clicks: int, x: float | None = None, y: float | None = None, coords_mode: str = "pixel") -> None:
        """
        Scrolls mouse vertical wheel.
        clicks > 0 scrolls up, clicks < 0 scrolls down.
        """
        if x is not None and y is not None:
            self.move(x, y, coords_mode)

        self.governor.pre_action()
        wheel_data = int(clicks * WHEEL_DELTA)
        # Clean signed-to-unsigned DWORD packing for negative scroll values
        packed_data = ctypes.c_ulong(wheel_data).value
        _send_mouse_event(MOUSEEVENTF_WHEEL, data=packed_data)
        self.governor.post_action()

    def scroll_horizontal(self, clicks: int, x: float | None = None, y: float | None = None, coords_mode: str = "pixel") -> None:
        """
        Scrolls mouse horizontal wheel.
        clicks > 0 scrolls right, clicks < 0 scrolls left.
        """
        if x is not None and y is not None:
            self.move(x, y, coords_mode)

        self.governor.pre_action()
        wheel_data = int(clicks * WHEEL_DELTA)
        packed_data = ctypes.c_ulong(wheel_data).value
        _send_mouse_event(MOUSEEVENTF_HWHEEL, data=packed_data)
        self.governor.post_action()


default_mouse = MouseEngine()
