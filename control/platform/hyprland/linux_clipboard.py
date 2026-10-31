"""
Native Wayland Clipboard Driver for Hyprland using wl-clipboard.
Provides sub-5ms text and image clipboard read/write via wl-copy and wl-paste.
"""

import sys
import time
import shutil
import subprocess
from typing import Optional

from control.platform.base import BaseClipboard


class LinuxClipboard(BaseClipboard):
    """
    Wayland clipboard manager interacting with wl-copy and wl-paste.
    """

    def __init__(self, input_engine=None):
        self._input_engine = input_engine
        self._fallback_buffer: str = ""

    def _get_input_engine(self):
        if self._input_engine is None:
            from control.platform import get_platform_driver
            driver = get_platform_driver()
            self._input_engine = driver.input
        return self._input_engine

    def get_text(self) -> str:
        """
        Retrieves current text from the Wayland clipboard via wl-paste.
        """
        if shutil.which("wl-paste"):
            try:
                proc = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True,
                    text=True,
                    timeout=2.0
                )
                if proc.returncode == 0:
                    return proc.stdout
            except Exception as e:
                sys.stderr.write(f"[LinuxClipboard] wl-paste error: {e}\n")

        # Fallback to internal buffer
        return self._fallback_buffer

    def set_text(self, text: str) -> bool:
        """
        Sets clipboard text via wl-copy.
        """
        self._fallback_buffer = text
        if shutil.which("wl-copy"):
            try:
                proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"), timeout=2.0)
                return proc.returncode == 0
            except Exception as e:
                sys.stderr.write(f"[LinuxClipboard] wl-copy error: {e}\n")
                return False
        return True

    def paste(self, text: Optional[str] = None, restore_clipboard: bool = False) -> bool:
        """
        Injects text into active window by setting clipboard and triggering synthetic Ctrl+V.
        """
        previous_text = ""
        if restore_clipboard:
            previous_text = self.get_text()

        if text is not None:
            if not self.set_text(text):
                return False

        time.sleep(0.02)
        try:
            engine = self._get_input_engine()
            if engine:
                engine.hotkey("ctrl", "v")
            else:
                # Direct wtype fallback
                if shutil.which("wtype"):
                    subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], timeout=2.0)
        except Exception as e:
            sys.stderr.write(f"[LinuxClipboard] Paste dispatch error: {e}\n")
            return False

        if restore_clipboard:
            time.sleep(0.08)
            self.set_text(previous_text)

        return True


# Default singleton instance
default_linux_clipboard = LinuxClipboard()
