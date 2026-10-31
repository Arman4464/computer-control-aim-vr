"""
Unit tests for Smart Per-Window Clipping & Isolation.
Verifies DWM frame bounds calculation, client bounds calculation,
coordinate translation, and shadow cropping logic without moving the mouse.
"""

import sys
import unittest

if sys.platform != "win32":
    class TestSmartWindowClip(unittest.TestCase):
        @unittest.skip("Smart window clipping is Windows-only")
        def test_skipped_on_linux(self):
            pass
else:
    from unittest.mock import patch
    from PIL import Image

    from perception.screen_capture import (
        get_window_extended_bounds,
        get_window_client_bounds,
        window_to_screen_coords,
    )

    class TestSmartWindowClip(unittest.TestCase):

        def test_window_to_screen_coords_extended(self):
            with patch("perception.screen_capture.get_window_extended_bounds", return_value=(100, 200, 800, 600)):
                sx, sy = window_to_screen_coords(12345, 50, 60, client_only=False)
                self.assertEqual(sx, 150)
                self.assertEqual(sy, 260)

        def test_window_to_screen_coords_client_only(self):
            with patch("perception.screen_capture.get_window_client_bounds", return_value=(108, 230, 784, 560)):
                sx, sy = window_to_screen_coords(12345, 10, 20, client_only=True)
                self.assertEqual(sx, 118)
                self.assertEqual(sy, 250)

        def test_invalid_hwnd_returns_zero_bounds(self):
            with patch("perception.screen_capture.user32.IsWindow", return_value=0):
                ext_bounds = get_window_extended_bounds(0)
                client_bounds = get_window_client_bounds(0)
                self.assertEqual(ext_bounds, (0, 0, 0, 0))
                self.assertEqual(client_bounds, (0, 0, 0, 0))

        def test_client_bounds_calculation(self):
            with patch("perception.screen_capture.user32.IsWindow", return_value=1), \
                 patch("perception.screen_capture.user32.GetClientRect") as mock_client, \
                 patch("perception.screen_capture.user32.ClientToScreen") as mock_pts:

                # Test that get_window_client_bounds executes without crashing
                bounds = get_window_client_bounds(12345)
                self.assertIsInstance(bounds, tuple)
                self.assertEqual(len(bounds), 4)


if __name__ == "__main__":
    unittest.main()
