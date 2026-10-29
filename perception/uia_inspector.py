"""
Windows UI Automation (UIA) Semantic Tree Inspector.
Extracts compact semantic accessibility trees (50-100 tokens), provides zero-token
direct element clicking by name/role, and detects empty trees for visual fallback.
"""

import sys
import ctypes
from ctypes import wintypes
from typing import Optional, List, Dict, Any, Tuple
from control.safety import ensure_interactive_desktop, run_in_interactive_desktop, user32

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
from perception.screen_capture import find_window, list_visible_windows, get_foreground_window_info

# Import uiautomation after desktop setup is available
import uiautomation as auto

# Prevent long UI hangs on unresponsive controls
auto.uiautomation.TIME_OUT_SECOND = 1.0

INTERACTIVE_TYPES = {
    "ButtonControl", "MenuItemControl", "MenuControl", "MenuBarControl",
    "TabItemControl", "EditControl", "CheckBoxControl", "RadioButtonControl",
    "ComboBoxControl", "HyperlinkControl", "TreeItemControl", "ListItemControl",
    "ToolBarControl", "ScrollBarControl", "SplitButtonControl", "HeaderItemControl"
}

CLEAN_ROLE_NAMES = {
    "ButtonControl": "Button",
    "MenuItemControl": "MenuItem",
    "MenuControl": "Menu",
    "MenuBarControl": "MenuBar",
    "TabItemControl": "Tab",
    "EditControl": "Edit",
    "CheckBoxControl": "CheckBox",
    "RadioButtonControl": "Radio",
    "ComboBoxControl": "ComboBox",
    "HyperlinkControl": "Link",
    "TreeItemControl": "TreeItem",
    "ListItemControl": "ListItem",
    "ToolBarControl": "ToolBar",
    "ScrollBarControl": "ScrollBar",
    "SplitButtonControl": "SplitButton",
    "PaneControl": "Pane",
    "WindowControl": "Window",
    "DocumentControl": "Document",
    "GroupControl": "Group",
    "TextControl": "Text",
}


def _clean_role(role_name: str) -> str:
    return CLEAN_ROLE_NAMES.get(role_name, role_name.replace("Control", ""))


def _clean_text(text: str) -> str:
    """Removes Private Use Area Unicode glyphs (e.g. Segoe Fluent Icons) and control characters."""
    if not text:
        return ""
    # Filter out Unicode Private Use Area (0xE000 - 0xF8FF) and control characters
    chars = [c for c in text if not (0xE000 <= ord(c) <= 0xF8FF or (ord(c) < 32 and c not in "\t\n\r"))]
    return "".join(chars).strip()


def get_control_bounds(control) -> Tuple[int, int, int, int]:
    rect = control.BoundingRectangle
    return (int(rect.left), int(rect.top), int(rect.width()), int(rect.height()))


def get_control_center(control) -> Tuple[int, int]:
    rect = control.BoundingRectangle
    cx = int(rect.left + rect.width() / 2)
    cy = int(rect.top + rect.height() / 2)
    return cx, cy


