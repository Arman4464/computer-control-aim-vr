"""
System Audio and Media Playback Controller (AIM-VR 3.0 Control Subsystem).
Provides hardware-level volume adjustment and media playback control (Play/Pause, Tracks)
without disturbing active foreground windows or workspace context, supporting both Windows and Linux.
"""

import sys
import os
import shutil
import subprocess
import time
from control.safety import default_governor, IS_WINDOWS

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    from control.mouse_engine import ULONG_PTR

    user32 = ctypes.windll.user32
    user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ULONG_PTR]
    user32.keybd_event.restype = None

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
else:
    user32 = None

# Multimedia Virtual Keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3


def _send_media_key(action_name: str, vk_code: int):
    """Sends media action across Windows or Linux."""
    if IS_WINDOWS:
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        time.sleep(0.015)
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        return

    # On Linux: try playerctl first for media controls
    if shutil.which("playerctl") and action_name in ["play_pause", "next_track", "prev_track", "stop"]:
        cmd_map = {
            "play_pause": "play-pause",
            "next_track": "next",
            "prev_track": "previous",
            "stop": "stop",
        }
        try:
            subprocess.run(["playerctl", cmd_map[action_name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass

    # Try input engine key press
    key_map = {
        "volume_up": "volume_up",
        "volume_down": "volume_down",
        "toggle_mute": "mute",
        "play_pause": "play_pause",
        "next_track": "next_track",
        "prev_track": "prev_track",
    }
    k = key_map.get(action_name)
    if k:
        try:
            from control.platform import get_platform_driver
            get_platform_driver().input.press_key(k)
        except Exception:
            pass


class MediaController:
    """Controls system master volume and media playback."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def volume_up(self, steps: int = 1):
        """Increases system volume by the specified number of steps (each step ~2%)."""
        self.governor.pre_action()
        for i in range(max(1, steps)):
            _send_media_key("volume_up", VK_VOLUME_UP)
            time.sleep(0.02)
        self.governor.post_action()
        return {"action": "volume_up", "steps": steps}

    def volume_down(self, steps: int = 1):
        """Decreases system volume by the specified number of steps (each step ~2%)."""
        self.governor.pre_action()
        for i in range(max(1, steps)):
            _send_media_key("volume_down", VK_VOLUME_DOWN)
            time.sleep(0.02)
        self.governor.post_action()
        return {"action": "volume_down", "steps": steps}

    def toggle_mute(self):
        """Toggles system audio mute on/off."""
        self.governor.pre_action()
        _send_media_key("toggle_mute", VK_VOLUME_MUTE)
        self.governor.post_action()
        return {"action": "toggle_mute"}

    def play_pause(self):
        """Toggles media play/pause on active player."""
        self.governor.pre_action()
        _send_media_key("play_pause", VK_MEDIA_PLAY_PAUSE)
        self.governor.post_action()
        return {"action": "play_pause"}

    def next_track(self):
        """Skips to the next media track."""
        self.governor.pre_action()
        _send_media_key("next_track", VK_MEDIA_NEXT_TRACK)
        self.governor.post_action()
        return {"action": "next_track"}

    def prev_track(self):
        """Returns to the previous media track."""
        self.governor.pre_action()
        _send_media_key("prev_track", VK_MEDIA_PREV_TRACK)
        self.governor.post_action()
        return {"action": "prev_track"}

    def stop(self):
        """Stops active media playback."""
        self.governor.pre_action()
        _send_media_key("stop", VK_MEDIA_STOP)
        self.governor.post_action()
        return {"action": "stop"}


default_media_controller = MediaController()
