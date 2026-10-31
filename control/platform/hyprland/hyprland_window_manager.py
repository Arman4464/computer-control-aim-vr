"""
Hyprland Window and Workspace Layout Manager (AIM-VR Arch Linux Control Subsystem).
Provides multi-monitor geometry computation, window enumeration via UNIX socket IPC,
floating coordinate repositioning, work-area snapping, workspace switching, and focus control.
"""

import sys
import time
from typing import Optional, Dict, Any, List, Tuple

from control.platform.base import BaseWindowManager
from control.platform.hyprland.hyprland_ipc import HyprlandIPC, default_hyprland_ipc


class HyprlandWindowManager(BaseWindowManager):
    """
    Native Window and Workspace Manager for Hyprland compositor.
    """

    def __init__(self, ipc: Optional[HyprlandIPC] = None):
        self.ipc = ipc or default_hyprland_ipc

    def get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """
        Calculates global virtual screen bounding box (left, top, width, height)
        spanning all active monitors taking scaling, rotation transform, and positions into account.
        """
        monitors = self.ipc.get_monitors()
        if not monitors:
            return 0, 0, 1920, 1080

        min_x = min(m.get("x", 0) for m in monitors)
        min_y = min(m.get("y", 0) for m in monitors)

        max_r_list = []
        max_b_list = []
        for m in monitors:
            scale = max(0.1, float(m.get("scale", 1.0)))
            w = int(m.get("width", 1920) / scale)
            h = int(m.get("height", 1080) / scale)
            if m.get("transform", 0) in (1, 3, 5, 7):
                w, h = h, w
            max_r_list.append(m.get("x", 0) + w)
            max_b_list.append(m.get("y", 0) + h)

        max_right = max(max_r_list)
        max_bottom = max(max_b_list)

        return min_x, min_y, max_right - min_x, max_bottom - min_y

    def list_monitors(self) -> List[Dict[str, Any]]:
        """
        Enumerates all active Wayland outputs/monitors connected to Hyprland.
        """
        raw_monitors = self.ipc.get_monitors()
        results = []
        for m in raw_monitors:
            scale = float(m.get("scale", 1.0))
            width = int(m.get("width", 1920))
            height = int(m.get("height", 1080))
            scaled_w = int(width / max(0.1, scale))
            scaled_h = int(height / max(0.1, scale))
            transform = int(m.get("transform", 0))
            if transform in (1, 3, 5, 7):
                scaled_w, scaled_h = scaled_h, scaled_w
            # Hyprland reserved format is [top, bottom, left, right]
            reserved = m.get("reserved", [0, 0, 0, 0])
            top_res = reserved[0] if len(reserved) > 0 else 0
            bottom_res = reserved[1] if len(reserved) > 1 else 0
            left_res = reserved[2] if len(reserved) > 2 else 0
            right_res = reserved[3] if len(reserved) > 3 else 0
            results.append({
                "id": m.get("id", 0),
                "name": m.get("name", ""),
                "bounds": [m.get("x", 0), m.get("y", 0), scaled_w, scaled_h],
                "raw_width": width,
                "raw_height": height,
                "scale": scale,
                "transform": transform,
                "focused": bool(m.get("focused", False)),
                "is_primary": bool(m.get("focused", False)),
                "reserved": [top_res, bottom_res, left_res, right_res],
                "work_area": [
                    m.get("x", 0) + left_res,
                    m.get("y", 0) + top_res,
                    scaled_w - left_res - right_res,
                    scaled_h - top_res - bottom_res,
                ],
            })
        return results

    def list_windows(self) -> List[Dict[str, Any]]:
        """
        Enumerates all active window clients from Hyprland IPC.
        """
        clients = self.ipc.get_clients()
        results = []
        active = self.get_active_window()
        active_addr = active.get("address") if active else None

        for c in clients:
            at = c.get("at", [0, 0])
            size = c.get("size", [0, 0])
            addr = c.get("address", "")
            results.append({
                "hwnd": addr,  # Abstract window identifier conforming to unified API
                "address": addr,
                "title": c.get("title", ""),
                "class": c.get("class", ""),
                "initial_class": c.get("initialClass", ""),
                "pid": c.get("pid", 0),
                "bounds": [at[0], at[1], size[0], size[1]],
                "workspace": c.get("workspace", {}),
                "floating": bool(c.get("floating", False)),
                "is_floating": bool(c.get("floating", False)),
                "fullscreen": bool(c.get("fullscreen", False)),
                "is_foreground": (addr == active_addr),
                "is_minimized": (c.get("workspace", {}).get("id", 0) < 0),
            })
        return results

    def get_active_window(self) -> Optional[Dict[str, Any]]:
        """
        Returns info for currently active/focused window.
        """
        win = self.ipc.get_active_window()
        if not win or not win.get("address"):
            return None
        at = win.get("at", [0, 0])
        size = win.get("size", [0, 0])
        addr = win.get("address", "")
        return {
            "hwnd": addr,
            "address": addr,
            "title": win.get("title", ""),
            "class": win.get("class", ""),
            "pid": win.get("pid", 0),
            "bounds": [at[0], at[1], size[0], size[1]],
            "workspace": win.get("workspace", {}),
            "floating": bool(win.get("floating", False)),
            "fullscreen": bool(win.get("fullscreen", False)),
            "is_foreground": True,
        }

    def find_window(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Finds window client matching query by address, title substring, class, or PID.
        """
        if not query:
            return self.get_active_window()

        q_lower = query.lower().strip()
        windows = self.list_windows()

        # 1. Exact address match (e.g. 0x560f4e3c9210)
        for w in windows:
            if w.get("address", "").lower() == q_lower or str(w.get("hwnd", "")).lower() == q_lower:
                return w

        # 2. Exact class match
        for w in windows:
            if w.get("class", "").lower() == q_lower:
                return w

        # 3. Title contains query
        for w in windows:
            if q_lower in w.get("title", "").lower():
                return w

        # 4. Class contains query
        for w in windows:
            if q_lower in w.get("class", "").lower():
                return w

        # 5. PID match
        if query.isdigit():
            q_pid = int(query)
            for w in windows:
                if w.get("pid") == q_pid:
                    return w

        return None

    def focus_window(self, identifier: Any) -> bool:
        """
        Brings window into focus via Hyprland dispatcher.
        """
        target_str = str(identifier).strip()
        win = self.find_window(target_str)
        if not win:
            return False
        addr = win["address"]
        resp = self.ipc.dispatch("focuswindow", f"address:{addr}")
        return "ok" in resp.lower() or resp == ""

    def close_window(self, identifier: Any, force: bool = False) -> bool:
        """
        Closes window via Hyprland dispatcher 'closewindow'.
        """
        win = self.find_window(str(identifier))
        if not win:
            return False
        addr = win["address"]
        resp = self.ipc.dispatch("closewindow", f"address:{addr}")
        return "ok" in resp.lower() or resp == ""

    def get_window_bounds(self, identifier: Any) -> Optional[Tuple[int, int, int, int]]:
        """Returns (x, y, w, h) bounds of window."""
        win = self.find_window(str(identifier))
        if win and "bounds" in win:
            b = win["bounds"]
            return b[0], b[1], b[2], b[3]
        return None

    def _get_target_monitor_for_window(self, win: Dict[str, Any]) -> Dict[str, Any]:
        """Finds monitor containing window center point or primary monitor."""
        monitors = self.list_monitors()
        if not monitors:
            return {
                "bounds": [0, 0, 1920, 1080],
                "work_area": [0, 0, 1920, 1080],
            }

        bounds = win.get("bounds", [0, 0, 800, 600])
        cx = bounds[0] + bounds[2] // 2
        cy = bounds[1] + bounds[3] // 2

        for m in monitors:
            mb = m["bounds"]
            if mb[0] <= cx <= mb[0] + mb[2] and mb[1] <= cy <= mb[1] + mb[3]:
                return m

        # Return focused or first monitor
        for m in monitors:
            if m.get("focused"):
                return m
        return monitors[0]

    def snap(self, target: str, position: str) -> Dict[str, Any]:
        """
        Snaps window to specified monitor region using Hyprland exact pixel positioning.
        Positions: 'left', 'right', 'top', 'bottom', 'top-left', 'top-right',
                   'bottom-left', 'bottom-right', 'center', 'maximize'.
        """
        win = self.find_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        addr = win["address"]
        mon = self._get_target_monitor_for_window(win)
        wa = mon.get("work_area", mon.get("bounds", [0, 0, 1920, 1080]))
        wx, wy, ww, wh = wa[0], wa[1], wa[2], wa[3]

        pos = position.lower().strip().replace("_", "-")
        half_w = ww // 2
        half_h = wh // 2

        if pos in ["left", "left-half"]:
            tx, ty, tw, th = wx, wy, half_w, wh
        elif pos in ["right", "right-half"]:
            tx, ty, tw, th = wx + half_w, wy, ww - half_w, wh
        elif pos in ["top", "top-half"]:
            tx, ty, tw, th = wx, wy, ww, half_h
        elif pos in ["bottom", "bottom-half"]:
            tx, ty, tw, th = wx, wy + half_h, ww, wh - half_h
        elif pos in ["top-left", "topleft"]:
            tx, ty, tw, th = wx, wy, half_w, half_h
        elif pos in ["top-right", "topright"]:
            tx, ty, tw, th = wx + half_w, wy, ww - half_w, half_h
        elif pos in ["bottom-left", "bottomleft"]:
            tx, ty, tw, th = wx, wy + half_h, half_w, wh - half_h
        elif pos in ["bottom-right", "bottomright"]:
            tx, ty, tw, th = wx + half_w, wy + half_h, ww - half_w, wh - half_h
        elif pos in ["center"]:
            tw = int(ww * 0.7)
            th = int(wh * 0.7)
            tx = wx + (ww - tw) // 2
            ty = wy + (wh - th) // 2
        elif pos in ["maximize", "full"]:
            tx, ty, tw, th = wx, wy, ww, wh
        else:
            return {"status": "error", "message": f"Unsupported snap position: '{position}'"}

        # 1. Ensure window is floating
        if not win.get("floating", False):
            self.ipc.dispatch("togglefloating", f"address:{addr}")
            time.sleep(0.05)

        # 2. Set exact size and position
        self.ipc.dispatch("resizewindowpixel", f"exact {tw} {th},address:{addr}")
        time.sleep(0.02)
        self.ipc.dispatch("movewindowpixel", f"exact {tx} {ty},address:{addr}")
        time.sleep(0.02)
        self.ipc.dispatch("focuswindow", f"address:{addr}")

        return {
            "status": "snapped",
            "target": win.get("title"),
            "address": addr,
            "position": pos,
            "bounds": [tx, ty, tw, th],
        }

    def set_state(self, target: str, state: str) -> Dict[str, Any]:
        """
        Sets window state: 'maximize', 'fullscreen', 'minimize' (special scratchpad), 'restore'.
        """
        win = self.find_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        addr = win["address"]
        st = state.lower().strip()

        if st in ["maximize", "fullscreen"]:
            self.focus_window(addr)
            self.ipc.dispatch("fullscreen", "1")
        elif st in ["minimize"]:
            # Move to special hidden scratchpad workspace in Hyprland
            self.ipc.dispatch("movetoworkspacesilent", f"special:minimized,address:{addr}")
        elif st in ["restore"]:
            # Focus and toggle fullscreen off or bring back from special workspace
            self.focus_window(addr)
            if win.get("fullscreen"):
                self.ipc.dispatch("fullscreen", "0")
            elif win.get("is_minimized"):
                active_ws = self.ipc.get_active_workspace().get("id", 1)
                self.ipc.dispatch("movetoworkspace", f"{active_ws},address:{addr}")
                self.focus_window(addr)
        else:
            return {"status": "error", "message": f"Unknown state: '{state}'"}

        return {"status": "state_changed", "target": win.get("title"), "state": st}

    def move_resize(self, target: str, x: int, y: int, width: int, height: int) -> Dict[str, Any]:
        """Moves and resizes window to exact pixel bounds."""
        win = self.find_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}

        addr = win["address"]
        if not win.get("floating", False):
            self.ipc.dispatch("togglefloating", f"address:{addr}")
            time.sleep(0.05)

        self.ipc.dispatch("resizewindowpixel", f"exact {width} {height},address:{addr}")
        time.sleep(0.02)
        self.ipc.dispatch("movewindowpixel", f"exact {x} {y},address:{addr}")
        time.sleep(0.02)
        self.focus_window(addr)

        return {
            "status": "moved_and_resized",
            "target": win.get("title"),
            "address": addr,
            "bounds": [x, y, width, height],
        }

    def switch_workspace(self, workspace_id: int) -> Dict[str, Any]:
        """Switches active workspace via Hyprland dispatcher."""
        self.ipc.dispatch("workspace", str(workspace_id))
        return {"status": "workspace_switched", "workspace": workspace_id}

    def move_window_to_workspace(self, target: str, workspace_id: int) -> Dict[str, Any]:
        """Moves window client to specified workspace."""
        win = self.find_window(target)
        if not win:
            return {"status": "error", "message": f"Window matching '{target}' not found."}
        addr = win["address"]
        self.ipc.dispatch("movetoworkspace", f"{workspace_id},address:{addr}")
        return {"status": "window_moved", "target": win.get("title"), "workspace": workspace_id}


# Default singleton instance
default_hyprland_wm = HyprlandWindowManager()
