"""
Windows Picture-in-Picture (PiP) Virtual Desktop Sandbox Engine.
Provides non-disruptive computer automation using isolated Windows Desktops (WinSta0\\AIMVR_Sandbox).
Allows the agent to launch applications, inspect UI trees, and execute automation workflows
without stealing the human user's physical mouse cursor, keyboard focus, or interrupting foreground work.
"""

import ctypes
from ctypes import wintypes
import time
import os
import sys
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image

IS_WINDOWS = (sys.platform == "win32")

# Desktop Access Flags
DESKTOP_READOBJECTS = 0x0001
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_CREATEMENU = 0x0004
DESKTOP_HOOKCONTROL = 0x0008
DESKTOP_JOURNALRECORD = 0x0010
DESKTOP_JOURNALPLAYBACK = 0x0020
DESKTOP_ENUMERATE = 0x0040
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100
GENERIC_ALL = 0x10000000
DESKTOP_ALL = (
    DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_HOOKCONTROL
    | DESKTOP_JOURNALRECORD
    | DESKTOP_JOURNALPLAYBACK
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_SWITCHDESKTOP
)

# Win32 Process & Window Constants
STARTF_USESHOWWINDOW = 0x00000001
SW_SHOW = 5
SW_SHOWNORMAL = 1
SW_RESTORE = 9
PW_RENDERFULLCONTENT = 2
COINIT_MULTITHREADED = 0x0

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32
    ole32 = ctypes.windll.ole32

    # 64-bit safe signatures
    user32.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    user32.CreateDesktopW.restype = wintypes.HANDLE

    user32.OpenDesktopW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    user32.OpenDesktopW.restype = wintypes.HANDLE

    user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    user32.SetThreadDesktop.restype = wintypes.BOOL

    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE

    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    # GDI and User32 64-bit safe prototypes
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC

    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

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

    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL

    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
else:
    user32 = None
    kernel32 = None
    gdi32 = None
    ole32 = None


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


if IS_WINDOWS:
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL


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


DEFAULT_SANDBOX_NAME = "AIMVR_Sandbox"


