"""
Linux AT-SPI2 Semantic Accessibility Tree Inspector (AIM-VR 3.0 Perception Subsystem).
Provides zero-token semantic accessibility tree extraction for Linux (GNOME, GTK, Qt, Electron, Firefox)
over the FreeDesktop AT-SPI2 D-Bus bus (org.a11y.atspi).
Matches the exact schema and interface of Windows UI Automation (inspect_ui / find_element).
"""

import sys
import os
import re
import json
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple

# Mapping of AT-SPI2 role names to clean, unified semantic roles
ATSPI_ROLE_MAP = {
    "push button": "Button",
    "push-button": "Button",
    "button": "Button",
    "check box": "CheckBox",
    "check-box": "CheckBox",
    "checkbox": "CheckBox",
    "radio button": "Radio",
    "radio-button": "Radio",
    "menu item": "MenuItem",
    "menu-item": "MenuItem",
    "menu": "Menu",
    "menu bar": "MenuBar",
    "menu-bar": "MenuBar",
    "page tab": "Tab",
    "page-tab": "Tab",
    "tab": "Tab",
    "entry": "Edit",
    "text": "Text",
    "password text": "Edit",
    "combo box": "ComboBox",
    "combo-box": "ComboBox",
    "link": "Link",
    "hyperlink": "Link",
    "window": "Window",
    "frame": "Window",
    "dialog": "Window",
    "panel": "Pane",
    "filler": "Pane",
    "label": "Text",
    "scroll bar": "ScrollBar",
    "scroll-bar": "ScrollBar",
    "tool bar": "ToolBar",
    "tool-bar": "ToolBar",
    "tree table": "Tree",
    "tree": "Tree",
    "table": "List",
    "list": "List",
    "list item": "ListItem",
    "list-item": "ListItem",
    "slider": "Slider",
    "heading": "Text",
    "section": "Pane",
}

INTERACTIVE_ROLES = {
    "Button", "MenuItem", "Menu", "MenuBar", "Tab", "Edit",
    "CheckBox", "Radio", "ComboBox", "Link", "ScrollBar",
    "ToolBar", "ListItem", "Slider"
}



# Regex matching Unicode Private Use Area (PUA) characters:
# BMP PUA: U+E000 - U+F8FF
# Supplementary PUA-A: U+F0000 - U+FFFFD
# Supplementary PUA-B: U+100000 - U+10FFFD
# Total PUA range: 0xE000–0xF8FF and 0xF0000–0x10FFFF
_PUA_REGEX = re.compile(r"[\uE000-\uF8FF\U000F0000-\U0010FFFF]")


def _clean_text(text: str) -> str:
    """
    Strips Unicode Private Use Area (PUA) glyphs (e.g. icon fonts from FontAwesome,
    NerdFonts, MaterialIcons) from text, preventing raw icon font noise in trees.
    """
    if not text:
        return ""
    cleaned = _PUA_REGEX.sub("", text)
    return " ".join(cleaned.split())


def clean_atspi_role(raw_role: str) -> str:
    """Normalizes raw AT-SPI2 role names into compact unified roles."""
    clean = raw_role.lower().strip()
    return ATSPI_ROLE_MAP.get(clean, clean.capitalize().replace("-", " "))



