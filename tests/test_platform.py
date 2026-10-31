"""
Comprehensive Headless Automated Test Suite for Cross-Platform Driver & Hyprland Subsystems.
100% Mocked & Synthetic - 0 Physical Hardware Side-Effects.

Strictly verifies:
  1. Platform Detection & Factory abstraction (WindowsPlatformDriver vs HyprlandPlatformDriver)
  2. Hyprland UNIX domain socket IPC (JSON queries, dispatchers, and hyprctl fallback)
  3. UInput virtual input engine (scancode mapping, evdev / wtype / ydotool dispatching)
  4. Zero-disk-write Grim screencopy & PPM pipe parser
  5. Hyprland window & workspace manager (geometry normalization, floating pixel snapping)
  6. Linux Wayland clipboard (wl-copy / wl-paste)
  7. Linux FreeDesktop notifier (notify-send)
  8. Linux application launcher (hyprctl dispatch exec & xdg-open)
  9. Linux streaming OCR (Tesseract TSV zero-disk-write parsing)
"""

import sys
import os
import io
import json
import socket
import subprocess
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

# Ensure package root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from control.platform.base import (
    BasePlatformDriver,
    BaseInputEngine,
    BaseWindowManager,
    BaseScreenCapture,
    BaseClipboard,
    BaseNotifier,
    BaseAppLauncher,
    BaseSafety,
)
from control.platform import get_platform_driver, set_platform_driver
from control.platform.hyprland.driver import HyprlandPlatformDriver
from control.platform.windows.driver import WindowsPlatformDriver
from control.platform.hyprland.hyprland_ipc import HyprlandIPC, HyprlandIPCClient
from control.platform.hyprland.uinput_engine import UInputEngine, KEY_MAP_NAME_TO_CODE
from control.platform.hyprland.hyprland_window_manager import HyprlandWindowManager
from control.platform.hyprland.hyprland_capture import HyprlandScreenCapture
from control.platform.hyprland.linux_clipboard import LinuxClipboard
from control.platform.hyprland.linux_notifications import LinuxNotifier
from control.platform.hyprland.linux_app_launcher import LinuxAppLauncher
from control.platform.hyprland.linux_ocr import LinuxOCR


class TestPlatformFactory(unittest.TestCase):
    """Verifies platform factory instantiation and custom driver overrides."""

    def test_current_platform_driver_instantiation(self):
        driver = get_platform_driver()
        self.assertIsInstance(driver, BasePlatformDriver)
        if sys.platform == "win32":
            self.assertIsInstance(driver, WindowsPlatformDriver)
            self.assertEqual(driver.get_platform_name(), "windows")

    def test_set_platform_driver_override(self):
        original = get_platform_driver()
        mock_driver = MagicMock(spec=BasePlatformDriver)
        mock_driver.get_platform_name.return_value = "mock_hyprland"

        set_platform_driver(mock_driver)
        self.assertEqual(get_platform_driver().get_platform_name(), "mock_hyprland")

        # Restore original
        set_platform_driver(original)
        self.assertEqual(get_platform_driver(), original)


class TestHyprlandIPC(unittest.TestCase):
    """Verifies UNIX domain socket IPC querying, fallback, and dispatch."""

    def setUp(self):
        self.ipc = HyprlandIPCClient(signature="fake_instance_signature")

    @patch("os.path.exists", return_value=True)
    @patch("socket.socket")
    def test_socket_query_success(self, mock_socket_cls, mock_exists):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.__enter__.return_value = mock_sock

        fake_clients = [
            {
                "address": "0x12345678",
                "title": "Alacritty - Terminal",
                "initialClass": "Alacritty",
                "at": [100, 200],
                "size": [800, 600],
                "workspace": {"id": 1, "name": "1"},
                "floating": False,
                "pid": 4242,
            }
        ]
        mock_sock.recv.side_effect = [json.dumps(fake_clients).encode("utf-8"), b""]

        with patch.object(socket, "AF_UNIX", 1, create=True):
            clients = self.ipc.get_clients()
            self.assertEqual(len(clients), 1)
            self.assertEqual(clients[0]["title"], "Alacritty - Terminal")
            self.assertEqual(clients[0]["pid"], 4242)
            mock_sock.sendall.assert_called_with(b"j/clients")

    @patch("subprocess.run")
    def test_socket_fallback_to_hyprctl(self, mock_run):
        # When socket is not available, falls back to hyprctl -j subcmd
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps([{"id": 1, "name": "eDP-1", "width": 1920, "height": 1080}])
        mock_run.return_value = mock_proc

        monitors = self.ipc.get_monitors()
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0]["name"], "eDP-1")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["hyprctl", "-j", "monitors"])

    @patch("os.path.exists", return_value=True)
    @patch("socket.socket")
    def test_dispatch_command(self, mock_socket_cls, mock_exists):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.recv.side_effect = [b"ok\n", b""]

        with patch.object(socket, "AF_UNIX", 1, create=True):
            res = self.ipc.dispatch("workspace 2")
            self.assertIn("ok", res)
            mock_sock.sendall.assert_called_with(b"dispatch workspace 2")


