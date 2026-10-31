"""
High-Performance Win32 GDI Screen Capture and Differential Dirty-Rect Detection.
Provides zero-dependency fast desktop capture, window-locked capture (PrintWindow / BitBlt),
and perceptual delta-diff computation to minimize token consumption.
"""

import ctypes
from ctypes import wintypes
import io
import time
import base64
import sys
from typing import Optional, Tuple, Dict, Any, List
from PIL import Image, ImageChops

from control.safety import ensure_interactive_desktop, run_in_interactive_desktop, IS_WINDOWS
from control.mouse_engine import get_virtual_screen_bounds

if IS_WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    SRCCOPY = 0x00CC0020
    PW_RENDERFULLCONTENT = 2
    SW_RESTORE = 9

    # Strict 64-bit Win32 GDI and User32 Signatures
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = wintypes.BOOL

    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL

    dwmapi = getattr(ctypes.windll, "dwmapi", None)
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
else:
    user32 = None
    gdi32 = None
    kernel32 = None
    dwmapi = None
    SRCCOPY = 0x00CC0020
    PW_RENDERFULLCONTENT = 2
    SW_RESTORE = 9
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _capture_dc_rect(hdc_source, left: int, top: int, width: int, height: int) -> Image.Image:
    """Captures a rectangle from a device context into a PIL Image."""
    width = max(1, int(width))
    height = max(1, int(height))

    hdc_mem = None
    hbm = None
    h_old = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_source)
        hbm = gdi32.CreateCompatibleBitmap(hdc_source, width, height)
        h_old = gdi32.SelectObject(hdc_mem, hbm)

        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_source, left, top, SRCCOPY)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # top-down DIB
        bmi.biPlanes = 1
        bmi.biBitCount = 32     # 32-bit BGRA
        bmi.biCompression = 0   # BI_RGB

        buf_size = width * height * 4
        buffer = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem, hbm, 0, height, buffer, ctypes.byref(bmi), 0)

        img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
        return img
    finally:
        if hdc_mem and h_old:
            gdi32.SelectObject(hdc_mem, h_old)
        if hbm:
            gdi32.DeleteObject(hbm)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)


