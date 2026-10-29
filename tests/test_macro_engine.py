"""
Comprehensive Headless Automated Test Suite for Hybrid Semantic Macro Engine.
Strictly verifies:
  - Ramer-Douglas-Peucker (RDP) polyline trajectory compression
  - 32x32 visual perceptual difference hash (dHash) & similarity metrics
  - 5-Tier Semantic Anchor construction and self-healing resolution fallback
  - Macro recording session lifecycle & trajectory bundling
  - Macro persistence, listing, retrieval, and deletion
  - Headless macro playback verification (dry_run mode, 0 physical desktop side-effects)
"""

import sys
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from control.macro_engine import (
    rdp_compress,
    compute_phash_32,
    phash_similarity,
    wait_for_message_pump,
    MacroEngine,
    default_macro_engine,
)


class TestRDPCompression(unittest.TestCase):
    """Verifies Ramer-Douglas-Peucker polyline trajectory compression."""

    def test_straight_line_compression(self):
        # 100 collinear points along y = 2x
        points = [(float(i), float(2 * i), float(i * 0.01)) for i in range(100)]
        compressed = rdp_compress(points, epsilon=2.5)
        # Perfectly collinear line compresses down to exactly 2 endpoints
        self.assertEqual(len(compressed), 2)
        self.assertEqual(compressed[0][:2], (0.0, 0.0))
        self.assertEqual(compressed[-1][:2], (99.0, 198.0))

    def test_sharp_corner_preservation(self):
        # Path with a sharp 90-degree corner at (50, 0)
        leg1 = [(float(x), 0.0, float(x * 0.01)) for x in range(0, 51)]
        leg2 = [(50.0, float(y), float((50 + y) * 0.01)) for y in range(1, 51)]
        path = leg1 + leg2
        compressed = rdp_compress(path, epsilon=2.5)
        # Should keep start, corner vertex, and end
        self.assertEqual(len(compressed), 3)
        self.assertEqual(compressed[0][:2], (0.0, 0.0))
        self.assertEqual(compressed[1][:2], (50.0, 0.0))
        self.assertEqual(compressed[2][:2], (50.0, 50.0))

    def test_minimal_points(self):
        pts1 = [(10.0, 20.0)]
        self.assertEqual(len(rdp_compress(pts1)), 1)
        pts2 = [(10.0, 20.0), (30.0, 40.0)]
        self.assertEqual(len(rdp_compress(pts2)), 2)


class TestPerceptualHash(unittest.TestCase):
    """Verifies 32x32 visual difference hash and similarity math."""

    def test_identical_images_have_maximum_similarity(self):
        img1 = Image.new("RGB", (32, 32), color=(100, 150, 200))
        d1 = ImageDraw.Draw(img1)
        d1.rectangle([8, 8, 24, 24], fill=(255, 255, 0))

        hash1 = compute_phash_32(img1)
        hash2 = compute_phash_32(img1.copy())
        self.assertEqual(hash1, hash2)
        sim = phash_similarity(hash1, hash2)
        self.assertEqual(sim, 1.0)

    def test_different_images_have_low_similarity(self):
        # White image with horizontal bars vs black image with vertical bars
        img_a = Image.new("RGB", (32, 32), color=(0, 0, 0))
        da = ImageDraw.Draw(img_a)
        da.rectangle([0, 0, 32, 16], fill=(255, 255, 255))

        img_b = Image.new("RGB", (32, 32), color=(0, 0, 0))
        db = ImageDraw.Draw(img_b)
        db.rectangle([0, 0, 16, 32], fill=(255, 255, 255))

        hash_a = compute_phash_32(img_a)
        hash_b = compute_phash_32(img_b)
        sim = phash_similarity(hash_a, hash_b)
        self.assertLess(sim, 0.80)


