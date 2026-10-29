"""
Antigravity Computer Control MCP Server.
Stdio JSON-RPC 2.0 implementation strictly adhering to the Model Context Protocol (2024-11-05).
Provides high-performance, low-token OS computer control for Windows.
"""

import sys
import os
import json
import traceback
from typing import Dict, Any, Optional

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from control.safety import (
    default_governor,
    is_process_elevated,
    FailsafeException,
    UserContentionException,
    ensure_interactive_desktop,
)
from control.mouse_engine import (
    default_mouse,
    get_virtual_screen_bounds,
    init_dpi_awareness,
)
from control.keyboard_engine import default_keyboard
from control.clipboard import default_clipboard
from control.window_manager import default_window_manager
from control.media_control import default_media_controller
from perception.screen_capture import (
    default_capture_manager,
    list_visible_windows,
    list_monitors,
    find_window,
    focus_window,
    close_window_safely,
    get_foreground_window_info,
    capture_screen,
    capture_window,
)
from control.app_launcher import launch_application, shell_execute
from perception.uia_inspector import (
    inspect_window,
    find_element_by_query,
    invoke_element,
    set_element_value,
)
from perception.visual_som import default_som
from perception.winrt_ocr import default_ocr
from perception.element_locator import default_locator
from control.visual_servoing import default_servoing
from control.virtual_desktop import default_virtual_desktop
from control.com_connectors import default_com_manager
from control.dag_executor import default_dag_executor, DAGExecutor
from perception.screen_recorder import default_recorder