class TestUInputEngine(unittest.TestCase):
    """Verifies virtual Linux input engine, scancodes, and fallbacks."""

    def setUp(self):
        self.engine = UInputEngine()

    def test_scancode_mappings(self):
        self.assertEqual(KEY_MAP_NAME_TO_CODE["enter"], 28)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["escape"], 1)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["backspace"], 14)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["tab"], 15)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["space"], 57)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["a"], 30)
        self.assertEqual(KEY_MAP_NAME_TO_CODE["z"], 44)

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_wtype_fallback_for_type_text(self, mock_run, mock_which):
        mock_which.side_effect = lambda tool: "/usr/bin/" + tool if tool == "wtype" else None
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        self.engine._uinput_device = None

        self.engine.type_text("Hello Wayland")
        mock_run.assert_called()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "wtype")
        self.assertEqual(cmd[-1], "Hello Wayland")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_mouse_click_fallback(self, mock_run, mock_which):
        mock_which.side_effect = lambda tool: "/usr/bin/" + tool if tool == "ydotool" else None
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        self.engine._uinput_device = None
        self.engine.ipc = MagicMock()
        self.engine.ipc.query_json.return_value = {"x": 500, "y": 300}

        cx, cy = self.engine.click(500, 300, button="left", clicks=1)
        self.assertEqual(cx, 500)
        self.assertEqual(cy, 300)