def _capture_screen_worker(bbox: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    vx, vy, vw, vh = get_virtual_screen_bounds()
    if bbox is not None:
        left, top, width, height = bbox
    else:
        left, top, width, height = vx, vy, vw, vh

    hdc_screen = user32.GetDC(0)
    try:
        return _capture_dc_rect(hdc_screen, left, top, width, height)
    finally:
        user32.ReleaseDC(0, hdc_screen)


def capture_screen(bbox: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    """
    Captures the virtual screen or specified bounding box (left, top, width, height).
    Runs inside interactive desktop worker thread to ensure display surface access.
    """
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            img, bounds = get_platform_driver().capture.capture_screen()
            if bbox:
                x, y, w, h = bbox
                vx, vy = bounds[0], bounds[1]
                rel_x = max(0, x - vx)
                rel_y = max(0, y - vy)
                img = img.crop((rel_x, rel_y, min(img.width, rel_x + w), min(img.height, rel_y + h)))
            return img
        except Exception:
            return Image.new("RGB", (1920, 1080), color=(30, 30, 46))
    return run_in_interactive_desktop(_capture_screen_worker, bbox)


def list_monitors() -> List[Dict[str, Any]]:
    """Returns a list of all active display monitors with their bounds, work areas, and primary status."""
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.list_monitors()
        except Exception:
            return []

    monitors = []

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def enum_mon_cb(hmon, hdc, rect_ptr, lparam):
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r_mon = mi.rcMonitor
            r_work = mi.rcWork
            monitors.append({
                "device": str(mi.szDevice),
                "is_primary": bool(mi.dwFlags & 1),
                "bounds": [int(r_mon.left), int(r_mon.top), int(r_mon.right - r_mon.left), int(r_mon.bottom - r_mon.top)],
                "work_area": [int(r_work.left), int(r_work.top), int(r_work.right - r_work.left), int(r_work.bottom - r_work.top)],
            })
        return True

    user32.EnumDisplayMonitors(0, None, MONITORENUMPROC(enum_mon_cb), 0)
    return monitors


def list_visible_windows() -> List[Dict[str, Any]]:
    """Returns a list of all genuine, active top-level windows with their titles and bounds."""
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.list_windows()
        except Exception:
            return []

    ensure_interactive_desktop()
    try:
        from control.vdm import default_vdm
    except Exception:
        default_vdm = None

    windows = []

    def enum_cb(hwnd, lparam):
        if not user32.IsWindow(hwnd):
            return True

        # Check process ID to filter out dead/ghost window stubs
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return True

        if user32.IsWindowVisible(hwnd):
            # Filter out cloaked background UWP apps and hidden virtual desktop windows
            if dwmapi:
                cloaked = wintypes.DWORD(0)
                hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if hr == 0 and cloaked.value != 0:
                    return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()

                if not title:
                    return True

                is_iconic = bool(user32.IsIconic(hwnd))
                ext = get_window_extended_bounds(hwnd)
                if ext[2] > 0 and ext[3] > 0:
                    win_bounds = [int(ext[0]), int(ext[1]), int(ext[2]), int(ext[3])]
                else:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    win_bounds = [int(rect.left), int(rect.top), int(w), int(h)]

                # Check virtual desktop placement (Task View)
                on_cur = True
                if default_vdm is not None:
                    try:
                        on_cur = default_vdm.is_window_on_current_desktop(hwnd)
                    except Exception:
                        on_cur = True

                # Ignore invisible 0x0 or offscreen ghost windows unless explicitly minimized
                if is_iconic:
                    windows.append({
                        "hwnd": int(hwnd),
                        "title": title,
                        "bounds": win_bounds,
                        "is_minimized": True,
                        "pid": int(pid.value),
                        "on_current_desktop": on_cur,
                    })
                elif win_bounds[2] > 0 and win_bounds[3] > 0 and win_bounds[0] > -30000:
                    windows.append({
                        "hwnd": int(hwnd),
                        "title": title,
                        "bounds": win_bounds,
                        "is_minimized": False,
                        "pid": int(pid.value),
                        "on_current_desktop": on_cur,
                    })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    cb_func = WNDENUMPROC(enum_cb)
    
    # Try standard EnumWindows first
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(cb_func, 0)

    # Fallback to EnumDesktopWindows on input desktop only if EnumWindows found no windows
    if not windows:
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, WNDENUMPROC, wintypes.LPARAM]
            user32.EnumDesktopWindows.restype = wintypes.BOOL
            user32.EnumDesktopWindows(h_input, cb_func, 0)
            user32.CloseDesktop(h_input)

    return windows


def find_window(target: str) -> Optional[Dict[str, Any]]:
    """Finds first matching visible window by title substring (case-insensitive)."""
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.find_window(target)
        except Exception:
            return None

    target_lower = target.lower()
    for win in list_visible_windows():
        if target_lower in win["title"].lower():
            return win
    return None


def focus_window(hwnd: Any) -> bool:
    """Brings the window to foreground, restores if minimized, and verifies activation."""
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.focus_window(hwnd)
        except Exception:
            return False

    ensure_interactive_desktop()
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return False

    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)

        # Shell taskbar activation bypass: restores minimized window and activates even from background processes
        if hasattr(user32, "SwitchToThisWindow"):
            try:
                user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
                user32.SwitchToThisWindow.restype = None
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass

        # Win32 Alt-key foreground unlock bypass to bypass Windows ForegroundLockTimeout
        user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
        res = user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
        if not res:
            # Safe bypass: attach thread input queues temporarily without touching keyboard state
            cur_tid = kernel32.GetCurrentThreadId()
            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            target_tid = user32.GetWindowThreadProcessId(hwnd, None)

            attached_fg = False
            attached_target = False
            try:
                if fg_tid and fg_tid != cur_tid:
                    attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
                if target_tid and target_tid != cur_tid:
                    attached_target = bool(user32.AttachThreadInput(cur_tid, target_tid, True))

                user32.SetForegroundWindow(hwnd)
            finally:
                if attached_fg:
                    user32.AttachThreadInput(cur_tid, fg_tid, False)
                if attached_target:
                    user32.AttachThreadInput(cur_tid, target_tid, False)

        # STRICT VERIFICATION: ensure window is actually foreground
        import time
        for _ in range(6):
            fg = user32.GetForegroundWindow()
            if fg == hwnd:
                return True
            fg_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
            if fg_pid.value == pid.value:
                return True
            time.sleep(0.04)

        return False
    except Exception as e:
        sys.stderr.write(f"[ScreenCapture] focus_window error: {e}\n")
        return False


