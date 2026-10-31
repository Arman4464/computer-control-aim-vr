"""
Low-Level Linux Kernel /dev/uinput Input Driver with Wayland Fallbacks (Arch Linux Hyprland).
Emits virtual input events through Linux kernel /dev/uinput (via evdev), with
seamless fallback to wtype (virtual-keyboard-v1), ydotool, and Hyprland dispatchers.
"""

import os
import sys
import time
import shutil
import subprocess
from typing import Optional, Tuple, Dict, Any, List

from control.platform.base import BaseInputEngine
from control.platform.hyprland.hyprland_ipc import HyprlandIPC, default_hyprland_ipc

# Linux Kernel Input Event Codes (linux/input-event-codes.h)
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT = 0

# Relative axes
REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08
REL_HWHEEL = 0x06

# Mouse buttons
BTN_MOUSE = 0x110
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

# Standard Keycodes
KEY_RESERVED = 0
KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_6 = 7
KEY_7 = 8
KEY_8 = 9
KEY_9 = 10
KEY_0 = 11
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_Q = 16
KEY_W = 17
KEY_E = 18
KEY_R = 19
KEY_T = 20
KEY_Y = 21
KEY_U = 22
KEY_I = 23
KEY_O = 24
KEY_P = 25
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_SEMICOLON = 39
KEY_APOSTROPHE = 40
KEY_GRAVE = 41
KEY_LEFTSHIFT = 42
KEY_BACKSLASH = 43
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_COMMA = 51
KEY_DOT = 52
KEY_SLASH = 53
KEY_RIGHTSHIFT = 54
KEY_KPASTERISK = 55
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_CAPSLOCK = 58
KEY_F1 = 59
KEY_F2 = 60
KEY_F3 = 61
KEY_F4 = 62
KEY_F5 = 63
KEY_F6 = 64
KEY_F7 = 65
KEY_F8 = 66
KEY_F9 = 67
KEY_F10 = 68
KEY_NUMLOCK = 69
KEY_SCROLLLOCK = 70
KEY_KP7 = 71
KEY_KP8 = 72
KEY_KP9 = 73
KEY_KPMINUS = 74
KEY_KP4 = 75
KEY_KP5 = 76
KEY_KP6 = 77
KEY_KPPLUS = 78
KEY_KP1 = 79
KEY_KP2 = 80
KEY_KP3 = 81
KEY_KP0 = 82
KEY_KPDOT = 83
KEY_F11 = 87
KEY_F12 = 88
KEY_KPENTER = 96
KEY_RIGHTCTRL = 97
KEY_KPSLASH = 98
KEY_SYSRQ = 99
KEY_RIGHTALT = 100
KEY_HOME = 102
KEY_UP = 103
KEY_PAGEUP = 104
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_END = 107
KEY_DOWN = 108
KEY_PAGEDOWN = 109
KEY_INSERT = 110
KEY_DELETE = 111
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126
KEY_PLAYPAUSE = 164
KEY_NEXTSONG = 163
KEY_PREVIOUSSONG = 165
KEY_STOPCD = 166

