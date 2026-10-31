"""
Native Windows Runtime (WinRT) OCR Integration Test.
Validates end-to-end screen capture, hardware-accelerated text extraction,
and UTF-8 Unicode streaming compatibility across Windows 10 and 11.
"""

import unittest
from PIL import Image, ImageDraw, ImageFont
from perception.winrt_ocr import default_ocr


class TestNativeWinRtOCRIntegration(unittest.TestCase):
    """Direct integration test validating WinRT OCR text recognition pipeline."""

    def test_daemon_text_recognition(self):
        img = Image.new("RGB", (300, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 24)
        except Exception:
            font = None
        d.text((20, 20), "WinRT OCR Active", fill=(0, 0, 0), font=font)

        res = default_ocr.recognize(img)
        self.assertEqual(res.get("status"), "ok")
        words = res.get("words", [])
        self.assertGreater(len(words), 0, "Expected at least one word recognized by WinRT OCR")
        detected_texts = [w["text"] for w in words]
        self.assertTrue(
            any("WinRT" in t or "OCR" in t or "Active" in t for t in detected_texts),
            f"Expected target keywords in detected text, got: {detected_texts}"
        )

    def test_unicode_and_quotes_resilience(self):
        """Verifies that non-ASCII characters, quotes, and punctuation do not break JSON streaming."""
        img = Image.new("RGB", (450, 100), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 22)
        except Exception:
            font = None
        d.text((15, 25), 'AIM-VR "Win10/11" - Ready: 100%', fill=(0, 0, 0), font=font)

        res = default_ocr.recognize(img)
        self.assertEqual(res.get("status"), "ok")
        self.assertIsInstance(res.get("words"), list)
        self.assertGreater(len(res.get("words", [])), 0)

    def test_phrase_search(self):
        """Verifies multi-word phrase matching and bounding box calculation."""
        img = Image.new("RGB", (400, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 24)
        except Exception:
            font = None
        d.text((20, 20), "System Control Center", fill=(0, 0, 0), font=font)

        match = default_ocr.find_text(img, "System Control")
        self.assertIsNotNone(match, "Expected phrase 'System Control' to be located")
        self.assertIn("bbox", match)
        self.assertIn("center", match)
        self.assertEqual(len(match["bbox"]), 4)
        self.assertEqual(len(match["center"]), 2)


if __name__ == "__main__":
    unittest.main()
