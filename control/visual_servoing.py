"""
Closed-Loop Visual Servoing and Action Reaction Verification.
Monitors target bounding box pixel delta, active foreground window changes,
and UI state updates within 50ms of an action to verify execution without LLM roundtrips.
"""

import time
from typing import Optional, Dict, Any, Tuple
from PIL import Image, ImageChops

from control.mouse_engine import get_virtual_screen_bounds


class VisualServoing:
    """
    Verifies that a mouse or keyboard action produced an immediate visual or state change.
    """

    def __init__(self, sample_interval_s: float = 0.03, timeout_s: float = 0.35):
        self.sample_interval_s = sample_interval_s
        self.timeout_s = timeout_s

    def sample_state(self, bbox: Optional[Tuple[int, int, int, int]] = None) -> Dict[str, Any]:
        """Captures a pre-action snapshot of the target region and active window."""
        from perception.screen_capture import capture_screen, get_foreground_window_info
        fg = get_foreground_window_info()
        crop_img = None
        if bbox is not None:
            # Crop a small region around target with a 10px margin
            x, y, w, h = bbox
            margin = 10
            vx, vy, vw, vh = get_virtual_screen_bounds()
            x1 = max(vx, x - margin)
            y1 = max(vy, y - margin)
            w1 = min(vw - (x1 - vx), max(4, w + 2 * margin))
            h1 = min(vh - (y1 - vy), max(4, h + 2 * margin))
            try:
                crop_img = capture_screen(bbox=(x1, y1, w1, h1))
            except Exception:
                crop_img = None

        return {
            "fg_hwnd": fg["hwnd"] if fg else None,
            "fg_title": fg["title"] if fg else None,
            "crop_img": crop_img,
            "timestamp": time.time(),
        }

    def verify_reaction(
        self,
        pre_state: Dict[str, Any],
        bbox: Optional[Tuple[int, int, int, int]] = None,
        timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Polls for changes against pre_state.
        Returns verification result including latency and change type.
        """
        timeout = timeout_s or self.timeout_s
        start_time = time.time()
        from perception.screen_capture import capture_screen, get_foreground_window_info
        initial_hwnd = pre_state.get("fg_hwnd")
        initial_title = pre_state.get("fg_title")
        initial_crop = pre_state.get("crop_img")
        effective_timeout = timeout if initial_crop is not None else min(timeout, 0.08)

        while time.time() - start_time < effective_timeout:
            time.sleep(self.sample_interval_s)
            elapsed_ms = round((time.time() - start_time) * 1000, 1)

            # 1. Check window focus / foreground change
            curr_fg = get_foreground_window_info()
            if curr_fg:
                curr_hwnd = curr_fg.get("hwnd")
                curr_title = curr_fg.get("title")
                if curr_hwnd != initial_hwnd:
                    return {
                        "verified": True,
                        "change_type": "window_activated",
                        "latency_ms": elapsed_ms,
                        "details": f"Active window changed to '{curr_title}' (HWND {curr_hwnd})",
                    }
                elif curr_title != initial_title:
                    return {
                        "verified": True,
                        "change_type": "title_updated",
                        "latency_ms": elapsed_ms,
                        "details": f"Window title updated to '{curr_title}'",
                    }

            # 2. Check pixel delta on target bounding box if available
            if initial_crop is not None and bbox is not None:
                x, y, w, h = bbox
                margin = 10
                vx, vy, vw, vh = get_virtual_screen_bounds()
                x1 = max(vx, x - margin)
                y1 = max(vy, y - margin)
                w1 = min(vw - (x1 - vx), max(4, w + 2 * margin))
                h1 = min(vh - (y1 - vy), max(4, h + 2 * margin))
                try:
                    curr_crop = capture_screen(bbox=(x1, y1, w1, h1))
                    if curr_crop and curr_crop.size == initial_crop.size:
                        diff = ImageChops.difference(initial_crop, curr_crop)
                        diff_bbox = diff.getbbox()
                        if diff_bbox is not None:
                            # Filter out subpixel font dithering or micro noise
                            extrema = diff.getextrema()
                            if any(e[1] > 12 for e in extrema):
                                return {
                                    "verified": True,
                                    "change_type": "pixel_delta",
                                    "latency_ms": elapsed_ms,
                                    "details": f"Visual pixel change detected in target area ({diff_bbox})",
                                }
                except Exception:
                    pass

        # If timeout expired without detecting change
        return {
            "verified": False,
            "change_type": "none",
            "latency_ms": round((time.time() - start_time) * 1000, 1),
            "details": "No immediate visual delta detected within timeout.",
        }


default_servoing = VisualServoing()