# Human-readable key name to Linux scancode
LINUX_KEY_MAP = {
    # Modifiers
    "ctrl": KEY_LEFTCTRL,
    "control": KEY_LEFTCTRL,
    "left_ctrl": KEY_LEFTCTRL,
    "right_ctrl": KEY_RIGHTCTRL,
    "shift": KEY_LEFTSHIFT,
    "left_shift": KEY_LEFTSHIFT,
    "right_shift": KEY_RIGHTSHIFT,
    "alt": KEY_LEFTALT,
    "left_alt": KEY_LEFTALT,
    "right_alt": KEY_RIGHTALT,
    "super": KEY_LEFTMETA,
    "win": KEY_LEFTMETA,
    "windows": KEY_LEFTMETA,
    "meta": KEY_LEFTMETA,
    "left_super": KEY_LEFTMETA,
    "right_super": KEY_RIGHTMETA,

    # Control keys
    "enter": KEY_ENTER,
    "return": KEY_ENTER,
    "tab": KEY_TAB,
    "space": KEY_SPACE,
    "backspace": KEY_BACKSPACE,
    "esc": KEY_ESC,
    "escape": KEY_ESC,
    "delete": KEY_DELETE,
    "del": KEY_DELETE,
    "insert": KEY_INSERT,
    "home": KEY_HOME,
    "end": KEY_END,
    "pageup": KEY_PAGEUP,
    "page_up": KEY_PAGEUP,
    "pagedown": KEY_PAGEDOWN,
    "page_down": KEY_PAGEDOWN,
    "capslock": KEY_CAPSLOCK,
    "caps_lock": KEY_CAPSLOCK,
    "printscreen": KEY_SYSRQ,
    "prtscn": KEY_SYSRQ,

    # Directional
    "up": KEY_UP,
    "down": KEY_DOWN,
    "left": KEY_LEFT,
    "right": KEY_RIGHT,

    # Function keys
    "f1": KEY_F1, "f2": KEY_F2, "f3": KEY_F3, "f4": KEY_F4,
    "f5": KEY_F5, "f6": KEY_F6, "f7": KEY_F7, "f8": KEY_F8,
    "f9": KEY_F9, "f10": KEY_F10, "f11": KEY_F11, "f12": KEY_F12,

    # Media keys
    "volume_up": KEY_VOLUMEUP,
    "volume_down": KEY_VOLUMEDOWN,
    "volume_mute": KEY_MUTE,
    "mute": KEY_MUTE,
    "play_pause": KEY_PLAYPAUSE,
    "next_track": KEY_NEXTSONG,
    "prev_track": KEY_PREVIOUSSONG,

    # Punctuation & symbols
    "-": KEY_MINUS, "minus": KEY_MINUS,
    "=": KEY_EQUAL, "equal": KEY_EQUAL,
    "[": KEY_LEFTBRACE, "]": KEY_RIGHTBRACE,
    "\\": KEY_BACKSLASH, ";": KEY_SEMICOLON,
    "'": KEY_APOSTROPHE, "`": KEY_GRAVE,
    ",": KEY_COMMA, ".": KEY_DOT, "/": KEY_SLASH,
}

# Add standard letters and numbers to map
for c in "abcdefghijklmnopqrstuvwxyz":
    code = globals().get(f"KEY_{c.upper()}")
    if code:
        LINUX_KEY_MAP[c] = code
for d in "0123456789":
    code = globals().get(f"KEY_{d}")
    if code:
        LINUX_KEY_MAP[d] = code

KEY_MAP_NAME_TO_CODE = LINUX_KEY_MAP



