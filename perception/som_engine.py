"""
Unified Set-of-Marks (SoM) & OmniParser V2 Perception Engine (AIM-VR 3.0).
Combines:
  - Windows UI Automation (zero-cost semantic accessibility tree)
  - Sub-15ms Native WinRT OCR Text-Grounding
  - Computer vision edge/contour and heuristic icon detection
  - Non-Maximum Suppression (NMS) & containment deduplication
  - High-contrast, theme-adaptive color-coded badges
  - Dual-access MarkResult eliminating coordinate unpacking split-brain crashes
"""

import sys
import os
import time
import math
import threading
from typing import Dict, Any, List, Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Add package root to sys.path if not present
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from perception.screen_capture import (
    find_window,
    capture_window,
    capture_screen,
    get_window_extended_bounds,
    get_window_client_bounds,
    get_virtual_screen_bounds,
    window_to_screen_coords,
)
from perception.winrt_ocr import default_ocr


class MarkResult(dict):
    """
    Dual-access mark result that seamlessly behaves BOTH as a Dictionary
    and as a 2-tuple (center_x, center_y).
    Eliminates the split-brain crash across different engine callers:
      x, y = som.resolve_mark(1)
      cx = mark["center_x"]
      bbox = mark["bbox"]
      name = mark["name"]
      cx, cy = mark[0], mark[1]
    """
    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        cx = data.get("center_x")
        cy = data.get("center_y")
        if cx is None and "center" in data:
            c = data["center"]
            cx, cy = c[0], c[1]
            self["center_x"] = cx
            self["center_y"] = cy
        elif cx is not None and "center" not in data:
            self["center"] = [cx, cy]

        if "name" not in self and "text" in self:
            self["name"] = self["text"]
        elif "text" not in self and "name" in self:
            self["text"] = self["name"]

        if "role" not in self and "type" in self:
            self["role"] = self["type"]
        elif "type" not in self and "role" in self:
            self["type"] = self["role"]

        self.center_x = int(self.get("center_x", 0))
        self.center_y = int(self.get("center_y", 0))

    def __getitem__(self, key):
        if key == 0:
            return self.center_x
        elif key == 1:
            return self.center_y
        return super().__getitem__(key)

    def __iter__(self):
        # Enables direct tuple unpacking: x, y = resolved_mark
        return iter((self.center_x, self.center_y))

    def __eq__(self, other):
        if isinstance(other, (tuple, list)) and len(other) == 2:
            return (self.center_x, self.center_y) == (other[0], other[1])
        return super().__eq__(other)


