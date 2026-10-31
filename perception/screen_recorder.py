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
import subprocess
import shutil
import signal
import tempfile
from ctypes import wintypes
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image, ImageDraw

# Ensure project root is in path
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from perception.screen_capture import default_capture_manager, get_foreground_window_info

from control.safety import get_physical_cursor_pos, IS_WINDOWS

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
else:
    user32 = None
    gdi32 = None

get_current_cursor_pos = get_physical_cursor_pos


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

        # Linux Hardware PipeWire Recorder Process (wl-screenrec / wf-recorder)
        self._hardware_proc: Optional[subprocess.Popen] = None
        self._hardware_tmp_file: Optional[str] = None
        self._hardware_tool: Optional[str] = None

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
            return self._recording or (self._hardware_proc is not None and self._hardware_proc.poll() is None)

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
        Starts the continuous recording loop in a background thread or launches
        hardware-accelerated PipeWire/wlroots recording (wl-screenrec / wf-recorder) on Linux.
        """
        with self._lock:
            if self._recording or (self._hardware_proc and self._hardware_proc.poll() is None):
                return {
                    "status": "already_recording",
                    "elapsed_s": round(time.time() - self.start_time, 2),
                    "frame_count": len(self.frames),
                }

            self.fps = max(1, min(60, int(fps)))
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

            # Check for Linux Hardware-Accelerated PipeWire ScreenCast Portal (wl-screenrec / wf-recorder)
            hw_tool = None
            if sys.platform.startswith("linux"):
                if shutil.which("wl-screenrec"):
                    hw_tool = "wl-screenrec"
                elif shutil.which("wf-recorder"):
                    hw_tool = "wf-recorder"

            if hw_tool:
                try:
                    fd, tmp_video = tempfile.mkstemp(suffix=".mp4", prefix="aim_rec_")
                    os.close(fd)
                    self._hardware_tmp_file = tmp_video
                    self._hardware_tool = hw_tool

                    cmd = [hw_tool]
                    geo_str = None
                    if self.crop_region:
                        rx, ry, rw, rh = self.crop_region
                        geo_str = f"{rx},{ry} {rw}x{rh}"
                    elif self.target:
                        try:
                            _, bounds = default_capture_manager.get_raw_frame(target=self.target)
                            if bounds and len(bounds) >= 4 and bounds[2] > 0 and bounds[3] > 0:
                                geo_str = f"{bounds[0]},{bounds[1]} {bounds[2]}x{bounds[3]}"
                        except Exception:
                            pass

                    if hw_tool == "wl-screenrec":
                        cmd.extend(["-f", tmp_video])
                        if geo_str:
                            cmd.extend(["-g", geo_str])
                        if not self.include_cursor:
                            cmd.append("--no-cursor")
                        cmd.append("--low-power=off")
                    elif hw_tool == "wf-recorder":
                        cmd.extend(["-f", tmp_video])
                        if geo_str:
                            cmd.extend(["-g", geo_str])
                        if not self.include_cursor:
                            cmd.append("-c")

                    self._hardware_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )

                    sys.stderr.write(
                        f"[ScreenRecorder] Started Linux PipeWire hardware recording via {hw_tool} @ {self.fps} FPS (cmd={' '.join(cmd)})\n"
                    )

                    return {
                        "status": "started",
                        "backend": f"hardware_{hw_tool}",
                        "fps": self.fps,
                        "target": self.target or "full_screen",
                        "max_dim": self.max_dim,
                        "include_cursor": self.include_cursor,
                    }
                except Exception as ex:
                    sys.stderr.write(f"[ScreenRecorder] Hardware recording start failed: {ex}. Falling back to software capture.\n")
                    self._hardware_proc = None
                    self._hardware_tmp_file = None
                    self._hardware_tool = None

            # Fallback: software capture worker thread
            self._thread = threading.Thread(target=self._capture_worker, daemon=True)
            self._thread.start()

            sys.stderr.write(
                f"[ScreenRecorder] Started software recording @ {self.fps} FPS (target={self.target or 'full_screen'}, max_dim={self.max_dim})\n"
            )

            return {
                "status": "started",
                "backend": "software_pil",
                "fps": self.fps,
                "target": self.target or "full_screen",
                "max_dim": self.max_dim,
                "include_cursor": self.include_cursor,
            }

    def status(self) -> Dict[str, Any]:
        """Returns current recording session telemetry."""
        with self._lock:
            if not self._recording and not (self._hardware_proc and self._hardware_proc.poll() is None):
                return {"is_recording": False, "status": "idle"}

            elapsed = time.time() - self.start_time
            if self._hardware_proc and self._hardware_proc.poll() is None:
                return {
                    "is_recording": True,
                    "backend": f"hardware_{self._hardware_tool}",
                    "is_paused": self._paused,
                    "elapsed_s": round(elapsed, 2),
                    "fps": self.fps,
                    "target": self.target or "full_screen",
                    "max_dim": self.max_dim,
                }

            count = len(self.frames)
            current_fps = round(count / elapsed, 1) if elapsed > 0 else 0.0

            return {
                "is_recording": True,
                "backend": "software_pil",
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
            if not self._recording and not (self._hardware_proc and self._hardware_proc.poll() is None):
                return {"status": "not_recording"}
            self._paused = True
            if self._hardware_proc and self._hardware_proc.poll() is None:
                if hasattr(signal, "SIGSTOP") and hasattr(os, "kill"):
                    try:
                        os.kill(self._hardware_proc.pid, signal.SIGSTOP)
                    except Exception:
                        pass
                return {"status": "paused", "backend": f"hardware_{self._hardware_tool}"}
            return {"status": "paused", "frame_count": len(self.frames)}

    def resume(self) -> Dict[str, Any]:
        """Resumes frame acquisition."""
        with self._lock:
            if not self._recording and not (self._hardware_proc and self._hardware_proc.poll() is None):
                return {"status": "not_recording"}
            self._paused = False
            if self._hardware_proc and self._hardware_proc.poll() is None:
                if hasattr(signal, "SIGCONT") and hasattr(os, "kill"):
                    try:
                        os.kill(self._hardware_proc.pid, signal.SIGCONT)
                    except Exception:
                        pass
                return {"status": "resumed", "backend": f"hardware_{self._hardware_tool}"}
            return {"status": "resumed", "frame_count": len(self.frames)}

    def stop(self, output_path: str, format: str = "webp") -> Dict[str, Any]:
        """
        Stops the recording worker and compiles recorded stream or buffered frames
        into an MP4, WebP, or GIF file.
        """
        with self._lock:
            if not self._recording and not self._hardware_proc:
                return {"status": "not_recording", "error": "No active recording session."}

            self._recording = False
            self._paused = False
            hw_proc = self._hardware_proc
            hw_tmp = self._hardware_tmp_file
            hw_tool = self._hardware_tool
            self._hardware_proc = None
            self._hardware_tmp_file = None
            self._hardware_tool = None

        elapsed = time.time() - self.start_time

        # Handle Hardware Recording Process Termination
        if hw_proc:
            try:
                sig = getattr(signal, "SIGINT", signal.SIGTERM)
                hw_proc.send_signal(sig)
                try:
                    hw_proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    hw_proc.kill()
                    hw_proc.wait(timeout=2.0)
            except Exception as e:
                sys.stderr.write(f"[ScreenRecorder] Error stopping hardware process: {e}\n")

            if not hw_tmp or not os.path.exists(hw_tmp) or os.path.getsize(hw_tmp) == 0:
                return {"status": "error", "error": f"Hardware recording with {hw_tool} produced no data."}

            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            fmt = format.lower().strip()
            if fmt in ("mp4", "mkv", "webm") or output_path.lower().endswith((".mp4", ".mkv", ".webm")):
                shutil.move(hw_tmp, output_path)
                file_size_kb = round(os.path.getsize(output_path) / 1024, 1)
                return {
                    "status": "saved",
                    "output_path": os.path.abspath(output_path),
                    "backend": f"hardware_{hw_tool}",
                    "format": fmt if fmt in ("mp4", "mkv", "webm") else "mp4",
                    "duration_s": round(elapsed, 2),
                    "fps": self.fps,
                    "file_size_kb": file_size_kb,
                }

            if shutil.which("ffmpeg"):
                try:
                    ffmpeg_cmd = [
                        "ffmpeg", "-y", "-i", hw_tmp,
                        "-vf", f"fps={self.fps},scale=min({self.max_dim}\\,iw):-1:flags=lanczos",
                    ]
                    if fmt == "webp":
                        ffmpeg_cmd.extend(["-vcodec", "libwebp", "-lossless", "0", "-q:v", str(self.quality), "-loop", "0", output_path])
                    else:
                        ffmpeg_cmd.extend(["-loop", "0", output_path])

                    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    if os.path.exists(hw_tmp):
                        os.remove(hw_tmp)
                    file_size_kb = round(os.path.getsize(output_path) / 1024, 1)
                    return {
                        "status": "saved",
                        "output_path": os.path.abspath(output_path),
                        "backend": f"hardware_{hw_tool}_transcoded",
                        "format": fmt,
                        "duration_s": round(elapsed, 2),
                        "fps": self.fps,
                        "file_size_kb": file_size_kb,
                    }
                except Exception as ex:
                    sys.stderr.write(f"[ScreenRecorder] ffmpeg transcode failed: {ex}. Falling back to copying raw MP4.\n")

            final_mp4 = output_path if output_path.lower().endswith(".mp4") else f"{output_path}.mp4"
            shutil.move(hw_tmp, final_mp4)
            file_size_kb = round(os.path.getsize(final_mp4) / 1024, 1)
            return {
                "status": "saved",
                "output_path": os.path.abspath(final_mp4),
                "backend": f"hardware_{hw_tool}",
                "format": "mp4",
                "duration_s": round(elapsed, 2),
                "fps": self.fps,
                "file_size_kb": file_size_kb,
                "note": "Saved as MP4 because ffmpeg was unavailable for animated WebP/GIF transcode.",
            }

        # Software capture fallback
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