class UInputEngine(BaseInputEngine):
    """
    Linux /dev/uinput Driver with Wayland/Hyprland dispatch fallbacks.
    """

    def __init__(self, ipc: Optional[HyprlandIPC] = None):
        self.ipc = ipc or default_hyprland_ipc
        self._uinput_device = None
        self._has_evdev = False
        self._uinput_initialized = False
        self._cursor_x = 0
        self._cursor_y = 0
        self._virtual_pointer = None
        try:
            from control.platform.hyprland.wayland_virtual_pointer import default_virtual_pointer
            self._virtual_pointer = default_virtual_pointer
        except Exception:
            self._virtual_pointer = None
        self._init_uinput()

    def _init_uinput(self):
        """Attempts to initialize Linux kernel /dev/uinput virtual device via evdev."""
        if not sys.platform.startswith("linux"):
            return

        try:
            import evdev
            self._has_evdev = True
            if os.path.exists("/dev/uinput") and os.access("/dev/uinput", os.W_OK):
                capabilities = {
                    evdev.ecodes.EV_REL: [
                        evdev.ecodes.REL_X,
                        evdev.ecodes.REL_Y,
                        evdev.ecodes.REL_WHEEL,
                        evdev.ecodes.REL_HWHEEL,
                    ],
                    evdev.ecodes.EV_KEY: [
                        evdev.ecodes.BTN_LEFT,
                        evdev.ecodes.BTN_RIGHT,
                        evdev.ecodes.BTN_MIDDLE,
                        evdev.ecodes.BTN_SIDE,
                        evdev.ecodes.BTN_EXTRA,
                    ] + list(LINUX_KEY_MAP.values()),
                }
                self._uinput_device = evdev.UInput(capabilities, name="AIMVR-Virtual-Input")
                self._uinput_initialized = True
                sys.stderr.write("[UInputEngine] Successfully opened /dev/uinput virtual input device.\n")
            else:
                sys.stderr.write(
                    "[UInputEngine] /dev/uinput is not writable by current user. Falling back to Hyprland dispatchers & wtype.\n"
                    "Tip: Set up udev rule /etc/udev/rules.d/99-aimvr-uinput.rules and add user to 'input' group.\n"
                )
        except Exception as e:
            sys.stderr.write(f"[UInputEngine] evdev /dev/uinput initialization failed: {e}\n")

    def _get_button_code(self, button: str) -> int:
        btn = button.lower().strip()
        if btn == "right":
            return BTN_RIGHT
        elif btn == "middle":
            return BTN_MIDDLE
        return BTN_LEFT

    def _get_ydotool_btn(self, button: str) -> int:
        btn = button.lower().strip()
        if btn == "right":
            return 0x01
        elif btn == "middle":
            return 0x02
        return 0x00

    def move_cursor(self, x: int, y: int) -> Tuple[int, int]:
        """
        Moves cursor to absolute coordinates (x, y).
        Uses Hyprland dispatcher 'movecursor <x> <y>' for instant hardware-synchronized positioning.
        """
        self._cursor_x = int(x)
        self._cursor_y = int(y)

        # Primary method: Hyprland dispatch movecursor
        try:
            self.ipc.dispatch("movecursor", str(self._cursor_x), str(self._cursor_y))
            return self._cursor_x, self._cursor_y
        except Exception:
            pass

        # SOTA Wayland Protocol Fallback: zwlr_virtual_pointer_v1
        if self._virtual_pointer and self._virtual_pointer.is_available():
            try:
                self._virtual_pointer.move_absolute(self._cursor_x, self._cursor_y)
                return self._cursor_x, self._cursor_y
            except Exception:
                pass

        # Fallback: ydotool mousemove --absolute
        if shutil.which("ydotool"):
            try:
                subprocess.run(
                    ["ydotool", "mousemove", "-a", str(self._cursor_x), str(self._cursor_y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5
                )
            except Exception:
                pass

        return self._cursor_x, self._cursor_y

    def get_position(self) -> Tuple[int, int]:
        """
        Returns the current cursor position (x, y).
        Queries Hyprland IPC cursorpos or cached value.
        """
        try:
            cursor_info = self.ipc.query_json("cursorpos")
            if isinstance(cursor_info, dict) and "x" in cursor_info and "y" in cursor_info:
                self._cursor_x = int(cursor_info["x"])
                self._cursor_y = int(cursor_info["y"])
                return self._cursor_x, self._cursor_y
            elif isinstance(cursor_info, str) and "," in cursor_info:
                clean = cursor_info.replace("at:", "").strip()
                px, py = clean.split(",", 1)
                self._cursor_x = int(px.strip())
                self._cursor_y = int(py.strip())
                return self._cursor_x, self._cursor_y
        except Exception:
            pass
        return self._cursor_x, self._cursor_y

    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        btn_code = self._get_button_code(button)

        # Primary SOTA Wayland Protocol: unprivileged zwlr_virtual_pointer_v1
        if self._virtual_pointer and self._virtual_pointer.is_available():
            try:
                self._virtual_pointer.button_down(btn_code)
                return self.get_position()
            except Exception:
                pass

        if self._uinput_device:
            self._uinput_device.write(EV_KEY, btn_code, 1)
            self._uinput_device.syn()
            return self.get_position()

        # Fallback: ydotool (0x40 = down)
        if shutil.which("ydotool"):
            btn_id = self._get_ydotool_btn(button)
            mask = hex(0x40 | btn_id)
            subprocess.run(["ydotool", "click", mask], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return self.get_position()

    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Tuple[int, int]:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        btn_code = self._get_button_code(button)

        # Primary SOTA Wayland Protocol: unprivileged zwlr_virtual_pointer_v1
        if self._virtual_pointer and self._virtual_pointer.is_available():
            try:
                self._virtual_pointer.button_up(btn_code)
                return self.get_position()
            except Exception:
                pass

        if self._uinput_device:
            self._uinput_device.write(EV_KEY, btn_code, 0)
            self._uinput_device.syn()
            return self.get_position()

        # Fallback: ydotool (0x80 = up)
        if shutil.which("ydotool"):
            btn_id = self._get_ydotool_btn(button)
            mask = hex(0x80 | btn_id)
            subprocess.run(["ydotool", "click", mask], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return self.get_position()

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> Tuple[int, int]:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        btn_code = self._get_button_code(button)

        # Primary SOTA Wayland Protocol: unprivileged zwlr_virtual_pointer_v1
        if self._virtual_pointer and self._virtual_pointer.is_available():
            try:
                self._virtual_pointer.click(btn_code, clicks=clicks)
                return self.get_position()
            except Exception:
                pass

        # Direct ydotool atomic click fallback (0xC0 = down | up)
        if not self._uinput_device and shutil.which("ydotool"):
            btn_id = self._get_ydotool_btn(button)
            mask = hex(0xC0 | btn_id)
            for i in range(max(1, clicks)):
                if i > 0:
                    time.sleep(0.04)
                subprocess.run(["ydotool", "click", mask], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.get_position()

        for _ in range(max(1, clicks)):
            self.mouse_down(button=button)
            time.sleep(0.02)
            self.mouse_up(button=button)
            if clicks > 1:
                time.sleep(0.05)

        return self.get_position()

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", duration: float = 0.5) -> Tuple[int, int]:
        self.move_cursor(start_x, start_y)
        time.sleep(0.05)
        self.mouse_down(button=button)
        time.sleep(0.05)

        steps = max(10, int(duration * 60))
        for i in range(1, steps + 1):
            t = i / steps
            cx = int(start_x + (end_x - start_x) * t)
            cy = int(start_y + (end_y - start_y) * t)
            self.move_cursor(cx, cy)
            time.sleep(duration / steps)

        time.sleep(0.05)
        self.mouse_up(button=button)
        return end_x, end_y

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        # Primary SOTA Wayland Protocol: unprivileged zwlr_virtual_pointer_v1
        if self._virtual_pointer and self._virtual_pointer.is_available():
            try:
                self._virtual_pointer.axis_scroll(clicks)
                return
            except Exception:
                pass

        if self._uinput_device:
            val = int(clicks)
            self._uinput_device.write(EV_REL, REL_WHEEL, val)
            self._uinput_device.syn()
            return

        # Fallback: ydotool mousemove -w -- 0 <vert_steps>
        if shutil.which("ydotool"):
            vert_steps = -int(clicks)
            subprocess.run(
                ["ydotool", "mousemove", "-w", "--", "0", str(vert_steps)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    def key_down(self, key: str) -> None:
        clean = key.lower().strip()
        code = LINUX_KEY_MAP.get(clean)
        if code and self._uinput_device:
            self._uinput_device.write(EV_KEY, code, 1)
            self._uinput_device.syn()
            return

        # Fallback: ydotool key <code:1>
        if code and shutil.which("ydotool"):
            subprocess.run(["ydotool", "key", f"{code}:1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key_up(self, key: str) -> None:
        clean = key.lower().strip()
        code = LINUX_KEY_MAP.get(clean)
        if code and self._uinput_device:
            self._uinput_device.write(EV_KEY, code, 0)
            self._uinput_device.syn()
            return

        # Fallback: ydotool key <code:0>
        if code and shutil.which("ydotool"):
            subprocess.run(["ydotool", "key", f"{code}:0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def press_key(self, key: str) -> None:
        self.key_down(key)
        time.sleep(0.02)
        self.key_up(key)

    def hotkey(self, *keys: str) -> None:
        if not keys:
            return
        # Press down in order
        for k in keys:
            self.key_down(k)
            time.sleep(0.01)
        time.sleep(0.02)
        # Release in reverse order
        for k in reversed(keys):
            self.key_up(k)
            time.sleep(0.01)

    def type_text(self, text: str, interval: float = 0.01) -> None:
        """
        Types text using:
        1. wtype (Wayland virtual-keyboard protocol) - Best Unicode and layout support.
        2. ydotool type (if ydotool daemon is running).
        3. wl-copy + Ctrl+V clipboard paste fallback.
        4. uinput scancodes for standard ASCII chars.
        """
        if not text:
            return

        # Method 1: wtype (Standard on Arch Wayland / Hyprland)
        if shutil.which("wtype"):
            try:
                subprocess.run(["wtype", "-d", str(int(interval * 1000)), "--", text], timeout=10.0, check=True)
                return
            except Exception:
                pass

        # Method 2: ydotool
        if shutil.which("ydotool"):
            try:
                subprocess.run(["ydotool", "type", "-d", str(int(interval * 1000)), "--", text], timeout=10.0, check=True)
                return
            except Exception:
                pass

        # Method 3: wl-copy + ctrl+v synthetic paste
        if shutil.which("wl-copy"):
            try:
                proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"), timeout=2.0)
                time.sleep(0.05)
                self.hotkey("ctrl", "v")
                return
            except Exception:
                pass

        # Method 4: Scancode typing via uinput
        if self._uinput_device:
            for ch in text:
                lower = ch.lower()
                is_upper = ch.isupper()
                code = LINUX_KEY_MAP.get(lower)
                if code:
                    if is_upper:
                        self.key_down("shift")
                    self.press_key(lower)
                    if is_upper:
                        self.key_up("shift")
                elif ch == " ":
                    self.press_key("space")
                elif ch == "\n":
                    self.press_key("enter")
                if interval > 0:
                    time.sleep(interval)