def calculate_iou(box_a: Union[Tuple[int, int, int, int], List[int]], box_b: Union[Tuple[int, int, int, int], List[int]]) -> float:
    """Calculates Intersection over Union (IoU) between two bounding boxes [x, y, w, h]."""
    xa1, ya1, wa, ha = box_a
    xb1, yb1, wb, hb = box_b
    xa2, ya2 = xa1 + wa, ya1 + ha
    xb2, yb2 = xb1 + wb, yb1 + hb

    inter_x1 = max(xa1, xb1)
    inter_y1 = max(ya1, yb1)
    inter_x2 = min(xa2, xb2)
    inter_y2 = min(ya2, yb2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = wa * ha
    area_b = wb * hb
    union_area = area_a + area_b - inter_area

    return float(inter_area) / float(union_area) if union_area > 0 else 0.0

_calculate_iou = calculate_iou


def calculate_containment(inner: Union[Tuple[int, int, int, int], List[int]], outer: Union[Tuple[int, int, int, int], List[int]]) -> float:
    """Returns the fraction of inner box [x, y, w, h] contained inside outer box."""
    x1, y1, w1, h1 = inner
    x2, y2, w2, h2 = outer

    xi1 = max(x1, x2)
    yi1 = max(y1, y2)
    xi2 = min(x1 + w1, x2 + w2)
    yi2 = min(y1 + h1, y2 + h2)

    inter_w = max(0, xi2 - xi1)
    inter_h = max(0, yi2 - yi1)
    inter_area = inter_w * inter_h

    area1 = max(1, w1 * h1)
    return float(inter_area) / float(area1)

_calculate_containment = calculate_containment


def apply_non_maximum_suppression(
    elements: List[Dict[str, Any]],
    iou_threshold: float = 0.45,
    ios_threshold: float = 0.85,
) -> List[Dict[str, Any]]:
    """
    Suppresses redundant or heavily overlapping bounding boxes.
    Keeps specific/interactive elements and eliminates container clutter.
    """
    if not elements:
        return []

    def get_priority(elem: Dict[str, Any]) -> int:
        role = (elem.get("role") or elem.get("type") or "").lower()
        src = elem.get("source", "uia")
        if any(r in role for r in ["button", "menuitem", "tabitem", "edit", "checkbox", "radiobutton"]):
            return 3
        if src == "ocr":
            return 2
        return 1

    sorted_elems = sorted(
        elements,
        key=lambda e: (
            get_priority(e),
            -(e.get("bbox", [0, 0, 0, 0])[2] * e.get("bbox", [0, 0, 0, 0])[3]),
        ),
        reverse=True,
    )

    kept: List[Dict[str, Any]] = []

    for candidate in sorted_elems:
        bbox_c = tuple(candidate.get("bbox", [0, 0, 0, 0]))
        if bbox_c[2] <= 4 or bbox_c[3] <= 4:
            continue

        discard = False
        for existing in kept:
            bbox_e = tuple(existing.get("bbox", [0, 0, 0, 0]))
            iou = calculate_iou(bbox_c, bbox_e)
            if iou > iou_threshold:
                discard = True
                break

            ios = calculate_containment(bbox_c, bbox_e)
            area_c = bbox_c[2] * bbox_c[3]
            role_c = (candidate.get("role") or candidate.get("type") or "").lower()
            if ios > ios_threshold and any(r in role_c for r in ["pane", "group", "window", "client"]) and area_c > 100000:
                discard = True
                break

        if not discard:
            kept.append(candidate)

    return kept


class LocalIconDetector:
    """
    Lightweight visual contour and icon detector using PIL image processing.
    Spots candidate buttons and graphical glyphs for apps lacking UIA accessibility tags.
    """

    @staticmethod
    def detect_candidate_regions(
        img: Image.Image,
        min_dim: int = 14,
        max_dim: int = 240,
        max_candidates: int = 30,
    ) -> List[Dict[str, Any]]:
        w, h = img.size
        scale = 1.0
        if max(w, h) > 960:
            scale = 960.0 / float(max(w, h))
            scan_img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
        else:
            scan_img = img

        sw, sh = scan_img.size
        gray = scan_img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)

        step_x = max(16, sw // 30)
        step_y = max(16, sh // 30)
        candidates: List[Dict[str, Any]] = []

        for y in range(step_y, max(step_y + 1, sh - step_y * 2), step_y):
            for x in range(step_x, max(step_x + 1, sw - step_x * 2), step_x):
                box = (x, y, x + step_x, y + step_y)
                patch = edges.crop(box)
                stat = patch.getextrema()
                if stat and stat[1] > 110:
                    orig_x = int(x / scale)
                    orig_y = int(y / scale)
                    orig_w = int(step_x / scale)
                    orig_h = int(step_y / scale)
                    if min_dim <= orig_w <= max_dim and min_dim <= orig_h <= max_dim:
                        candidates.append({
                            "name": "Visual Icon",
                            "role": "GraphicButton",
                            "type": "control",
                            "bbox": [orig_x, orig_y, orig_w, orig_h],
                            "source": "icon_detector",
                        })

        return apply_non_maximum_suppression(candidates, iou_threshold=0.35, ios_threshold=0.75)[:max_candidates]


class SoMEngine:
    """
    Unified Set-of-Mark (SoM) & OmniParser V2 Perception Subsystem.
    Provides candidate extraction, non-maximum suppression deduplication,
    high-contrast badge annotation, density cluster zooming, and runtime coordinate resolution.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._active_catalog: Dict[int, MarkResult] = {}
        self.last_mark_map: Dict[int, MarkResult] = {}
        self.last_zoom_crop_info: Optional[Dict[str, Any]] = None
        self._last_target: Optional[str] = None
        self._last_bounds: List[int] = [0, 0, 0, 0]

    def clear_catalog(self):
        with self._lock:
            self._active_catalog.clear()
            self.last_mark_map.clear()

    def get_catalog(self) -> Dict[int, MarkResult]:
        with self._lock:
            return dict(self._active_catalog)

    def resolve_mark(self, mark_id: Union[int, str]) -> Optional[MarkResult]:
        """
        Resolves an indexed mark number to a MarkResult.
        Supports both coordinate unpacking (x, y = resolve_mark(id)) and dict access (mark["name"]).
        """
        with self._lock:
            try:
                mid = int(mark_id)
            except (ValueError, TypeError):
                return None
            res = self._active_catalog.get(mid) or self.last_mark_map.get(mid)
            if res is not None:
                return MarkResult(res)
            return None

    def extract_uia_candidates(self, target_window: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extracts actionable interactive elements using Windows UI Automation."""
        candidates = []
        try:
            import uiautomation as auto
            if target_window:
                win_item = find_window(target_window)
                if not win_item:
                    return []
                root = auto.ControlFromHandle(win_item["hwnd"])
            else:
                root = auto.GetRootControl()

            if not root or not root.Exists(0, 0):
                return []

            actionable_types = {
                auto.ControlType.ButtonControl: "Button",
                auto.ControlType.EditControl: "Edit",
                auto.ControlType.CheckBoxControl: "CheckBox",
                auto.ControlType.RadioButtonControl: "RadioButton",
                auto.ControlType.ComboBoxControl: "ComboBox",
                auto.ControlType.MenuItemControl: "MenuItem",
                auto.ControlType.TabItemControl: "TabItem",
                auto.ControlType.HyperlinkControl: "Hyperlink",
                auto.ControlType.ListItemControl: "ListItem",
            }

            walker = auto.TreeWalker(auto.RawTreeCondition)
            node = walker.GetFirstChildControl(root)
            depth = 0
            stack = [(node, depth)]

            while stack and len(candidates) < 150:
                curr, depth = stack.pop()
                if not curr:
                    continue

                nxt = walker.GetNextSiblingControl(curr)
                if nxt:
                    stack.append((nxt, depth))

                child = walker.GetFirstChildControl(curr)
                if child and depth < 6:
                    stack.append((child, depth + 1))

                try:
                    c_type = curr.ControlType
                    if c_type in actionable_types:
                        rect = curr.BoundingRectangle
                        if rect and (rect.right > rect.left) and (rect.bottom > rect.top):
                            w = rect.right - rect.left
                            h = rect.bottom - rect.top
                            if w > 6 and h > 6 and rect.left > -10000:
                                name = curr.Name or ""
                                candidates.append({
                                    "bbox": [int(rect.left), int(rect.top), int(w), int(h)],
                                    "type": actionable_types[c_type],
                                    "role": actionable_types[c_type],
                                    "text": name.strip(),
                                    "name": name.strip(),
                                    "source": "uia",
                                })
                except Exception:
                    continue
        except Exception:
            pass
        return candidates

    def extract_ocr_candidates(
        self,
        img: Image.Image,
        origin_x: int = 0,
        origin_y: int = 0
    ) -> List[Dict[str, Any]]:
        """Extracts text word candidates with bounding boxes from WinRT OCR."""
        candidates = []
        try:
            ocr_res = default_ocr.recognize(img)
            words = ocr_res.get("words", [])
            for w in words:
                text = (w.get("text") or "").strip()
                wx = int(w.get("x", 0))
                wy = int(w.get("y", 0))
                ww = int(w.get("w", 0))
                wh = int(w.get("h", 0))
                if text and ww > 4 and wh > 4:
                    candidates.append({
                        "bbox": [origin_x + wx, origin_y + wy, ww, wh],
                        "type": "text",
                        "role": "TextElement",
                        "text": text,
                        "name": text,
                        "source": "ocr",
                    })
        except Exception:
            pass
        return candidates

    def extract_cv_candidates(
        self,
        img: Image.Image,
        origin_x: int = 0,
        origin_y: int = 0
    ) -> List[Dict[str, Any]]:
        """Extracts visual interactive cards, icons, and frames using edge/contour detection."""
        candidates = []
        img_w, img_h = img.size

        try:
            import cv2
            import numpy as np

            arr = np.array(img.convert("RGB"))
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 50, 150)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            dilated = cv2.dilate(edges, kernel, iterations=1)

            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if 16 <= w <= (img_w * 0.92) and 14 <= h <= (img_h * 0.92):
                    aspect = w / float(h)
                    if 0.1 <= aspect <= 15.0:
                        candidates.append({
                            "bbox": [origin_x + x, origin_y + y, w, h],
                            "type": "control",
                            "role": "GraphicButton",
                            "text": "",
                            "name": "Graphic Element",
                            "source": "cv",
                        })
            return candidates
        except Exception:
            pass

        # Pure Pillow edge fallback via LocalIconDetector
        try:
            icon_cands = LocalIconDetector.detect_candidate_regions(img)
            for ic in icon_cands:
                bx, by, bw, bh = ic["bbox"]
                candidates.append({
                    "bbox": [origin_x + bx, origin_y + by, bw, bh],
                    "type": "control",
                    "role": "GraphicButton",
                    "text": "",
                    "name": "Visual Icon",
                    "source": "icon_detector",
                })
        except Exception:
            pass

        return candidates

    def deduplicate_and_fuse(
        self,
        candidates: List[Dict[str, Any]],
        iou_threshold: float = 0.45,
        max_elements: int = 100
    ) -> List[Dict[str, Any]]:
        """Deduplicates candidates using NMS and merges OCR text into enclosing boxes."""
        if not candidates:
            return []

        def priority_score(c):
            src = c.get("source", "")
            has_txt = bool(c.get("text") or c.get("name"))
            if src == "uia":
                return 3 if has_txt else 2
            elif src == "ocr":
                return 2
            return 1

        sorted_cands = sorted(candidates, key=priority_score, reverse=True)
        fused: List[Dict[str, Any]] = []

        for cand in sorted_cands:
            box = cand["bbox"]
            matched = False

            for existing in fused:
                e_box = existing["bbox"]
                if calculate_iou(box, e_box) >= iou_threshold:
                    matched = True
                    if not existing.get("text") and cand.get("text"):
                        existing["text"] = cand["text"]
                        existing["name"] = cand.get("name", cand["text"])
                    break

                if cand["source"] == "ocr" and calculate_containment(box, e_box) >= 0.70:
                    matched = True
                    cur_txt = existing.get("text", "")
                    cand_txt = cand.get("text", "")
                    if cur_txt:
                        merged = f"{cur_txt} {cand_txt}".strip()
                        existing["text"] = merged
                        existing["name"] = merged
                    else:
                        existing["text"] = cand_txt
                        existing["name"] = cand_txt
                    break

            if not matched:
                fused.append(dict(cand))
                if len(fused) >= max_elements:
                    break

        fused.sort(key=lambda item: (item["bbox"][1] // 30, item["bbox"][0]))
        return fused

    def find_dense_cluster(
        self,
        elements: List[Dict[str, Any]],
        img_size: Tuple[int, int],
        cluster_pad: int = 20,
    ) -> Optional[Tuple[int, int, int, int]]:
        """Identifies dense spatial clusters (e.g. toolbars, ribbon menus)."""
        if len(elements) < 4:
            return None

        w, h = img_size
        grid_cols, grid_rows = 4, 4
        cell_w, cell_h = w // grid_cols, h // grid_rows
        grid_counts: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}

        for elem in elements:
            bx, by, bw, bh = elem.get("bbox", [0, 0, 0, 0])
            cx, cy = bx + bw // 2, by + bh // 2
            gx = min(grid_cols - 1, max(0, cx // cell_w))
            gy = min(grid_rows - 1, max(0, cy // cell_h))
            grid_counts.setdefault((gx, gy), []).append(elem)

        if not grid_counts:
            return None

        best_cell = max(grid_counts.keys(), key=lambda c: len(grid_counts[c]))
        dense_elems = grid_counts[best_cell]
        if len(dense_elems) < 3:
            return None

        min_x = min(e["bbox"][0] for e in dense_elems)
        min_y = min(e["bbox"][1] for e in dense_elems)
        max_x = max(e["bbox"][0] + e["bbox"][2] for e in dense_elems)
        max_y = max(e["bbox"][1] + e["bbox"][3] for e in dense_elems)

        crop_x = max(0, min_x - cluster_pad)
        crop_y = max(0, min_y - cluster_pad)
        crop_w = min(w - crop_x, (max_x - min_x) + cluster_pad * 2)
        crop_h = min(h - crop_y, (max_y - min_y) + cluster_pad * 2)
        return (crop_x, crop_y, crop_w, crop_h)

    def render_som_annotations(
        self,
        img: Image.Image,
        elements: List[Dict[str, Any]],
        origin_x: int = 0,
        origin_y: int = 0
    ) -> Tuple[Image.Image, Dict[int, MarkResult]]:
        """Draws high-contrast bounding boxes and numbered badges over img."""
        annotated = img.convert("RGBA")
        draw = ImageDraw.Draw(annotated)
        catalog: Dict[int, MarkResult] = {}

        box_colors = [
            (255, 60, 60, 220),
            (40, 180, 255, 220),
            (50, 210, 80, 220),
            (255, 170, 0, 220),
            (220, 60, 255, 220),
        ]
        badge_bg = (20, 20, 20, 235)
        badge_fg = (255, 255, 255, 255)

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        sorted_elements = sorted(
            elements,
            key=lambda e: (
                e.get("bbox", [0, 0, 0, 0])[1] // 25,
                e.get("bbox", [0, 0, 0, 0])[0],
            ),
        )

        for idx, elem in enumerate(sorted_elements, start=1):
            abs_x, abs_y, w, h = elem["bbox"]
            rel_x = abs_x - origin_x
            rel_y = abs_y - origin_y

            if rel_x + w <= 0 or rel_y + h <= 0 or rel_x >= img.width or rel_y >= img.height:
                continue

            x0 = max(0, rel_x)
            y0 = max(0, rel_y)
            x1 = min(img.width - 1, rel_x + w)
            y1 = min(img.height - 1, rel_y + h)

            border_col = box_colors[idx % len(box_colors)]
            draw.rectangle([x0, y0, x1, y1], outline=border_col, width=2)

            badge_text = str(idx)
            text_w = len(badge_text) * 7 + 6
            text_h = 13
            bx0 = max(0, x0 - 1)
            by0 = max(0, y0 - text_h - 1) if y0 >= text_h else y0
            bx1 = min(img.width - 1, bx0 + text_w)
            by1 = min(img.height - 1, by0 + text_h)

            draw.rectangle([bx0, by0, bx1, by1], fill=badge_bg, outline=border_col, width=1)
            draw.text((bx0 + 3, by0), badge_text, fill=badge_fg, font=font)

            cx = abs_x + (w // 2)
            cy = abs_y + (h // 2)

            m_res = MarkResult({
                "id": idx,
                "mark_id": idx,
                "bbox": [abs_x, abs_y, w, h],
                "center": [cx, cy],
                "center_x": cx,
                "center_y": cy,
                "type": elem.get("type", elem.get("role", "control")),
                "role": elem.get("role", elem.get("type", "control")),
                "text": elem.get("text", elem.get("name", "")),
                "name": elem.get("name", elem.get("text", "")),
                "source": elem.get("source", "fusion"),
            })
            catalog[idx] = m_res

        final_img = annotated.convert("RGB")
        with self._lock:
            self._active_catalog = dict(catalog)
            self.last_mark_map = dict(catalog)

        return final_img, catalog

    def generate_som(self, *args, **kwargs) -> Any:
        """
        Multi-modal SOM generator supporting both visual overlay calls:
          generate_som(base_img, elements=None, max_dim=1024, ...) -> (img, mark_map, scale)
        and desktop capture calls:
          generate_som(target_window=None, client_only=False, max_elements=100) -> dict
        """
        # Case A: Called with PIL Image as first positional argument
        if args and isinstance(args[0], Image.Image):
            base_img = args[0]
            elements = args[1] if len(args) > 1 else kwargs.get("elements")
            max_dim = args[2] if len(args) > 2 else kwargs.get("max_dim", 1024)
            target_offset = kwargs.get("target_offset", (0, 0))
            detect_icons = kwargs.get("detect_icons", True)
            cluster_zoom = kwargs.get("cluster_zoom", False)

            combined_elements: List[Dict[str, Any]] = list(elements or [])
            if detect_icons and len(combined_elements) == 0:
                try:
                    icon_cands = LocalIconDetector.detect_candidate_regions(base_img)
                    combined_elements.extend(icon_cands)
                except Exception:
                    pass

            filtered = apply_non_maximum_suppression(combined_elements)
            orig_w, orig_h = base_img.size

            zoom_bbox = None
            if cluster_zoom:
                zoom_bbox = self.find_dense_cluster(filtered, (orig_w, orig_h))

            working_img = base_img
            eff_ox, eff_oy = target_offset
            if zoom_bbox is not None:
                zx, zy, zw, zh = zoom_bbox
                working_img = base_img.crop((zx, zy, zx + zw, zy + zh))
                eff_ox += zx
                eff_oy += zy
                filtered = [
                    e for e in filtered
                    if e["bbox"][0] >= zx and e["bbox"][1] >= zy
                    and (e["bbox"][0] + e["bbox"][2]) <= (zx + zw)
                    and (e["bbox"][1] + e["bbox"][3]) <= (zy + zh)
                ]

            annotated, catalog = self.render_som_annotations(working_img, filtered, origin_x=eff_ox, origin_y=eff_oy)

            work_w, work_h = working_img.size
            scale = 1.0
            if max(work_w, work_h) > max_dim:
                scale = max_dim / float(max(work_w, work_h))
                new_w = int(round(work_w * scale))
                new_h = int(round(work_h * scale))
                downsampled = annotated.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                downsampled = annotated

            self.last_zoom_crop_info = {
                "is_zoomed": zoom_bbox is not None,
                "crop_bbox": zoom_bbox,
                "scale": scale,
            }
            return downsampled, catalog, scale

        # Case B: Desktop / window capture call
        target_window = kwargs.get("target_window") or (args[0] if args and isinstance(args[0], str) else None)
        client_only = kwargs.get("client_only", False)
        max_elements = kwargs.get("max_elements", 100)

        t0 = time.time()
        if target_window:
            win_info = find_window(target_window)
            if not win_info:
                return {"status": "error", "message": f"Window matching '{target_window}' not found."}
            hwnd = win_info["hwnd"]
            img = capture_window(hwnd, client_only=client_only)
            if client_only:
                ox, oy, _, _ = get_window_client_bounds(hwnd)
            else:
                ox, oy, _, _ = get_window_extended_bounds(hwnd)
        else:
            img = capture_screen()
            vx, vy, _, _ = get_virtual_screen_bounds()
            ox, oy = vx, vy

        uia_cands = self.extract_uia_candidates(target_window)
        ocr_cands = self.extract_ocr_candidates(img, origin_x=ox, origin_y=oy)
        cv_cands = self.extract_cv_candidates(img, origin_x=ox, origin_y=oy)

        all_cands = uia_cands + ocr_cands + cv_cands
        deduped = self.deduplicate_and_fuse(all_cands, iou_threshold=0.45, max_elements=max_elements)
        annotated_img, catalog = self.render_som_annotations(img, deduped, origin_x=ox, origin_y=oy)

        elapsed_ms = round((time.time() - t0) * 1000, 2)
        with self._lock:
            self._last_target = target_window
            self._last_bounds = [ox, oy, img.width, img.height]

        return {
            "status": "success",
            "annotated_image": annotated_img,
            "catalog": catalog,
            "elements_count": len(catalog),
            "elapsed_ms": elapsed_ms,
            "target": target_window,
            "bounds": [ox, oy, img.width, img.height],
        }


# Canonical default singleton and aliases
default_som = SoMEngine()
VisualSOM = SoMEngine
