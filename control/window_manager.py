"""
Windows Window Management and Layout Engine.
Provides window state manipulation (maximize, minimize, restore),
screen work-area snapping (left, right, top, bottom, quadrants, center),
and precise coordinate repositioning without disrupting background apps.
"""

import ctypes
from ctypes import wintypes
import time
import os
import sys
from typing import Optional, Dict, Any, Tuple

from control.safety import ensure_interactive_desktop, default_governor

user32 = ctypes.windll.user32
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

# Win32 Constants
SW_HIDE = 0
SW_NORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

MONITOR_DEFAULTTONEAREST = 2

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]

user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint
]
user32.SetWindowPos.restype = wintypes.BOOL


def get_window_monitor_work_area(hwnd: int) -> Tuple[int, int, int, int]:
    """Returns (left, top, width, height) of the monitor work area where the window resides."""
    h_mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not h_mon:
        # Fallback to primary screen virtual bounds
        vx = int(user32.GetSystemMetrics(76))
        vy = int(user32.GetSystemMetrics(77))
        vw = int(user32.GetSystemMetrics(78))
        vh = int(user32.GetSystemMetrics(79))
        return vx, vy, vw, vh

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
        left = int(mi.rcWork.left)
        top = int(mi.rcWork.top)
        width = int(mi.rcWork.right - mi.rcWork.left)
        height = int(mi.rcWork.bottom - mi.rcWork.top)
        return left, top, width, height

    return 0, 0, 1920, 1080


class WindowManager:
    """Controls window layout, snapping, and state."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def get_window(self, target: str) -> Optional[Dict[str, Any]]:
        """Resolves target substring to visible window info."""
        from perception.screen_capture import find_window
        return find_window(target)

    def set_state(self, target: str, state: str) -> Dict[str, Any]:
        """
        Changes window state: 'maximize', 'minimize', or 'restore'.
        """
        self.governor.pre_action()
        win = self.get_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        hwnd = win["hwnd"]
        st = state.lower().strip()
        cmd = SW_RESTORE

        if st in ("max", "maximize", "maximized"):
            cmd = SW_MAXIMIZE
        elif st in ("min", "minimize", "minimized"):
            cmd = SW_MINIMIZE
        elif st in ("restore", "normal"):
            cmd = SW_RESTORE
        else:
            return {"status": "error", "message": f"Unknown state '{state}'. Use maximize, minimize, or restore."}

        user32.ShowWindow(hwnd, cmd)
        time.sleep(0.05)
        self.governor.post_action()
        return {"status": "success", "title": win["title"], "hwnd": hwnd, "state": st}

    def snap(self, target: str, position: str) -> Dict[str, Any]:
        """
        Snaps window to a layout position on its monitor:
          - 'left': Left half of monitor work area
          - 'right': Right half of monitor work area
          - 'top': Top half
          - 'bottom': Bottom half
          - 'top-left', 'top-right', 'bottom-left', 'bottom-right': Quadrants
          - 'center': Centered on monitor (75% width, 80% height)
        """
        self.governor.pre_action()
        win = self.get_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        hwnd = win["hwnd"]
        # Restore window if maximized or minimized so resizing succeeds
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.04)

        wl, wt, ww, wh = get_window_monitor_work_area(hwnd)
        pos = position.lower().strip()

        half_w = ww // 2
        half_h = wh // 2

        if pos == "left":
            nx, ny, nw, nh = wl, wt, half_w, wh
        elif pos == "right":
            nx, ny, nw, nh = wl + half_w, wt, ww - half_w, wh
        elif pos == "top":
            nx, ny, nw, nh = wl, wt, ww, half_h
        elif pos == "bottom":
            nx, ny, nw, nh = wl, wt + half_h, ww, wh - half_h
        elif pos in ("top-left", "top_left"):
            nx, ny, nw, nh = wl, wt, half_w, half_h
        elif pos in ("top-right", "top_right"):
            nx, ny, nw, nh = wl + half_w, wt, ww - half_w, half_h
        elif pos in ("bottom-left", "bottom_left"):
            nx, ny, nw, nh = wl, wt + half_h, half_w, wh - half_h
        elif pos in ("bottom-right", "bottom_right"):
            nx, ny, nw, nh = wl + half_w, wt + half_h, ww - half_w, wh - half_h
        elif pos == "center":
            nw = int(ww * 0.75)
            nh = int(wh * 0.8)
            nx = wl + (ww - nw) // 2
            ny = wt + (wh - nh) // 2
        else:
            return {
                "status": "error",
                "message": f"Unknown snap position '{position}'. Use left, right, top, bottom, top-left, top-right, bottom-left, bottom-right, or center."
            }

        flags = SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
        res = user32.SetWindowPos(hwnd, 0, nx, ny, nw, nh, flags)
        self.governor.post_action()

        return {
            "status": "success",
            "title": win["title"],
            "hwnd": hwnd,
            "position": pos,
            "bounds": [nx, ny, nw, nh],
            "win32_success": bool(res),
        }

    def move_resize(self, target: str, x: int, y: int, width: int, height: int) -> Dict[str, Any]:
        """Sets exact pixel bounds for the target window."""
        self.governor.pre_action()
        win = self.get_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        hwnd = win["hwnd"]
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.04)

        flags = SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
        res = user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height), flags)
        self.governor.post_action()

        return {
            "status": "success",
            "title": win["title"],
            "hwnd": hwnd,
            "bounds": [int(x), int(y), int(width), int(height)],
            "win32_success": bool(res),
        }


default_window_manager = WindowManager()