# Reconfigure stdout/stdin/stderr to strict UTF-8
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVER_NAME = "computer-control"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS_DEFINITIONS = [
    {
        "name": "get_screen_info",
        "description": "Returns multi-monitor virtual screen bounds, display resolution, DPI awareness, process elevation (admin status), and active foreground window info.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "screenshot",
        "description": "Captures a screenshot of the virtual desktop or a target window. Supports Set-of-Marks (SOM) overlays (som=True) and differential dirty-rect crops (mode='delta') to drastically reduce token burn.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Optional window title substring to capture only that window (e.g. 'Notepad'). Default captures full desktop.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "delta", "pip"],
                    "default": "full",
                    "description": "Capture mode: 'full' captures full view, 'delta' transmits changed bounding box, and 'pip' captures the Picture-in-Picture sandbox preview.",
                },
                "som": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, overlays numbered Set-of-Marks (SOM) badges on interactive elements for direct integer clicking.",
                },
                "cluster_zoom": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true in SOM mode, automatically zooms into the densest cluster of controls (e.g. ribbon/toolbar) for high-precision targeting.",
                },
                "detect_icons": {
                    "type": "boolean",
                    "default": True,
                    "description": "When true in SOM mode, runs local heuristic icon detection to ground buttons in non-UIA GPU-rendered apps.",
                },
                "max_dim": {
                    "type": "integer",
                    "default": 1024,
                    "description": "Maximum dimension for image downsampling (default 1024 keeps image tokens at ~250 tokens).",
                },
                "quality": {
                    "type": "integer",
                    "default": 75,
                    "description": "JPEG compression quality (1-100).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_ui",
        "description": "Extracts a compact semantic accessibility tree (50-100 tokens) using Windows UI Automation. Yields exact control roles, names, and bounding boxes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Optional window title substring (e.g. 'Notepad'). Defaults to foreground/active window.",
                },
                "max_depth": {
                    "type": "integer",
                    "default": 4,
                    "description": "Tree traversal depth limit (default 4 keeps output token-efficient).",
                },
                "max_elements": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum number of interactive controls to return.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "click",
        "description": "Performs a mouse click. Can click raw pixel coordinates (x, y), a Set-of-Marks mark ID (mark_id), a dynamic text label (text/query) via sub-15ms WinRT OCR, or a semantic UIA control (element_name, element_role).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Dynamic text or button label to locate and click in real-time (e.g. 'Post', 'Apply', 'Discussion', 'Save', 'Submit'). Automatically resolves live screen center via UIA + WinRT OCR.",
                },
                "query": {
                    "type": "string",
                    "description": "Universal semantic click query. Can be any button name, folder, tab, menu, or taskbar icon (e.g. 'Downloads', 'Save', 'File Explorer', 'Start'). Resolves to exact center coordinates in <0.2s without taking a screenshot.",
                },
                "x": {
                    "type": "number",
                    "description": "X coordinate to click (screen pixel or normalized [0..1000]).",
                },
                "y": {
                    "type": "number",
                    "description": "Y coordinate to click (screen pixel or normalized [0..1000]).",
                },
                "mark_id": {
                    "type": "integer",
                    "description": "Mark badge ID from a previous SOM screenshot. Directly resolves to exact center coordinates.",
                },
                "element_name": {
                    "type": "string",
                    "description": "Semantic element name from inspect_ui to click (e.g. 'File', 'Save', 'Open').",
                },
                "element_role": {
                    "type": "string",
                    "description": "Optional semantic element role filter (e.g. 'Button', 'MenuItem').",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                    "description": "Mouse button to click.",
                },
                "clicks": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "default": 1,
                    "description": "Number of clicks: 1 for single click, 2 for double click, 3 for triple click.",
                },
                "coords_mode": {
                    "type": "string",
                    "enum": ["pixel", "normalized_1000"],
                    "default": "pixel",
                    "description": "Coordinate space for (x, y): 'pixel' for screen pixels, 'normalized_1000' for [0..1000].",
                },
                "target": {
                    "type": "string",
                    "description": "Optional window title substring to target. Restricts interaction to this window and ensures it is focused.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find_element",
        "description": "Locates a UI element by text, label, or role using hybrid UIA + sub-15ms WinRT OCR. Returns its exact physical screen bounding box [x, y, w, h] and center (cx, cy) coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text, label, or element name to spot on screen (e.g. 'Post', 'Apply', 'Discussion', 'Save', 'Cancel').",
                },
                "target": {
                    "type": "string",
                    "description": "Optional window title substring to scope search (e.g. 'Chrome', 'Notepad'). Defaults to full screen or foreground window.",
                },
                "role": {
                    "type": "string",
                    "description": "Optional semantic role filter (e.g. 'Button', 'MenuItem', 'Tab', 'Edit').",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "move_cursor",
        "description": "Moves mouse cursor to specified coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Target X coordinate."},
                "y": {"type": "number", "description": "Target Y coordinate."},
                "coords_mode": {
                    "type": "string",
                    "enum": ["pixel", "normalized_1000"],
                    "default": "pixel",
                    "description": "Coordinate space.",
                },
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mouse_down",
        "description": "Presses and holds a mouse button.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "mouse_up",
        "description": "Releases a held mouse button.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "drag",
        "description": "Performs a smooth interpolated drag from start coordinates to end coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_x": {"type": "number", "description": "Starting X coordinate."},
                "start_y": {"type": "number", "description": "Starting Y coordinate."},
                "end_x": {"type": "number", "description": "Ending X coordinate."},
                "end_y": {"type": "number", "description": "Ending Y coordinate."},
                "duration": {
                    "type": "number",
                    "default": 0.3,
                    "description": "Duration of drag in seconds.",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "coords_mode": {
                    "type": "string",
                    "enum": ["pixel", "normalized_1000"],
                    "default": "pixel",
                },
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scroll",
        "description": "Scrolls mouse wheel. Positive clicks scroll up; negative clicks scroll down.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clicks": {
                    "type": "integer",
                    "description": "Number of scroll clicks (+up, -down).",
                },
                "x": {"type": "number", "description": "Optional X coordinate before scrolling."},
                "y": {"type": "number", "description": "Optional Y coordinate before scrolling."},
                "coords_mode": {
                    "type": "string",
                    "enum": ["pixel", "normalized_1000"],
                    "default": "pixel",
                },
            },
            "required": ["clicks"],
            "additionalProperties": False,
        },
    },
    {
        "name": "type_text",
        "description": "Types text using layout-independent Unicode key events (KEYEVENTF_UNICODE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
                "interval": {
                    "type": "number",
                    "default": 0.01,
                    "description": "Delay between keystrokes in seconds.",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "press_key",
        "description": "Presses a single keyboard key (e.g. 'enter', 'tab', 'esc', 'backspace', 'delete', 'space', 'f1'-'f12', arrows).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name to press."},
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hotkey",
        "description": "Executes a key combination shortcut using hardware scan codes (e.g. ['ctrl', 's'], ['win', 'r'], ['alt', 'tab'], ['ctrl', 'shift', 'p']).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of key names to press simultaneously.",
                },
            },
            "required": ["keys"],
            "additionalProperties": False,
        },
    },
    {
        "name": "close_window",
        "description": "Safely and cleanly closes a window matching target title using targeted Win32 messages (WM_CLOSE / SC_CLOSE). Does NOT affect other windows or the active foreground window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Window title substring of the window to close (e.g. 'File Explorer', 'Notepad')."},
                "force": {"type": "boolean", "default": False, "description": "If true, forcefully terminates the target process if graceful close does not respond."},
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "launch_app",
        "description": "Launches a desktop application or opens a file/folder/URL. Automatically resolves common paths (Chrome, Brave, Edge, Notepad, File Explorer, Calculator, Terminal, etc.) and waits for the window to appear.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Application name or binary (e.g. 'chrome', 'brave', 'explorer', 'notepad', 'calc', 'cmd', or full path)."},
                "args": {"type": "string", "description": "Optional command-line arguments or file path/URL to open."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "focus_window",
        "description": "Restores and brings a window to the foreground by title substring.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Window title substring."},
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "configure_safety",
        "description": "Configures safety settings, failsafe corner abort, physical mouse contention detection, and speed limiter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "speed": {
                    "type": "string",
                    "enum": ["fast", "normal", "step-by-step"],
                    "description": "Execution speed delay between actions.",
                },
                "failsafe": {
                    "type": "boolean",
                    "description": "Enable or disable (0, 0) top-left corner failsafe.",
                },
                "contention": {
                    "type": "boolean",
                    "description": "Enable or disable physical user mouse movement contention yield.",
                },
                "desktop_mode": {
                    "type": "string",
                    "enum": ["interactive", "isolated_pip"],
                    "description": "Desktop isolation mode: 'interactive' (standard foreground execution) or 'isolated_pip' (runs in background PiP sandbox without moving user's mouse).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ocr_screen",
        "description": "Performs local sub-15ms text recognition on the screen or a target window using native Windows WinRT OCR. Returns recognized text and all word bounding boxes with exact physical coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Optional window title substring to scope OCR to.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional text to search for; returns exact match coordinates.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_autonomous_task",
        "description": "Autonomous In-Memory Vision Runner (AIM-VR). Executes a sequence of multi-step desktop actions in a fast closed loop locally. Each step resolves elements via UIA -> WinRT OCR -> SOM, performs the action, and verifies visual reaction in memory (<50ms) without multi-turn LLM round-trips.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "click",
                                    "double_click",
                                    "right_click",
                                    "triple_click",
                                    "hover",
                                    "move",
                                    "type_text",
                                    "paste_text",
                                    "press_key",
                                    "hotkey",
                                    "wait",
                                    "focus_window",
                                    "close_window",
                                    "launch_app",
                                    "manage_window",
                                    "control_media",
                                    "invoke_element",
                                    "set_value",
                                ],
                                "description": "Action type to perform.",
                            },
                            "query": {
                                "type": "string",
                                "description": "Semantic name or text of UI element to click/move to (e.g. 'Downloads', 'Save', 'File Explorer').",
                            },
                            "name": {
                                "type": "string",
                                "description": "Application name for 'launch_app' (e.g. 'chrome', 'notepad').",
                            },
                            "args": {
                                "type": "string",
                                "description": "Optional arguments for 'launch_app'.",
                            },
                            "force": {
                                "type": "boolean",
                                "description": "Optional force flag for 'close_window'.",
                            },
                            "target": {
                                "type": "string",
                                "description": "Target window title substring to focus, close, or scope the action to.",
                            },
                            "mark_id": {
                                "type": "integer",
                                "description": "Set-of-Marks integer badge ID to click.",
                            },
                            "x": {"type": "number", "description": "Optional explicit X coordinate."},
                            "y": {"type": "number", "description": "Optional explicit Y coordinate."},
                            "text": {"type": "string", "description": "Text to type for 'type_text'."},
                            "key": {"type": "string", "description": "Key name for 'press_key'."},
                            "keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Key combo for 'hotkey' (e.g. ['ctrl', 'l']).",
                            },
                            "seconds": {"type": "number", "description": "Seconds to wait for 'wait'."},
                        },
                        "required": ["action"],
                    },
                    "description": "List of actions to execute sequentially in memory.",
                },
                "verify": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to run closed-loop visual servoing reaction verification after each action.",
                },
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "manage_window",
        "description": "Controls window layout and state. Snaps window to screen work areas (left, right, top, bottom, quadrants, center), changes state (maximize, minimize, restore), or sets exact pixel bounds without touching other applications.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Window title substring."},
                "action": {
                    "type": "string",
                    "enum": ["snap", "state", "move_resize"],
                    "description": "Action type: 'snap' to screen region, 'state' for max/min/restore, 'move_resize' for explicit bounds.",
                },
                "position": {
                    "type": "string",
                    "enum": ["left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right", "center"],
                    "description": "Snap position (required if action='snap').",
                },
                "state": {
                    "type": "string",
                    "enum": ["maximize", "minimize", "restore"],
                    "description": "Window state (required if action='state').",
                },
                "bounds": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "[x, y, width, height] bounds (required if action='move_resize').",
                },
            },
            "required": ["target", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "control_media",
        "description": "Controls system audio volume and media playback without disturbing active window context or application state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["volume_up", "volume_down", "toggle_mute", "play_pause", "next_track", "prev_track", "stop"],
                    "description": "Media or volume action to perform.",
                },
                "steps": {
                    "type": "integer",
                    "default": 1,
                    "description": "Number of volume steps to adjust (for volume_up / volume_down).",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "clipboard",
        "description": "High-performance Win32 native clipboard manager. Get current clipboard text, set clipboard text, or instantly paste multiline text/code via Ctrl+V without dropped characters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "paste"],
                    "description": "Clipboard action: 'get' text, 'set' text, or 'paste' text via simulated Ctrl+V.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to set or paste (required for action='set' or 'paste').",
                },
                "restore": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true during paste, restores previous clipboard content after pasting.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hover",
        "description": "Moves mouse cursor to target coordinates or UI element and hovers for a specified duration. Activates flyout menus, tooltips, and dynamic hover UI states.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic element name or text to hover over."},
                "target": {"type": "string", "description": "Optional window title substring to scope element search to."},
                "x": {"type": "number", "description": "Explicit X coordinate."},
                "y": {"type": "number", "description": "Explicit Y coordinate."},
                "duration": {"type": "number", "default": 0.25, "description": "Hover duration in seconds."},
                "coords_mode": {"type": "string", "enum": ["pixel", "normalized_1000"], "default": "pixel"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sandbox_launch",
        "description": "Launches an application directly onto the isolated sandbox desktop (WinSta0\\AIMVR_Sandbox). The application window will not appear on the user's physical screen and will not steal mouse or keyboard focus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Executable path or command to launch (e.g. 'notepad.exe', 'calc.exe', 'cmd.exe')."},
                "cwd": {"type": "string", "description": "Optional working directory."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sandbox_capture",
        "description": "Captures a Picture-in-Picture (PiP) composite preview of all windows running inside the isolated sandbox desktop (AIMVR_Sandbox).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_dim": {"type": "integer", "default": 1024, "description": "Maximum dimension of the captured PiP preview image."},
                "quality": {"type": "integer", "default": 75, "description": "JPEG compression quality (1-100)."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sandbox_manage",
        "description": "Manages the isolated sandbox desktop: 'status' reports state and open windows, 'list_windows' lists window bounds and handles, 'close_window' sends WM_CLOSE, and 'destroy' terminates sandbox processes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list_windows", "close_window", "destroy"],
                    "description": "Action to perform on sandbox desktop.",
                },
                "target": {"type": "string", "description": "Target window title substring (required for action='close_window')."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "com_explorer",
        "description": "Direct Windows Shell.Application COM connector for File Explorer. Allows zero-token instantaneous folder opening, path navigation, window enumeration, and selected item retrieval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "open", "get_selected"],
                    "description": "Action: 'list' open Explorer windows and paths, 'open' navigates/opens a folder path, 'get_selected' gets selected files.",
                },
                "path": {"type": "string", "description": "Filesystem path to open (required for action='open')."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "com_excel",
        "description": "Direct Microsoft Excel COM Object interface. Reads cell values, writes formulas, queries active sheets, and reads ranges instantaneously in 5ms without GUI clicking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "read_cell", "write_cell", "read_range"],
                    "description": "Excel COM action: 'status' checks running state, 'read_cell' reads a cell, 'write_cell' sets value/formula, 'read_range' reads a 2D matrix.",
                },
                "cell": {"type": "string", "description": "Cell reference (e.g. 'A1', 'C15'). Required for read_cell and write_cell."},
                "value": {"type": "string", "description": "Value or formula to write (e.g. '1234', '=SUM(A1:A10)'). Required for write_cell."},
                "sheet": {"type": "string", "description": "Optional worksheet name. Defaults to active worksheet."},
                "rows": {"type": "integer", "default": 10, "description": "Number of rows to read for read_range."},
                "cols": {"type": "integer", "default": 10, "description": "Number of columns to read for read_range."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "com_browser_cdp",
        "description": "Direct Chrome / Edge Chrome DevTools Protocol (CDP) connector. Queries active tabs, URLs, and navigates tabs without taking vision screenshots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list_tabs", "navigate"],
                    "description": "CDP action: 'status' checks if CDP port is open, 'list_tabs' lists tabs and URLs, 'navigate' activates/navigates tab.",
                },
                "tab_id": {"type": "string", "description": "Browser tab ID (required for action='navigate')."},
                "url": {"type": "string", "description": "Target URL to navigate to."},
                "port": {"type": "integer", "default": 9222, "description": "Browser remote debugging port (default 9222)."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_action_dag",
        "description": "Executes a compound Speculative Action DAG in a fast closed loop. Resolves step dependencies topologically, passes variables between steps ({{steps.id.result}}), verifies visual reaction (<30ms) between steps, and provides automatic adaptive reflection and error recovery snapshots on failure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "List of action step objects in the DAG.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique identifier for this step (e.g. 's1', 'open_folder')."},
                            "action": {"type": "string", "description": "Tool or action name to execute (e.g. 'com_explorer', 'launch_app', 'click', 'type_text', 'hotkey', 'com_excel')."},
                            "args": {"type": "object", "description": "Arguments dictionary for the action. Supports template variables e.g. {{steps.s1.result.path}}."},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of step IDs that must succeed before executing this step."
                            },
                            "verify": {
                                "type": "string",
                                "enum": ["auto", "visual", "none"],
                                "default": "auto",
                                "description": "Verification strategy: 'auto' (servoing for clicks/keys), 'visual' (strict ImageChops delta/window check), 'none'."
                            },
                            "retries": {"type": "integer", "default": 0, "description": "Number of retries if step or verification fails."},
                            "on_failure": {
                                "type": "string",
                                "enum": ["abort", "continue"],
                                "default": "abort",
                                "description": "'abort' stops execution and captures reflection snapshot; 'continue' logs error and proceeds."
                            }
                        },
                        "required": ["action"]
                    }
                },
                "stop_on_error": {"type": "boolean", "default": True, "description": "Whether to halt the DAG upon any step failure."},
                "auto_verify": {"type": "boolean", "default": True, "description": "Whether to verify interactive steps with visual servoing."}
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_screen",
        "description": "Continuous high-speed screen recorder. Captures smooth desktop or window streams and compiles them into animated WebP or GIF videos with optional physical mouse cursor stamping.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status", "pause", "resume"],
                    "description": "Recorder action: 'start' initiates recording, 'stop' compiles and saves video file, 'status' reports telemetry, 'pause'/'resume' controls loop."
                },
                "output_path": {
                    "type": "string",
                    "description": "Destination file path for output video (e.g. 'assets/demo.webp' or 'assets/demo.gif'). Required when action is 'stop'."
                },
                "fps": {
                    "type": "integer",
                    "default": 15,
                    "description": "Capture frame rate (5 to 30 FPS). Default is 15 FPS."
                },
                "target": {
                    "type": "string",
                    "description": "Optional window title substring to scope recording strictly to that application window."
                },
                "crop_region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional [x, y, w, h] pixel bounding box to record a specific region of interest."
                },
                "max_dim": {
                    "type": "integer",
                    "default": 800,
                    "description": "Maximum resolution dimension (e.g. 720, 800, 1080) for downscaling. Default 800px ensures compact filesize."
                },
                "quality": {
                    "type": "integer",
                    "default": 75,
                    "description": "Compression quality (1-100). Default 75."
                },
                "include_cursor": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to render a visible hardware mouse pointer arrow onto the frames."
                },
                "format": {
                    "type": "string",
                    "enum": ["webp", "gif"],
                    "default": "webp",
                    "description": "Video animation format: 'webp' (24-bit truecolor high compression) or 'gif'."
                },
                "max_duration": {
                    "type": "number",
                    "default": 120.0,
                    "description": "Safety timeout in seconds to auto-stop recording and prevent runaway memory usage."
                }
            },
            "required": ["action"]
        }
    },
]


