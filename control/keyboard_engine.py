"""
High-Performance Win32 Keyboard Engine using SendInput with Hardware Scan Codes
(KEYEVENTF_SCANCODE) for hotkeys and Unicode (KEYEVENTF_UNICODE) for text typing.
"""

import ctypes
from ctypes import wintypes
import time
import sys
from control.mouse_engine import (
    INPUT,
    KEYBDINPUT,
    INPUT_KEYBOARD,
    ULONG_PTR,
    user32
)
from control.safety import default_governor

user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
user32.MapVirtualKeyW.restype = ctypes.c_uint
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ULONG_PTR]
user32.keybd_event.restype = None

# Win32 Keyboard Event Flags
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MAPVK_VK_TO_VSC = 0

# Mapping of common key names to Virtual Key Codes (VK_*)
VK_MAP = {
    # Modifiers
    "ctrl": 0x11,
    "control": 0x11,
    "left_ctrl": 0xA2,
    "right_ctrl": 0xA3,
    "shift": 0x10,
    "left_shift": 0xA0,
    "right_shift": 0xA1,
    "alt": 0x12,
    "menu": 0x12,
    "left_alt": 0xA4,
    "right_alt": 0xA5,
    "win": 0x5B,
    "windows": 0x5B,
    "left_win": 0x5B,
    "right_win": 0x5C,

    # Control Keys
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "esc": 0x1B,
    "escape": 0x1B,
    "capslock": 0x14,
    "caps_lock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "printscreen": 0x2C,
    "prtscn": 0x2C,
    "pause": 0x13,

    # Navigation / Editing
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "pgup": 0x21,
    "pgdn": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,

    # Function Keys
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,

    # Punctuation & Symbols (OEM keys)
    ".": 0xBE, "period": 0xBE, "dot": 0xBE,
    ",": 0xBC, "comma": 0xBC,
    "-": 0xBD, "minus": 0xBD, "dash": 0xBD,
    "=": 0xBB, "equal": 0xBB, "equals": 0xBB, "plus": 0xBB,
    ";": 0xBA, "semicolon": 0xBA,
    "/": 0xBF, "slash": 0xBF, "forward_slash": 0xBF,
    "`": 0xC0, "backtick": 0xC0, "grave": 0xC0,
    "[": 0xDB, "open_bracket": 0xDB, "bracket_left": 0xDB,
    "\\": 0xDC, "backslash": 0xDC,
    "]": 0xDD, "close_bracket": 0xDD, "bracket_right": 0xDD,
    "'": 0xDE, "quote": 0xDE, "single_quote": 0xDE, "apostrophe": 0xDE,
}

# Extended keys that require KEYEVENTF_EXTENDEDKEY flag
EXTENDED_VKS = {
    0x25, 0x26, 0x27, 0x28,  # Arrows: Left, Up, Right, Down
    0x2D, 0x2E,              # Insert, Delete
    0x24, 0x23,              # Home, End
    0x21, 0x22,              # PageUp, PageDown
    0x5B, 0x5C,              # Left/Right Win
    0xA3, 0xA5,              # Right Ctrl, Right Alt
    0x2C,                    # PrintScreen
    0x90,                    # NumLock
    0x6F,                    # Divide
}


