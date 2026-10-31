"""
Native Windows WinRT OCR Engine (Local, Zero-Cost, 15ms Text Spotting).
Communicates with a persistent Windows PowerShell daemon executing Windows.Media.Ocr.OcrEngine
over stdio to spot text words and phrases with exact physical screen bounding boxes.
Compatible with Windows 10 (1809+) and Windows 11.
"""

import subprocess
import threading
import atexit
import os
import sys
import json
import time
import tempfile
import uuid
import re
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image


class WinRtOcrEngine:
    """
    Manages a persistent Windows Runtime OCR worker process.
    Provides sub-15ms text recognition and phrase location without external API costs.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._daemon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "winrt_ocr_daemon.ps1"
        )
        self._temp_dir = tempfile.gettempdir()
        self._initialized = False
        atexit.register(self.shutdown)

    def _cleanup_proc(self):
        """Safely cleans up daemon process and pipes without resource warnings."""
        if self._proc is not None:
            proc = self._proc
            self._proc = None
            self._initialized = False
            try:
                if proc.poll() is None:
                    try:
                        if proc.stdin and not proc.stdin.closed:
                            proc.stdin.write("EXIT\n")
                            proc.stdin.flush()
                    except Exception:
                        pass
                    proc.terminate()
                    proc.wait(timeout=1.0)
            except Exception:
                pass
            finally:
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe and not getattr(pipe, "closed", True):
                        try:
                            pipe.close()
                        except Exception:
                            pass

    def _ensure_daemon(self):
        """Starts or restarts the background PowerShell WinRT OCR worker."""
        if sys.platform != "win32":
            return
        if self._proc is not None and self._proc.poll() is None:
            return

        if not os.path.exists(self._daemon_path):
            raise FileNotFoundError(f"WinRT OCR daemon script not found at {self._daemon_path}")

        self._cleanup_proc()

        try:
            self._proc = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    self._daemon_path,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            # Wait for READY signal from daemon
            ready_line = self._proc.stdout.readline().strip()
            if ready_line != "READY":
                err = self._proc.stderr.read()
                self._cleanup_proc()
                raise RuntimeError(f"OCR daemon failed to initialize: {ready_line} (stderr: {err})")
            self._initialized = True
            sys.stderr.write("[WinRtOCR] Native Windows OCR daemon initialized and ready.\n")
        except Exception as e:
            sys.stderr.write(f"[WinRtOCR] Failed to start OCR daemon: {e}\n")
            self._cleanup_proc()
            raise

    def recognize(self, img: Image.Image) -> Dict[str, Any]:
        """
        Runs OCR on a PIL Image and returns detected text and word bounding boxes.
        Returns:
            {"status": "ok", "text": "...", "words": [{"text": str, "x": int, "y": int, "w": int, "h": int}]}
        """
        if sys.platform != "win32":
            from control.platform.hyprland.linux_ocr import default_linux_ocr
            return default_linux_ocr.recognize(img)

        with self._lock:
            self._ensure_daemon()

            # Verify process is still alive before sending command
            if self._proc is None or self._proc.poll() is not None:
                self._ensure_daemon()

            # Save frame to a unique temporary file to avoid collisions
            temp_path = os.path.join(self._temp_dir, f"ocr_frame_{uuid.uuid4().hex}.png")
            try:
                img.save(temp_path, format="PNG")
                self._proc.stdin.write(temp_path + "\n")
                self._proc.stdin.flush()

                response_line = self._proc.stdout.readline()
                if not response_line:
                    self._cleanup_proc()
                    raise RuntimeError("OCR daemon closed stdout unexpectedly.")

                try:
                    data = json.loads(response_line.strip(), strict=False)
                except Exception:
                    # Sanitize any raw control characters (except \t, \n, \r) if emitted by Windows 10 WinRT OCR
                    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', response_line.strip())
                    data = json.loads(cleaned, strict=False)

                if isinstance(data, dict):
                    words = data.get("words", [])
                    if isinstance(words, dict):
                        data["words"] = [words]
                    elif not isinstance(words, list):
                        data["words"] = []
                return data
            except Exception:
                # If communication fails, clean up proc to restart on next attempt
                self._cleanup_proc()
                raise
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

    def find_text(self, img: Image.Image, query: str) -> Optional[Dict[str, Any]]:
        """
        Searches for `query` in the image.
        Returns the bounding box [x, y, w, h] and center (cx, cy) of the first or best match.
        """
        query_norm = query.strip().lower()
        if not query_norm:
            return None

        ocr_res = self.recognize(img)
        if ocr_res.get("status") != "ok":
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

        # 2. Substring inside a single word
        for w in words:
            if query_norm in w["text"].strip().lower():
                return {
                    "text": w["text"],
                    "bbox": [w["x"], w["y"], w["w"], w["h"]],
                    "center": [w["x"] + w["w"] // 2, w["y"] + w["h"] // 2],
                    "confidence": 0.9,
                }

        # 3. Multi-word phrase search across contiguous word sequence
        query_tokens = query_norm.split()
        if len(query_tokens) > 1 and len(words) >= len(query_tokens):
            for i in range(len(words) - len(query_tokens) + 1):
                slice_words = words[i : i + len(query_tokens)]
                slice_text = " ".join(sw["text"].strip().lower() for sw in slice_words)
                if query_norm in slice_text or all(qt in slice_text for qt in query_tokens):
                    min_x = min(sw["x"] for sw in slice_words)
                    min_y = min(sw["y"] for sw in slice_words)
                    max_x = max(sw["x"] + sw["w"] for sw in slice_words)
                    max_y = max(sw["y"] + sw["h"] for sw in slice_words)
                    w = max_x - min_x
                    h = max_y - min_y
                    return {
                        "text": slice_text,
                        "bbox": [min_x, min_y, w, h],
                        "center": [min_x + w // 2, min_y + h // 2],
                        "confidence": 0.95,
                    }

        return None

    def shutdown(self):
        """Cleanly terminates the OCR daemon process."""
        if sys.platform != "win32":
            return

        with self._lock:
            self._cleanup_proc()


default_ocr = WinRtOcrEngine()
