"""
Unit tests for Set-of-Mark (SoM) Grounding Engine.
Tests IoU computation, candidate deduplication, text fusion,
visual badge rendering, and catalog coordinate resolution using synthetic data.
"""

import unittest
from PIL import Image

from perception.som_engine import (
    SoMEngine,
    _calculate_iou,
    _calculate_containment,
)


class TestSoMEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SoMEngine()

    def test_iou_calculation(self):
        # Identical boxes -> IoU = 1.0
        self.assertAlmostEqual(_calculate_iou([10, 10, 100, 100], [10, 10, 100, 100]), 1.0)
        # Disjoint boxes -> IoU = 0.0
        self.assertEqual(_calculate_iou([0, 0, 10, 10], [50, 50, 10, 10]), 0.0)
        # Half overlap
        # box1: [0, 0, 20, 10] (area 200)
        # box2: [10, 0, 20, 10] (area 200)
        # intersection: [10, 0, 10, 10] (area 100)
        # union: 200 + 200 - 100 = 300
        # IoU = 100 / 300 = 0.3333
        self.assertAlmostEqual(_calculate_iou([0, 0, 20, 10], [10, 0, 20, 10]), 100 / 300, places=3)

    def test_containment_calculation(self):
        inner = [20, 20, 40, 20]  # area 800
        outer = [10, 10, 100, 100]  # area 10000
        # inner completely inside outer
        self.assertAlmostEqual(_calculate_containment(inner, outer), 1.0)
        # disjoint
        self.assertEqual(_calculate_containment([0, 0, 10, 10], [100, 100, 10, 10]), 0.0)

    def test_deduplicate_and_fuse_text(self):
        # A button with no text + an OCR text box inside the button
        candidates = [
            {"bbox": [100, 100, 120, 40], "type": "button", "text": "", "source": "uia"},
            {"bbox": [110, 110, 80, 20], "type": "text", "text": "Submit", "source": "ocr"},
        ]
        fused = self.engine.deduplicate_and_fuse(candidates)
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["text"], "Submit")
        self.assertEqual(fused[0]["type"], "button")

    def test_render_som_annotations_and_resolve(self):
        img = Image.new("RGB", (640, 480), color=(240, 240, 240))
        elements = [
            {"bbox": [50, 50, 100, 40], "type": "button", "text": "Save", "source": "uia"},
            {"bbox": [200, 50, 120, 40], "type": "button", "text": "Cancel", "source": "uia"},
            {"bbox": [50, 120, 300, 30], "type": "input", "text": "Search...", "source": "uia"},
        ]

        annotated_img, catalog = self.engine.render_som_annotations(img, elements, origin_x=0, origin_y=0)

        # 3 elements -> 3 catalog entries
        self.assertEqual(len(catalog), 3)
        self.assertEqual(catalog[1]["text"], "Save")
        self.assertEqual(catalog[2]["text"], "Cancel")
        self.assertEqual(catalog[3]["text"], "Search...")

        # Test center coordinates
        # Element 1: [50, 50, 100, 40] -> center = (50 + 50, 50 + 20) = (100, 70)
        self.assertEqual(catalog[1]["center"], [100, 70])

        # Test resolve_mark
        coords = self.engine.resolve_mark(1)
        self.assertEqual(coords, (100, 70))

        # Test non-existent mark
        self.assertIsNone(self.engine.resolve_mark(999))

        # Test clear
        self.engine.clear_catalog()
        self.assertEqual(len(self.engine.get_catalog()), 0)


if __name__ == "__main__":
    unittest.main()