def close_window_safely(target: str, force: bool = False) -> bool:
    """
    Safely closes a window matching target title using direct Win32 messages or Hyprland IPC.
    Never sends global keyboard shortcuts (Alt+F4); completely immune to misdirected closes.
    """
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.close_window(target, force=force)
        except Exception:
            return False

    win = find_window(target)
    if not win:
        return True

    hwnd = win["hwnd"]
    if not user32.IsWindow(hwnd):
        return True

    # 1. Send WM_CLOSE directly to target window's message queue
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    import time
    time.sleep(0.25)
    if not user32.IsWindow(hwnd) or not find_window(target):
        return True

    # 2. If still open, send WM_SYSCOMMAND SC_CLOSE (identical to clicking caption bar 'X')
    WM_SYSCOMMAND = 0x0112
    SC_CLOSE = 0xF060
    user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0)
    time.sleep(0.25)

    if not user32.IsWindow(hwnd) or not find_window(target):
        return True

    # 3. If force is requested and still alive, terminate only that specific PID
    if force and win.get("pid"):
        try:
            import os
            import signal
            os.kill(win["pid"], signal.SIGTERM)
            time.sleep(0.2)
        except Exception:
            pass

    return find_window(target) is None


def get_foreground_window_info() -> Optional[Dict[str, Any]]:
    """Returns information about the currently active foreground window."""
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().window_manager.get_active_window()
        except Exception:
            return None

    ensure_interactive_desktop()
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value

    ext = get_window_extended_bounds(hwnd)
    if ext[2] > 0 and ext[3] > 0:
        bounds = [int(ext[0]), int(ext[1]), int(ext[2]), int(ext[3])]
    else:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        bounds = [int(rect.left), int(rect.top), int(w), int(h)]

    return {
        "hwnd": int(hwnd),
        "title": title,
        "bounds": bounds
    }


def get_window_extended_bounds(hwnd: Any) -> Tuple[int, int, int, int]:
    """
    Returns (left, top, width, height) of genuine visible window surface,
    excluding invisible Windows 10/11 aero drop-shadow resizing margins.
    Falls back to GetWindowRect if DWM is unavailable.
    """
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            b = get_platform_driver().window_manager.get_window_bounds(hwnd)
            return b if b else (0, 0, 800, 600)
        except Exception:
            return (0, 0, 800, 600)

    if not hwnd or not user32.IsWindow(hwnd):
        return (0, 0, 0, 0)

    rect = wintypes.RECT()
    if dwmapi:
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect)
        )
        if hr == 0:
            w = max(0, rect.right - rect.left)
            h = max(0, rect.bottom - rect.top)
            return (int(rect.left), int(rect.top), int(w), int(h))

    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = max(0, rect.right - rect.left)
    h = max(0, rect.bottom - rect.top)
    return (int(rect.left), int(rect.top), int(w), int(h))


def get_window_client_bounds(hwnd: Any) -> Tuple[int, int, int, int]:
    """
    Returns (left, top, width, height) in absolute screen coordinates
    for the client/content area of the window (excluding OS title bar and frames).
    """
    if not IS_WINDOWS:
        return get_window_extended_bounds(hwnd)

    if not hwnd or not user32.IsWindow(hwnd):
        return (0, 0, 0, 0)

    client_rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client_rect))
    w = max(0, client_rect.right - client_rect.left)
    h = max(0, client_rect.bottom - client_rect.top)

    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (int(pt.x), int(pt.y), int(w), int(h))


