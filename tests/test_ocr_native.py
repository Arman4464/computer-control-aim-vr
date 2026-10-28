"""
Native Windows Runtime (WinRT) OCR Integration Test.
Validates end-to-end screen capture and hardware-accelerated text extraction.
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


if __name__ == "__main__":
    unittest.main()
