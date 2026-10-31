"""
Platform Registry and Driver Factory for AIM-VR Computer Control.
Detects operating system and desktop environment:
  - Windows ('win32') -> WindowsPlatformDriver
  - Arch Linux + Hyprland ('linux') -> HyprlandPlatformDriver
"""

import sys
import os
import shutil
from typing import Optional

from control.platform.base import BasePlatformDriver

_CURRENT_PLATFORM_DRIVER: Optional[BasePlatformDriver] = None


def detect_platform_name() -> str:
    """Detects current operating system and desktop compositor."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return "hyprland"
        if os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "hyprland":
            return "hyprland"
        if shutil.which("hyprctl"):
            return "hyprland"
        return "hyprland"  # Primary Linux compositor target
    return "unsupported"


def get_platform_driver() -> BasePlatformDriver:
    """Returns the singleton platform driver for current operating environment."""
    global _CURRENT_PLATFORM_DRIVER
    if _CURRENT_PLATFORM_DRIVER is not None:
        return _CURRENT_PLATFORM_DRIVER

    platform_name = detect_platform_name()

    if platform_name == "windows":
        from control.platform.windows.driver import WindowsPlatformDriver
        _CURRENT_PLATFORM_DRIVER = WindowsPlatformDriver()
    elif platform_name == "hyprland":
        from control.platform.hyprland.driver import HyprlandPlatformDriver
        _CURRENT_PLATFORM_DRIVER = HyprlandPlatformDriver()
    else:
        # Fallback to Hyprland driver for generic Linux environments
        from control.platform.hyprland.driver import HyprlandPlatformDriver
        _CURRENT_PLATFORM_DRIVER = HyprlandPlatformDriver()

    return _CURRENT_PLATFORM_DRIVER


def set_platform_driver(driver: Optional[BasePlatformDriver]):
    """Sets or overrides the active platform driver (useful for tests and mocks)."""
    global _CURRENT_PLATFORM_DRIVER
    _CURRENT_PLATFORM_DRIVER = driver


def reset_platform_driver():
    """Resets the platform driver singleton to trigger re-detection."""
    global _CURRENT_PLATFORM_DRIVER
    _CURRENT_PLATFORM_DRIVER = None


__all__ = [
    "detect_platform_name",
    "get_platform_driver",
    "set_platform_driver",
    "reset_platform_driver",
    "BasePlatformDriver",
]