def window_to_screen_coords(hwnd: Any, rx: int, ry: int, client_only: bool = False) -> Tuple[int, int]:
    """
    Translates relative window/client coordinates (rx, ry) into absolute desktop screen coordinates.
    """
    if client_only:
        left, top, _, _ = get_window_client_bounds(hwnd)
    else:
        left, top, _, _ = get_window_extended_bounds(hwnd)
    return (left + rx, top + ry)


def _capture_window_worker(hwnd: int, client_only: bool = False) -> Image.Image:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    full_left = int(rect.left)
    full_top = int(rect.top)
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)

    hdc_screen = user32.GetDC(0)
    hdc_mem = None
    hbm = None
    h_old = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        h_old = gdi32.SelectObject(hdc_mem, hbm)

        # Try PrintWindow first for hardware accelerated windows
        res = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf_size = width * height * 4
        buffer = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem, hbm, 0, height, buffer, ctypes.byref(bmi), 0)

        img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")

        # If PrintWindow failed or returned a blank all-black image, fallback to BitBlt
        if not res or img.getextrema() == ((0, 0), (0, 0), (0, 0)):
            # Ensure window is topmost before BitBlt from screen DC to avoid capturing occluding windows
            focus_window(hwnd)
            time.sleep(0.04)
            gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, rect.left, rect.top, SRCCOPY)
            gdi32.GetDIBits(hdc_mem, hbm, 0, height, buffer, ctypes.byref(bmi), 0)
            img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")

        # Smart clipping:
        if client_only:
            cl_left, cl_top, cw, ch = get_window_client_bounds(hwnd)
            if cw > 0 and ch > 0:
                crop_x = max(0, cl_left - full_left)
                crop_y = max(0, cl_top - full_top)
                crop_w = min(width - crop_x, cw)
                crop_h = min(height - crop_y, ch)
                if crop_w > 0 and crop_h > 0 and (crop_x > 0 or crop_y > 0 or crop_w < width or crop_h < height):
                    img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        else:
            ext_left, ext_top, ew, eh = get_window_extended_bounds(hwnd)
            if ew > 0 and eh > 0 and (ew < width or eh < height):
                crop_x = max(0, ext_left - full_left)
                crop_y = max(0, ext_top - full_top)
                crop_w = min(width - crop_x, ew)
                crop_h = min(height - crop_y, eh)
                if crop_w > 0 and crop_h > 0 and (crop_x > 0 or crop_y > 0 or crop_w < width or crop_h < height):
                    img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

        return img
    finally:
        if hdc_mem and h_old:
            gdi32.SelectObject(hdc_mem, h_old)
        if hbm:
            gdi32.DeleteObject(hbm)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_screen:
            user32.ReleaseDC(0, hdc_screen)


def capture_window(hwnd: Any, client_only: bool = False) -> Image.Image:
    """
    Captures a specific window using PrintWindow (PW_RENDERFULLCONTENT) on Windows
    or grim on Wayland.
    """
    if not IS_WINDOWS:
        try:
            from control.platform import get_platform_driver
            img, _ = get_platform_driver().capture.capture_window(str(hwnd))
            if img:
                return img
        except Exception:
            pass
        return Image.new("RGB", (800, 600), color=(40, 40, 50))
    return run_in_interactive_desktop(_capture_window_worker, hwnd, client_only)


