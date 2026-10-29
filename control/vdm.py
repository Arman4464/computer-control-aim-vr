"""
Windows 10/11 Task View Virtual Desktop Manager (AIM-VR 3.0 Control Subsystem).
Interfaces with the Windows COM IVirtualDesktopManager interface to determine whether
application windows are situated on the user's active virtual desktop.
"""

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

ole32 = ctypes.windll.ole32

# Configure CoInitialize and CoCreateInstance signatures
ole32.CoInitialize.argtypes = [ctypes.c_void_p]
ole32.CoInitialize.restype = ctypes.c_long

ole32.CoCreateInstance.argtypes = [
    ctypes.c_void_p,                 # rclsid
    ctypes.c_void_p,                 # pUnkOuter
    ctypes.c_ulong,                  # dwClsContext
    ctypes.c_void_p,                 # riid
    ctypes.POINTER(ctypes.c_void_p)  # ppv
]
ole32.CoCreateInstance.restype = ctypes.c_long

# Standard COM CLSIDs and IIDs for IVirtualDesktopManager
CLSID_VirtualDesktopManager = "{aa509086-5ca9-4c25-8f95-589d3c07b48a}"
IID_IVirtualDesktopManager = "{a5cd92ff-29be-454c-8d04-d82879fb3f1b}"

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8)
    ]

def _guid_from_str(guid_str: str) -> GUID:
    clean = guid_str.strip("{}").replace("-", "")
    data1 = int(clean[0:8], 16)
    data2 = int(clean[8:12], 16)
    data3 = int(clean[12:16], 16)
    data4 = (ctypes.c_ubyte * 8)(*(int(clean[i:i+2], 16) for i in range(16, 32, 2)))
    return GUID(data1, data2, data3, data4)

CLSCTX_INPROC_SERVER = 0x1

_local_storage = threading.local()


class VirtualDesktopManager:
    """Provides querying and filtering of Windows 10/11 virtual desktops with STA thread-safety."""

    def _ensure_vdm(self) -> Optional[ctypes.c_void_p]:
        ptr = getattr(_local_storage, "vdm_ptr", None)
        if ptr is not None and ptr.value:
            return ptr

        try:
            ole32.CoInitialize(None)
        except Exception:
            pass

        clsid = _guid_from_str(CLSID_VirtualDesktopManager)
        iid = _guid_from_str(IID_IVirtualDesktopManager)
        new_ptr = ctypes.c_void_p()

        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(iid),
            ctypes.byref(new_ptr)
        )
        if hr == 0 and new_ptr.value:
            _local_storage.vdm_ptr = new_ptr
            return new_ptr
        else:
            _local_storage.vdm_ptr = None
            return None

    def release(self):
        """Releases the thread-local COM instance if present."""
        ptr = getattr(_local_storage, "vdm_ptr", None)
        if ptr and ptr.value:
            try:
                vtable_ptr = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                release_fn_type = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
                release_fn = release_fn_type(vtable_ptr.contents[2])
                release_fn(ptr)
            except Exception:
                pass
            _local_storage.vdm_ptr = None

    def is_window_on_current_desktop(self, hwnd: int) -> bool:
        """
        Returns True if the given top-level window HWND resides on the active virtual desktop.
        Returns True as fallback if VirtualDesktopManager COM service is unavailable.
        """
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            return False

        try:
            ptr = self._ensure_vdm()
            if not ptr:
                return True

            # IVirtualDesktopManager vtable:
            # 0: QueryInterface, 1: AddRef, 2: Release
            # 3: IsWindowOnCurrentVirtualDesktop(HWND, BOOL*)
            vtable_ptr = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
            is_on_cur_fn_type = ctypes.WINFUNCTYPE(
                ctypes.c_long,  # HRESULT
                ctypes.c_void_p,  # this
                wintypes.HWND,  # topLevelWindow
                ctypes.POINTER(wintypes.BOOL)  # onCurrentDesktop
            )
            is_on_cur_fn = is_on_cur_fn_type(vtable_ptr.contents[3])

            on_current = wintypes.BOOL(0)
            hr = is_on_cur_fn(ptr, wintypes.HWND(hwnd), ctypes.byref(on_current))
            if hr == 0:
                return bool(on_current.value)
            return True
        except Exception:
            return True


default_vdm = VirtualDesktopManager()
