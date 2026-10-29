"""
Safety Governor and Contention Management for OS-level Computer Control.
Provides:
  - Corner failsafe ((0, 0) abort)
  - User physical mouse contention detection and graceful yield
  - Speed profile governor (fast, normal, step-by-step)
  - Interactive desktop thread attachment (WinSta0\\Default)
  - Process elevation / UIPI checking
"""

import ctypes
from ctypes import wintypes
import time
import sys
import math

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
ole32 = ctypes.windll.ole32

# 64-bit safe Win32 User32 / Kernel32 / Shell32 signatures
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
user32.GetThreadDesktop.restype = wintypes.HANDLE
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL


class FailsafeException(Exception):
    """Raised when the mouse cursor is moved to the (0, 0) corner failsafe."""
    pass


class UserContentionException(Exception):
    """Raised when the user moves the physical mouse during automation."""
    pass


_desktop_handle = None

# COM Apartment Threading Flags
COINIT_MULTITHREADED = 0x0
COINIT_APARTMENTTHREADED = 0x2

ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = getattr(wintypes, "HRESULT", ctypes.HRESULT)
ole32.CoUninitialize.argtypes = []
ole32.CoUninitialize.restype = None

def run_in_interactive_desktop(func, *args, timeout: float = 10.0, **kwargs):
    """
    Executes a callable inside a dedicated clean worker thread attached to the
    interactive user desktop (WinSta0\\Default). Windows User32 prohibits SetThreadDesktop
    on threads that have already created windows or hooks (ERROR_BUSY), so a fresh thread
    is required for 100% reliable UI Automation enumeration from background processes.
    Uses MTA (COINIT_MULTITHREADED) to avoid message pump deadlocks during COM/UIA calls.
    """
    import threading
    result = [None]
    exc = [None]
    desk_handle = [None]

    def target():
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            desk_handle[0] = h_input
            user32.SetThreadDesktop(h_input)
        # UI Automation clients in worker threads must initialize MTA
        ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exc[0] = e
        finally:
            ole32.CoUninitialize()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    # Close desktop handle in parent thread after worker thread terminates (avoids ERROR_BUSY 170)
    if desk_handle[0]:
        try:
            user32.CloseDesktop(desk_handle[0])
        except Exception:
            pass
    if t.is_alive():
        raise TimeoutError(f"Desktop worker thread timed out after {timeout}s.")
    if exc[0]:
        raise exc[0]
    return result[0]


def ensure_interactive_desktop() -> bool:
    """
    Attaches current thread to the interactive user input desktop ('Default' in WinSta0)
    to ensure 100% reliable physical cursor reading and event dispatch across worker
    threads and background subshell sessions.
    """
    global _desktop_handle
    try:
        tid = kernel32.GetCurrentThreadId()
        h_cur = user32.GetThreadDesktop(tid)
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            if h_cur != h_input:
                res = user32.SetThreadDesktop(h_input)
                if res:
                    _desktop_handle = h_input
                    return True
                # If thread already has open UI windows/hooks, it retains its existing valid desktop
                return bool(h_cur)
            return True
        return bool(h_cur)
    except Exception as e:
        sys.stderr.write(f"[Safety] ensure_interactive_desktop error: {e}\n")
    return False


# Attach current thread to interactive desktop only if needed
ensure_interactive_desktop()


def get_physical_cursor_pos() -> tuple[int, int]:
    """Returns the current physical cursor screen position (x, y)."""
    ensure_interactive_desktop()
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def is_process_elevated() -> bool:
    """Returns True if the current process is running with Administrator privileges."""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