class TestHyprlandCapture(unittest.TestCase):
    """Verifies zero-disk-write Grim pipe capture and PPM decoding."""

    def setUp(self):
        self.mock_wm = MagicMock()
        self.mock_wm.get_virtual_screen_bounds.return_value = (0, 0, 1920, 1080)
        self.capture = HyprlandScreenCapture(wm=self.mock_wm)

    def test_decode_ppm_stream(self):
        # Create a small 2x2 RGB image and convert to PPM bytes
        raw_img = Image.new("RGB", (2, 2), color=(255, 0, 0))
        buf = io.BytesIO()
        raw_img.save(buf, format="PPM")
        ppm_bytes = buf.getvalue()

        decoded = self.capture._decode_ppm(ppm_bytes)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.size, (2, 2))
        self.assertEqual(decoded.getpixel((0, 0)), (255, 0, 0))

    @patch("subprocess.Popen")
    def test_capture_desktop_stream(self, mock_popen):
        # Generate mock PPM output
        raw_img = Image.new("RGB", (10, 10), color=(0, 255, 0))
        buf = io.BytesIO()
        raw_img.save(buf, format="PPM")
        ppm_bytes = buf.getvalue()

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (ppm_bytes, b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        img, bounds = self.capture.capture_screen()
        self.assertIsNotNone(img)
        self.assertEqual(img.size, (10, 10))
        self.assertEqual(img.getpixel((0, 0)), (0, 255, 0))


class TestHyprlandWindowManager(unittest.TestCase):
    """Verifies window and workspace geometry handling on Hyprland."""

    def setUp(self):
        self.mock_ipc = MagicMock()
        self.wm = HyprlandWindowManager(ipc=self.mock_ipc)

    def test_list_windows_normalization(self):
        self.mock_ipc.get_clients.return_value = [
            {
                "address": "0x55aa66bb",
                "title": "Firefox Web Browser",
                "initialClass": "firefox",
                "at": [50, 100],
                "size": [1200, 800],
                "workspace": {"id": 2, "name": "web"},
                "floating": True,
                "pid": 1122,
            }
        ]

        wins = self.wm.list_windows()
        self.assertEqual(len(wins), 1)
        win = wins[0]
        self.assertEqual(win["hwnd"], "0x55aa66bb")
        self.assertEqual(win["title"], "Firefox Web Browser")
        self.assertEqual(win["bounds"], [50, 100, 1200, 800])
        self.assertEqual(win["pid"], 1122)
        self.assertTrue(win["is_floating"])

    def test_snap_window_left(self):
        self.mock_ipc.get_monitors.return_value = [
            {"id": 0, "name": "eDP-1", "x": 0, "y": 0, "width": 1920, "height": 1080}
        ]
        self.mock_ipc.get_clients.return_value = [
            {
                "address": "0x1111",
                "title": "Code",
                "initialClass": "code",
                "at": [100, 100],
                "size": [800, 600],
                "workspace": {"id": 1, "name": "1"},
                "floating": False,
                "pid": 999,
            }
        ]

        res = self.wm.snap("Code", "left")
        self.assertEqual(res["status"], "snapped")
        self.assertEqual(res["position"], "left")
        self.assertEqual(res["bounds"], [0, 0, 960, 1080])

        # Verify togglefloating, resizewindowpixel, and movewindowpixel were dispatched
        dispatch_calls = [c[0][0] for c in self.mock_ipc.dispatch.call_args_list]
        self.assertTrue(any("togglefloating" in cmd for cmd in dispatch_calls))
        self.assertTrue(any("resizewindowpixel" in cmd for cmd in dispatch_calls))
        self.assertTrue(any("movewindowpixel" in cmd for cmd in dispatch_calls))


class TestLinuxSubsystems(unittest.TestCase):
    """Verifies Wayland Clipboard, FreeDesktop Notifier, and App Launcher."""

    @patch("shutil.which")
    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_clipboard_set_and_get(self, mock_run, mock_popen, mock_which):
        mock_which.side_effect = lambda tool: f"/usr/bin/{tool}"
        clip = LinuxClipboard()

        # Test set_text via wl-copy
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        ok = clip.set_text("Hello Wayland Clipboard")
        self.assertTrue(ok)
        mock_popen.assert_called_with(["wl-copy"], stdin=-1)

        # Test get_text via wl-paste
        mock_run_proc = MagicMock()
        mock_run_proc.returncode = 0
        mock_run_proc.stdout = "Hello Wayland Clipboard"
        mock_run.return_value = mock_run_proc

        text = clip.get_text()
        self.assertEqual(text, "Hello Wayland Clipboard")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_notification_dispatch(self, mock_run, mock_which):
        mock_which.side_effect = lambda tool: f"/usr/bin/{tool}"
        notifier = LinuxNotifier()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        res = notifier.send_notification("Hyprland Alert", "Task complete successfully")
        self.assertEqual(res["status"], "success")
        mock_run.assert_called()
        cmd = mock_run.call_args[0][0]
        self.assertIn("notify-send", cmd)
        self.assertIn("Hyprland Alert", cmd)
        self.assertIn("Task complete successfully", cmd)

    @patch("subprocess.Popen")
    def test_app_launcher(self, mock_popen):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = "ok"
        launcher = LinuxAppLauncher(ipc=mock_ipc)

        # 1. Launch command via hyprctl dispatch exec
        res = launcher.launch("alacritty")
        self.assertEqual(res["status"], "launched")
        mock_ipc.dispatch.assert_called_with("exec", "alacritty")

        # 2. Open URL / file via xdg-open
        mock_proc = MagicMock()
        mock_proc.pid = 777
        mock_popen.return_value = mock_proc

        with patch("shutil.which", return_value="/usr/bin/xdg-open"):
            res_open = launcher.open_file_or_url("https://archlinux.org")
            self.assertEqual(res_open["status"], "opened")
            mock_popen.assert_called_with(
                ["xdg-open", "https://archlinux.org"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )


class TestLinuxOCR(unittest.TestCase):
    """Verifies streaming Tesseract TSV parsing into words and bounding boxes."""

    @patch("shutil.which", return_value="/usr/bin/tesseract")
    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_tsv_ocr_parsing(self, mock_run, mock_popen, mock_which):
        ocr = LinuxOCR()

        # Simulated Tesseract TSV output
        sample_tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t100\t150\t80\t30\t95\tTerminal\n"
            "5\t1\t1\t1\t1\t2\t190\t150\t60\t30\t92\tWindow\n"
        )
        mock_run_proc = MagicMock()
        mock_run_proc.returncode = 0
        mock_run.return_value = mock_run_proc

        mock_popen_proc = MagicMock()
        mock_popen_proc.returncode = 0
        mock_popen_proc.communicate.return_value = (sample_tsv.encode("utf-8"), b"")
        mock_popen.return_value = mock_popen_proc

        test_img = Image.new("RGB", (400, 300), color=(255, 255, 255))
        res = ocr.recognize(test_img)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["text"], "Terminal Window")
        words = res["words"]
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0]["text"], "Terminal")
        self.assertEqual(words[0]["x"], 100)
        self.assertEqual(words[0]["y"], 150)
        self.assertEqual(words[1]["text"], "Window")


if __name__ == "__main__":
    unittest.main()
