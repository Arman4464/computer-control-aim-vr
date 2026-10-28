"""
OmniParser V2 & Set-of-Marks (SOM) Visual Grounding Engine.
Provides:
  - Non-Maximum Suppression (NMS) and containment filtering to prevent badge collisions.
  - Local heuristic icon & graphical contour detector for non-UIA GPU-rendered apps (Electron, Chrome, games).
  - Spatial density clustering and sub-crop auto-zooming for dense toolbars and ribbon menus.
  - High-contrast, theme-adaptive color-coded badges for hallucination-free visual clicking.
"""

from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import io
import math


def calculate_iou(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
    """Calculates Intersection over Union (IoU) between two bounding boxes (x, y, w, h)."""
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


def calculate_containment(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
    """Calculates Intersection over Smaller area (IoS) to detect nesting."""
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

    min_area = min(wa * ha, wb * hb)
    return float(inter_area) / float(min_area) if min_area > 0 else 0.0


def apply_non_maximum_suppression(
    elements: List[Dict[str, Any]],
    iou_threshold: float = 0.45,
    ios_threshold: float = 0.85,
) -> List[Dict[str, Any]]:
    """
    Suppresses redundant or heavily overlapping bounding boxes.
    Keeps more specific/interactive elements and eliminates container clutter.
    """
    if not elements:
        return []

    # Priority ranking: explicit UIA controls > OCR text > raw visual icons
    def get_priority(elem: Dict[str, Any]) -> int:
        role = (elem.get("role") or "").lower()
        src = elem.get("source", "uia")
        if any(r in role for r in ["button", "menuitem", "tabitem", "edit", "checkbox", "radiobutton"]):
            return 3
        if src == "ocr":
            return 2
        return 1

    # Sort by priority desc, then by smaller area (more specific)
    sorted_elems = sorted(
        elements,
        key=lambda e: (
            get_priority(e),
            - (e.get("bbox", [0, 0, 0, 0])[2] * e.get("bbox", [0, 0, 0, 0])[3]),
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
            area_c = bbox_c[2] * bbox_c[3]
            area_e = bbox_e[2] * bbox_e[3]
            min_area = min(area_c, area_e)
            max_area = max(area_c, area_e)
            area_ratio = float(min_area) / float(max_area) if max_area > 0 else 0.0

            # 1. High spatial overlap
            if iou > iou_threshold:
                discard = True
                break

            # 2. Near-duplicate enclosing box (e.g. wrapper border with area ratio > 0.65)
            ios = calculate_containment(bbox_c, bbox_e)
            if ios > ios_threshold and area_ratio > 0.65:
                discard = True
                break

            # 3. Suppress giant generic structural panes (>100,000 px) if child elements exist
            role_c = (candidate.get("role") or "").lower()
            if ios > ios_threshold and any(r in role_c for r in ["pane", "group", "window", "client"]) and area_c > 100000:
                discard = True
                break

        if not discard:
            kept.append(candidate)

    return kept


class LocalIconDetector:
    """
    Lightweight visual contour and icon detector using PIL image processing.
    Extracts candidate buttons and graphical glyphs for apps lacking UIA accessibility tags.
    """

    @staticmethod
    def detect_candidate_regions(
        img: Image.Image,
        min_dim: int = 14,
        max_dim: int = 240,
        max_candidates: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Spots high-contrast rectangular button/icon contours across the image.
        """
        w, h = img.size
        # Fast downsampling for edge scanning if image is huge
        scale = 1.0
        if max(w, h) > 960:
            scale = 960.0 / float(max(w, h))
            scan_img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
        else:
            scan_img = img

        sw, sh = scan_img.size
        gray = scan_img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)

        # Scan for high edge density bounding patches using horizontal/vertical line projections
        # Inset scan grid by step to avoid synthetic boundary padding artifacts
        step_x = max(16, sw // 30)
        step_y = max(16, sh // 30)

        candidates: List[Dict[str, Any]] = []

        # Fast patch-based edge variance check (excluding 1-step border padding)
        for y in range(step_y, max(step_y + 1, sh - step_y * 2), step_y):
            for x in range(step_x, max(step_x + 1, sw - step_x * 2), step_x):
                box = (x, y, x + step_x, y + step_y)
                patch = edges.crop(box)
                stat = patch.getextrema()
                # If high contrast edge exists in this patch
                if stat and stat[1] > 110:
                    orig_x = int(x / scale)
                    orig_y = int(y / scale)
                    orig_w = int(step_x / scale)
                    orig_h = int(step_y / scale)

                    if min_dim <= orig_w <= max_dim and min_dim <= orig_h <= max_dim:
                        candidates.append({
                            "name": "Visual Icon",
                            "role": "GraphicButton",
                            "bbox": [orig_x, orig_y, orig_w, orig_h],
                            "source": "icon_detector",
                        })

        # Consolidate overlapping patches via NMS
        return apply_non_maximum_suppression(candidates, iou_threshold=0.35, ios_threshold=0.75)[:max_candidates]


class VisualSOM:
    """
    Set-of-Marks & OmniParser V2 perception engine.
    Supports NMS suppression, hybrid visual grounding, density clustering, and sub-crop zoom.
    """

    def __init__(self):
        self.last_mark_map: Dict[int, Dict[str, Any]] = {}
        self.last_zoom_crop_info: Optional[Dict[str, Any]] = None

    def find_dense_cluster(
        self,
        elements: List[Dict[str, Any]],
        img_size: Tuple[int, int],
        cluster_pad: int = 20,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Identifies the densest spatial cluster of UI controls (e.g. toolbars or ribbon menus).
        Returns bounding box (x, y, w, h) of the dense region.
        """
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

        # Find densest cell
        best_cell = max(grid_counts.keys(), key=lambda c: len(grid_counts[c]))
        dense_elems = grid_counts[best_cell]

        if len(dense_elems) < 3:
            return None

        min_x = min(e["bbox"][0] for e in dense_elems)
        min_y = min(e["bbox"][1] for e in dense_elems)
        max_x = max(e["bbox"][0] + e["bbox"][2] for e in dense_elems)
        max_y = max(e["bbox"][1] + e["bbox"][3] for e in dense_elems)

        x1 = max(0, min_x - cluster_pad)
        y1 = max(0, min_y - cluster_pad)
        x2 = min(w, max_x + cluster_pad)
        y2 = min(h, max_y + cluster_pad)

        return (x1, y1, x2 - x1, y2 - y1)

    def generate_som(
        self,
        base_img: Image.Image,
        elements: Optional[List[Dict[str, Any]]] = None,
        max_dim: int = 1024,
        target_offset: Tuple[int, int] = (0, 0),
        quality: int = 75,
        detect_icons: bool = True,
        cluster_zoom: bool = False,
    ) -> Tuple[Image.Image, Dict[int, Dict[str, Any]], float]:
        """
        Overlays high-contrast numbered badges onto base_img with NMS filtering,
        icon detection fallback, and optional density cluster zooming.
        """
        orig_w, orig_h = base_img.size
        combined_elements: List[Dict[str, Any]] = list(elements or [])

        # If no elements provided, supplement with local icon detector
        if detect_icons and len(combined_elements) == 0:
            try:
                icon_candidates = LocalIconDetector.detect_candidate_regions(base_img)
                combined_elements.extend(icon_candidates)
            except Exception:
                pass

        # Apply Non-Maximum Suppression to eliminate badge clutter & container overlap
        filtered_elements = apply_non_maximum_suppression(combined_elements)

        # Handle density cluster zoom if requested
        zoom_bbox = None
        if cluster_zoom:
            zoom_bbox = self.find_dense_cluster(filtered_elements, (orig_w, orig_h))

        working_img = base_img
        eff_offset_x, eff_offset_y = target_offset

        if zoom_bbox is not None:
            zx, zy, zw, zh = zoom_bbox
            working_img = base_img.crop((zx, zy, zx + zw, zy + zh))
            eff_offset_x += zx
            eff_offset_y += zy
            # Filter elements to only those inside the crop
            scoped_elems = []
            for e in filtered_elements:
                bx, by, bw, bh = e["bbox"]
                if bx >= zx and by >= zy and (bx + bw) <= (zx + zw) and (by + bh) <= (zy + zh):
                    scoped_elems.append(e)
            filtered_elements = scoped_elems

        work_w, work_h = working_img.size
        annotated = working_img.copy()
        draw = ImageDraw.Draw(annotated, "RGBA")

        # Load clean font
        try:
            font = ImageFont.truetype("arial.ttf", 13)
        except Exception:
            font = ImageFont.load_default()

        # Sort surviving marks deterministically in natural visual reading order (top-to-bottom, left-to-right)
        filtered_elements = sorted(
            filtered_elements,
            key=lambda e: (
                e.get("bbox", [0, 0, 0, 0])[1] // 25,
                e.get("bbox", [0, 0, 0, 0])[0],
            ),
        )

        mark_map: Dict[int, Dict[str, Any]] = {}
        mark_id = 1

        for elem in filtered_elements:
            bbox = elem.get("bbox")
            if not bbox:
                continue
            bx, by, bw, bh = bbox

            # Local coordinates relative to working image crop
            local_x = bx - eff_offset_x
            local_y = by - eff_offset_y

            if local_x + bw < 0 or local_y + bh < 0 or local_x > work_w or local_y > work_h:
                continue

            local_x = max(0, min(work_w - 1, local_x))
            local_y = max(0, min(work_h - 1, local_y))
            local_x2 = min(work_w - 1, local_x + bw)
            local_y2 = min(work_h - 1, local_y + bh)

            src = elem.get("source", "uia")
            # Color coding: Yellow for UIA, Green for OCR, Cyan for Icons
            if src == "icon_detector":
                badge_bg = (0, 220, 255, 235)       # Cyan
                badge_fg = (0, 0, 0, 255)
                box_outline = (0, 180, 255, 140)
            elif src == "ocr":
                badge_bg = (50, 220, 50, 235)       # Light Green
                badge_fg = (0, 0, 0, 255)
                box_outline = (50, 220, 50, 140)
            else:
                badge_bg = (255, 225, 0, 240)       # High-contrast Golden Yellow
                badge_fg = (0, 0, 0, 255)
                box_outline = (255, 200, 0, 160)

            # Draw translucent bounding box
            draw.rectangle([local_x, local_y, local_x2, local_y2], outline=box_outline, width=1)

            # Badge size computation
            badge_text = str(mark_id)
            try:
                left, top, right, bottom = font.getbbox(badge_text)
                tw, th = right - left, bottom - top
            except Exception:
                tw, th = len(badge_text) * 7, 11

            pad = 2
            badge_w = tw + pad * 2 + 2
            badge_h = th + pad * 2

            badge_x1 = local_x
            badge_y1 = max(0, local_y - badge_h) if local_y >= badge_h else local_y
            badge_x2 = badge_x1 + badge_w
            badge_y2 = badge_y1 + badge_h

            # High-contrast badge rectangle with rounded look
            draw.rectangle([badge_x1, badge_y1, badge_x2, badge_y2], fill=badge_bg, outline=(0, 0, 0, 255), width=1)
            draw.text((badge_x1 + pad + 1, badge_y1 + pad - 1), badge_text, fill=badge_fg, font=font)

            # Physical screen center coordinates
            cx = bx + bw // 2
            cy = by + bh // 2

            mark_map[mark_id] = {
                "mark_id": mark_id,
                "center_x": cx,
                "center_y": cy,
                "bbox": bbox,
                "name": elem.get("name", ""),
                "role": elem.get("role", ""),
                "source": src,
            }
            mark_id += 1

        # Downsample to max_dim (preserving aspect ratio) to drastically save vision tokens
        scale = 1.0
        if max(work_w, work_h) > max_dim:
            scale = max_dim / float(max(work_w, work_h))
            new_w = int(round(work_w * scale))
            new_h = int(round(work_h * scale))
            downsampled = annotated.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            downsampled = annotated

        self.last_mark_map = mark_map
        self.last_zoom_crop_info = {
            "is_zoomed": zoom_bbox is not None,
            "crop_bbox": zoom_bbox,
            "scale": scale,
        }
        return downsampled, mark_map, scale

    def resolve_mark(self, mark_id: int) -> Optional[Dict[str, Any]]:
        """Resolves a mark_id back to its physical screen coordinates."""
        return self.last_mark_map.get(int(mark_id))


default_som = VisualSOM()