class ScreenCaptureManager:
    """
    Manages screen frame state, differential dirty-rect detection,
    and downsampling for token-efficient transmission.
    """

    def __init__(self):
        self.last_frame: Optional[Image.Image] = None
        self.last_target: Optional[str] = None

    def get_raw_frame(self, target: Optional[str] = None, client_only: bool = False) -> Tuple[Image.Image, List[int]]:
        """Captures raw unscaled PIL image and returns (image, bounds)."""
        if target:
            win = find_window(target)
            if not win:
                raise ValueError(f"Window matching '{target}' not found.")
            img = capture_window(win["hwnd"], client_only=client_only)
            if client_only:
                target_bounds = list(get_window_client_bounds(win["hwnd"]))
            else:
                target_bounds = list(get_window_extended_bounds(win["hwnd"]))
        else:
            img = capture_screen()
            vx, vy, vw, vh = get_virtual_screen_bounds()
            target_bounds = [vx, vy, vw, vh]
        self.last_frame = img.copy()
        self.last_target = target
        return img, target_bounds

    def capture(
        self,
        target: Optional[str] = None,
        mode: str = "full",
        max_dim: int = 1024,
        quality: int = 75,
        client_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Captures screen or target window.
        mode: 'full' (always full image), 'delta' (only differential bounding box if changed)
        max_dim: downsample so width/height <= max_dim (saves tokens)
        """
        target_changed = (target != self.last_target)
        self.last_target = target

        if target:
            win = find_window(target)
            if not win:
                raise ValueError(f"Window matching '{target}' not found.")
            img = capture_window(win["hwnd"], client_only=client_only)
            if client_only:
                target_bounds = list(get_window_client_bounds(win["hwnd"]))
            else:
                target_bounds = list(get_window_extended_bounds(win["hwnd"]))
        else:
            img = capture_screen()
            vx, vy, vw, vh = get_virtual_screen_bounds()
            target_bounds = [vx, vy, vw, vh]

        orig_w, orig_h = img.size

        # Check differential delta if requested and target didn't change
        if mode == "delta" and not target_changed and self.last_frame is not None and self.last_frame.size == img.size:
            diff = ImageChops.difference(self.last_frame, img)
            bbox = diff.getbbox()  # (left, top, right, bottom)

            if bbox is None:
                # Screen state completely unchanged
                return {
                    "status": "unchanged",
                    "bounds": target_bounds,
                    "delta_bbox": None,
                    "image_b64": None,
                    "width": orig_w,
                    "height": orig_h,
                    "scale": 1.0,
                }

            # Bounding box of delta
            dx1, dy1, dx2, dy2 = bbox
            delta_w = dx2 - dx1
            delta_h = dy2 - dy1
            total_pixels = orig_w * orig_h
            delta_pixels = delta_w * delta_h

            # If delta is less than 50% of the screen, return cropped delta
            if delta_pixels < 0.5 * total_pixels and delta_w > 0 and delta_h > 0:
                crop_img = img.crop(bbox)
                self.last_frame = img.copy()

                # Calculate offset in absolute screen coordinates
                abs_left = target_bounds[0] + dx1
                abs_top = target_bounds[1] + dy1

                return {
                    "status": "delta",
                    "bounds": target_bounds,
                    "delta_bbox": [abs_left, abs_top, delta_w, delta_h],
                    "image_b64": self.encode_image(crop_img, quality=quality),
                    "width": delta_w,
                    "height": delta_h,
                    "scale": 1.0,
                }

        # Otherwise full frame update
        self.last_frame = img.copy()

        # Downsample to max_dim if necessary to save tokens
        scale = 1.0
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = int(round(orig_w * scale))
            new_h = int(round(orig_h * scale))
            proc_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            proc_img = img

        return {
            "status": "full",
            "bounds": target_bounds,
            "delta_bbox": [target_bounds[0], target_bounds[1], orig_w, orig_h],
            "image_b64": self.encode_image(proc_img, quality=quality),
            "width": proc_img.size[0],
            "height": proc_img.size[1],
            "scale": scale,
        }

    def capture_roi(
        self,
        bbox: Tuple[int, int, int, int],
        max_dim: int = 1024,
        quality: int = 75
    ) -> Dict[str, Any]:
        """
        Captures a specific Region of Interest (ROI) [x, y, w, h] in screen pixels.
        Preserves fine details while drastically minimizing token consumption.
        """
        img = capture_screen(bbox=bbox)
        orig_w, orig_h = img.size
        scale = 1.0
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = int(round(orig_w * scale))
            new_h = int(round(orig_h * scale))
            proc_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            proc_img = img

        return {
            "status": "roi",
            "bbox": list(bbox),
            "width": proc_img.size[0],
            "height": proc_img.size[1],
            "scale": scale,
            "image_b64": self.encode_image(proc_img, quality=quality),
        }

    @staticmethod
    def encode_image(img: Image.Image, format: str = "JPEG", quality: int = 75) -> str:
        """Encodes PIL Image to base64 string."""
        buf = io.BytesIO()
        if format.upper() == "JPEG":
            img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        else:
            img.save(buf, format=format)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


default_capture_manager = ScreenCaptureManager()
