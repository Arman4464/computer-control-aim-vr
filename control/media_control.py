"""
Windows System Audio and Media Playback Controller.
Provides hardware-level volume adjustment and media playback control (Play/Pause, Tracks)
without disturbing active foreground windows or workspace context.
"""

import ctypes
from ctypes import wintypes
import time
from control.safety import default_governor
from control.mouse_engine import ULONG_PTR

user32 = ctypes.windll.user32
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ULONG_PTR]
user32.keybd_event.restype = None

# Win32 Multimedia Virtual Keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


def _send_media_key(vk_code: int):
    """Sends keydown and keyup for a multimedia virtual key."""
    user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
    time.sleep(0.015)
    user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


class MediaController:
    """Controls system master volume and media playback."""

    def __init__(self, governor=None):
        self.governor = governor or default_governor

    def volume_up(self, steps: int = 1):
        """Increases system volume by the specified number of steps (each step ~2%)."""
        self.governor.pre_action()
        for i in range(max(1, steps)):
            _send_media_key(VK_VOLUME_UP)
            time.sleep(0.02)
        self.governor.post_action()
        return {"action": "volume_up", "steps": steps}

    def volume_down(self, steps: int = 1):
        """Decreases system volume by the specified number of steps (each step ~2%)."""
        self.governor.pre_action()
        for i in range(max(1, steps)):
            _send_media_key(VK_VOLUME_DOWN)
            time.sleep(0.02)
        self.governor.post_action()
        return {"action": "volume_down", "steps": steps}

    def toggle_mute(self):
        """Toggles system audio mute on/off."""
        self.governor.pre_action()
        _send_media_key(VK_VOLUME_MUTE)
        self.governor.post_action()
        return {"action": "toggle_mute"}

    def play_pause(self):
        """Toggles media play/pause on the active media session (Spotify, YouTube, VLC, etc.)."""
        self.governor.pre_action()
        _send_media_key(VK_MEDIA_PLAY_PAUSE)
        self.governor.post_action()
        return {"action": "play_pause"}

    def next_track(self):
        """Skips to the next media track."""
        self.governor.pre_action()
        _send_media_key(VK_MEDIA_NEXT_TRACK)
        self.governor.post_action()
        return {"action": "next_track"}

    def prev_track(self):
        """Returns to the previous media track."""
        self.governor.pre_action()
        _send_media_key(VK_MEDIA_PREV_TRACK)
        self.governor.post_action()
        return {"action": "prev_track"}

    def stop(self):
        """Stops active media playback."""
        self.governor.pre_action()
        _send_media_key(VK_MEDIA_STOP)
        self.governor.post_action()
        return {"action": "stop"}


default_media_controller = MediaController()
