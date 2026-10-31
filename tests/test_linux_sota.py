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
from control.platform.hyprland.uinput_engine import UInputEngine


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

    def test_relative_motion_opcode_0_framing(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        self.client.motion(10, -5, time_ms=1000)

        self.assertEqual(mock_sock.sendall.call_count, 2)
        args_list = mock_sock.sendall.call_args_list

        motion_bytes = args_list[0][0][0]
        obj_id, opcode_and_size = struct.unpack("<II", motion_bytes[:8])
        self.assertEqual(obj_id, 42)
        self.assertEqual(opcode_and_size & 0xFFFF, 0)  # opcode 0 = motion

        t_ms, dx_fixed, dy_fixed = struct.unpack("<Iii", motion_bytes[8:])
        self.assertEqual(t_ms, 1000)
        self.assertEqual(dx_fixed, int(10 * 256.0))
        self.assertEqual(dy_fixed, int(-5 * 256.0))

        frame_bytes = args_list[1][0][0]
        frame_obj_id, frame_op = struct.unpack("<II", frame_bytes[:8])
        self.assertEqual(frame_obj_id, 42)
        self.assertEqual(frame_op & 0xFFFF, 3)  # opcode 3 = frame

        self.assertEqual(self.client.get_position(), (10, -5))

    def test_destroy_opcode_8_framing(self):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        self.client.destroy()

        mock_sock.sendall.assert_called_once()
        destroy_bytes = mock_sock.sendall.call_args[0][0]
        obj_id, opcode_and_size = struct.unpack("<II", destroy_bytes[:8])
        self.assertEqual(obj_id, 42)
        self.assertEqual(opcode_and_size & 0xFFFF, 8)  # opcode 8 = destroy
        self.assertEqual(len(destroy_bytes), 8)  # No payload

        self.assertFalse(self.client._connected)
        self.assertIsNone(self.client._sock)
        self.assertEqual(self.client._pointer_id, 0)

    @patch("control.platform.get_platform_driver")
    def test_dynamic_extents_scaling_1440p_and_4k(self, mock_get_driver):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        # 1. 1440p (2560x1440)
        mock_driver = MagicMock()
        mock_wm = MagicMock()
        mock_wm.get_virtual_desktop_bounds.return_value = (0, 0, 2560, 1440)
        mock_driver.window_manager = mock_wm
        mock_get_driver.return_value = mock_driver

        self.client.move_absolute(1280, 720)
        motion_bytes = mock_sock.sendall.call_args_list[0][0][0]
        t_ms, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes[8:])
        self.assertEqual((x, y), (1280, 720))
        self.assertEqual(x_extent, 2560)
        self.assertEqual(y_extent, 1440)

        # 2. 4K (3840x2160)
        mock_wm.get_virtual_desktop_bounds.return_value = (0, 0, 3840, 2160)
        self.client.move_absolute(1920, 1080)
        motion_bytes_4k = mock_sock.sendall.call_args_list[2][0][0]
        _, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes_4k[8:])
        self.assertEqual((x, y), (1920, 1080))
        self.assertEqual(x_extent, 3840)
        self.assertEqual(y_extent, 2160)

        # 3. Fallback to 1920x1080 when query raises
        mock_wm.get_virtual_desktop_bounds.side_effect = RuntimeError("WM offline")
        self.client.move_absolute(100, 100)
        motion_bytes_fallback = mock_sock.sendall.call_args_list[4][0][0]
        _, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes_fallback[8:])
        self.assertEqual(x_extent, 1920)
        self.assertEqual(y_extent, 1080)

    @patch("control.platform.get_platform_driver")
    def test_zero_bounds_fallback_and_negative_coordinate_clamping(self, mock_get_driver):
        mock_sock = MagicMock()
        self.client._sock = mock_sock
        self.client._connected = True
        self.client._pointer_id = 42

        # 1. Zero bounds (0, 0, 0, 0) should fallback to (1920, 1080)
        mock_driver = MagicMock()
        mock_wm = MagicMock()
        mock_wm.get_virtual_desktop_bounds.return_value = (0, 0, 0, 0)
        mock_driver.window_manager = mock_wm
        mock_get_driver.return_value = mock_driver

        self.client.move_absolute(500, 300)
        motion_bytes = mock_sock.sendall.call_args_list[0][0][0]
        t_ms, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes[8:])
        self.assertEqual((x, y), (500, 300))
        self.assertEqual(x_extent, 1920)
        self.assertEqual(y_extent, 1080)

        # 2. Explicit zero/negative extents should fallback to (1920, 1080)
        self.client.move_absolute(100, 200, x_extent=0, y_extent=-5)
        motion_bytes_zero_ext = mock_sock.sendall.call_args_list[2][0][0]
        _, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes_zero_ext[8:])
        self.assertEqual((x, y), (100, 200))
        self.assertEqual(x_extent, 1920)
        self.assertEqual(y_extent, 1080)

        # 3. Negative coordinates should be clamped to 0 to avoid struct.error with 'I' format
        self.client.move_absolute(-50, -100)
        motion_bytes_neg = mock_sock.sendall.call_args_list[4][0][0]
        _, x, y, x_extent, y_extent = struct.unpack("<IIIII", motion_bytes_neg[8:])
        self.assertEqual((x, y), (0, 0))
        self.assertEqual(x_extent, 1920)
        self.assertEqual(y_extent, 1080)



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
        self.assertIn("--max-fps", cmd)
        self.assertEqual(cmd[cmd.index("--max-fps") + 1], "60")
        self.assertIn("--low-power=off", cmd)

        status = self.recorder.status()
        self.assertTrue(status["is_recording"])
        self.assertEqual(status["backend"], "hardware_wl-screenrec")

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_start_hardware_recording_wf_recorder_60fps_no_cursor(self, mock_popen, mock_which):
        def which_side_effect(cmd):
            if cmd == "wf-recorder":
                return "/usr/bin/wf-recorder"
            return None

        mock_which.side_effect = which_side_effect
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch.dict(os.environ, {"AIMVR_RECORDER_ENCODER": ""}, clear=False):
            res = self.recorder.start(fps=60, include_cursor=False, crop_region=(0, 0, 1920, 1080))

        self.assertEqual(res["status"], "started")
        self.assertEqual(res["backend"], "hardware_wf-recorder")
        self.assertEqual(res["fps"], 60)

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "wf-recorder")
        self.assertIn("-f", cmd)
        self.assertIn("-g", cmd)
        self.assertIn("-r", cmd)
        self.assertEqual(cmd[cmd.index("-r") + 1], "60")

        # Verify hardware codec flags
        self.assertIn("-c", cmd)
        c_idx = cmd.index("-c")
        self.assertEqual(cmd[c_idx + 1], "h264_vaapi")
        self.assertIn("-d", cmd)
        d_idx = cmd.index("-d")
        self.assertEqual(cmd[d_idx + 1], "/dev/dri/renderD128")

        # Crucial: verify NO dangling -c flag
        self.assertNotEqual(cmd[-1], "-c")
        for i, token in enumerate(cmd):
            if token == "-c":
                self.assertLess(i + 1, len(cmd))
                self.assertFalse(cmd[i + 1].startswith("-"))

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_start_hardware_recording_wl_screenrec_nvenc(self, mock_popen, mock_which):
        def which_side_effect(cmd):
            if cmd == "wl-screenrec":
                return "/usr/bin/wl-screenrec"
            return None

        mock_which.side_effect = which_side_effect
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch.dict(os.environ, {"AIMVR_RECORDER_ENCODER": "h264_nvenc"}, clear=False):
            res = self.recorder.start(fps=60)

        self.assertEqual(res["status"], "started")
        self.assertEqual(res["backend"], "hardware_wl-screenrec")
        cmd = mock_popen.call_args[0][0]
        self.assertIn("--max-fps", cmd)
        self.assertEqual(cmd[cmd.index("--max-fps") + 1], "60")
        self.assertIn("--encoder", cmd)
        self.assertEqual(cmd[cmd.index("--encoder") + 1], "h264_nvenc")

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
    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_start_hardware_recording_120fps(self, mock_popen, mock_which):
        # 1. Test wl-screenrec with 120 FPS
        mock_which.side_effect = lambda cmd: "/usr/bin/wl-screenrec" if cmd == "wl-screenrec" else None
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        res_wl = self.recorder.start(fps=120)
        self.assertEqual(res_wl["status"], "started")
        self.assertEqual(res_wl["backend"], "hardware_wl-screenrec")
        self.assertEqual(res_wl["fps"], 120)

        cmd_wl = mock_popen.call_args[0][0]
        self.assertIn("--max-fps", cmd_wl)
        self.assertEqual(cmd_wl[cmd_wl.index("--max-fps") + 1], "120")

        # Stop recorder for next test
        self.recorder._hardware_proc = None
        self.recorder._recording = False

        # 2. Test wf-recorder with 120 FPS
        mock_which.side_effect = lambda cmd: "/usr/bin/wf-recorder" if cmd == "wf-recorder" else None
        mock_popen.reset_mock()

        with patch.dict(os.environ, {"AIMVR_RECORDER_ENCODER": ""}, clear=False):
            res_wf = self.recorder.start(fps=120)

        self.assertEqual(res_wf["status"], "started")
        self.assertEqual(res_wf["backend"], "hardware_wf-recorder")
        self.assertEqual(res_wf["fps"], 120)

        cmd_wf = mock_popen.call_args[0][0]
        self.assertIn("-r", cmd_wf)
        self.assertEqual(cmd_wf[cmd_wf.index("-r") + 1], "120")

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value=None)
    @patch("threading.Thread")
    def test_fallback_to_software_when_no_hardware_tools(self, mock_thread, mock_which):
        res = self.recorder.start(fps=15)
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["backend"], "software_pil")
        mock_thread.assert_called_once()


