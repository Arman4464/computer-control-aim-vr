"""
Unit tests for the High-Speed Screen Recorder Engine (AIM-VR 3.0 Perception Subsystem).
"""

import unittest
import os
import time
from PIL import Image
from perception.screen_recorder import ScreenRecorder


class TestScreenRecorder(unittest.TestCase):
    """Verifies ScreenRecorder frame capture loop, status telemetry, and WebP compilation."""

    def setUp(self):
        self.recorder = ScreenRecorder()
        self.test_output = os.path.abspath("tests/test_rec_output.webp")

    def tearDown(self):
        if self.recorder.is_recording:
            try:
                self.recorder.stop(self.test_output)
            except Exception:
                pass
        if os.path.exists(self.test_output):
            try:
                os.remove(self.test_output)
            except OSError:
                pass

    def test_recorder_lifecycle_and_webp_generation(self):
        # 1. Start recording
        start_res = self.recorder.start(fps=15, max_dim=400, quality=70, include_cursor=True)
        self.assertEqual(start_res["status"], "started")
        self.assertTrue(self.recorder.is_recording)

        # 2. Check telemetry
        time.sleep(0.6)  # Record ~8-10 frames
        status = self.recorder.status()
        self.assertTrue(status["is_recording"])
        self.assertGreater(status["frame_count"], 2)

        # 3. Stop recording and compile animated WebP
        stop_res = self.recorder.stop(self.test_output, format="webp")
        self.assertEqual(stop_res["status"], "saved")
        self.assertFalse(self.recorder.is_recording)
        self.assertTrue(os.path.exists(self.test_output))
        self.assertGreater(stop_res["file_size_kb"], 0)

        # 4. Verify output file is a genuine animated WebP image
        with Image.open(self.test_output) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertTrue(getattr(img, "is_animated", False))
            self.assertGreater(img.n_frames, 2)
            self.assertLessEqual(max(img.size), 400)


if __name__ == "__main__":
    unittest.main()
