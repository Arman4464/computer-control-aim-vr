"""
Unit tests for the Local UI Condition Waiter (AIM-VR 3.0 Control Subsystem).
"""

import unittest
from unittest.mock import patch
from control.wait_for import wait_for_condition


class TestWaitFor(unittest.TestCase):

    def test_unknown_condition(self):
        res = wait_for_condition("nonexistent_cond")
        self.assertEqual(res["status"], "error")
        self.assertIn("Unknown condition", res["message"])

    def test_missing_params(self):
        res1 = wait_for_condition("window_exists", target=None)
        self.assertEqual(res1["status"], "error")

        res2 = wait_for_condition("text_exists", query=None)
        self.assertEqual(res2["status"], "error")

    @patch("control.wait_for.find_window")
    def test_window_exists_satisfied(self, mock_find):
        mock_find.return_value = {"hwnd": 1234, "title": "Notepad"}
        res = wait_for_condition("window_exists", target="Notepad", timeout=1.0)
        self.assertEqual(res["status"], "satisfied")
        self.assertEqual(res["window"]["title"], "Notepad")


if __name__ == "__main__":
    unittest.main()