def _send_key_input(vk: int, scan: int, flags: int):
    """Sends a single keyboard event via SendInput with both VK and scan code preserved."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wVk = vk
    inp.u.ki.wScan = scan
    inp.u.ki.dwFlags = flags
    inp.u.ki.time = 0
    inp.u.ki.dwExtraInfo = 0
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        # Fallback to user32.keybd_event to bypass background UIPI blocks
        user32.keybd_event(vk, scan, flags, 0)


def get_vk_and_scan(key_name: str) -> tuple[int, int, bool]:
    """
    Resolves key name into (vk_code, scan_code, is_extended).
    Accurately maps alphanumeric keys, punctuation symbols, and special keys.
    """
    clean_name = key_name.lower().strip()
    if clean_name in VK_MAP:
        vk = VK_MAP[clean_name]
    elif len(clean_name) == 1:
        if "a" <= clean_name <= "z" or "0" <= clean_name <= "9":
            vk = ord(clean_name.upper())
        else:
            # Punctuation/symbol conversion via Windows VkKeyScanW
            vks = user32.VkKeyScanW(ord(clean_name))
            if vks != -1 and vks != 0xFFFF:
                vk = vks & 0xFF
            else:
                raise ValueError(f"Unknown key or unmappable symbol: {key_name}")
    else:
        raise ValueError(f"Unknown key: {key_name}")

    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    is_extended = vk in EXTENDED_VKS
    return vk, scan, is_extended


class KeyboardEngine:
    """High-level keyboard control interface."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def _raw_key_down(self, key_name: str):
        vk, scan, is_ext = get_vk_and_scan(key_name)
        flags = KEYEVENTF_SCANCODE if scan != 0 else 0
        if is_ext:
            flags |= KEYEVENTF_EXTENDEDKEY
        _send_key_input(vk, scan, flags)

    def _raw_key_up(self, key_name: str):
        vk, scan, is_ext = get_vk_and_scan(key_name)
        flags = (KEYEVENTF_SCANCODE if scan != 0 else 0) | KEYEVENTF_KEYUP
        if is_ext:
            flags |= KEYEVENTF_EXTENDEDKEY
        _send_key_input(vk, scan, flags)

    def key_down(self, key_name: str):
        """Sends a hardware scan-code KEYDOWN event."""
        self.governor.pre_action()
        self._raw_key_down(key_name)

    def key_up(self, key_name: str):
        """Sends a hardware scan-code KEYUP event."""
        self._raw_key_up(key_name)
        self.governor.post_action()

    def press_key(self, key_name: str, duration: float = 0.02):
        """Presses and releases a single key."""
        self.governor.pre_action()
        # For single printable non-alphanumeric characters, send via Unicode input for 100% fidelity without shift loss
        if len(key_name) == 1 and not ("a" <= key_name.lower() <= "z" or "0" <= key_name <= "9"):
            utf16_bytes = key_name.encode("utf-16-le")
            for i in range(0, len(utf16_bytes), 2):
                code_unit = utf16_bytes[i] | (utf16_bytes[i + 1] << 8)
                _send_key_input(0, code_unit, KEYEVENTF_UNICODE)
                time.sleep(duration)
                _send_key_input(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        else:
            self._raw_key_down(key_name)
            time.sleep(duration)
            self._raw_key_up(key_name)
        self.governor.post_action()

    def hotkey(self, *keys: str, duration: float = 0.04):
        """
        Presses multiple keys simultaneously in sequence, waits duration,
        then releases them in reverse order.
        Example: hotkey("ctrl", "shift", "p") or hotkey("win", "r")
        """
        self.governor.pre_action()
        pressed_keys = []
        try:
            for k in keys:
                self._raw_key_down(k)
                pressed_keys.append(k)
                time.sleep(0.01)

            time.sleep(duration)
        finally:
            # Release in reverse order without intervening governor sleeps
            for k in reversed(pressed_keys):
                try:
                    self._raw_key_up(k)
                    time.sleep(0.01)
                except Exception:
                    pass
            # Universal failsafe: ensure all standard modifiers are physically released
            EXTENDED_MODS = {0x5B, 0x5C, 0xA3, 0xA5}
            for mod_vk in (0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5, 0x10, 0xA0, 0xA1, 0x5B, 0x5C):
                flags = KEYEVENTF_KEYUP
                if mod_vk in EXTENDED_MODS:
                    flags |= KEYEVENTF_EXTENDEDKEY
                user32.keybd_event(mod_vk, 0, flags, 0)
        self.governor.post_action()

    def type_text(self, text: str, interval: float = 0.01):
        """
        Types text using layout-independent Unicode events (KEYEVENTF_UNICODE).
        Guarantees that characters, symbols, and multilingual text type correctly
        regardless of active keyboard layout. Supports UTF-16 surrogate pairs (emojis).
        """
        self.governor.pre_action()
        # Normalize CRLF to prevent double-enter execution
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        for char in normalized_text:
            if char == "\n":
                self.press_key("enter")
            elif char == "\t":
                self.press_key("tab")
            else:
                # UTF-16LE encoding to handle both BMP and supplementary characters (surrogate pairs)
                utf16_bytes = char.encode("utf-16-le")
                for i in range(0, len(utf16_bytes), 2):
                    code_unit = utf16_bytes[i] | (utf16_bytes[i + 1] << 8)
                    # Key down
                    _send_key_input(0, code_unit, KEYEVENTF_UNICODE)
                    time.sleep(0.001)
                    # Key up
                    _send_key_input(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
            if interval > 0:
                time.sleep(interval)
        self.governor.post_action()


default_keyboard = KeyboardEngine()
