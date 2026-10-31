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

    def find_text(self, image: Image.Image, query: str, fuzzy: bool = True) -> List[Dict[str, Any]]:
        """
        Locates query text or phrase in image.
        """
        res = self.recognize_text(image)
        if res.get("status") != "success":
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
        if not matches:
            for word in res.get("words", []):
                if q_lower in word["text"].lower():
                    matches.append({
                        "text": word["text"],
                        "bbox": word["bbox"],
                        "center": word["center"],
                        "type": "word",
                    })

    def recognize(self, image: Image.Image) -> Dict[str, Any]:
        """Recognize alias matching WinRtOcrEngine interface."""
        res = self.recognize_text(image)
        if res.get("status") == "success":
            res["status"] = "ok"
        return res


# Default singleton instance
default_linux_ocr = LinuxOcrEngine()
LinuxOCR = LinuxOcrEngine