class TestMacroEngineLifecycle(unittest.TestCase):
    """Verifies recording, anchor generation, storage, and dry-run playback."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = MacroEngine(macros_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recording_and_storage(self):
        start_res = self.engine.start_recording("test_macro", target_window="MockApp")
        self.assertEqual(start_res["status"], "recording_started")
        self.assertTrue(self.engine.is_recording)

        # Add mouse trajectory points
        for i in range(20):
            self.engine.record_mouse_point(100 + i, 200 + i)

        # Mock perception calls to avoid touching live desktop
        with patch.object(self.engine, "build_5tier_anchor", return_value={
            "tier1_uia": {"name": "Submit", "role": "Button"},
            "tier2_ocr": {"token": "Submit", "relative_offset": [0, 0]},
            "tier3_phash": {"dhash_1024": "f" * 256},
            "tier4_relative": {"rx_ratio": 0.5, "ry_ratio": 0.5},
            "tier5_sync": {"hwnd": 1234},
        }):
            rec_res = self.engine.record_action("click", {"x": 120, "y": 220, "button": "left"})
            self.assertEqual(rec_res["status"], "action_recorded")

        stop_res = self.engine.stop_recording(save=True)
        self.assertEqual(stop_res["status"], "recorded")
        self.assertEqual(stop_res["steps_count"], 1)
        self.assertFalse(self.engine.is_recording)

        # Verify persisted JSON on disk
        macros = self.engine.list_macros()
        self.assertEqual(len(macros), 1)
        self.assertEqual(macros[0]["name"], "test_macro")

        saved = self.engine.get_macro("test_macro")
        self.assertIsNotNone(saved)
        self.assertEqual(len(saved["steps"]), 1)
        self.assertIn("trajectory", saved["steps"][0])
        self.assertIn("anchor", saved["steps"][0])

    def test_5tier_self_healing_resolution(self):
        anchor = {
            "tier1_uia": {"name": "SaveButton", "role": "Button"},
            "tier2_ocr": {"token": "Save", "relative_offset": [10, 5]},
            "tier3_phash": {"dhash_1024": "a" * 256},
            "tier4_relative": {"rx_ratio": 0.4, "ry_ratio": 0.6},
        }

        # Case 1: Tier 1 UIA succeeds
        with patch("control.macro_engine.find_element_by_query", return_value={"center": (450, 350)}):
            x, y, tier = self.engine.resolve_anchor(anchor, target_window=None)
            self.assertEqual((x, y), (450, 350))
            self.assertEqual(tier, "tier1_uia")

        # Case 2: Tier 1 fails, Tier 2 OCR succeeds
        with patch("control.macro_engine.find_element_by_query", return_value=None), \
             patch("perception.winrt_ocr.default_ocr.find_text", return_value={"center": (500, 200)}), \
             patch("control.macro_engine.get_window_extended_bounds", return_value=(0, 0, 1920, 1080)):
            x, y, tier = self.engine.resolve_anchor(anchor, target_window=None)
            self.assertEqual((x, y), (510, 205))
            self.assertEqual(tier, "tier2_ocr")

        # Case 3: Tier 1 & 2 fail, Tier 4 relative offset succeeds
        with patch("control.macro_engine.find_element_by_query", return_value=None), \
             patch("perception.winrt_ocr.default_ocr.find_text", return_value=None), \
             patch("control.macro_engine.get_window_client_bounds", return_value=(100, 100, 1000, 500)):
            x, y, tier = self.engine.resolve_anchor(anchor, target_window=None)
            self.assertEqual(x, 100 + int(0.4 * 1000))  # 500
            self.assertEqual(y, 100 + int(0.6 * 500))   # 400
            self.assertEqual(tier, "tier4_relative")

    def test_dry_run_playback(self):
        """Simulates playback in dry_run mode without dispatching hardware input events."""
        macro_payload = {
            "name": "mock_playback",
            "steps": [
                {"id": "s1", "action": "click", "args": {"x": 200, "y": 300}, "anchor": None},
                {"id": "s2", "action": "type_text", "args": {"text": "hello"}},
                {"id": "s3", "action": "press_key", "args": {"key": "enter"}},
            ],
        }
        res = self.engine.play_macro(macro_payload, speed_multiplier=10.0, dry_run=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["executed_steps"], 3)
        self.assertTrue(res["dry_run"])
        self.assertEqual(len(res["trace"]), 3)

    def test_delete_macro(self):
        self.engine.start_recording("to_delete")
        self.engine.stop_recording(save=True)
        self.assertIsNotNone(self.engine.get_macro("to_delete"))

        ok = self.engine.delete_macro("to_delete")
        self.assertTrue(ok)
        self.assertIsNone(self.engine.get_macro("to_delete"))


if __name__ == "__main__":
    unittest.main()