class SafetyGovernor:
    """
    Central safety manager for Computer Control actions.
    """

    SPEED_PROFILES = {
        "fast": 0.05,
        "normal": 0.15,
        "step-by-step": 0.5,
    }

    def __init__(self, speed: str = "normal", failsafe: bool = True, contention: bool = True, desktop_mode: str = "interactive"):
        self.speed = speed if speed in self.SPEED_PROFILES else "normal"
        self.failsafe_enabled = failsafe
        self.contention_enabled = contention
        self.desktop_mode = desktop_mode
        self.last_agent_pos: tuple[int, int] | None = None
        self.last_action_time: float = 0.0
        self.contention_threshold_px = 15.0  # px delta indicating human movement
        self.contention_cooldown_s = 0.5     # seconds to yield after human movement
        self._custom_delay: float | None = None

    @property
    def action_delay(self) -> float:
        if self._custom_delay is not None:
            return self._custom_delay
        return self.SPEED_PROFILES.get(self.speed, 0.15)

    @action_delay.setter
    def action_delay(self, val: float):
        self._custom_delay = max(0.0, float(val))

    def configure(
        self,
        speed: str | None = None,
        failsafe: bool | None = None,
        contention: bool | None = None,
        desktop_mode: str | None = None
    ):
        if speed is not None and speed in self.SPEED_PROFILES:
            self.speed = speed
            self._custom_delay = None
        if failsafe is not None:
            self.failsafe_enabled = bool(failsafe)
        if contention is not None:
            self.contention_enabled = bool(contention)
        if desktop_mode is not None:
            from control.virtual_desktop import default_virtual_desktop
            self.desktop_mode = default_virtual_desktop.set_mode(desktop_mode)
        sys.stderr.write(
            f"[Safety] Configured: speed={self.speed}, failsafe={self.failsafe_enabled}, contention={self.contention_enabled}, desktop_mode={self.desktop_mode}\n"
        )

    def check_failsafe(self):
        """
        Polls cursor position. If cursor is at or near the top-left corner
        of the primary screen (0, 0) or virtual desktop (vx, vy), aborts execution.
        """
        if not self.failsafe_enabled:
            return
        x, y = get_physical_cursor_pos()
        # Primary screen corner: 0 <= x <= 3 and 0 <= y <= 3
        is_primary_corner = (0 <= x <= 3 and 0 <= y <= 3)

        # Virtual desktop top-left corner (handles multi-monitor negative offsets)
        vx = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
        vy = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
        is_virtual_corner = (vx <= x <= vx + 3 and vy <= y <= vy + 3)

        if is_primary_corner or is_virtual_corner:
            raise FailsafeException(
                f"Failsafe triggered! Cursor at ({x}, {y}) near screen corner. Aborting computer control action."
            )

    def check_and_handle_contention(self) -> bool:
        """
        Detects if the user has physically moved the mouse since the agent's last commanded position.
        If movement detected, yields briefly to avoid cursor fighting.
        Returns True if contention occurred and was handled, False otherwise.
        """
        if not self.contention_enabled or self.last_agent_pos is None:
            return False

        curr_x, curr_y = get_physical_cursor_pos()
        last_x, last_y = self.last_agent_pos
        dist = math.hypot(curr_x - last_x, curr_y - last_y)

        # If user moved the cursor more than the threshold px
        if dist > self.contention_threshold_px:
            sys.stderr.write(
                f"[Safety] User physical mouse contention detected (delta={dist:.1f}px). Yielding control for {self.contention_cooldown_s}s...\n"
            )
            time.sleep(self.contention_cooldown_s)
            # Update last known pos to current user pos
            self.last_agent_pos = get_physical_cursor_pos()
            return True

        return False

    # Backward-compatible alias
    check_user_contention = check_and_handle_contention

    def pre_action(self):
        """Run before any mouse or keyboard action."""
        self.check_failsafe()
        self.check_and_handle_contention()

    def post_action(self, commanded_pos: tuple[int, int] | None = None):
        """Run after any mouse or keyboard action."""
        if commanded_pos is not None:
            self.last_agent_pos = commanded_pos
        else:
            self.last_agent_pos = get_physical_cursor_pos()

        self.last_action_time = time.time()
        delay = self.action_delay
        if delay > 0:
            time.sleep(delay)


# Global default instance
default_governor = SafetyGovernor()
