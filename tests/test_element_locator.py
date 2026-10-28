"""
Unit tests for the Unified Element Locator Engine (AIM-VR 3.0).
"""

import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
import sys, os

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from perception.element_locator import ElementLocator


class TestElementLocator(unittest.TestCase):

    def setUp(self):
        self.mock_ocr = MagicMock()
        self.locator = ElementLocator(ocr_engine=self.mock_ocr)

    def test_empty_query(self):
        res = self.locator.locate("")
        self.assertIsNone(res)

    @patch("perception.element_locator.find_element_by_query")
    def test_uia_priority(self, mock_uia):
        # When UIA finds the element, it should return UIA result without OCR
        mock_uia.return_value = {
            "name": "Save",
            "role": "Button",
            "bbox": [100, 200, 80, 30],
            "center": (140, 215),
        }

        res = self.locator.locate("Save")
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "uia")
        self.assertEqual(res["center"], (140, 215))
        self.assertEqual(res["confidence"], 1.0)
        self.mock_ocr.find_text.assert_not_called()

    @patch("perception.element_locator.find_element_by_query")
    @patch("perception.element_locator.capture_screen")
    def test_ocr_fallback(self, mock_capture, mock_uia):
        # When UIA returns None (e.g. web/GPU apps), falls back to OCR
        mock_uia.return_value = None
        fake_img = Image.new("RGB", (800, 600), (255, 255, 255))
        mock_capture.return_value = fake_img

        self.mock_ocr.find_text.return_value = {
            "text": "Post",
            "bbox": [500, 400, 60, 25],
            "center": [530, 412],
            "confidence": 0.95,
        }

        res = self.locator.locate("Post")
        self.assertIsNotNone(res)
        self.assertEqual(res["source"], "ocr")
        self.assertEqual(res["name"], "Post")
        self.assertEqual(res["center"], (530, 412))
        self.assertEqual(res["bbox"], [500, 400, 60, 25])
        self.mock_ocr.find_text.assert_called_once()

    @patch("perception.element_locator.capture_screen")
    def test_locate_all(self, mock_capture):
        fake_img = Image.new("RGB", (800, 600), (255, 255, 255))
        mock_capture.return_value = fake_img

        self.mock_ocr.recognize.return_value = {
            "words": [
                {"text": "Post", "x": 100, "y": 150, "w": 40, "h": 20},
                {"text": "Posted", "x": 200, "y": 150, "w": 50, "h": 20},
                {"text": "Other", "x": 300, "y": 150, "w": 40, "h": 20},
            ]
        }

        matches = self.locator.locate_all("post")
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["name"], "Post")
        self.assertEqual(matches[1]["name"], "Posted")


if __name__ == "__main__":
    unittest.main()