def _inspect_window_core(
    target: Optional[str] = None,
    max_depth: int = 4,
    max_elements: int = 50,
    win_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Extracts a compact semantic accessibility tree for target window or foreground window.
    Returns:
      - formatted_text: token-efficient representation (50-100 tokens)
      - elements: list of interactive element dicts with centers and bounding boxes
      - count: total elements extracted
      - has_rich_uia: True if enough interactive elements found, False if custom canvas
    """
    ensure_interactive_desktop()

    root_ctrl = None
    win_title = ""
    win_bounds = [0, 0, 0, 0]

    if target:
        if not win_info:
            win_info = find_window(target)
        if not win_info:
            w = auto.WindowControl(searchDepth=2, SubName=target)
            if w.Exists(0.2):
                root_ctrl = w
                win_title = w.Name
                rect = w.BoundingRectangle
                win_bounds = [int(rect.left), int(rect.top), int(rect.width()), int(rect.height())]
            else:
                raise ValueError(f"Target window matching '{target}' not found.")
        else:
            root_ctrl = auto.ControlFromHandle(win_info["hwnd"])
            win_title = win_info["title"]
            win_bounds = win_info["bounds"]
    else:
        # Check active foreground window first
        fg = get_foreground_window_info()
        if fg and fg["title"] and fg["title"] not in ("Program Manager", "Windows Input Experience"):
            root_ctrl = auto.ControlFromHandle(fg["hwnd"])
            win_title = fg["title"]
            win_bounds = fg["bounds"]

        if not root_ctrl:
            # Fallback to first visible top-level app window
            windows = list_visible_windows()
            if windows:
                chosen = windows[0]
                for w in windows:
                    if w["title"] and w["title"] not in ("Program Manager", "Windows Input Experience"):
                        chosen = w
                        break
                root_ctrl = auto.ControlFromHandle(chosen["hwnd"])
                win_title = chosen["title"]
                win_bounds = chosen["bounds"]
            else:
                root_ctrl = auto.GetRootControl()
                win_title = "Desktop"

    if not root_ctrl:
        return {
            "formatted_text": "No accessibility tree available.",
            "elements": [],
            "count": 0,
            "has_rich_uia": False,
        }

    elements: List[Dict[str, Any]] = []
    lines: List[str] = [f'Window: "{win_title}" @ {win_bounds}']

    def walk(node, current_depth: int):
        if len(elements) >= max_elements or current_depth > max_depth:
            return

        try:
            children = node.GetChildren()
        except Exception:
            return

        for child in children:
            if len(elements) >= max_elements:
                break

            try:
                rect = child.BoundingRectangle
                w = rect.width()
                h = rect.height()
                # Ignore invisible / offscreen controls
                if w <= 0 or h <= 0 or rect.left < -10000:
                    continue

                type_name = child.ControlTypeName
                name = _clean_text(child.Name) if child.Name else ""
                auto_id = _clean_text(child.AutomationId) if child.AutomationId else ""
                role = _clean_role(type_name)

                is_interactive = type_name in INTERACTIVE_TYPES or (name and len(name) > 0)

                if is_interactive:
                    bbox = [int(rect.left), int(rect.top), int(w), int(h)]
                    cx, cy = get_control_center(child)
                    elem_info = {
                        "name": name,
                        "role": role,
                        "id": auto_id,
                        "bbox": bbox,
                        "center": [cx, cy],
                        "enabled": bool(child.IsEnabled),
                    }
                    elements.append(elem_info)

                    # Build compact line representation
                    indent = "  " * current_depth
                    name_repr = f' "{name}"' if name else ""
                    id_repr = f' id="{auto_id}"' if auto_id else ""
                    lines.append(f"{indent}[{role}]{name_repr}{id_repr} @ {bbox}")

                # Recurse down
                walk(child, current_depth + 1)
            except Exception:
                continue

    walk(root_ctrl, 1)

    # If fewer than 3 interactive elements found, this is likely a custom canvas/game
    has_rich_uia = len(elements) >= 3

    return {
        "formatted_text": "\n".join(lines),
        "elements": elements,
        "count": len(elements),
        "has_rich_uia": has_rich_uia,
    }


def inspect_window(
    target: Optional[str] = None,
    max_depth: int = 4,
    max_elements: int = 50
) -> Dict[str, Any]:
    """
    Public API: Runs inspect_window inside run_in_interactive_desktop to ensure
    100% desktop handle attachment without UIPI or ERROR_BUSY failures.
    """
    win_info = find_window(target) if target else None
    return run_in_interactive_desktop(_inspect_window_core, target, max_depth, max_elements, win_info)


def find_element_by_query(
    target: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = None,
    automation_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Fast direct-lookup search for a specific UI element in the tree and returns its coordinates.
    Runs inside run_in_interactive_desktop for zero-guesswork precision in <0.2s.
    """
    # Fast bypass for Chromium / web browsers:
    # Browsers render DOM elements on GPU canvas without exposing UIA nodes unless specialized flags are set.
    # Bypassing UIA immediately routes element queries to sub-15ms WinRT OCR without tree-walk lag.
    if target:
        t_low = target.lower()
        if any(b in t_low for b in ["chrome", "brave", "edge", "firefox", "browser"]):
            return None
    fg = get_foreground_window_info()
    if fg and any(b in (fg.get("title") or "").lower() for b in ["chrome", "brave", "edge", "firefox", "google chrome"]):
        return None

    win_info = find_window(target) if target else None

    def _search():
        search_root = None
        if target:
            if win_info and win_info.get("hwnd"):
                try:
                    search_root = auto.ControlFromHandle(win_info["hwnd"])
                except Exception:
                    pass
            if not search_root:
                # Try finding window by SubName or ClassName
                w = auto.WindowControl(searchDepth=2, SubName=target)
                if not w.Exists(0.2):
                    w = auto.WindowControl(searchDepth=2, ClassName=target)
                if w and w.Exists(0.2):
                    search_root = w
        else:
            fg = get_foreground_window_info()
            if fg and fg["hwnd"]:
                try:
                    w = auto.ControlFromHandle(fg["hwnd"])
                    if w and w.Exists(0.2):
                        search_root = w
                except Exception:
                    pass

        if not search_root:
            search_root = auto.GetRootControl()

        if name:
            control_types = []
            if role:
                r_lower = role.lower()
                if "button" in r_lower: control_types.append(auto.ButtonControl)
                elif "tree" in r_lower: control_types.append(auto.TreeItemControl)
                elif "menu" in r_lower: control_types.append(auto.MenuItemControl)
                elif "tab" in r_lower: control_types.append(auto.TabItemControl)
                elif "list" in r_lower: control_types.append(auto.ListItemControl)
                elif "link" in r_lower: control_types.append(auto.HyperlinkControl)
                elif "edit" in r_lower: control_types.append(auto.EditControl)
            
            if not control_types:
                control_types = [
                    auto.TreeItemControl, auto.ListItemControl, auto.MenuItemControl,
                    auto.TabItemControl, auto.ButtonControl, auto.HyperlinkControl,
                    auto.SplitButtonControl, auto.Control
                ]

            candidates = []
            for ctype in control_types:
                try:
                    ctrl = ctype(searchFromControl=search_root, searchDepth=8, SubName=name)
                    if ctrl.Exists(0.15):
                        rect = ctrl.BoundingRectangle
                        w_px = rect.width()
                        h_px = rect.height()
                        if w_px > 0 and h_px > 0 and rect.left > -10000:
                            c_name = ctrl.Name or ""
                            cx = int(rect.left + w_px / 2)
                            cy = int(rect.top + h_px / 2)
                            info = {
                                "name": c_name,
                                "role": _clean_role(ctrl.ControlTypeName),
                                "id": ctrl.AutomationId or "",
                                "bbox": [int(rect.left), int(rect.top), int(w_px), int(h_px)],
                                "center": [cx, cy],
                                "enabled": bool(ctrl.IsEnabled),
                            }
                            # Exact or prefix match is preferred immediately
                            if c_name.strip().lower() == name.lower() or c_name.strip().lower().startswith(name.lower()):
                                return info
                            candidates.append(info)
                except Exception:
                    continue

            if candidates:
                return candidates[0]

            # If not found in primary search_root and no specific target was requested, check Taskbar ('Shell_TrayWnd')
            if not target:
                tb_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
                if tb_hwnd:
                    try:
                        tb_ctrl = auto.ControlFromHandle(tb_hwnd)
                        for ctype in [auto.ButtonControl, auto.ListItemControl, auto.Control]:
                            ctrl = ctype(searchFromControl=tb_ctrl, searchDepth=6, SubName=name)
                            if ctrl.Exists(0.15):
                                rect = ctrl.BoundingRectangle
                                w_px = rect.width()
                                h_px = rect.height()
                                if w_px > 0 and h_px > 0 and rect.left > -10000:
                                    cx = int(rect.left + w_px / 2)
                                    cy = int(rect.top + h_px / 2)
                                    return {
                                        "name": ctrl.Name,
                                        "role": _clean_role(ctrl.ControlTypeName),
                                        "id": ctrl.AutomationId or "",
                                        "bbox": [int(rect.left), int(rect.top), int(w_px), int(h_px)],
                                        "center": [cx, cy],
                                        "enabled": bool(ctrl.IsEnabled),
                                    }
                    except Exception:
                        pass

        # 2. Fallback to tree walk if direct search didn't find it
        tree_data = _inspect_window_core(target=target, max_depth=6, max_elements=150, win_info=win_info)
        name_lower = name.lower() if name else None
        role_lower = role.lower() if role else None
        id_lower = automation_id.lower() if automation_id else None

        for elem in tree_data["elements"]:
            match_name = (not name_lower) or (name_lower in elem["name"].lower())
            match_role = (not role_lower) or (role_lower in elem["role"].lower())
            match_id = (not id_lower) or (id_lower in elem["id"].lower())

            if match_name and match_role and match_id:
                return elem

        # 3. Tier 2 Fallback: Native WinRT OCR text spotting
        if name:
            try:
                from perception.winrt_ocr import default_ocr
                from perception.screen_capture import capture_window, capture_screen
                from control.mouse_engine import get_virtual_screen_bounds

                if target and win_info and win_info.get("hwnd"):
                    win_img = capture_window(win_info["hwnd"])
                    offset_x, offset_y = win_info["bounds"][0], win_info["bounds"][1]
                else:
                    win_img = capture_screen()
                    vx, vy, _, _ = get_virtual_screen_bounds()
                    offset_x, offset_y = vx, vy

                ocr_match = default_ocr.find_text(win_img, name)
                if ocr_match:
                    bx, by, bw, bh = ocr_match["bbox"]
                    abs_cx = offset_x + ocr_match["center"][0]
                    abs_cy = offset_y + ocr_match["center"][1]
                    abs_bbox = [offset_x + bx, offset_y + by, bw, bh]
                    return {
                        "name": ocr_match["text"],
                        "role": "Text (OCR)",
                        "id": "",
                        "bbox": abs_bbox,
                        "center": [abs_cx, abs_cy],
                        "enabled": True,
                        "source": "winrt_ocr",
                    }
            except Exception as e:
                sys.stderr.write(f"[UIA] OCR fallback error: {e}\n")

        return None

    return run_in_interactive_desktop(_search)


def invoke_element(target: Optional[str] = None, name: Optional[str] = None) -> bool:
    """Invokes a button or clickable control directly without moving cursor unnecessarily."""
    if not name:
        return False

    def _invoke():
        elem_info = find_element_by_query(target=target, name=name)
        if not elem_info:
            return False
        from control.mouse_engine import default_mouse
        default_mouse.click(elem_info["center"][0], elem_info["center"][1])
        return True

    return run_in_interactive_desktop(_invoke)


def set_element_value(target: Optional[str] = None, name: Optional[str] = None, value: str = "") -> bool:
    """Focuses target input control and instantaneously injects value."""
    if not name:
        return False

    def _set_val():
        import time
        elem_info = find_element_by_query(target=target, name=name, role="Edit")
        if not elem_info:
            elem_info = find_element_by_query(target=target, name=name)
        if not elem_info:
            return False

        from control.mouse_engine import default_mouse
        from control.clipboard import default_clipboard
        from control.keyboard_engine import default_keyboard
        default_mouse.click(elem_info["center"][0], elem_info["center"][1])
        time.sleep(0.04)
        default_keyboard.hotkey("ctrl", "a")
        time.sleep(0.02)
        default_clipboard.paste(value)
        return True

    return run_in_interactive_desktop(_set_val)