class MCPServer:
    """Stdio JSON-RPC MCP Server."""

    def __init__(self):
        self.dpi_mode = init_dpi_awareness()
        ensure_interactive_desktop()
        self.last_capture_scale: float = 1.0
        self.last_capture_offset: tuple[int, int] = (0, 0)
        self.last_capture_target: Optional[str] = None
        self.dag_executor = DAGExecutor(servoing=default_servoing, tool_dispatcher=self.execute_tool)

    def _project_coordinates(
        self, x: float, y: float, coords_mode: str = "pixel", target: Optional[str] = None
    ) -> tuple[int, int, str]:
        """
        Projects coordinates returned by a Vision-Language Model (VLM) back into
        native physical screen coordinates.
        - Automatically inverts downsampling scale factor (x / scale, y / scale).
        - Automatically adds window origin offset if screenshot was scoped to a window.
        """
        if coords_mode == "normalized_1000":
            return int(round(x)), int(round(y)), "normalized_1000"

        cur_x = float(x)
        cur_y = float(y)

        # 1. Reverse downsampling scale factor if active screenshot was scaled
        if self.last_capture_scale and self.last_capture_scale > 0 and self.last_capture_scale != 1.0:
            cur_x = cur_x / self.last_capture_scale
            cur_y = cur_y / self.last_capture_scale

        # 2. Add window origin offset strictly when target is specified
        if target:
            win = find_window(target)
            if win:
                cur_x += win["bounds"][0]
                cur_y += win["bounds"][1]
            elif self.last_capture_target and self.last_capture_target.lower() in target.lower() and self.last_capture_offset != (0, 0):
                cur_x += self.last_capture_offset[0]
                cur_y += self.last_capture_offset[1]

        return int(round(cur_x)), int(round(cur_y)), "pixel"

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Handle notifications (no id)
        if req_id is None:
            if method == "notifications/initialized":
                sys.stderr.write("[MCP] Client initialized successfully.\n")
            return None

        # Handle methods
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS_DEFINITIONS,
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                content, is_error = self.execute_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": content,
                        "isError": is_error,
                    },
                }
            except Exception as e:
                sys.stderr.write(f"[MCP] Error in tool {tool_name}: {traceback.format_exc()}\n")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Tool Execution Error: {str(e)}"}],
                        "isError": True,
                    },
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }

    def execute_tool(self, name: str, args: Dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        ensure_interactive_desktop()

        if name == "get_screen_info":
            vx, vy, vw, vh = get_virtual_screen_bounds()
            cur_x, cur_y = default_mouse.get_position()
            fg_win = get_foreground_window_info()
            all_wins = [
                {
                    "title": w["title"],
                    "hwnd": w["hwnd"],
                    "pid": w["pid"],
                    "is_minimized": w.get("is_minimized", False),
                    "is_foreground": fg_win is not None and fg_win.get("hwnd") == w["hwnd"],
                }
                for w in list_visible_windows()
            ]
            info = {
                "virtual_screen": {"left": vx, "top": vy, "width": vw, "height": vh},
                "cursor_position": {"x": cur_x, "y": cur_y},
                "is_admin": is_process_elevated(),
                "dpi_mode": self.dpi_mode,
                "foreground_window": fg_win,
                "monitors": list_monitors(),
                "visible_windows": all_wins,
                "safety_settings": {
                    "speed": default_governor.speed,
                    "failsafe_enabled": default_governor.failsafe_enabled,
                    "contention_enabled": default_governor.contention_enabled,
                },
            }
            return [{"type": "text", "text": json.dumps(info, indent=2)}], False

        elif name == "screenshot":
            target = args.get("target")
            mode = args.get("mode", "full")
            som = bool(args.get("som", False))
            max_dim = int(args.get("max_dim", 1024))
            quality = int(args.get("quality", 75))

            if mode == "pip" or args.get("pip", False) or default_virtual_desktop.get_mode() == "isolated_pip":
                res = default_virtual_desktop.capture_pip_composite(max_dim=max_dim, quality=quality)
                content = [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "status": "pip_preview",
                            "desktop": res["desktop"],
                            "mode": res["mode"],
                            "windows_count": res["windows_count"],
                            "width": res["width"],
                            "height": res["height"],
                            "windows": res["windows"],
                        }, indent=2),
                    },
                    {"type": "image", "data": res["image_b64"], "mimeType": "image/jpeg"},
                ]
                return content, False

            if som:
                # Capture base unscaled image and bounds directly
                raw_img, bounds = default_capture_manager.get_raw_frame(target=target)
                # Inspect UI elements
                tree_res = inspect_window(target=target, max_depth=3, max_elements=40)
                # Generate Set-of-Marks overlay
                offset = (bounds[0], bounds[1])
                cluster_zoom = bool(args.get("cluster_zoom", False))
                detect_icons = bool(args.get("detect_icons", True))
                annotated_img, mark_map, scale = default_som.generate_som(
                    raw_img,
                    tree_res["elements"],
                    max_dim=max_dim,
                    target_offset=offset,
                    quality=quality,
                    detect_icons=detect_icons,
                    cluster_zoom=cluster_zoom,
                )
                self.last_capture_scale = float(scale)
                if default_som.last_zoom_crop_info and default_som.last_zoom_crop_info.get("is_zoomed"):
                    zx, zy, _, _ = default_som.last_zoom_crop_info["crop_bbox"]
                    self.last_capture_offset = (int(bounds[0] + zx), int(bounds[1] + zy))
                else:
                    self.last_capture_offset = (int(bounds[0]), int(bounds[1]))
                self.last_capture_target = target
                b64 = default_capture_manager.encode_image(annotated_img, quality=quality)
                meta = {
                    "status": "som_full",
                    "width": annotated_img.size[0],
                    "height": annotated_img.size[1],
                    "scale": scale,
                    "bounds": bounds,
                    "marks_count": len(mark_map),
                    "cluster_zoom_active": bool(default_som.last_zoom_crop_info and default_som.last_zoom_crop_info.get("is_zoomed")),
                    "marks_summary": [
                        f"[{m['mark_id']}] {m.get('source', 'uia').upper()} {m['role']} '{m['name']}' @ {m['bbox']}"
                        for m in list(mark_map.values())[:25]
                    ],
                }
                content = [
                    {"type": "text", "text": json.dumps(meta, indent=2)},
                    {"type": "image", "data": b64, "mimeType": "image/jpeg"},
                ]
                return content, False

            else:
                res = default_capture_manager.capture(target=target, mode=mode, max_dim=max_dim, quality=quality)
                self.last_capture_scale = float(res.get("scale", 1.0))
                bnds = res.get("bounds", [0, 0, 0, 0])
                self.last_capture_offset = (int(bnds[0]), int(bnds[1]))
                self.last_capture_target = target
                content = []
                meta = {
                    "status": res["status"],
                    "bounds": res["bounds"],
                    "delta_bbox": res["delta_bbox"],
                    "width": res["width"],
                    "height": res["height"],
                    "scale": res["scale"],
                }
                content.append({"type": "text", "text": json.dumps(meta, indent=2)})
                if res["image_b64"]:
                    content.append({"type": "image", "data": res["image_b64"], "mimeType": "image/jpeg"})
                return content, False

        elif name == "inspect_ui":
            target = args.get("target")
            max_depth = int(args.get("max_depth", 4))
            max_elements = int(args.get("max_elements", 50))
            tree = inspect_window(target=target, max_depth=max_depth, max_elements=max_elements)
            summary = {
                "count": tree["count"],
                "has_rich_uia": tree["has_rich_uia"],
                "formatted_tree": tree["formatted_text"],
            }
            return [{"type": "text", "text": json.dumps(summary, indent=2)}], False

        elif name == "find_element":
            q = args.get("query")
            target = args.get("target")
            role = args.get("role")
            if not q:
                return [{"type": "text", "text": "Error: Missing required 'query' parameter."}], True

            elem = default_locator.locate(query=q, target_window=target, role=role)
            if not elem:
                return [{"type": "text", "text": f"Element matching '{q}' not found via UIA or OCR on screen."}], False

            return [{
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "found",
                        "query": q,
                        "name": elem["name"],
                        "role": elem["role"],
                        "bbox": elem["bbox"],
                        "center": elem["center"],
                        "source": elem["source"],
                        "confidence": elem["confidence"],
                    },
                    indent=2,
                ),
            }], False

        elif name == "click":
            x = args.get("x")
            y = args.get("y")
            mark_id = args.get("mark_id")
            query = args.get("query") or args.get("text")
            elem_name = args.get("element_name") or query
            elem_role = args.get("element_role")
            target = args.get("target")
            btn = args.get("button", "left")
            clicks = int(args.get("clicks", 1))
            coords_mode = args.get("coords_mode", "pixel")

            # Validate that at least one target parameter is provided
            if x is None and y is None and mark_id is None and not elem_name:
                return [{"type": "text", "text": "Error: Missing target to click. Provide 'text'/'query' (e.g. text='Post'), 'mark_id', or coordinates (x, y)."}], True

            # Validate coordinate pairing
            if (x is not None and y is None) or (x is None and y is not None):
                return [{"type": "text", "text": "Error: Both x and y coordinates must be provided together."}], True

            # If target window specified, ensure it is found and brought to foreground
            if target:
                win = find_window(target)
                if not win:
                    return [{"type": "text", "text": f"Error: Target window matching '{target}' not found."}], True
                focus_window(win["hwnd"])

            target_x = None
            target_y = None
            source_tag = ""

            if mark_id is not None:
                mark = default_som.resolve_mark(mark_id)
                if not mark:
                    return [{"type": "text", "text": f"Error: Mark ID {mark_id} not found in recent marks."}], True
                target_x = mark["center_x"]
                target_y = mark["center_y"]
                target_bbox = mark["bbox"]
                coords_mode = "pixel"
                source_tag = f" [mark #{mark_id}]"

            elif elem_name is not None or elem_role is not None:
                elem = default_locator.locate(query=elem_name, target_window=target, role=elem_role)
                if not elem:
                    return [{"type": "text", "text": f"Error: Element matching text/label '{elem_name}' (role={elem_role}) not found via UIA or OCR on screen."}], True
                target_x = elem["center"][0]
                target_y = elem["center"][1]
                target_bbox = elem["bbox"]
                coords_mode = "pixel"
                source_tag = f" [resolved '{elem_name}' via {elem['source'].upper()}]"

            elif x is not None and y is not None:
                target_x, target_y, coords_mode = self._project_coordinates(x, y, coords_mode, target=target)
                target_bbox = [target_x - 20, target_y - 20, 40, 40]
            else:
                target_bbox = None

            eff_bbox = tuple(target_bbox) if target_bbox else None
            pre_state = default_servoing.sample_state(bbox=eff_bbox)
            cx, cy = default_mouse.click(x=target_x, y=target_y, button=btn, clicks=clicks, coords_mode=coords_mode)
            reaction = default_servoing.verify_reaction(pre_state, bbox=eff_bbox)

            msg = f"Clicked {btn} (clicks={clicks}) at ({cx}, {cy}){source_tag}. Reaction: {reaction['details']} ({reaction['latency_ms']}ms)"
            return [{"type": "text", "text": msg}], False

        elif name == "move_cursor":
            x = args["x"]
            y = args["y"]
            coords_mode = args.get("coords_mode", "pixel")
            px, py, mode = self._project_coordinates(x, y, coords_mode)
            cx, cy = default_mouse.move(px, py, coords_mode=mode)
            return [{"type": "text", "text": f"Cursor moved to ({cx}, {cy})."}], False

        elif name == "mouse_down":
            btn = args.get("button", "left")
            default_mouse.mouse_down(btn)
            return [{"type": "text", "text": f"Mouse button '{btn}' down."}], False

        elif name == "mouse_up":
            btn = args.get("button", "left")
            default_mouse.mouse_up(btn)
            return [{"type": "text", "text": f"Mouse button '{btn}' up."}], False

        elif name == "drag":
            sx = args["start_x"]
            sy = args["start_y"]
            ex = args["end_x"]
            ey = args["end_y"]
            dur = float(args.get("duration", 0.3))
            btn = args.get("button", "left")
            coords_mode = args.get("coords_mode", "pixel")
            psx, psy, mode_s = self._project_coordinates(sx, sy, coords_mode)
            pex, pey, mode_e = self._project_coordinates(ex, ey, coords_mode)
            default_mouse.drag(psx, psy, pex, pey, duration=dur, button=btn, coords_mode=mode_s)
            return [{"type": "text", "text": f"Dragged from ({psx}, {psy}) to ({pex}, {pey})."}], False

        elif name == "scroll":
            clicks = int(args["clicks"])
            x = args.get("x")
            y = args.get("y")
            coords_mode = args.get("coords_mode", "pixel")
            if x is not None and y is not None:
                x, y, coords_mode = self._project_coordinates(x, y, coords_mode)
            default_mouse.scroll(clicks, x=x, y=y, coords_mode=coords_mode)
            return [{"type": "text", "text": f"Scrolled mouse wheel {clicks} clicks."}], False

        elif name == "type_text":
            text = args["text"]
            interval = float(args.get("interval", 0.01))
            default_keyboard.type_text(text, interval=interval)
            return [{"type": "text", "text": f"Typed {len(text)} characters."}], False

        elif name == "press_key":
            key = args["key"]
            default_keyboard.press_key(key)
            return [{"type": "text", "text": f"Pressed key '{key}'."}], False

        elif name == "hotkey":
            keys = args["keys"]
            default_keyboard.hotkey(*keys)
            return [{"type": "text", "text": f"Executed hotkey combo: {' + '.join(keys)}."}], False

        elif name == "focus_window":
            target = args["target"]
            win = find_window(target)
            if not win:
                return [{"type": "text", "text": f"Window matching '{target}' not found."}], True
            ok = focus_window(win["hwnd"])
            return [{"type": "text", "text": f"Focused window '{win['title']}' (success={ok})."}], not ok

        elif name == "close_window":
            target = args["target"]
            force = bool(args.get("force", False))
            ok = close_window_safely(target, force=force)
            if ok:
                return [{"type": "text", "text": f"Successfully closed window matching '{target}'."}], False
            else:
                return [{"type": "text", "text": f"Window matching '{target}' not found or could not be closed."}], True

        elif name == "launch_app":
            app_name = args["name"]
            app_args = args.get("args")
            res = launch_application(app_name, app_args)
            is_err = res.get("status") == "error"
            return [{"type": "text", "text": json.dumps(res, indent=2)}], is_err

        elif name == "configure_safety":
            speed = args.get("speed")
            failsafe = args.get("failsafe")
            contention = args.get("contention")
            desktop_mode = args.get("desktop_mode")
            default_governor.configure(speed=speed, failsafe=failsafe, contention=contention, desktop_mode=desktop_mode)
            return [{
                "type": "text",
                "text": f"Safety configured: speed={default_governor.speed}, failsafe={default_governor.failsafe_enabled}, contention={default_governor.contention_enabled}, desktop_mode={default_governor.desktop_mode}",
            }], False

        elif name == "sandbox_launch":
            cmd = args["command"]
            cwd = args.get("cwd")
            res = default_virtual_desktop.launch_in_sandbox(cmd, cwd=cwd)
            is_err = res.get("status") == "error"
            return [{"type": "text", "text": json.dumps(res, indent=2)}], is_err

        elif name == "sandbox_capture":
            max_dim = int(args.get("max_dim", 1024))
            quality = int(args.get("quality", 75))
            res = default_virtual_desktop.capture_pip_composite(max_dim=max_dim, quality=quality)
            content = [
                {"type": "text", "text": json.dumps({
                    "status": res["status"],
                    "desktop": res["desktop"],
                    "mode": res["mode"],
                    "windows_count": res["windows_count"],
                    "width": res["width"],
                    "height": res["height"],
                    "windows": res["windows"],
                }, indent=2)},
                {"type": "image", "data": res["image_b64"], "mimeType": "image/jpeg"},
            ]
            return content, False

        elif name == "sandbox_manage":
            act = args["action"]
            if act == "status":
                try:
                    default_virtual_desktop.ensure_sandbox()
                    wins = default_virtual_desktop.list_sandbox_windows()
                    active = True
                except Exception:
                    active = False
                    wins = []
                res = {
                    "desktop": default_virtual_desktop.sandbox_name,
                    "mode": default_virtual_desktop.get_mode(),
                    "active": active,
                    "windows_count": len(wins),
                    "windows": wins,
                }
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            elif act == "list_windows":
                wins = default_virtual_desktop.list_sandbox_windows()
                return [{"type": "text", "text": json.dumps(wins, indent=2)}], False
            elif act == "close_window":
                target = args.get("target")
                if not target:
                    return [{"type": "text", "text": "Error: 'target' window title required for close_window."}], True
                ok = default_virtual_desktop.close_sandbox_window(target)
                return [{"type": "text", "text": f"Closed window '{target}' in sandbox: success={ok}"}], not ok
            elif act == "destroy":
                res = default_virtual_desktop.destroy_sandbox()
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            else:
                return [{"type": "text", "text": f"Unknown sandbox action: {act}"}], True

        elif name == "com_explorer":
            act = args["action"]
            if act == "list":
                explorers = default_com_manager.explorer.list_open_explorers()
                return [{"type": "text", "text": json.dumps(explorers, indent=2)}], False
            elif act == "open":
                path = args.get("path")
                if not path:
                    return [{"type": "text", "text": "Error: 'path' required to open folder."}], True
                res = default_com_manager.explorer.open_folder(path)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            elif act == "get_selected":
                sel = default_com_manager.explorer.get_selected_items()
                return [{"type": "text", "text": json.dumps(sel, indent=2)}], False
            else:
                return [{"type": "text", "text": f"Unknown explorer action: {act}"}], True

        elif name == "com_excel":
            act = args["action"]
            sheet = args.get("sheet")
            if act == "status":
                res = default_com_manager.excel.get_status()
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            elif act == "read_cell":
                cell = args.get("cell")
                if not cell:
                    return [{"type": "text", "text": "Error: 'cell' required (e.g. 'A1')."}], True
                res = default_com_manager.excel.read_cell(cell, sheet_name=sheet)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            elif act == "write_cell":
                cell = args.get("cell")
                val = args.get("value")
                if not cell or val is None:
                    return [{"type": "text", "text": "Error: 'cell' and 'value' required."}], True
                res = default_com_manager.excel.write_cell(cell, val, sheet_name=sheet)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            elif act == "read_range":
                start_cell = args.get("cell", "A1")
                rows = int(args.get("rows", 10))
                cols = int(args.get("cols", 10))
                res = default_com_manager.excel.read_range(start_cell=start_cell, rows=rows, cols=cols, sheet_name=sheet)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            else:
                return [{"type": "text", "text": f"Unknown excel action: {act}"}], True

        elif name == "com_browser_cdp":
            act = args["action"]
            port = int(args.get("port", 9222))
            cdp = default_com_manager.cdp
            cdp.port = port
            cdp.base_url = f"http://127.0.0.1:{port}"

            if act == "status":
                avail = cdp.is_available()
                return [{"type": "text", "text": json.dumps({"cdp_available": avail, "port": port}, indent=2)}], False
            elif act == "list_tabs":
                tabs = cdp.list_tabs()
                return [{"type": "text", "text": json.dumps(tabs, indent=2)}], False
            elif act == "navigate":
                tab_id = args.get("tab_id")
                url = args.get("url")
                if not tab_id or not url:
                    return [{"type": "text", "text": "Error: 'tab_id' and 'url' required for cdp navigate."}], True
                res = cdp.navigate_tab(tab_id, url)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            else:
                return [{"type": "text", "text": f"Unknown cdp action: {act}"}], True

        elif name == "ocr_screen":
            target = args.get("target")
            query = args.get("query")

            win_info = find_window(target) if target else None
            if target and not win_info:
                return [{"type": "text", "text": f"Error: Target window matching '{target}' not found."}], True

            if win_info and win_info.get("hwnd"):
                img = capture_window(win_info["hwnd"])
                offset_x, offset_y = win_info["bounds"][0], win_info["bounds"][1]
            else:
                img = capture_screen()
                vx, vy, _, _ = get_virtual_screen_bounds()
                offset_x, offset_y = vx, vy

            if query:
                match = default_ocr.find_text(img, query)
                if not match:
                    return [{"type": "text", "text": f"Text query '{query}' not found via OCR."}], True
                res = {
                    "query": query,
                    "matched_text": match["text"],
                    "center": [offset_x + match["center"][0], offset_y + match["center"][1]],
                    "bbox": [offset_x + match["bbox"][0], offset_y + match["bbox"][1], match["bbox"][2], match["bbox"][3]],
                    "confidence": match["confidence"],
                }
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            else:
                ocr_data = default_ocr.recognize(img)
                words_abs = []
                for w in ocr_data.get("words", []):
                    words_abs.append({
                        "text": w["text"],
                        "bbox": [offset_x + w["x"], offset_y + w["y"], w["w"], w["h"]],
                        "center": [offset_x + w["x"] + w["w"] // 2, offset_y + w["y"] + w["h"] // 2],
                    })
                res = {
                    "text": ocr_data.get("text", ""),
                    "words_count": len(words_abs),
                    "words": words_abs[:50],
                }
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False

        elif name == "manage_window":
            target = args["target"]
            act = args["action"]
            if act == "snap":
                pos = args.get("position", "left")
                res = default_window_manager.snap(target, pos)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            elif act == "state":
                state = args.get("state", "restore")
                res = default_window_manager.set_state(target, state)
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            elif act == "move_resize":
                b = args.get("bounds", [100, 100, 800, 600])
                res = default_window_manager.move_resize(target, b[0], b[1], b[2], b[3])
                return [{"type": "text", "text": json.dumps(res, indent=2)}], res.get("status") == "error"
            else:
                return [{"type": "text", "text": f"Unknown manage_window action: {act}"}], True

        elif name == "control_media":
            act = args["action"]
            steps = int(args.get("steps", 1))
            if act == "volume_up":
                res = default_media_controller.volume_up(steps)
            elif act == "volume_down":
                res = default_media_controller.volume_down(steps)
            elif act == "toggle_mute":
                res = default_media_controller.toggle_mute()
            elif act == "play_pause":
                res = default_media_controller.play_pause()
            elif act == "next_track":
                res = default_media_controller.next_track()
            elif act == "prev_track":
                res = default_media_controller.prev_track()
            elif act == "stop":
                res = default_media_controller.stop()
            else:
                return [{"type": "text", "text": f"Unknown media action: {act}"}], True
            return [{"type": "text", "text": json.dumps(res, indent=2)}], False

        elif name == "clipboard":
            act = args["action"]
            if act == "get":
                text = default_clipboard.get_text()
                return [{"type": "text", "text": json.dumps({"status": "success", "text": text}, indent=2)}], False
            elif act == "set":
                text = args.get("text", "")
                ok = default_clipboard.set_text(text)
                return [{"type": "text", "text": json.dumps({"status": "success" if ok else "error", "length": len(text)}, indent=2)}], not ok
            elif act == "paste":
                text = args.get("text", "")
                restore = bool(args.get("restore", False))
                ok = default_clipboard.paste(text, restore_clipboard=restore)
                return [{"type": "text", "text": json.dumps({"status": "success" if ok else "error", "pasted_length": len(text)}, indent=2)}], not ok
            else:
                return [{"type": "text", "text": f"Unknown clipboard action: {act}"}], True

        elif name == "hover":
            query = args.get("query")
            target = args.get("target")
            duration = float(args.get("duration", 0.25))
            coords_mode = args.get("coords_mode", "pixel")
            if query:
                elem = find_element_by_query(target=target, name=query)
                if not elem:
                    return [{"type": "text", "text": f"Element matching '{query}' not found."}], True
                hx, hy = elem["center"][0], elem["center"][1]
                coords_mode = "pixel"
            elif args.get("x") is not None and args.get("y") is not None:
                hx, hy, coords_mode = self._project_coordinates(args["x"], args["y"], coords_mode, target=target)
            else:
                return [{"type": "text", "text": "Error: Either 'query' or both 'x' and 'y' must be provided to hover."}], True
            cx, cy = default_mouse.hover(hx, hy, duration=duration, coords_mode=coords_mode)
            return [{"type": "text", "text": f"Hovered at ({cx}, {cy}) for {duration}s."}], False

        elif name == "execute_action_dag":
            steps = args.get("steps", [])
            stop_on_error = bool(args.get("stop_on_error", True))
            auto_verify = bool(args.get("auto_verify", True))
            if not steps:
                return [{"type": "text", "text": "Error: 'steps' list cannot be empty."}], True
            res = self.dag_executor.run_dag(steps, stop_on_error=stop_on_error, auto_verify=auto_verify)
            is_err = res.get("status") != "success"
            return [{"type": "text", "text": json.dumps(res, indent=2)}], is_err

        elif name == "execute_autonomous_task":
            import time
            steps = args.get("steps", [])
            should_verify = args.get("verify", True)
            if not steps:
                return [{"type": "text", "text": "Error: 'steps' list cannot be empty."}], True

            execution_log = []
            start_total = time.time()

            for idx, step in enumerate(steps, 1):
                act = step.get("action")
                t_step_start = time.time()
                step_record = {"step": idx, "action": act, "status": "pending"}

                try:
                    if act in ["click", "double_click", "right_click", "triple_click", "move", "hover"]:
                        s_query = step.get("query") or step.get("text")
                        s_role = step.get("role") or step.get("element_role")
                        s_mark = step.get("mark_id")
                        s_target = step.get("target")
                        s_x = step.get("x")
                        s_y = step.get("y")
                        btn = "right" if act == "right_click" else "left"
                        if act == "triple_click":
                            clicks = 3
                        elif act == "double_click":
                            clicks = 2
                        else:
                            clicks = 1

                        if s_target:
                            win = find_window(s_target)
                            if win:
                                focus_window(win["hwnd"])

                        target_x, target_y = None, None
                        target_bbox = None

                        if s_mark is not None:
                            mark = default_som.resolve_mark(s_mark)
                            if not mark:
                                raise ValueError(f"Mark ID {s_mark} not found.")
                            target_x, target_y = mark["center_x"], mark["center_y"]
                            target_bbox = mark["bbox"]
                        elif s_query:
                            elem = default_locator.locate(query=s_query, target_window=s_target, role=s_role)
                            if not elem:
                                raise ValueError(f"Element matching '{s_query}' not found via UIA or OCR on screen.")
                            target_x, target_y = elem["center"][0], elem["center"][1]
                            target_bbox = elem["bbox"]
                            step_record["source"] = elem.get("source", "ocr")
                        elif s_x is not None and s_y is not None:
                            target_x, target_y, _ = self._project_coordinates(s_x, s_y, "pixel", target=s_target)

                        if target_x is None or target_y is None:
                            raise ValueError(f"Step {idx}: missing query, mark_id, or x/y coordinates.")

                        # Sample pre-state for verification if requested
                        pre_state = default_servoing.sample_state(bbox=tuple(target_bbox) if target_bbox else None) if should_verify else None

                        if act == "move":
                            cx, cy = default_mouse.move(target_x, target_y)
                            step_record["details"] = f"Moved to ({cx}, {cy})"
                        elif act == "hover":
                            dur = float(step.get("duration", 0.25))
                            cx, cy = default_mouse.hover(target_x, target_y, duration=dur)
                            step_record["details"] = f"Hovered at ({cx}, {cy}) for {dur}s"
                        else:
                            cx, cy = default_mouse.click(x=target_x, y=target_y, button=btn, clicks=clicks)
                            step_record["details"] = f"Clicked {btn} (x{clicks}) at ({cx}, {cy})"

                        if should_verify and pre_state and act not in ["move", "hover"]:
                            reaction = default_servoing.verify_reaction(pre_state, bbox=tuple(target_bbox) if target_bbox else None)
                            step_record["reaction"] = reaction["details"]
                            step_record["verified"] = reaction["verified"]

                    elif act == "type_text":
                        text_to_type = step.get("text", "")
                        interval = float(step.get("interval", 0.01))
                        default_keyboard.type_text(text_to_type, interval=interval)
                        step_record["details"] = f"Typed '{text_to_type[:20]}...'" if len(text_to_type) > 20 else f"Typed '{text_to_type}'"

                    elif act == "paste_text":
                        text_to_paste = step.get("text", "")
                        rst = bool(step.get("restore", False))
                        ok = default_clipboard.paste(text_to_paste, restore_clipboard=rst)
                        step_record["details"] = f"Pasted {len(text_to_paste)} characters (success={ok})"

                    elif act == "press_key":
                        k = step.get("key", "enter")
                        default_keyboard.press_key(k)
                        step_record["details"] = f"Pressed '{k}'"

                    elif act == "hotkey":
                        keys = step.get("keys", [])
                        default_keyboard.hotkey(*keys)
                        step_record["details"] = f"Hotkey {keys}"

                    elif act == "wait":
                        sec = float(step.get("seconds", 0.5))
                        time.sleep(sec)
                        step_record["details"] = f"Waited {sec}s"

                    elif act == "scroll":
                        clicks = int(step.get("clicks", -3))
                        sx = step.get("x")
                        sy = step.get("y")
                        default_mouse.scroll(clicks, sx, sy)
                        step_record["details"] = f"Scrolled {clicks} clicks at ({sx}, {sy})"

                    elif act == "focus_window":
                        w_target = step.get("target")
                        win = find_window(w_target)
                        if not win:
                            raise ValueError(f"Window matching '{w_target}' not found.")
                        focus_window(win["hwnd"])
                        step_record["details"] = f"Focused '{win['title']}'"

                    elif act == "close_window":
                        w_target = step.get("target") or step.get("query")
                        if not w_target:
                            raise ValueError(f"Step {idx}: 'close_window' requires 'target'.")
                        force = bool(step.get("force", False))
                        ok = close_window_safely(w_target, force=force)
                        step_record["details"] = f"Closed window matching '{w_target}' (success={ok})"

                    elif act == "launch_app":
                        app_name = step.get("name") or step.get("query")
                        if not app_name:
                            raise ValueError(f"Step {idx}: 'launch_app' requires 'name'.")
                        app_args = step.get("args")
                        res = launch_application(app_name, app_args)
                        if res.get("status") == "error":
                            raise RuntimeError(res.get("message", "App launch failed."))
                        step_record["details"] = f"Launched '{app_name}' (status={res.get('status')})"

                    elif act == "manage_window":
                        w_target = step.get("target")
                        if not w_target:
                            raise ValueError(f"Step {idx}: 'manage_window' requires 'target'.")
                        sub_act = step.get("sub_action", "snap")
                        if sub_act == "snap":
                            res = default_window_manager.snap(w_target, step.get("position", "left"))
                        elif sub_act == "state":
                            res = default_window_manager.set_state(w_target, step.get("state", "restore"))
                        elif sub_act == "move_resize":
                            b = step.get("bounds", [100, 100, 800, 600])
                            res = default_window_manager.move_resize(w_target, b[0], b[1], b[2], b[3])
                        else:
                            raise ValueError(f"Unknown manage_window sub_action '{sub_act}'")
                        step_record["details"] = f"Window {sub_act}: {res.get('status')}"

                    elif act == "control_media":
                        sub_act = step.get("sub_action") or step.get("command", "play_pause")
                        st = int(step.get("steps", 1))
                        if sub_act == "volume_up":
                            default_media_controller.volume_up(st)
                        elif sub_act == "volume_down":
                            default_media_controller.volume_down(st)
                        elif sub_act == "toggle_mute":
                            default_media_controller.toggle_mute()
                        elif sub_act == "play_pause":
                            default_media_controller.play_pause()
                        elif sub_act == "next_track":
                            default_media_controller.next_track()
                        elif sub_act == "prev_track":
                            default_media_controller.prev_track()
                        step_record["details"] = f"Media command: {sub_act}"

                    elif act == "invoke_element":
                        e_target = step.get("target")
                        e_query = step.get("query")
                        ok = invoke_element(target=e_target, name=e_query)
                        step_record["details"] = f"Invoked '{e_query}' (success={ok})"

                    elif act == "set_value":
                        e_target = step.get("target")
                        e_query = step.get("query")
                        e_val = step.get("text", "")
                        ok = set_element_value(target=e_target, name=e_query, value=e_val)
                        step_record["details"] = f"Set value for '{e_query}' (success={ok})"

                    else:
                        raise ValueError(f"Unknown action: '{act}'")

                    step_record["status"] = "success"
                    step_record["latency_ms"] = round((time.time() - t_step_start) * 1000, 1)
                    execution_log.append(step_record)

                except Exception as step_err:
                    step_record["status"] = "failed"
                    step_record["error"] = str(step_err)
                    step_record["latency_ms"] = round((time.time() - t_step_start) * 1000, 1)
                    execution_log.append(step_record)
                    # Halt on error
                    summary = {
                        "status": "partial_failure",
                        "completed_steps": idx - 1,
                        "failed_step": idx,
                        "total_time_ms": round((time.time() - start_total) * 1000, 1),
                        "log": execution_log,
                    }
                    return [{"type": "text", "text": json.dumps(summary, indent=2)}], True

            summary = {
                "status": "success",
                "completed_steps": len(steps),
                "total_time_ms": round((time.time() - start_total) * 1000, 1),
                "log": execution_log,
            }
            return [{"type": "text", "text": json.dumps(summary, indent=2)}], False

        elif name == "record_screen":
            action = args.get("action", "status")
            if action == "start":
                res = default_recorder.start(
                    fps=int(args.get("fps", 15)),
                    target=args.get("target"),
                    crop_region=tuple(args["crop_region"]) if args.get("crop_region") else None,
                    max_dim=int(args.get("max_dim", 800)),
                    quality=int(args.get("quality", 75)),
                    include_cursor=bool(args.get("include_cursor", True)),
                    max_duration=float(args.get("max_duration", 120.0)),
                )
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            elif action == "stop":
                out_path = args.get("output_path")
                if not out_path:
                    return [{"type": "text", "text": "Error: output_path is required to stop recording."}], True
                fmt = args.get("format", "webp")
                res = default_recorder.stop(output_path=out_path, format=fmt)
                is_err = res.get("status") == "error"
                return [{"type": "text", "text": json.dumps(res, indent=2)}], is_err
            elif action == "pause":
                res = default_recorder.pause()
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            elif action == "resume":
                res = default_recorder.resume()
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False
            else:
                res = default_recorder.status()
                return [{"type": "text", "text": json.dumps(res, indent=2)}], False

        else:
            return [{"type": "text", "text": f"Unknown tool: '{name}'"}], True

    def run(self):
        """Main stdio loop reading JSON-RPC requests from sys.stdin."""
        sys.stderr.write(f"[{SERVER_NAME}] Starting stdio JSON-RPC server (version {SERVER_VERSION})...\n")

        stdin_buf = sys.stdin.buffer
        stdout_buf = sys.stdout.buffer

        while True:
            try:
                line_bytes = stdin_buf.readline()
                if not line_bytes:
                    break

                line_str = line_bytes.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                # Support Content-Length / Content-Type HTTP-style header framing if present
                if line_str.lower().startswith("content-length:") or line_str.lower().startswith("content-type:"):
                    content_length = None
                    if line_str.lower().startswith("content-length:"):
                        content_length = int(line_str.split(":", 1)[1].strip())

                    # Loop through any remaining headers until blank line delimiter
                    while True:
                        hdr_line = stdin_buf.readline()
                        if not hdr_line or hdr_line.strip() == b"":
                            break
                        hdr_str = hdr_line.decode("utf-8", errors="replace").strip()
                        if hdr_str.lower().startswith("content-length:"):
                            content_length = int(hdr_str.split(":", 1)[1].strip())

                    if content_length is None:
                        continue

                    body_bytes = stdin_buf.read(content_length)
                    req_json = json.loads(body_bytes.decode("utf-8"))
                    uses_content_length = True
                else:
                    req_json = json.loads(line_str)
                    uses_content_length = False

                response = self.handle_request(req_json)
                if response is not None:
                    res_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
                    if uses_content_length:
                        stdout_buf.write(f"Content-Length: {len(res_bytes)}\r\n\r\n".encode("ascii"))
                        stdout_buf.write(res_bytes)
                    else:
                        stdout_buf.write(res_bytes + b"\n")
                    stdout_buf.flush()

            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                sys.stderr.write(f"[{SERVER_NAME}] Stdio Loop Error: {traceback.format_exc()}\n")


if __name__ == "__main__":
    server = MCPServer()
    server.run()