class ATSPIInspector:
    """
    FreeDesktop AT-SPI2 Accessibility Inspector querying org.a11y.atspi over D-Bus.
    """

    _clean_text = staticmethod(_clean_text)

    def __init__(self, bus_address: Optional[str] = None):
        self._bus_address = bus_address
        self._mock_tree: Optional[Dict[str, Any]] = None

    def set_mock_tree(self, tree: Optional[Dict[str, Any]]):
        """Allows injecting synthetic accessibility trees for testing and simulation."""
        self._mock_tree = tree

    def get_atspi_bus_address(self) -> Optional[str]:
        """
        Resolves the AT-SPI D-Bus bus address from:
        1. Environment variable AT_SPI_BUS_ADDRESS
        2. org.a11y.Bus.GetAddress via busctl / gdbus on session bus
        3. Standard socket path /run/user/<uid>/at-spi/bus_0
        """
        if self._bus_address:
            return self._bus_address

        env_addr = os.environ.get("AT_SPI_BUS_ADDRESS")
        if env_addr:
            self._bus_address = env_addr
            return env_addr

        # Method 2: Query session bus for org.a11y.Bus
        if shutil.which("busctl"):
            try:
                res = subprocess.run(
                    ["busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"],
                    capture_output=True, text=True, timeout=1.5
                )
                if res.returncode == 0 and "s \"" in res.stdout:
                    match = re.search(r's "([^"]+)"', res.stdout)
                    if match:
                        self._bus_address = match.group(1)
                        return self._bus_address
            except Exception:
                pass

        if shutil.which("gdbus"):
            try:
                res = subprocess.run(
                    ["gdbus", "call", "--session", "--dest", "org.a11y.Bus", "--object-path", "/org/a11y/bus",
                     "--method", "org.a11y.Bus.GetAddress"],
                    capture_output=True, text=True, timeout=1.5
                )
                if res.returncode == 0 and "('" in res.stdout:
                    match = re.search(r"\('([^']+)'", res.stdout)
                    if match:
                        self._bus_address = match.group(1)
                        return self._bus_address
            except Exception:
                pass

        # Method 3: Check standard runtime socket
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        sock_candidate = f"/run/user/{uid}/at-spi/bus_0"
        if os.path.exists(sock_candidate):
            self._bus_address = f"unix:path={sock_candidate}"
            return self._bus_address

        return None

    def is_available(self) -> bool:
        """Checks if AT-SPI2 daemon is running and reachable."""
        if self._mock_tree is not None:
            return True
        return self.get_atspi_bus_address() is not None

    def inspect_tree(
        self,
        target: Optional[str] = None,
        max_depth: int = 4,
        max_elements: int = 50,
    ) -> Dict[str, Any]:
        """
        Extracts a compact semantic accessibility tree matching inspect_ui format:
        {
            "count": int,
            "has_rich_uia": bool,
            "formatted_text": str,
            "formatted_tree": str,
            "elements": [ {name, role, id, bbox, center, enabled}, ... ]
        }
        """
        if self._mock_tree is not None:
            res = self._filter_tree(self._mock_tree, target=target, max_depth=max_depth, max_elements=max_elements)
        elif not self.is_available():
            # Fall back to Hyprland Window Manager active window + OCR
            res = self._fallback_window_tree(target=target)
        else:
            # Query live AT-SPI2 bus
            raw_elements = self._query_atspi_elements(target=target, max_depth=max_depth, max_elements=max_elements)
            if not raw_elements:
                res = self._fallback_window_tree(target=target)
            else:
                res = self._format_elements_to_tree(raw_elements, target=target)

        # Ensure both formatted_tree and formatted_text keys are present
        if "formatted_tree" in res and "formatted_text" not in res:
            res["formatted_text"] = res["formatted_tree"]
        elif "formatted_text" in res and "formatted_tree" not in res:
            res["formatted_tree"] = res["formatted_text"]

        return res

    def _fallback_window_tree(self, target: Optional[str] = None) -> Dict[str, Any]:
        """Generates semantic tree from Hyprland IPC window list when AT-SPI2 is absent."""
        try:
            from control.platform import get_platform_driver
            driver = get_platform_driver()
            windows = driver.window_manager.list_windows()
            active_win = driver.window_manager.get_active_window()
        except Exception:
            windows = []
            active_win = None

        if target:
            t_lower = target.lower().strip()
            windows = [w for w in windows if t_lower in w.get("title", "").lower() or t_lower in w.get("class", "").lower()]

        lines = []
        elements = []
        for win in windows[:10]:
            title = _clean_text(win.get("title", ""))
            w_class = _clean_text(win.get("class", ""))
            b = win.get("bounds") or [0, 0, 800, 600]
            if len(b) < 4 or any(v is None for v in b):
                b = [0, 0, 800, 600]
            cx = b[0] + b[2] // 2
            cy = b[1] + b[3] // 2
            line = f'Window: "{title}" class="{w_class}" @ {b}'
            lines.append(line)
            elements.append({
                "name": title,
                "role": "Window",
                "id": str(win.get("hwnd", win.get("address", ""))),
                "bbox": b,
                "center": [cx, cy],
                "enabled": True,
            })

        formatted = "\n".join(lines) if lines else 'Window: "Root Workspace" @ [0, 0, 1920, 1080]'
        return {
            "count": len(elements),
            "has_rich_uia": len(elements) > 0,
            "formatted_text": formatted,
            "formatted_tree": formatted,
            "elements": elements,
        }

    def _query_atspi_elements(
        self,
        target: Optional[str] = None,
        max_depth: int = 4,
        max_elements: int = 50,
    ) -> List[Dict[str, Any]]:
        """Queries accessible elements via busctl or gdbus."""
        elements = []
        bus_addr = self.get_atspi_bus_address()
        if not bus_addr or not shutil.which("busctl"):
            return elements

        # Query tree of accessible objects under /org/a11y/atspi/accessible/root
        try:
            cmd = [
                "busctl",
                f"--address={bus_addr}",
                "tree",
                "org.a11y.atspi.Registry",
                "/org/a11y/atspi/accessible/root",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0:
                paths = [p.strip().replace("`->", "").replace("|-", "").strip() for p in res.stdout.split("\n") if "/org/a11y/atspi" in p]
                # Filter depth and limit
                for path in paths[:max_elements]:
                    elem = self._query_single_accessible(bus_addr, "org.a11y.atspi.Registry", path)
                    if elem:
                        if target:
                            w_title = (elem.get("window") or elem.get("app") or "").lower()
                            if w_title and target.lower().strip() not in w_title:
                                continue
                        elements.append(elem)
        except Exception:
            pass

        return elements

    def _query_single_accessible(self, bus_addr: str, service: str, path: str) -> Optional[Dict[str, Any]]:
        """Queries name, role, and extents of a single AT-SPI accessible object."""
        try:
            # 1. GetRoleName
            role_cmd = ["busctl", f"--address={bus_addr}", "call", service, path, "org.a11y.atspi.Accessible", "GetRoleName"]
            role_res = subprocess.run(role_cmd, capture_output=True, text=True, timeout=0.8)
            raw_role = "unknown"
            if role_res.returncode == 0 and 's "' in role_res.stdout:
                m = re.search(r's "([^"]+)"', role_res.stdout)
                if m:
                    raw_role = m.group(1)

            # 2. Name property
            name_cmd = ["busctl", f"--address={bus_addr}", "get-property", service, path, "org.a11y.atspi.Accessible", "Name"]
            name_res = subprocess.run(name_cmd, capture_output=True, text=True, timeout=0.8)
            name = ""
            if name_res.returncode == 0 and 's "' in name_res.stdout:
                m = re.search(r's "([^"]+)"', name_res.stdout)
                if m:
                    name = _clean_text(m.group(1))

            # 3. Component.GetExtents (coord_type=0 screen)
            ext_cmd = ["busctl", f"--address={bus_addr}", "call", service, path, "org.a11y.atspi.Component", "GetExtents", "u", "0"]
            ext_res = subprocess.run(ext_cmd, capture_output=True, text=True, timeout=0.8)
            bbox = [0, 0, 100, 30]
            if ext_res.returncode == 0 and "(iiii)" in ext_res.stdout:
                nums = re.findall(r"-?\d+", ext_res.stdout)
                if len(nums) >= 4:
                    bbox = [int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])]

            role = clean_atspi_role(raw_role)
            cx = bbox[0] + bbox[2] // 2
            cy = bbox[1] + bbox[3] // 2

            return {
                "name": name,
                "role": role,
                "id": path,
                "bbox": bbox,
                "center": [cx, cy],
                "enabled": True,
            }
        except Exception:
            return None

    def _filter_tree(
        self,
        tree: Dict[str, Any],
        target: Optional[str] = None,
        max_depth: int = 4,
        max_elements: int = 50,
    ) -> Dict[str, Any]:
        """Filters an injected or cached accessibility tree."""
        elements = tree.get("elements", [])
        if target:
            t_low = target.lower().strip()
            has_win_meta = any("window" in e or "app" in e for e in elements)
            if has_win_meta:
                elements = [
                    e for e in elements
                    if t_low in (e.get("window") or "").lower() or t_low in (e.get("app") or "").lower()
                ]

        limited = elements[:max_elements]
        return self._format_elements_to_tree(limited, target=target)

    def _format_elements_to_tree(self, elements: List[Dict[str, Any]], target: Optional[str] = None) -> Dict[str, Any]:
        """Formats normalized elements into hierarchical text tree."""
        lines = []
        if target:
            lines.append(f'Window: "{_clean_text(target)}"')
        else:
            lines.append('Window: "Desktop Root"')

        cleaned_elements = []
        for elem in elements:
            elem_copy = dict(elem)
            role = clean_atspi_role(elem_copy.get("role", "Control"))
            name = _clean_text(elem_copy.get("name", ""))
            elem_id = elem_copy.get("id", "")
            bbox = elem_copy.get("bbox") or [0, 0, 0, 0]
            if len(bbox) < 4 or any(v is None for v in bbox):
                bbox = [0, 0, 0, 0]

            elem_copy["name"] = name
            elem_copy["role"] = role
            elem_copy["bbox"] = bbox
            cleaned_elements.append(elem_copy)

            name_str = f' "{name}"' if name else ""
            id_str = f' id="{elem_id}"' if elem_id and not elem_id.startswith("/") else ""
            line = f'  [{role}]{name_str}{id_str} @ {bbox}'
            lines.append(line)

        tree_text = "\n".join(lines)
        return {
            "count": len(cleaned_elements),
            "has_rich_uia": len(cleaned_elements) > 0,
            "formatted_text": tree_text,
            "formatted_tree": tree_text,
            "elements": cleaned_elements,
        }

    def find_element(
        self,
        query: str,
        role: Optional[str] = None,
        target: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Locates the single best matching accessible element by name and optional role.
        Returns conforming dict: {name, role, id, bbox, center, enabled}.
        """
        tree_res = self.inspect_tree(target=target, max_elements=100)
        elements = tree_res.get("elements", [])
        if not elements:
            return None

        if not query or not query.strip():
            return None

        q_cleaned = _clean_text(query).lower()
        q_lower = q_cleaned if q_cleaned else query.lower().strip()
        if not q_lower:
            return None

        role_lower = role.lower().strip() if role else None

        # 1. Exact name match + exact role match
        for elem in elements:
            if elem.get("name", "").lower() == q_lower:
                if not role_lower or elem.get("role", "").lower() == role_lower:
                    return elem

        # 2. Substring name match + role match
        for elem in elements:
            if q_lower in elem.get("name", "").lower():
                if not role_lower or elem.get("role", "").lower() == role_lower:
                    return elem

        # 3. ID match
        for elem in elements:
            if q_lower in elem.get("id", "").lower():
                return elem

        return None

    def find_element_at_point(
        self,
        x: int,
        y: int,
        target: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Locates the most specific accessible element containing point (x, y).
        Returns conforming dict: {name, role, id, bbox, bounding_box, center, enabled}.
        """
        tree_res = self.inspect_tree(target=target, max_elements=100)
        elements = tree_res.get("elements", [])
        if not elements:
            return None

        candidates = []
        for elem in elements:
            b = elem.get("bbox") or [0, 0, 0, 0]
            if len(b) >= 4:
                ex, ey, ew, eh = b[0], b[1], b[2], b[3]
                if ex <= x <= ex + ew and ey <= y <= ey + eh:
                    area = ew * eh
                    candidates.append((area, elem))

        if not candidates:
            return None

        # Sort by area ascending so the smallest enclosing child is selected
        candidates.sort(key=lambda c: c[0])
        best = dict(candidates[0][1])
        if "bbox" in best and "bounding_box" not in best:
            best["bounding_box"] = best["bbox"]
        return best


# Default singleton instance
default_atspi = ATSPIInspector()
