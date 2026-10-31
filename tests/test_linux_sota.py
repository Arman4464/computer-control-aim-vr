"""
Comprehensive Automated Test Suite for Native Linux SOTA Subsystems:
1. AT-SPI2 Semantic Accessibility Tree Inspector (D-Bus / org.a11y.atspi)
2. Wayland Virtual Pointer Protocol Client (zwlr_virtual_pointer_v1)
3. PipeWire Hardware Screen Recording Portal (wl-screenrec / wf-recorder)

100% Mocked & Synthetic - Runs Headlessly on Any OS (Zero Side-Effects).
"""

import sys
import os
import struct
import signal
import subprocess
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from perception.atspi_inspector import ATSPIInspector, clean_atspi_role, default_atspi
from control.platform.hyprland.wayland_virtual_pointer import (
    WaylandVirtualPointerClient,
    _pack_string,
    _unpack_string,
)
from perception.screen_recorder import ScreenRecorder


class TestATSPIInspector(unittest.TestCase):
    """Verifies AT-SPI2 semantic accessibility tree parsing and querying."""

    def setUp(self):
        self.inspector = ATSPIInspector()

    def test_role_cleaning(self):
        self.assertEqual(clean_atspi_role("push button"), "Button")
        self.assertEqual(clean_atspi_role("push-button"), "Button")
        self.assertEqual(clean_atspi_role("entry"), "Edit")
        self.assertEqual(clean_atspi_role("text"), "Text")
        self.assertEqual(clean_atspi_role("check box"), "CheckBox")
        self.assertEqual(clean_atspi_role("radio button"), "Radio")
        self.assertEqual(clean_atspi_role("list item"), "ListItem")

    def test_mock_tree_inspection_and_find_element(self):
        mock_tree = {
            "elements": [
                {
                    "name": "SearchInput",
                    "role": "Edit",
                    "id": "/org/a11y/app/search",
                    "bbox": [50, 50, 300, 40],
                    "center": [200, 70],
                    "enabled": True,
                },
                {
                    "name": "SubmitBtn",
                    "role": "Button",
                    "id": "/org/a11y/app/submit",
                    "bbox": [360, 50, 100, 40],
                    "center": [410, 70],
                    "enabled": True,
                },
            ]
        }
        self.inspector.set_mock_tree(mock_tree)

        # Inspect tree
        tree_res = self.inspector.inspect_tree()
        self.assertEqual(tree_res["count"], 2)
        self.assertTrue(tree_res["has_rich_uia"])
        self.assertIn("SubmitBtn", tree_res["formatted_tree"])

        # Find element by query
        elem = self.inspector.find_element(query="Search")
        self.assertIsNotNone(elem)
        self.assertEqual(elem["name"], "SearchInput")
        self.assertEqual(elem["role"], "Edit")

        # Find element by role
        btn = self.inspector.find_element(query="Submit", role="Button")
        self.assertIsNotNone(btn)
        self.assertEqual(btn["center"], [410, 70])

        # Non-matching
        none_elem = self.inspector.find_element(query="NonExistent")
        self.assertIsNone(none_elem)


class TestWaylandVirtualPointerProtocol(unittest.TestCase):
    """Verifies zwlr_virtual_pointer_v1 binary wire protocol client."""

    def setUp(self):
        self.client = WaylandVirtualPointerClient()

    def test_pack_unpack_string(self):
        packed = _pack_string("wl_registry")
        self.assertEqual(len(packed) % 4, 0)
        self.assertTrue(packed.startswith(struct.pack("<I", 12)))

        unpacked, next_offset = _unpack_string(packed, 0)
        self.assertEqual(unpacked, "wl_registry")
        self.assertEqual(next_offset, len(packed))

    def test_message_framing_and_send(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock

        payload = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"
        self.client._send_message(1, 7, payload)

        mock_sock.sendall.assert_called_once()
        sent_data = mock_sock.sendall.call_args[0][0]

        obj_id, opcode_and_size = struct.unpack("<II", sent_data[:8])
        self.assertEqual(obj_id, 1)
        self.assertEqual(opcode_and_size & 0xFFFF, 7)
        self.assertEqual(opcode_and_size >> 16, 20)
        self.assertEqual(sent_data[8:], payload)

    def test_motion_absolute_dispatch(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        self.client.move_absolute(500, 300, 1920, 1080)

        self.assertEqual(mock_sock.sendall.call_count, 2)
        args_list = mock_sock.sendall.call_args_list

        motion_bytes = args_list[0][0][0]
        obj_id, opcode_and_size = struct.unpack("<II", motion_bytes[:8])
        self.assertEqual(obj_id, 42)
        self.assertEqual(opcode_and_size & 0xFFFF, 7)

        frame_bytes = args_list[1][0][0]
        frame_obj_id, frame_op = struct.unpack("<II", frame_bytes[:8])
        self.assertEqual(frame_obj_id, 42)
        self.assertEqual(frame_op & 0xFFFF, 3)

    def test_button_events_dispatch(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        self.client.button_down(0x110)
        down_bytes = mock_sock.sendall.call_args_list[0][0][0]
        _, op = struct.unpack("<II", down_bytes[:8])
        self.assertEqual(op & 0xFFFF, 1)

        self.client.button_up(0x110)
        self.assertEqual(mock_sock.sendall.call_count, 4)

    def test_axis_scroll_encoding(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        self.client.axis_scroll(2)
        scroll_bytes = mock_sock.sendall.call_args_list[0][0][0]
        _, op = struct.unpack("<II", scroll_bytes[:8])
        self.assertEqual(op & 0xFFFF, 2)


class TestPipeWireScreenRecorder(unittest.TestCase):
    """Verifies Linux Hardware Screen Recording Portal (wl-screenrec / wf-recorder)."""

    def setUp(self):
        self.recorder = ScreenRecorder()

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_start_hardware_recording_wl_screenrec(self, mock_popen, mock_which):
        def which_side_effect(cmd):
            if cmd == "wl-screenrec":
                return "/usr/bin/wl-screenrec"
            return None

        mock_which.side_effect = which_side_effect
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        res = self.recorder.start(fps=60, crop_region=(10, 20, 800, 600))
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["backend"], "hardware_wl-screenrec")
        self.assertEqual(res["fps"], 60)

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "wl-screenrec")
        self.assertIn("-f", cmd)
        self.assertIn("-g", cmd)
        self.assertIn("10,20 800x600", cmd)
        self.assertIn("--low-power=off", cmd)

        status = self.recorder.status()
        self.assertTrue(status["is_recording"])
        self.assertEqual(status["backend"], "hardware_wl-screenrec")

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    @patch("subprocess.Popen")
    @patch("shutil.move")
    @patch("os.path.exists", return_value=True)
    @patch("os.path.getsize", return_value=102400)
    def test_stop_hardware_recording_mp4(self, mock_getsize, mock_exists, mock_move, mock_popen, mock_which):
        mock_which.return_value = "/usr/bin/wl-screenrec"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        self.recorder.start(fps=30)
        res = self.recorder.stop(output_path="/tmp/recording.mp4", format="mp4")

        self.assertEqual(res["status"], "saved")
        self.assertEqual(res["backend"], "hardware_wl-screenrec")
        self.assertEqual(res["format"], "mp4")
        mock_proc.send_signal.assert_called_once()
        mock_move.assert_called_once()

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value=None)
    @patch("threading.Thread")
    def test_fallback_to_software_when_no_hardware_tools(self, mock_thread, mock_which):
        res = self.recorder.start(fps=15)
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["backend"], "software_pil")
        mock_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
