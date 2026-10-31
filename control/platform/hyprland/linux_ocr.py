"""
Native Linux OCR Engine for Arch Linux Hyprland.
Uses Tesseract OCR with stdin/stdout pipe streaming (zero disk writes)
and parses TSV data for exact bounding boxes, word confidences, and text lines.
"""

import io
import sys
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image


class LinuxOcrEngine:
    """
    Tesseract-based native Linux OCR Engine.
    Streams image buffers directly into tesseract stdin and parses TSV word geometries.
    """

    def __init__(self, tesseract_cmd: Optional[str] = None):
        self.cmd = tesseract_cmd or shutil.which("tesseract") or "tesseract"

    def is_available(self) -> bool:
        """Returns True if tesseract is executable on system."""
        try:
            res = subprocess.run([self.cmd, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
            return res.returncode == 0
        except Exception:
            return False

    def recognize_text(self, image: Image.Image) -> Dict[str, Any]:
        """
        Runs OCR on PIL image, returning structured text words with bounding boxes.
        Zero disk writes: image is encoded to PNG in memory and piped to stdin.
        """
        if not self.is_available():
            return {
                "status": "unavailable",
                "text": "",
                "words": [],
                "lines": [],
                "error": "Tesseract OCR binary not found. Install via 'sudo pacman -S tesseract tesseract-data-eng'.",
            }

        # Encode image to PNG in memory
        buf = io.BytesIO()
        rgb_img = image.convert("RGB") if image.mode != "RGB" else image
        rgb_img.save(buf, format="PNG")
        png_data = buf.getvalue()

        try:
            # Run tesseract: tesseract stdin stdout tsv
            proc = subprocess.Popen(
                [self.cmd, "stdin", "stdout", "tsv"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout_data, stderr_data = proc.communicate(input=png_data, timeout=15.0)

            if proc.returncode != 0:
                return {
                    "status": "error",
                    "text": "",
                    "words": [],
                    "lines": [],
                    "error": stderr_data.decode("utf-8", errors="replace"),
                }

            tsv_text = stdout_data.decode("utf-8", errors="replace")
            words, lines, full_text = self._parse_tsv(tsv_text)

            return {
                "status": "success",
                "text": full_text,
                "words": words,
                "lines": lines,
                "count": len(words),
            }

        except Exception as e:
            return {
                "status": "error",
                "text": "",
                "words": [],
                "lines": [],
                "error": str(e),
            }

    def _parse_tsv(self, tsv_str: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        """
        Parses Tesseract TSV output format:
        level, page_num, block_num, par_num, line_num, word_num, left, top, width, height, conf, text
        """
        lines_raw = tsv_str.strip().split("\n")
        if len(lines_raw) < 2:
            return [], [], ""

        words = []
        lines_map = {}
        all_words_text = []

        header = lines_raw[0].split("\t")
        col_indices = {col.strip(): i for i, col in enumerate(header)}

        for row in lines_raw[1:]:
            parts = row.split("\t")
            if len(parts) <= max(col_indices.values()):
                continue

            conf_str = parts[col_indices.get("conf", 10)].strip()
            text = parts[col_indices.get("text", 11)].strip() if len(parts) > 11 else ""

            # Words have level == 5 and non-empty text
            if not text or conf_str == "-1":
                continue

            try:
                conf = float(conf_str)
                left = int(parts[col_indices["left"]])
                top = int(parts[col_indices["top"]])
                width = int(parts[col_indices["width"]])
                height = int(parts[col_indices["height"]])
                line_id = f"{parts[col_indices.get('block_num', 2)]}_{parts[col_indices.get('line_num', 4)]}"

                word_entry = {
                    "text": text,
                    "confidence": conf,
                    "bbox": [left, top, width, height],
                    "x": left,
                    "y": top,
                    "w": width,
                    "h": height,
                    "center": [left + width // 2, top + height // 2],
                }
                words.append(word_entry)
                all_words_text.append(text)

                if line_id not in lines_map:
                    lines_map[line_id] = {
                        "text": text,
                        "bbox": [left, top, width, height],
                        "words": [word_entry],
                    }
                else:
                    curr = lines_map[line_id]
                    curr["text"] += f" {text}"
                    curr["words"].append(word_entry)
                    # Expand line bbox
                    cur_b = curr["bbox"]
                    new_left = min(cur_b[0], left)
                    new_top = min(cur_b[1], top)
                    new_right = max(cur_b[0] + cur_b[2], left + width)
                    new_bottom = max(cur_b[1] + cur_b[3], top + height)
                    curr["bbox"] = [new_left, new_top, new_right - new_left, new_bottom - new_top]

            except Exception:
                continue

        return words, list(lines_map.values()), " ".join(all_words_text)

    def find_text(self, image: Image.Image, query: str) -> Optional[Dict[str, Any]]:
        """
        Searches for `query` in the image, returning the single best match dict
        conforming to WinRtOcrEngine schema:
            {"text": str, "bbox": [x, y, w, h], "center": [cx, cy], "confidence": float}
        """
        query_norm = query.strip().lower()
        if not query_norm:
            return None

        ocr_res = self.recognize(image)
        if ocr_res.get("status") not in ("ok", "success"):
            return None

        words = ocr_res.get("words", [])
        if not words:
            return None

        # 1. Exact single word match
        for w in words:
            if w["text"].strip().lower() == query_norm:
                return {
                    "text": w["text"],
                    "bbox": [w["x"], w["y"], w["w"], w["h"]],
                    "center": [w["x"] + w["w"] // 2, w["y"] + w["h"] // 2],
                    "confidence": 1.0,
                }

        # 2. Multi-word phrase search across sequential words on same line
        query_tokens = query_norm.split()
        if len(query_tokens) > 1:
            for i in range(len(words) - len(query_tokens) + 1):
                slice_words = words[i : i + len(query_tokens)]
                slice_text = " ".join(sw["text"] for sw in slice_words)
                slice_lower = " ".join(sw["text"].strip().lower() for sw in slice_words)
                if query_norm in slice_lower or all(qt in slice_lower for qt in query_tokens):
                    min_x = min(sw["x"] for sw in slice_words)
                    min_y = min(sw["y"] for sw in slice_words)
                    max_x = max(sw["x"] + sw["w"] for sw in slice_words)
                    max_y = max(sw["y"] + sw["h"] for sw in slice_words)
                    w_box = max_x - min_x
                    h_box = max_y - min_y
                    return {
                        "text": slice_text,
                        "bbox": [min_x, min_y, w_box, h_box],
                        "center": [min_x + w_box // 2, min_y + h_box // 2],
                        "confidence": 0.95,
                    }

            # Check full lines
            for line in ocr_res.get("lines", []):
                if query_norm in line["text"].lower():
                    b = line["bbox"]
                    return {
                        "text": line["text"],
                        "bbox": b,
                        "center": [b[0] + b[2] // 2, b[1] + b[3] // 2],
                        "confidence": 0.90,
                    }

        # 3. Substring in single word (e.g. "Download" in "Downloads")
        for w in words:
            word_clean = w["text"].strip().lower()
            if query_norm in word_clean or (len(word_clean) >= 4 and len(query_tokens) == 1 and word_clean in query_norm):
                return {
                    "text": w["text"],
                    "bbox": [w["x"], w["y"], w["w"], w["h"]],
                    "center": [w["x"] + w["w"] // 2, w["y"] + w["h"] // 2],
                    "confidence": 0.85,
                }

        return None

    def find_all_text(self, image: Image.Image, query: str) -> List[Dict[str, Any]]:
        """
        Locates all occurrences of query text in image lines and words.
        """
        res = self.recognize_text(image)
        if res.get("status") not in ("ok", "success"):
            return []

        q_lower = query.lower().strip()
        matches = []

        # 1. Check line matches
        for line in res.get("lines", []):
            if q_lower in line["text"].lower():
                matches.append({
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "center": [line["bbox"][0] + line["bbox"][2] // 2, line["bbox"][1] + line["bbox"][3] // 2],
                    "type": "line",
                })

        # 2. Check individual words
        for word in res.get("words", []):
            if q_lower in word["text"].lower():
                matches.append({
                    "text": word["text"],
                    "bbox": word["bbox"],
                    "center": word["center"],
                    "type": "word",
                })

        return matches

    def recognize(self, image: Image.Image) -> Dict[str, Any]:
        """Recognize alias matching WinRtOcrEngine interface."""
        res = self.recognize_text(image)
        if res.get("status") == "success":
            res["status"] = "ok"
        return res


# Default singleton instance
default_linux_ocr = LinuxOcrEngine()
LinuxOCR = LinuxOcrEngine

