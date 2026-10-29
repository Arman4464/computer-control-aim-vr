"""
Unit tests for the Native Windows Toast Notification Manager (AIM-VR 3.0).
"""

import unittest
from unittest.mock import patch, MagicMock
from control.notifications import send_toast_notification


class TestNotifications(unittest.TestCase):

    def test_empty_params(self):
        res = send_toast_notification("", "")
        self.assertEqual(res["status"], "error")

    @patch("subprocess.run")
    def test_toast_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "SUCCESS\n"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = send_toast_notification("Test Title", "Test Message", sound=False)
        self.assertEqual(res["status"], "success")
        self.assertIn("Test Title", res["message"])
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