class TestUInputEngineM2(unittest.TestCase):
    """Verifies UInputEngine dynamic resolution extents and rootless keyboard fallbacks."""

    def setUp(self):
        self.engine = UInputEngine()

    def test_move_queries_dynamic_desktop_bounds(self):
        mock_wm = MagicMock()
        mock_wm.get_virtual_desktop_bounds.return_value = (0, 0, 2560, 1440)
        self.engine.wm = mock_wm

        mock_vp = MagicMock()
        mock_vp.is_available.return_value = True
        self.engine._virtual_pointer = mock_vp

        pos = self.engine.move(500, 300)
        self.assertEqual(pos, (500, 300))
        mock_vp.move_absolute.assert_called_once_with(500, 300, x_extent=2560, y_extent=1440)

    def test_zero_bounds_fallback_to_1920x1080(self):
        mock_wm = MagicMock()
        mock_wm.get_virtual_desktop_bounds.return_value = (0, 0, 0, 0)
        self.engine.wm = mock_wm

        bounds = self.engine._get_desktop_bounds()
        self.assertEqual(bounds, (1920, 1080))

        mock_vp = MagicMock()
        mock_vp.is_available.return_value = True
        self.engine._virtual_pointer = mock_vp

        pos = self.engine.move(100, 200)
        self.assertEqual(pos, (100, 200))
        mock_vp.move_absolute.assert_called_once_with(100, 200, x_extent=1920, y_extent=1080)


    @patch("shutil.which")
    @patch("subprocess.run")
    def test_rootless_keyboard_fallback_wtype(self, mock_run, mock_which):
        mock_which.side_effect = lambda tool: "/usr/bin/" + tool if tool == "wtype" else None
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        self.engine._uinput_device = None

        # key_down fallback to wtype -k <key>
        self.engine.key_down("enter")
        mock_run.assert_called_with(["wtype", "-k", "enter"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)

        # key_up fallback to wtype -k <key>
        self.engine.key_up("enter")
        mock_run.assert_called_with(["wtype", "-k", "enter"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)

        # write_text fallback to wtype "<text>"
        self.engine.write_text("Hello M2")
        mock_run.assert_called_with(["wtype", "-d", "10", "--", "Hello M2"], timeout=10.0, check=True)

    @patch("shutil.which", return_value=None)
    def test_rootless_keyboard_fallback_hyprland_ipc(self, mock_which):
        self.engine._uinput_device = None
        mock_ipc = MagicMock()
        self.engine.ipc = mock_ipc

        self.engine.key_down("a")
        mock_ipc.dispatch.assert_called_with("sendshortcut", ", a")

        self.engine.key_up("a")
        mock_ipc.dispatch.assert_called_with("sendshortcut", ", a")


class TestMilestoneM3LinuxSOTA(unittest.TestCase):
    """
    Milestone M3 Test Suite:
    - 5-Tier Semantic Anchor AT-SPI2 recording & self-healing on Linux
    - Hex window address handling in focus_anchor without ValueError
    - Speculative Action DAG text_exists condition routing to LinuxOCR
    - App launcher window readiness polling
    - Tier 5 barrier compositor responsiveness check
    """

    def setUp(self):
        from control.macro_engine import MacroEngine
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.engine = MacroEngine(macros_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("sys.platform", "linux")
    def test_macro_anchor_atspi_tier1_recording(self):
        """Verifies 5-tier anchor Tier 1 AT-SPI2 recording on Linux."""
        mock_driver = MagicMock()
        mock_driver.window_manager.get_active_window.return_value = {
            "hwnd": "0x560f4e3c9210",
            "address": "0x560f4e3c9210",
            "title": "Arch App",
            "bounds": [100, 100, 800, 600],
        }

        mock_elem = {
            "name": "SaveButton",
            "role": "Button",
            "bounding_box": [120, 200, 80, 30],
            "bbox": [120, 200, 80, 30],
            "id": "/org/a11y/save",
        }

        with patch("control.platform.get_platform_driver", return_value=mock_driver), \
             patch("perception.atspi_inspector.default_atspi.find_element_at_point", return_value=mock_elem), \
             patch("control.macro_engine.get_window_client_bounds", return_value=(100, 100, 800, 600)), \
             patch("control.macro_engine.get_window_extended_bounds", return_value=(100, 100, 800, 600)), \
             patch("control.macro_engine.capture_screen", return_value=Image.new("RGB", (32, 32))):

            anchor = self.engine.build_5tier_anchor(150, 215)
            self.assertIsNotNone(anchor.get("tier1_element"))
            self.assertEqual(anchor["tier1_element"]["name"], "SaveButton")
            self.assertEqual(anchor["tier1_element"]["role"], "Button")
            self.assertEqual(anchor["tier1_element"]["bounding_box"], [120, 200, 80, 30])
            self.assertEqual(anchor["tier5_sync"]["hwnd"], "0x560f4e3c9210")
            self.assertEqual(anchor["tier5_sync"]["window_title"], "Arch App")

    @patch("sys.platform", "linux")
    def test_hex_window_address_in_focus_anchor(self):
        """Verifies hex window addresses ('0x...') do not raise ValueError in focus_anchor."""
        from control.macro_engine import focus_anchor
        mock_driver = MagicMock()
        mock_driver.window_manager.focus_window.return_value = True

        with patch("control.platform.get_platform_driver", return_value=mock_driver):
            # Direct hex address string
            ok1 = focus_anchor("0x560f4e3c9210")
            self.assertTrue(ok1)
            mock_driver.window_manager.focus_window.assert_called_with("0x560f4e3c9210")

            # Dict with tier5_sync hex address
            anchor_dict = {
                "tier5_sync": {"hwnd": "0x560f4e3c9210", "window_title": "Arch Window"}
            }
            ok2 = focus_anchor(anchor_dict)
            self.assertTrue(ok2)

            # String integer handle
            ok3 = focus_anchor("123456")
            self.assertTrue(ok3)

            # Native integer handle
            ok4 = self.engine.focus_anchor(987654)
            self.assertTrue(ok4)

    def test_dag_text_exists_condition_linux_ocr(self):
        """Verifies DAG text_exists condition routes to default_linux_ocr on Linux."""
        from control.dag_executor import DAGExecutor
        executor = DAGExecutor()

        mock_ocr = MagicMock()
        mock_ocr.find_text.side_effect = lambda img, q: (
            {"text": "Ready", "center": [200, 300]} if q == "Ready" else None
        )

        with patch("control.dag_executor.IS_WINDOWS", False), \
             patch("control.platform.hyprland.linux_ocr.default_linux_ocr.find_text", mock_ocr.find_text), \
             patch("perception.screen_capture.capture_screen", return_value=Image.new("RGB", (100, 100))):

            # Condition satisfied
            cond_true = {"type": "text_exists", "query": "Ready"}
            sat_true, reason_true = executor.evaluate_condition(cond_true, {})
            self.assertTrue(sat_true)
            self.assertIn("text_exists('Ready') -> True", reason_true)

            # Condition not satisfied
            cond_false = {"type": "text_exists", "query": "NotPresent"}
            sat_false, reason_false = executor.evaluate_condition(cond_false, {})
            self.assertFalse(sat_false)
            self.assertIn("text_exists('NotPresent') -> False", reason_false)

    def test_linux_app_launcher_readiness_polling(self):
        """Verifies LinuxAppLauncher readiness polling discovers window or times out."""
        from control.platform.hyprland.linux_app_launcher import LinuxAppLauncher
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = "ok"

        mock_wm = MagicMock()
        # Window appears on 2nd query
        mock_wm.list_windows.side_effect = [
            [],
            [{"title": "Terminal - Kitty", "class": "kitty", "address": "0x560f11", "bounds": [0, 0, 800, 600]}],
        ]
        mock_wm.get_active_window.return_value = None
        mock_wm.focus_window.return_value = True

        launcher = LinuxAppLauncher(ipc=mock_ipc, window_manager=mock_wm)

        with patch.object(launcher, "resolve_binary", return_value="/usr/bin/kitty"):
            res = launcher.launch_app("kitty", timeout=1.0)

        self.assertEqual(res["status"], "launched")
        self.assertEqual(res["method"], "hyprland_exec")
        self.assertIn("window", res)
        self.assertEqual(res["window"]["title"], "Terminal - Kitty")
        self.assertEqual(res["window"]["hwnd"], "0x560f11")
        mock_wm.focus_window.assert_called_with("0x560f11")

    def test_linux_app_launcher_readiness_timeout(self):
        """Verifies LinuxAppLauncher handles window not appearing within timeout gracefully."""
        from control.platform.hyprland.linux_app_launcher import LinuxAppLauncher
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = "ok"

        mock_wm = MagicMock()
        mock_wm.list_windows.return_value = []
        mock_wm.get_active_window.return_value = None

        launcher = LinuxAppLauncher(ipc=mock_ipc, window_manager=mock_wm)
        with patch.object(launcher, "resolve_binary", return_value="/usr/bin/daemon"):
            res = launcher.launch_app("daemon", timeout=0.2)

        self.assertEqual(res["status"], "launched")
        self.assertIn("note", res)
        self.assertNotIn("window", res)

    @patch("sys.platform", "linux")
    def test_verify_tier5_barrier_linux_responsiveness(self):
        """Verifies verify_tier5_barrier pings compositor IPC responsiveness on Linux."""
        from control.macro_engine import verify_tier5_barrier, wait_for_message_pump

        mock_driver = MagicMock()
        mock_driver.ipc.query_json.return_value = {"address": "0x560f4e3c9210", "title": "Active"}

        with patch("control.platform.get_platform_driver", return_value=mock_driver):
            # Responsive compositor returns True
            ok = verify_tier5_barrier("0x560f4e3c9210", timeout_ms=100)
            self.assertTrue(ok)
            mock_driver.ipc.query_json.assert_called_with("activewindow")

            # Backward-compatible wait_for_message_pump returns True
            ok_pump = wait_for_message_pump("0x560f4e3c9210", timeout_ms=100)
            self.assertTrue(ok_pump)

        # Unresponsive or failed compositor IPC returns False
        mock_driver_err = MagicMock()
        mock_driver_err.ipc.query_json.side_effect = TimeoutError("Hyprland socket timeout")

        with patch("control.platform.get_platform_driver", return_value=mock_driver_err):
            ok_err = verify_tier5_barrier("0x560f4e3c9210", timeout_ms=100)
            self.assertFalse(ok_err)


class TestPackagingAndSystemIntegrationM4(unittest.TestCase):
    """
    Milestone M4 Test Suite:
    - PKGBUILD Arch Linux standards compliance ($srcdir, $pkgdir, check(), MIT license, optdepends)
    - assets/aimvr-uinput.conf systemd modules-load configuration
    - pyproject.toml PEP 508 environment markers and metadata
    - requirements.txt PEP 508 cross-platform modernization
    """

    def setUp(self):
        self.pkgbuild_path = os.path.join(PROJECT_ROOT, "PKGBUILD")
        self.uinput_conf_path = os.path.join(PROJECT_ROOT, "assets", "aimvr-uinput.conf")
        self.uinput_rules_path = os.path.join(PROJECT_ROOT, "assets", "99-aimvr-uinput.rules")
        self.pyproject_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        self.requirements_path = os.path.join(PROJECT_ROOT, "requirements.txt")
        self.license_path = os.path.join(PROJECT_ROOT, "LICENSE")

    def test_pkgbuild_arch_standards_and_hygiene(self):
        """Verifies PKGBUILD follows Arch packaging standards without $startdir."""
        self.assertTrue(os.path.exists(self.pkgbuild_path), "PKGBUILD must exist in project root")
        with open(self.pkgbuild_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Non-standard $startdir must not appear anywhere
        self.assertNotIn("$startdir", content, "PKGBUILD must eliminate all references to $startdir")

        # 2. $srcdir must be used in build(), check(), and package()
        self.assertIn('cd "$srcdir"', content, 'PKGBUILD must execute cd "$srcdir"')

        # 3. $pkgdir must be used in package()
        self.assertIn('"$pkgdir"', content, "PKGBUILD must install into $pkgdir")

        # 4. Standard package metadata
        self.assertIn("pkgname=python-computercontrol-aim-vr", content)
        self.assertIn("pkgver=3.0.0", content)
        self.assertIn("pkgrel=1", content)
        self.assertIn("license=('MIT')", content)

        # 5. check() function executing test suite
        self.assertIn("check() {", content, "PKGBUILD must define check() function")
        self.assertIn("test_linux_sota.py", content, "PKGBUILD check() must execute test_linux_sota.py")
        self.assertIn("test_platform.py", content, "PKGBUILD check() must execute test_platform.py")

        # 6. MIT license installation
        self.assertIn(
            'install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"',
            content,
            "PKGBUILD must install MIT license to /usr/share/licenses/$pkgname/LICENSE",
        )

        # 7. System integration file installations
        self.assertIn(
            'install -Dm644 assets/aimvr-uinput.conf "$pkgdir/usr/lib/modules-load.d/aimvr-uinput.conf"',
            content,
            "PKGBUILD must install aimvr-uinput.conf to /usr/lib/modules-load.d/",
        )
        self.assertIn(
            'install -Dm644 assets/99-aimvr-uinput.rules "$pkgdir/usr/lib/udev/rules.d/99-aimvr-uinput.rules"',
            content,
            "PKGBUILD must install 99-aimvr-uinput.rules to /usr/lib/udev/rules.d/",
        )

        # 8. Required optdepends
        expected_optdepends = [
            "tesseract-data-eng: In-memory Tesseract TSV OCR",
            "pipewire: PipeWire multimedia server for DMA-BUF capture",
            "wireplumber: Session manager for PipeWire",
            "wf-recorder: Hardware-accelerated 60 FPS screen recorder",
            "wl-screenrec: High-performance NVENC/DMA-BUF screen recorder",
            "wtype: Rootless virtual keyboard fallback",
            "wl-clipboard: Wayland clipboard provider",
        ]
        for opt in expected_optdepends:
            self.assertIn(opt, content, f"PKGBUILD optdepends missing expected entry: {opt}")

    def test_aimvr_uinput_conf_modules_load(self):
        """Verifies systemd modules-load configuration file for uinput."""
        self.assertTrue(os.path.exists(self.uinput_conf_path), "assets/aimvr-uinput.conf must exist")
        with open(self.uinput_conf_path, "r", encoding="utf-8") as f:
            content = f.read()

        active_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertIn("uinput", active_lines, "aimvr-uinput.conf must declare uinput kernel module")

        # Also verify companion udev rules
        self.assertTrue(os.path.exists(self.uinput_rules_path), "assets/99-aimvr-uinput.rules must exist")
        with open(self.uinput_rules_path, "r", encoding="utf-8") as f:
            rule_content = f.read()
        self.assertIn('KERNEL=="uinput"', rule_content)
        self.assertIn('GROUP="input"', rule_content)

    def test_pyproject_toml_pep508_and_metadata(self):
        """Verifies pyproject.toml PEP 508 environment markers and packaging metadata."""
        self.assertTrue(os.path.exists(self.pyproject_path), "pyproject.toml must exist")
        with open(self.pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check PEP 508 marker for evdev
        self.assertIn(
            "evdev>=1.6.0; sys_platform == 'linux'",
            content,
            "pyproject.toml dependencies must specify PEP 508 marker for evdev on Linux",
        )

        # Ensure no unconditional evdev dependency
        lines = [l.strip().strip('",') for l in content.splitlines()]
        self.assertNotIn("evdev>=1.6.0", lines, "evdev must not be specified unconditionally")

        try:
            import tomllib
            data = tomllib.loads(content)
            proj = data.get("project", {})
            self.assertEqual(proj.get("name"), "computercontrol-aim-vr")
            self.assertEqual(proj.get("version"), "3.0.0")
            self.assertEqual(proj.get("license", {}).get("text"), "MIT")
            self.assertIn("Pillow>=9.0.0", proj.get("dependencies", []))
            self.assertIn("evdev>=1.6.0; sys_platform == 'linux'", proj.get("dependencies", []))
            self.assertIn("test", proj.get("optional-dependencies", {}))
        except ImportError:
            # Fallback for Python < 3.11
            self.assertIn('name = "computercontrol-aim-vr"', content)
            self.assertIn('version = "3.0.0"', content)
            self.assertIn('license = { text = "MIT" }', content)

    def test_requirements_txt_pep508_modernization(self):
        """Verifies requirements.txt uses PEP 508 environment markers and eliminates uiautomation."""
        self.assertTrue(os.path.exists(self.requirements_path), "requirements.txt must exist")
        with open(self.requirements_path, "r", encoding="utf-8") as f:
            content = f.read()

        active_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        # Verify unconditional uiautomation is eliminated
        for line in active_lines:
            self.assertFalse(
                line.startswith("uiautomation"),
                f"requirements.txt must not contain unconditional uiautomation: {line}",
            )

        # Verify evdev has PEP 508 marker
        self.assertIn(
            "evdev>=1.6.0; sys_platform == 'linux'",
            content,
            "requirements.txt must specify PEP 508 environment marker for evdev",
        )

        # Verify Pillow is present
        self.assertTrue(
            any("Pillow" in line for line in active_lines),
            "requirements.txt must declare Pillow",
        )


if __name__ == "__main__":
    unittest.main()
