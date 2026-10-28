"""
Perception subsystem package for AIM-VR 3.0.
"""

from perception.screen_capture import (
    default_capture_manager,
    capture_screen,
    capture_window,
    list_visible_windows,
    find_window,
    focus_window,
    close_window_safely,
    get_foreground_window_info,
    list_monitors,
)
from perception.uia_inspector import (
    inspect_window,
    find_element_by_query,
    invoke_element,
    set_element_value,
)
from perception.winrt_ocr import default_ocr, WinRtOcrEngine
from perception.visual_som import default_som, VisualSOM
from perception.screen_recorder import default_recorder, ScreenRecorder
from perception.element_locator import default_locator, ElementLocator

__all__ = [
    "default_capture_manager",
    "capture_screen",
    "capture_window",
    "list_visible_windows",
    "find_window",
    "focus_window",
    "close_window_safely",
    "get_foreground_window_info",
    "list_monitors",
    "inspect_window",
    "find_element_by_query",
    "invoke_element",
    "set_element_value",
    "default_ocr",
    "WinRtOcrEngine",
    "default_som",
    "VisualSOM",
    "default_recorder",
    "ScreenRecorder",
    "default_locator",
    "ElementLocator",
]
