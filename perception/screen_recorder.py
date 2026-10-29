"""
High-Performance Screen Recorder Engine for Windows (AIM-VR 3.0 Perception Subsystem).
Provides continuous, high-speed, thread-safe desktop and window recording.
Outputs highly compressed 24-bit animated WebP, GIF, or raw frames with zero external dependencies.
Includes optional hardware cursor rendering and granular AI controls.
"""

import sys
import os
import time
import threading
import ctypes
from ctypes import wintypes
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image, ImageDraw

# Ensure project root is in path
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from perception.screen_capture import default_capture_manager, get_foreground_window_info

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# Win32 Cursor Information Structure
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HICON),
        ("ptScreenPos", POINT),
    ]

CURSOR_SHOWING = 0x00000001


def get_current_cursor_pos() -> Tuple[int, int]:
    """Returns current physical cursor (x, y) coordinates."""
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


class ScreenRecorder:
    """
    Continuous screen recorder engine for autonomous agents.
    Captures smooth desktop or window streams and compiles them into animated WebP/GIF.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._recording = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None

        # Configuration for active recording session
        self.fps: int = 15
        self.target: Optional[str] = None
        self.crop_region: Optional[Tuple[int, int, int, int]] = None
        self.max_dim: int = 800
        self.quality: int = 75
        self.include_cursor: bool = True
        self.max_duration: float = 120.0  # Safety cutoff in seconds

        # Session metrics & buffer
        self.start_time: float = 0.0
        self.frames: List[Image.Image] = []
        self.frame_timestamps: List[float] = []

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(
        self,
        fps: int = 15,
        target: Optional[str] = None,
        crop_region: Optional[Tuple[int, int, int, int]] = None,
        max_dim: int = 800,
        quality: int = 75,
        include_cursor: bool = True,
        max_duration: float = 120.0,
    ) -> Dict[str, Any]:
        """
        Starts the continuous recording loop in a background thread.
        """
        with self._lock:
            if self._recording:
                return {
                    "status": "already_recording",
                    "elapsed_s": round(time.time() - self.start_time, 2),
                    "frame_count": len(self.frames),
                }

            self.fps = max(1, min(30, int(fps)))
            self.target = target
            self.crop_region = crop_region
            self.max_dim = int(max_dim)
            self.quality = int(quality)
            self.include_cursor = bool(include_cursor)
            self.max_duration = float(max_duration)

            self.frames.clear()
            self.frame_timestamps.clear()
            self.start_time = time.time()
            self._recording = True
            self._paused = False

            self._thread = threading.Thread(target=self._capture_worker, daemon=True)
            self._thread.start()

            sys.stderr.write(
                f"[ScreenRecorder] Started recording @ {self.fps} FPS (target={self.target or 'full_screen'}, max_dim={self.max_dim})\n"
            )

            return {
                "status": "started",
                "fps": self.fps,
                "target": self.target or "full_screen",
                "max_dim": self.max_dim,
                "include_cursor": self.include_cursor,
            }

    def status(self) -> Dict[str, Any]:
        """Returns current recording session telemetry."""
        with self._lock:
            if not self._recording:
                return {"is_recording": False, "status": "idle"}

            elapsed = time.time() - self.start_time
            count = len(self.frames)
            current_fps = round(count / elapsed, 1) if elapsed > 0 else 0.0

            return {
                "is_recording": True,
                "is_paused": self._paused,
                "elapsed_s": round(elapsed, 2),
                "frame_count": count,
                "fps": current_fps,
                "target": self.target or "full_screen",
                "max_dim": self.max_dim,
            }

    def pause(self) -> Dict[str, Any]:
        """Pauses frame acquisition."""
        with self._lock:
            if not self._recording:
                return {"status": "not_recording"}
            self._paused = True
            return {"status": "paused", "frame_count": len(self.frames)}

    def resume(self) -> Dict[str, Any]:
        """Resumes frame acquisition."""
        with self._lock:
            if not self._recording:
                return {"status": "not_recording"}
            self._paused = False
            return {"status": "resumed", "frame_count": len(self.frames)}

    def stop(self, output_path: str, format: str = "webp") -> Dict[str, Any]:
        """
        Stops the recording worker and compiles buffered frames into an animated WebP or GIF file.
        """
        with self._lock:
            if not self._recording:
                return {"status": "not_recording", "error": "No active recording session."}

            self._recording = False
            self._paused = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        with self._lock:
            frame_count = len(self.frames)
            elapsed = time.time() - self.start_time
            if frame_count == 0:
                return {"status": "error", "error": "No frames were captured during recording."}

            # Ensure parent output directory exists
            out_dir = os.path.dirname(os.path.abspath(output_path))
            os.makedirs(out_dir, exist_ok=True)

            fmt = format.lower().strip()
            if fmt not in ("webp", "gif"):
                fmt = "webp"

            # Compute average frame duration in ms
            frame_duration_ms = max(20, int(1000 / self.fps))

            sys.stderr.write(
                f"[ScreenRecorder] Compiling {frame_count} frames into {fmt.upper()} ({output_path})...\n"
            )

            first_frame = self.frames[0]
            other_frames = self.frames[1:]

            if fmt == "webp":
                first_frame.save(
                    output_path,
                    format="WEBP",
                    save_all=True,
                    append_images=other_frames,
                    duration=frame_duration_ms,
                    loop=0,
                    quality=self.quality,
                    method=4,  # High compression balance
                )
            else:
                first_frame.save(
                    output_path,
                    format="GIF",
                    save_all=True,
                    append_images=other_frames,
                    duration=frame_duration_ms,
                    loop=0,
                    optimize=True,
                )

            file_size_kb = round(os.path.getsize(output_path) / 1024, 1)
            sys.stderr.write(
                f"[ScreenRecorder] Saved {output_path} ({file_size_kb} KB, {frame_count} frames, {round(elapsed, 1)}s)\n"
            )

            # Free in-memory frames
            self.frames.clear()
            self.frame_timestamps.clear()

            return {
                "status": "saved",
                "output_path": os.path.abspath(output_path),
                "format": fmt,
                "frame_count": frame_count,
                "duration_s": round(elapsed, 2),
                "fps": round(frame_count / elapsed, 1) if elapsed > 0 else self.fps,
                "file_size_kb": file_size_kb,
            }

    def _draw_cursor(self, img: Image.Image, screen_offset: Tuple[int, int], scale: float):
        """Draws a crisp hardware cursor arrow onto the frame at physical mouse position."""
        try:
            cx, cy = get_current_cursor_pos()
            # Map physical screen coordinate to image local coordinate
            lx = int((cx - screen_offset[0]) * scale)
            ly = int((cy - screen_offset[1]) * scale)

            w, h = img.size
            if 0 <= lx < w and 0 <= ly < h:
                d = ImageDraw.Draw(img)
                # Draw standard cursor pointer arrow
                arrow_points = [
                    (lx, ly),
                    (lx, ly + 14),
                    (lx + 4, ly + 11),
                    (lx + 7, ly + 16),
                    (lx + 9, ly + 15),
                    (lx + 6, ly + 10),
                    (lx + 11, ly + 10),
                ]
                # Black outline
                d.polygon(arrow_points, fill="#FFFFFF", outline="#000000")
        except Exception:
            pass

    def _capture_worker(self):
        """High-speed capture loop executing on dedicated thread."""
        frame_interval = 1.0 / self.fps

        while True:
            loop_start = time.time()

            with self._lock:
                if not self._recording:
                    break
                if self._paused:
                    time.sleep(0.05)
                    continue
                # Auto-stop cutoff safety
                if loop_start - self.start_time > self.max_duration:
                    sys.stderr.write("[ScreenRecorder] Reached max duration safety cutoff. Stopping loop.\n")
                    self._recording = False
                    self.frames.clear()
                    self.frame_timestamps.clear()
                    break

            try:
                # Capture frame
                raw_img, bounds = default_capture_manager.get_raw_frame(target=self.target)
                offset = (bounds[0], bounds[1])

                # Crop if ROI specified
                if self.crop_region:
                    rx, ry, rw, rh = self.crop_region
                    raw_img = raw_img.crop((rx, ry, rx + rw, ry + rh))
                    offset = (bounds[0] + rx, bounds[1] + ry)

                orig_w, orig_h = raw_img.size
                scale = 1.0

                # Downscale for performance and filesize
                if self.max_dim > 0 and (orig_w > self.max_dim or orig_h > self.max_dim):
                    if orig_w >= orig_h:
                        new_w = self.max_dim
                        new_h = int(orig_h * (self.max_dim / orig_w))
                    else:
                        new_h = self.max_dim
                        new_w = int(orig_w * (self.max_dim / orig_h))
                    scale = new_w / float(orig_w)
                    frame_img = raw_img.resize((new_w, new_h), Image.Resampling.BILINEAR)
                else:
                    frame_img = raw_img.copy()

                # Render physical cursor
                if self.include_cursor:
                    self._draw_cursor(frame_img, offset, scale)

                with self._lock:
                    if self._recording:
                        max_frames = int(self.fps * self.max_duration)
                        if len(self.frames) >= max_frames:
                            sys.stderr.write("[ScreenRecorder] Frame buffer reached maximum capacity. Auto-resetting session.\n")
                            self._recording = False
                            self.frames.clear()
                            self.frame_timestamps.clear()
                            break
                        self.frames.append(frame_img)
                        self.frame_timestamps.append(loop_start)

            except Exception as e:
                sys.stderr.write(f"[ScreenRecorder] Frame capture error: {e}\n")

            # Pacing sleep to match target FPS
            elapsed = time.time() - loop_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


# Global default recorder instance
default_recorder = ScreenRecorder()
