"""
High-Performance Win32 Native Clipboard Bridge.
Provides instantaneous text retrieval, text injection, and simulated paste (Ctrl+V)
without layout mismatches or dropped keystrokes.
"""

import ctypes
from ctypes import wintypes
import time
import sys
from control.keyboard_engine import default_keyboard
from control.safety import default_governor

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
GHND = GMEM_MOVEABLE | GMEM_ZEROINIT

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [ctypes.c_uint, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _open_clipboard_with_retry(max_retries: int = 5, delay: float = 0.02) -> bool:
    """Attempts to open clipboard with short retries to handle brief locks by other apps."""
    for _ in range(max_retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


class ClipboardManager:
    """Win32 Native Clipboard Interface."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def get_text(self) -> str:
        """Returns the current plain/Unicode text on the system clipboard."""
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""

        if not _open_clipboard_with_retry():
            return ""

        try:
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if not h_data:
                return ""

            p_data = kernel32.GlobalLock(h_data)
            if not p_data:
                return ""

            try:
                text = ctypes.wstring_at(p_data)
                return text
            finally:
                kernel32.GlobalUnlock(h_data)
        finally:
            user32.CloseClipboard()

    def set_text(self, text: str) -> bool:
        """Sets Unicode text onto the system clipboard."""
        if not _open_clipboard_with_retry():
            return False

        try:
            user32.EmptyClipboard()
            # String length including null terminator in bytes (wchar_t is 2 bytes on Windows)
            encoded_bytes = (text + "\0").encode("utf-16le")
            size = len(encoded_bytes)

            h_mem = kernel32.GlobalAlloc(GHND, size)
            if not h_mem:
                return False

            p_mem = kernel32.GlobalLock(h_mem)
            if not p_mem:
                kernel32.GlobalFree(h_mem)
                return False

            try:
                ctypes.memmove(p_mem, encoded_bytes, size)
            finally:
                kernel32.GlobalUnlock(h_mem)

            res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            if not res:
                kernel32.GlobalFree(h_mem)
                return False
            return True
        finally:
            user32.CloseClipboard()

    def paste(self, text: str, restore_clipboard: bool = False) -> bool:
        """
        Instantaneously injects text by copying it to clipboard and simulating Ctrl+V.
        Orders of magnitude faster than simulating character-by-character key events
        and completely immune to layout mismatches or dropped keystrokes.
        """
        self.governor.pre_action()

        old_text = None
        if restore_clipboard:
            try:
                old_text = self.get_text()
            except Exception:
                old_text = None

        success = self.set_text(text)
        if not success:
            return False

        time.sleep(0.02)
        default_keyboard.hotkey("ctrl", "v")
        time.sleep(0.04)

        if restore_clipboard and old_text is not None:
            time.sleep(0.1)
            self.set_text(old_text)

        self.governor.post_action()
        return True


default_clipboard = ClipboardManager()