class VirtualDesktopManager:
    """
    Manages isolated desktop lifecycle (creation, process execution, window capture).
    """

    def __init__(self, sandbox_name: str = DEFAULT_SANDBOX_NAME):
        self.sandbox_name = sandbox_name
        self.desktop_mode: str = "interactive"  # "interactive" | "isolated_pip"
        self._sandbox_handle: Optional[int] = None
        self._original_desktop: Optional[int] = None
        self._tracked_pids: List[int] = []

    def set_mode(self, mode: str) -> str:
        """Sets active desktop automation mode ('interactive' or 'isolated_pip')."""
        clean_mode = mode.lower().strip()
        if clean_mode not in ["interactive", "isolated_pip"]:
            raise ValueError(f"Unknown desktop mode '{mode}'. Choose 'interactive' or 'isolated_pip'.")
        self.desktop_mode = clean_mode
        if self.desktop_mode == "isolated_pip":
            if IS_WINDOWS:
                self.ensure_sandbox()
        sys.stderr.write(f"[VirtualDesktop] Desktop mode switched to: {self.desktop_mode}\n")
        return self.desktop_mode

    def get_mode(self) -> str:
        """Returns the current desktop automation mode."""
        return self.desktop_mode

    def ensure_sandbox(self) -> int:
        """
        Creates or opens the dedicated isolated sandbox desktop.
        Returns the HDESK handle.
        """
        if not IS_WINDOWS:
            return 0

        if self._sandbox_handle:
            return self._sandbox_handle

        # Try opening existing desktop first
        h_desk = user32.OpenDesktopW(self.sandbox_name, 0, False, DESKTOP_ALL)
        if not h_desk:
            # Create new desktop inside WinSta0
            h_desk = user32.CreateDesktopW(
                self.sandbox_name,
                None,
                None,
                0,
                DESKTOP_ALL,
                None,
            )

        if not h_desk:
            raise ctypes.WinError(f"Failed to create or open sandbox desktop '{self.sandbox_name}'.")

        self._sandbox_handle = h_desk
        sys.stderr.write(f"[VirtualDesktop] Sandbox desktop '{self.sandbox_name}' active (handle={h_desk}).\n")
        return self._sandbox_handle

    def run_in_sandbox(self, func, *args, timeout: float = 10.0, **kwargs):
        """
        Executes a callable inside a dedicated clean worker thread attached to the
        isolated sandbox desktop with Multithreaded Apartment (MTA) COM.
        """
        if not IS_WINDOWS:
            return func(*args, **kwargs)

        import threading
        self.ensure_sandbox()
        result = [None]
        exc = [None]
        desk_handle = [None]

        def target():
            h_desk = user32.OpenDesktopW(self.sandbox_name, 0, False, DESKTOP_ALL)
            if h_desk:
                desk_handle[0] = h_desk
                user32.SetThreadDesktop(h_desk)
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
            raise TimeoutError(f"Sandbox worker thread timed out after {timeout}s.")
        if exc[0]:
            raise exc[0]
        return result[0]

    def launch_in_sandbox(self, command_line: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Launches an application directly onto the isolated sandbox desktop using CreateProcessW.
        The window will not appear on the user's physical screen and will not receive physical clicks.
        """
        if not IS_WINDOWS:
            from control.platform import get_platform_driver
            driver = get_platform_driver()
            return driver.get_app_launcher().launch(command_line)

        self.ensure_sandbox()

        # Bind desktop string to local scope to prevent garbage collection before CreateProcessW runs
        desktop_target = f"WinSta0\\{self.sandbox_name}"
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop = desktop_target
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNORMAL

        pi = PROCESS_INFORMATION()

        cmd_buf = ctypes.create_unicode_buffer(command_line)
        cwd_w = wintypes.LPCWSTR(cwd) if cwd else None

        success = kernel32.CreateProcessW(
            None,
            cmd_buf,
            None,
            None,
            False,
            0,
            None,
            cwd_w,
            ctypes.byref(si),
            ctypes.byref(pi),
        )

        if not success:
            err = ctypes.GetLastError()
            return {
                "status": "error",
                "message": f"CreateProcessW failed with error code {err}",
                "command": command_line,
                "desktop": self.sandbox_name,
            }

        pid = int(pi.dwProcessId)
        self._tracked_pids.append(pid)

        # Close process and thread handles to avoid handle leaks
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)

        # Allow time for initial window creation
        time.sleep(0.3)

        return {
            "status": "launched_in_sandbox",
            "pid": pid,
            "command": command_line,
            "desktop": self.sandbox_name,
            "desktop_mode": "isolated_pip",
        }

    # Backward-compatible alias
    launch_process_in_sandbox = launch_in_sandbox

    def list_sandbox_windows(self) -> List[Dict[str, Any]]:
        """
        Enumerates all top-level windows currently open inside the isolated sandbox desktop.
        """
        if not IS_WINDOWS:
            return []

        def _list():
            h_desk = self.ensure_sandbox()
            windows = []

            def enum_cb(hwnd, lparam):
                if not user32.IsWindow(hwnd):
                    return True
                if not user32.IsWindowVisible(hwnd):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()

                if not title:
                    return True

                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                if w > 0 and h > 0:
                    windows.append({
                        "hwnd": int(hwnd),
                        "title": title,
                        "bounds": [int(rect.left), int(rect.top), int(w), int(h)],
                        "pid": int(pid.value),
                    })
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            cb_func = WNDENUMPROC(enum_cb)
            user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, WNDENUMPROC, wintypes.LPARAM]
            user32.EnumDesktopWindows.restype = wintypes.BOOL
            user32.EnumDesktopWindows(h_desk, cb_func, 0)
            return windows

        return self.run_in_sandbox(_list)

    def capture_sandbox_window(self, hwnd: int) -> Image.Image:
        """
        Captures the visual buffer of a window inside the isolated sandbox using PrintWindow.
        """
        if not IS_WINDOWS:
            return Image.new("RGB", (100, 100), (0, 0, 0))

        def _capture():
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
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

                user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)

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

        return self.run_in_sandbox(_capture)

    def capture_pip_composite(
        self,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
        max_dim: int = 1024,
        quality: int = 75,
        scale: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Picture-in-Picture composite preview of all windows open in the sandbox.
        Renders them onto a simulated dark desktop background and downsamples for token efficiency.
        """
        if not IS_WINDOWS:
            return {
                "status": "unsupported_platform",
                "desktop": self.sandbox_name,
                "mode": self.desktop_mode,
                "windows_count": 0,
                "rendered_windows": 0,
                "width": canvas_width,
                "height": canvas_height,
                "scale": 1.0,
                "image_b64": "",
                "windows": [],
                "message": "Windows PiP sandbox desktop is only available on Windows",
            }
        import io
        import base64

        if scale is not None and scale > 0:
            max_dim = max(100, int(1024 * scale))

        windows = self.list_sandbox_windows()
        # Create dark slate simulated desktop canvas
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(30, 34, 42))

        rendered_count = 0
        for win in windows:
            try:
                hwnd = win["hwnd"]
                bx, by, bw, bh = win["bounds"]
                w_img = self.capture_sandbox_window(hwnd)
                if w_img and w_img.size[0] > 0 and w_img.size[1] > 0:
                    # Clip coordinates inside canvas bounds
                    paste_x = max(0, min(bx, canvas_width - 10))
                    paste_y = max(0, min(by, canvas_height - 10))
                    canvas.paste(w_img, (paste_x, paste_y))
                    rendered_count += 1
            except Exception as e:
                sys.stderr.write(f"[VirtualDesktop] Window render error: {e}\n")

        # Downsample to max_dim preserving aspect ratio
        scale = 1.0
        orig_w, orig_h = canvas.size
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            new_w = int(round(orig_w * scale))
            new_h = int(round(orig_h * scale))
            proc_img = canvas.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            proc_img = canvas

        buf = io.BytesIO()
        proc_img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {
            "status": "pip_preview",
            "desktop": self.sandbox_name,
            "mode": self.desktop_mode,
            "windows_count": len(windows),
            "rendered_windows": rendered_count,
            "width": proc_img.size[0],
            "height": proc_img.size[1],
            "scale": scale,
            "image_b64": b64,
            "windows": windows,
        }

    def close_sandbox_window(self, target: str) -> bool:
        """Sends WM_CLOSE to a window inside the sandbox desktop."""
        if not IS_WINDOWS:
            return False

        target_lower = target.lower()
        windows = self.list_sandbox_windows()
        for win in windows:
            if target_lower in win["title"].lower():
                hwnd = win["hwnd"]
                WM_CLOSE = 0x0010
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True
        return False

    def destroy_sandbox(self) -> Dict[str, Any]:
        """
        Terminates tracked sandbox processes and cleans up desktop handles.
        """
        if not IS_WINDOWS:
            self._tracked_pids.clear()
            self.desktop_mode = "interactive"
            return {
                "status": "destroyed",
                "desktop": self.sandbox_name,
                "mode": "interactive",
            }

        import subprocess
        # Collect any remaining processes owning windows inside the sandbox desktop
        try:
            active_wins = self.list_sandbox_windows()
            for w in active_wins:
                w_pid = w.get("pid")
                if w_pid and w_pid not in self._tracked_pids:
                    self._tracked_pids.append(w_pid)
        except Exception:
            pass

        for pid in list(self._tracked_pids):
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            except Exception:
                pass
        self._tracked_pids.clear()

        if self._sandbox_handle:
            user32.CloseDesktop(self._sandbox_handle)
            self._sandbox_handle = None

        self.desktop_mode = "interactive"
        return {
            "status": "destroyed",
            "desktop": self.sandbox_name,
            "mode": "interactive",
        }


# Global default instance
default_virtual_desktop = VirtualDesktopManager()
