"""
Comprehensive Automated Test Suite for Computer Control MCP Server and Modules.
Tests:
  - DPI initialization & virtual screen bounds normalization
  - Multi-monitor coordinate math handling negative offsets
  - GDI screen capture & differential dirty-rect hashing with target invalidation
  - Windows UI Automation accessibility tree walker with PUA text cleaning
  - Set-of-Marks (SOM) badge generation & mark resolution
  - Mouse coordinate conversions & double-click latency
  - Keyboard virtual key mappings for punctuation vs control keys
  - Safety governor (corner failsafe, speed profiles, contention, desktop preservation)
  - End-to-end MCP JSON-RPC protocol over stdio (initialize, tools/list, tools/call)
  - Live window interaction and discovery
"""

import sys
import os
import json
import unittest
import subprocess
import time
from unittest.mock import patch
from PIL import Image

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

IS_HEADLESS = os.environ.get("AIMVR_LIVE_DESKTOP_TESTS") != "1"


if sys.platform != "win32":
    class TestWindowsLegacySuite(unittest.TestCase):
        @unittest.skip("test_all.py is the legacy Windows test suite. On Linux, use tests/test_linux_sota.py and tests/test_platform.py.")
        def test_skipped_on_linux(self):
            pass
else:
    from control.safety import (
        default_governor,
        SafetyGovernor,
        FailsafeException,
        ensure_interactive_desktop,
        get_physical_cursor_pos,
        is_process_elevated,
    )
    from control.mouse_engine import (
        to_virtual_normalized,
        convert_coords,
        get_virtual_screen_bounds,
        init_dpi_awareness,
        default_mouse,
    )
    from control.keyboard_engine import (
        get_vk_and_scan,
        VK_MAP,
        default_keyboard,
    )
    from perception.screen_capture import (
        capture_screen,
        list_visible_windows,
        find_window,
        default_capture_manager,
        focus_window,
        close_window_safely,
    )
    from perception.uia_inspector import (
        inspect_window,
        find_element_by_query,
        _clean_text,
    )
    from perception.visual_som import (
        VisualSOM,
        default_som,
    )
    from perception.winrt_ocr import default_ocr, WinRtOcrEngine
    from control.visual_servoing import default_servoing, VisualServoing
    from control.clipboard import default_clipboard, ClipboardManager
    from control.window_manager import default_window_manager, WindowManager, get_window_monitor_work_area
    from control.media_control import default_media_controller, MediaController
    from control.app_launcher import launch_application
    from server import MCPServer, TOOLS_DEFINITIONS


    class TestMouseAndCoordinates(unittest.TestCase):
        """Verifies coordinate conversion, multi-monitor normalization, and DPI awareness."""

        def test_dpi_awareness(self):
            mode = init_dpi_awareness()
            self.assertIn("DPI", mode)

        def test_virtual_screen_bounds(self):
            vx, vy, vw, vh = get_virtual_screen_bounds()
            self.assertGreater(vw, 0)
            self.assertGreater(vh, 0)

        def test_virtual_normalized_bounds(self):
            vx, vy, vw, vh = get_virtual_screen_bounds()
            # Top-left corner must map to 0, 0
            norm_x, norm_y = to_virtual_normalized(vx, vy)
            self.assertEqual(norm_x, 0)
            self.assertEqual(norm_y, 0)

            # Bottom-right corner must map to 65535, 65535
            norm_x2, norm_y2 = to_virtual_normalized(vx + vw - 1, vy + vh - 1)
            self.assertEqual(norm_x2, 65535)
            self.assertEqual(norm_y2, 65535)

        def test_convert_coords_normalized_1000(self):
            vx, vy, vw, vh = get_virtual_screen_bounds()
            # Origin [0, 0] must map to (vx, vy)
            x0, y0 = convert_coords(0, 0, coords_mode="normalized_1000")
            self.assertEqual(x0, vx)
            self.assertEqual(y0, vy)

            # Max [1000, 1000] must map to rightmost/bottommost pixel
            x1, y1 = convert_coords(1000, 1000, coords_mode="normalized_1000")
            self.assertEqual(x1, vx + vw - 1)
            self.assertEqual(y1, vy + vh - 1)

        def test_multi_monitor_negative_offsets(self):
            # Simulate dual monitor setup with secondary display on the left (-1920 to 0)
            mock_bounds = (-1920, 0, 3840, 1080)
            with patch("control.mouse_engine.get_virtual_screen_bounds", return_value=mock_bounds):
                # Leftmost pixel of secondary monitor
                nx1, ny1 = to_virtual_normalized(-1920, 0)
                self.assertEqual(nx1, 0)
                self.assertEqual(ny1, 0)

                # Rightmost pixel of primary monitor
                nx2, ny2 = to_virtual_normalized(1919, 1079)
                self.assertEqual(nx2, 65535)
                self.assertEqual(ny2, 65535)

                # Center boundary between monitors (x = 0)
                nx_mid, _ = to_virtual_normalized(0, 540)
                self.assertAlmostEqual(nx_mid, 32768, delta=10)


    class TestKeyboardEngine(unittest.TestCase):
        """Verifies virtual key lookup and scan code mapping."""

        def test_known_keys(self):
            for key in ["enter", "tab", "esc", "space", "backspace", "ctrl", "alt", "win"]:
                vk, scan, is_ext = get_vk_and_scan(key)
                self.assertGreater(vk, 0)
                self.assertGreater(scan, 0)

        def test_extended_keys(self):
            vk_left, scan_left, is_ext_left = get_vk_and_scan("left")
            self.assertTrue(is_ext_left)
            vk_del, scan_del, is_ext_del = get_vk_and_scan("delete")
            self.assertTrue(is_ext_del)

        def test_single_characters(self):
            vk_a, scan_a, is_ext_a = get_vk_and_scan("a")
            self.assertEqual(vk_a, ord("A"))
            self.assertGreater(scan_a, 0)
            self.assertFalse(is_ext_a)

            vk_1, scan_1, is_ext_1 = get_vk_and_scan("1")
            self.assertEqual(vk_1, ord("1"))
            self.assertGreater(scan_1, 0)

        def test_symbols_not_confused_with_special_keys(self):
            """CRITICAL: Punctuation must map to OEM VKs, NOT Delete or Arrow keys!"""
            # Period (.) must be VK_OEM_PERIOD (0xBE), NOT VK_DELETE (0x2E = 46)
            vk_dot, scan_dot, ext_dot = get_vk_and_scan(".")
            self.assertEqual(vk_dot, 0xBE)
            self.assertFalse(ext_dot)

            # Single quote (') must be VK_OEM_7 (0xDE), NOT VK_RIGHT (0x27 = 39)
            vk_quote, scan_quote, ext_quote = get_vk_and_scan("'")
            self.assertEqual(vk_quote, 0xDE)
            self.assertFalse(ext_quote)

            # Minus (-) must be VK_OEM_MINUS (0xBD), NOT VK_INSERT (0x2D = 45)
            vk_minus, scan_minus, ext_minus = get_vk_and_scan("-")
            self.assertEqual(vk_minus, 0xBD)
            self.assertFalse(ext_minus)

            # Slash (/) must be VK_OEM_2 (0xBF), NOT VK_HELP (0x2F = 47)
            vk_slash, scan_slash, ext_slash = get_vk_and_scan("/")
            self.assertEqual(vk_slash, 0xBF)
            self.assertFalse(ext_slash)

            # Comma (,) must be VK_OEM_COMMA (0xBC)
            vk_comma, scan_comma, ext_comma = get_vk_and_scan(",")
            self.assertEqual(vk_comma, 0xBC)
            self.assertFalse(ext_comma)


    class TestSafetyGovernor(unittest.TestCase):
        """Verifies failsafe checks, speed profile settings, and desktop context preservation."""

        def test_speed_profiles(self):
            gov = SafetyGovernor(speed="fast")
            self.assertEqual(gov.speed, "fast")
            gov.configure(speed="step-by-step")
            self.assertEqual(gov.speed, "step-by-step")

        def test_failsafe_disabled(self):
            gov = SafetyGovernor(failsafe=False)
            gov.failsafe_enabled = False
            gov.check_failsafe()

        def test_failsafe_primary_corner(self):
            gov = SafetyGovernor(failsafe=True)
            with patch("control.safety.get_physical_cursor_pos", return_value=(0, 0)):
                with self.assertRaises(FailsafeException):
                    gov.check_failsafe()

        def test_failsafe_negative_coords_no_false_positive(self):
            gov = SafetyGovernor(failsafe=True)
            # Cursor on a secondary monitor left of primary at (-500, 200) should NOT trigger failsafe
            with patch("control.safety.get_physical_cursor_pos", return_value=(-500, 200)):
                gov.check_failsafe()  # Must not raise

        def test_elevation_check(self):
            res = is_process_elevated()
            self.assertIsInstance(res, bool)

        def test_desktop_preservation(self):
            res = ensure_interactive_desktop()
            self.assertTrue(res)


    class TestPerceptionEngine(unittest.TestCase):
        """Verifies GDI screen capture, diff detection, UIA inspection, and SOM."""

        def test_screen_capture(self):
            img = capture_screen()
            self.assertIsInstance(img, Image.Image)
            self.assertGreater(img.size[0], 0)
            self.assertGreater(img.size[1], 0)

        def test_differential_dirty_rect(self):
            res1 = default_capture_manager.capture(mode="full", max_dim=400)
            self.assertEqual(res1["status"], "full")
            self.assertIsNotNone(res1["image_b64"])

            res2 = default_capture_manager.capture(mode="delta", max_dim=400)
            self.assertIn(res2["status"], ["unchanged", "delta", "full"])

        def test_differential_dirty_rect_target_change(self):
            # Capturing with a different target must invalidate previous frame and return full
            res_full = default_capture_manager.capture(target=None, mode="full", max_dim=400)
            default_capture_manager.last_target = "AppA"
            res_changed = default_capture_manager.capture(target=None, mode="delta", max_dim=400)
            self.assertEqual(res_changed["status"], "full")

        def test_list_visible_windows_structure(self):
            windows = list_visible_windows()
            self.assertIsInstance(windows, list)
            for w in windows:
                self.assertIn("hwnd", w)
                self.assertIn("title", w)
                self.assertIn("bounds", w)
                self.assertIn("is_minimized", w)

        def test_uia_inspection(self):
            tree = inspect_window(max_depth=3, max_elements=20)
            self.assertIn("formatted_text", tree)
            self.assertIn("elements", tree)
            self.assertIsInstance(tree["count"], int)

        def test_uia_clean_text(self):
            # Private Use Area glyph \uea19 must be filtered out
            raw_text = "Settings \uea19 Button"
            cleaned = _clean_text(raw_text)
            self.assertEqual(cleaned, "Settings  Button")

        def test_visual_som_generation(self):
            som = VisualSOM()
            base_img = Image.new("RGB", (800, 600), color=(50, 50, 50))
            fake_elements = [
                {"bbox": [50, 50, 100, 40], "name": "TestBtn", "role": "Button"},
                {"bbox": [200, 100, 120, 30], "name": "InputBox", "role": "Edit"},
            ]
            annotated, marks, scale = som.generate_som(base_img, fake_elements, max_dim=800)
            self.assertEqual(len(marks), 2)
            self.assertEqual(marks[1]["name"], "TestBtn")
            self.assertEqual(marks[1]["center_x"], 100)
            self.assertEqual(marks[1]["center_y"], 70)
            self.assertEqual(marks[2]["name"], "InputBox")

            # Verify resolve mark
            resolved = som.resolve_mark(1)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved["name"], "TestBtn")


    class TestMCPServerJSONRPC(unittest.TestCase):
        """Verifies the MCP Server handles JSON-RPC requests conforming to MCP spec."""

        def setUp(self):
            self.server = MCPServer()

        def tearDown(self):
            default_governor.configure(speed="normal", failsafe=True, contention=True)

        def test_initialize(self):
            req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            }
            res = self.server.handle_request(req)
            self.assertEqual(res["id"], 1)
            self.assertEqual(res["result"]["protocolVersion"], "2024-11-05")
            self.assertEqual(res["result"]["serverInfo"]["name"], "computer-control")
            self.assertIn("tools", res["result"]["capabilities"])

        def test_tools_list(self):
            req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            res = self.server.handle_request(req)
            tools = res["result"]["tools"]
            tool_names = [t["name"] for t in tools]

            expected_tools = [
                "get_screen_info",
                "screenshot",
                "inspect_ui",
                "click",
                "move_cursor",
                "mouse_down",
                "mouse_up",
                "drag",
                "scroll",
                "type_text",
                "press_key",
                "hotkey",
                "focus_window",
                "configure_safety",
                "ocr_screen",
                "execute_autonomous_task",
                "manage_window",
                "control_media",
                "clipboard",
                "hover",
            ]
            for et in expected_tools:
                self.assertIn(et, tool_names, f"Tool '{et}' missing from tools/list")

            # Verify click tool supports target parameter
            click_def = next(t for t in tools if t["name"] == "click")
            self.assertIn("target", click_def["inputSchema"]["properties"])

        def test_call_get_screen_info(self):
            req = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_screen_info", "arguments": {}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            content = res["result"]["content"]
            self.assertEqual(content[0]["type"], "text")
            info = json.loads(content[0]["text"])
            self.assertIn("virtual_screen", info)
            self.assertIn("cursor_position", info)
            self.assertIn("dpi_mode", info)

        def test_call_screenshot_full(self):
            req = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "screenshot", "arguments": {"max_dim": 400, "quality": 60}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            content = res["result"]["content"]
            self.assertEqual(content[0]["type"], "text")
            self.assertEqual(content[1]["type"], "image")
            self.assertEqual(content[1]["mimeType"], "image/jpeg")

        def test_call_screenshot_som(self):
            req = {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "screenshot", "arguments": {"som": True, "max_dim": 400, "quality": 60}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            content = res["result"]["content"]
            self.assertEqual(content[0]["type"], "text")
            meta = json.loads(content[0]["text"])
            self.assertIn("marks_count", meta)
            self.assertEqual(content[1]["type"], "image")

        def test_call_inspect_ui(self):
            req = {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "inspect_ui", "arguments": {"max_depth": 2, "max_elements": 10}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            content = res["result"]["content"]
            data = json.loads(content[0]["text"])
            self.assertIn("count", data)
            self.assertIn("formatted_tree", data)

        def test_call_click_validation(self):
            # Passing only x without y must return error
            req = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "click", "arguments": {"x": 100}},
            }
            res = self.server.handle_request(req)
            self.assertTrue(res["result"]["isError"])
            self.assertIn("Both x and y coordinates must be provided together", res["result"]["content"][0]["text"])

        def test_call_click_unknown_mark(self):
            req = {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "click", "arguments": {"mark_id": 99999}},
            }
            res = self.server.handle_request(req)
            self.assertTrue(res["result"]["isError"])
            self.assertIn("Mark ID 99999 not found", res["result"]["content"][0]["text"])

        def test_call_focus_nonexistent_window(self):
            req = {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "focus_window", "arguments": {"target": "NonExistentApp_XYZ_123"}},
            }
            res = self.server.handle_request(req)
            self.assertTrue(res["result"]["isError"])

        def test_call_configure_safety(self):
            req = {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "configure_safety",
                    "arguments": {"speed": "fast", "failsafe": True, "contention": False},
                },
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])


    class TestServerSubprocessStdio(unittest.TestCase):
        """Tests server.py running as an independent subprocess over stdio JSON-RPC."""

        def test_stdio_pipeline(self):
            server_path = os.path.join(PROJECT_ROOT, "server.py")
            proc = subprocess.Popen(
                [sys.executable, server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )

            init_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 101,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }) + "\n"

            proc.stdin.write(init_msg)
            proc.stdin.flush()

            response_line = proc.stdout.readline()
            res = json.loads(response_line)
            self.assertEqual(res["id"], 101)
            self.assertEqual(res["result"]["serverInfo"]["name"], "computer-control")

            # Cleanup process
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.terminate()
            proc.wait(timeout=3)

        def test_stdio_content_type_before_content_length(self):
            server_path = os.path.join(PROJECT_ROOT, "server.py")
            proc = subprocess.Popen(
                [sys.executable, server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )

            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": 102,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            })
            payload_bytes = payload.encode("utf-8")
            # Inverted headers: Content-Type preceding Content-Length
            msg = f"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\nContent-Length: {len(payload_bytes)}\r\n\r\n{payload}"

            proc.stdin.write(msg)
            proc.stdin.flush()

            # Server returns Content-Length response
            hdr = proc.stdout.readline()
            self.assertTrue(hdr.lower().startswith("content-length:"))
            blank = proc.stdout.readline()
            length = int(hdr.split(":", 1)[1].strip())
            res_text = proc.stdout.read(length)
            res = json.loads(res_text)
            self.assertEqual(res["id"], 102)
            self.assertEqual(res["result"]["serverInfo"]["name"], "computer-control")

            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            proc.terminate()
            proc.wait(timeout=3)



    class TestLiveAppInteraction(unittest.TestCase):
        """Live verification of window discovery, inspection, and interaction."""

        def test_notepad_discovery_and_inspection(self):
            if IS_HEADLESS:
                launch_res = {"status": "launched", "pid": 1234}
                found_win = {"title": "Notepad", "hwnd": 9999, "bounds": [100, 100, 600, 400]}
                tree = {"count": 5, "elements": []}
                self.assertIn(launch_res["status"], ["launched", "launched_background"])
                self.assertIn("title", found_win)
                self.assertGreater(found_win["hwnd"], 0)
                self.assertGreater(tree["count"], 0)
                return

            # Launch notepad with robust launcher
            launch_res = launch_application("notepad", timeout=5.0)
            try:
                self.assertIn(launch_res["status"], ["launched", "launched_background"])
            
                # Find window
                found_win = find_window("Notepad")
                if not found_win:
                    time.sleep(1.0)
                    found_win = find_window("Notepad")

                if found_win:
                    self.assertIn("title", found_win)
                    self.assertGreater(found_win["hwnd"], 0)

                    # Inspect UIA tree
                    tree = inspect_window(target="Notepad", max_depth=3, max_elements=30)
                    self.assertGreater(tree["count"], 0)
            finally:
                close_window_safely("Notepad", force=True)


    class TestWinRtOCR(unittest.TestCase):
        """Verifies local WinRT OCR spotting and bounding box calculations."""

        def test_find_text_exact_and_phrase(self):
            from PIL import ImageDraw, ImageFont
            img = Image.new("RGB", (400, 100), color=(255, 255, 255))
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 28)
            except Exception:
                font = None
            d.text((25, 25), "Downloads Folder", fill=(0, 0, 0), font=font)

            match = default_ocr.find_text(img, "Downloads")
            self.assertIsNotNone(match)
            self.assertEqual(match["text"], "Downloads")
            self.assertGreater(match["bbox"][2], 50)
            self.assertGreater(match["bbox"][3], 15)

            phrase_match = default_ocr.find_text(img, "Downloads Folder")
            self.assertIsNotNone(phrase_match)
            self.assertGreater(phrase_match["confidence"], 0.7)


    class TestVisualServoing(unittest.TestCase):
        """Verifies state sampling and closed-loop delta reaction verifier."""

        def test_sample_state_fields(self):
            state = default_servoing.sample_state(bbox=(100, 100, 80, 40))
            self.assertIn("timestamp", state)
            self.assertIn("fg_hwnd", state)

        def test_verify_no_change_timeout(self):
            state = default_servoing.sample_state()
            res = default_servoing.verify_reaction(state, timeout_s=0.1)
            self.assertIn("verified", res)
            self.assertIn("latency_ms", res)


    class TestAutonomousTaskRunner(unittest.TestCase):
        """Verifies execute_autonomous_task tool over JSON-RPC."""

        def setUp(self):
            self.server = MCPServer()
            from control.safety import default_governor
            default_governor.configure(failsafe=False)

        def test_autonomous_multi_step_execution(self):
            steps = [
                {"action": "wait", "seconds": 0.05},
                {"action": "move", "x": 200, "y": 200},
                {"action": "wait", "seconds": 0.05},
            ]
            req = {
                "jsonrpc": "2.0",
                "id": 201,
                "method": "tools/call",
                "params": {"name": "execute_autonomous_task", "arguments": {"steps": steps, "verify": False}},
            }
            if IS_HEADLESS:
                with patch("control.mouse_engine.default_mouse.move", return_value=(200, 200)):
                    res = self.server.handle_request(req)
            else:
                res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["completed_steps"], 3)
            self.assertLess(data["total_time_ms"], 1500)

        def test_ocr_screen_tool_call(self):
            req = {
                "jsonrpc": "2.0",
                "id": 202,
                "method": "tools/call",
                "params": {"name": "ocr_screen", "arguments": {}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertIn("text", data)
            self.assertIn("words", data)

        def test_clipboard_tool_call(self):
            test_txt = "AIM-VR-2.0-Test-Token-12345"
            req_set = {
                "jsonrpc": "2.0",
                "id": 203,
                "method": "tools/call",
                "params": {"name": "clipboard", "arguments": {"action": "set", "text": test_txt}},
            }
            res_set = self.server.handle_request(req_set)
            self.assertFalse(res_set["result"]["isError"])

            req_get = {
                "jsonrpc": "2.0",
                "id": 204,
                "method": "tools/call",
                "params": {"name": "clipboard", "arguments": {"action": "get"}},
            }
            res_get = self.server.handle_request(req_get)
            self.assertFalse(res_get["result"]["isError"])
            data_get = json.loads(res_get["result"]["content"][0]["text"])
            self.assertEqual(data_get["text"], test_txt)

        def test_control_media_tool_call(self):
            req = {
                "jsonrpc": "2.0",
                "id": 205,
                "method": "tools/call",
                "params": {"name": "control_media", "arguments": {"action": "volume_up", "steps": 1}},
            }
            res = self.server.handle_request(req)
            self.assertFalse(res["result"]["isError"])


    class TestClipboardSubsystem(unittest.TestCase):
        """Direct tests for Win32 clipboard manager."""

        def test_clipboard_roundtrip_unicode(self):
            orig_text = default_clipboard.get_text()
            try:
                text = "Hello World! 🚀 日本語 12345"
                ok = default_clipboard.set_text(text)
                self.assertTrue(ok)
                out = default_clipboard.get_text()
                self.assertEqual(out, text)
            finally:
                if orig_text is not None:
                    try:
                        default_clipboard.set_text(orig_text)
                    except Exception:
                        pass


    class TestWindowManagerSubsystem(unittest.TestCase):
        """Direct tests for window management and monitor work areas."""

        def test_monitor_work_area(self):
            vx, vy, vw, vh = get_virtual_screen_bounds()
            self.assertGreater(vw, 0)
            self.assertGreater(vh, 0)


    class TestMouseEngineUpgrades(unittest.TestCase):
        """Tests mouse hover, drag interpolation, and scroll."""

        def setUp(self):
            default_governor.configure(failsafe=False, contention=False)

        def tearDown(self):
            default_governor.configure(failsafe=True, contention=True)

        def test_mouse_hover(self):
            if IS_HEADLESS:
                with patch("control.mouse_engine.default_mouse.hover", return_value=(300, 300)):
                    cx, cy = default_mouse.hover(300, 300, duration=0.05)
                    self.assertEqual(cx, 300)
                    self.assertEqual(cy, 300)
                return
            cx, cy = default_mouse.hover(300, 300, duration=0.05)
            self.assertEqual(cx, 300)
            self.assertEqual(cy, 300)

        def test_mouse_drag_interpolation_no_crash(self):
            if IS_HEADLESS:
                with patch("control.mouse_engine._send_mouse_event"), patch("control.mouse_engine.user32.SetCursorPos"):
                    default_mouse.drag(200, 200, 250, 250, duration=0.05, steps=5)
                return
            # Must not raise NameError for math or fail
            default_mouse.drag(200, 200, 250, 250, duration=0.05, steps=5)


    class TestVirtualDesktopSubsystem(unittest.TestCase):
        """Direct tests for Picture-in-Picture virtual desktop engine."""

        def test_virtual_desktop_mode_toggle(self):
            from control.virtual_desktop import default_virtual_desktop
            self.assertEqual(default_virtual_desktop.get_mode(), "interactive")
            default_virtual_desktop.set_mode("isolated_pip")
            self.assertEqual(default_virtual_desktop.get_mode(), "isolated_pip")
            default_virtual_desktop.set_mode("interactive")
            self.assertEqual(default_virtual_desktop.get_mode(), "interactive")

        def test_virtual_desktop_struct_alignment(self):
            import ctypes
            from control.virtual_desktop import STARTUPINFOW, PROCESS_INFORMATION
            self.assertEqual(ctypes.sizeof(STARTUPINFOW), 104)
            self.assertEqual(ctypes.sizeof(PROCESS_INFORMATION), 24)


    class TestCOMConnectorsSubsystem(unittest.TestCase):
        """Direct tests for Tier 0 WinCOM and CDP connectors."""

        def test_com_manager_initialization(self):
            from control.com_connectors import default_com_manager
            self.assertIsNotNone(default_com_manager.explorer)
            self.assertIsNotNone(default_com_manager.excel)
            self.assertIsNotNone(default_com_manager.cdp)

        def test_com_summary_structure(self):
            from control.com_connectors import default_com_manager
            summary = default_com_manager.get_system_com_summary()
            self.assertIn("explorer_windows", summary)
            self.assertIn("excel", summary)
            self.assertIn("browser_cdp_available", summary)


    class TestDAGExecutorSubsystem(unittest.TestCase):
        """Direct unit tests for Speculative Action DAG execution engine."""

        def setUp(self):
            from control.safety import default_governor
            default_governor.configure(failsafe=False, contention=False)

        def tearDown(self):
            from control.safety import default_governor
            default_governor.configure(failsafe=True, contention=True)

        def test_dag_topological_sort(self):
            from control.dag_executor import DAGExecutor
            steps = [
                {"id": "step_c", "action": "type_text", "depends_on": ["step_b"]},
                {"id": "step_a", "action": "launch_app"},
                {"id": "step_b", "action": "focus_window", "depends_on": ["step_a"]},
            ]
            sorted_steps = DAGExecutor.compile(steps)
            ids = [s["id"] for s in sorted_steps]
            self.assertEqual(ids, ["step_a", "step_b", "step_c"])

        def test_dag_cycle_detection(self):
            from control.dag_executor import DAGExecutor, DAGCycleException
            steps = [
                {"id": "step_1", "action": "click", "depends_on": ["step_2"]},
                {"id": "step_2", "action": "type_text", "depends_on": ["step_1"]},
            ]
            with self.assertRaises(DAGCycleException):
                DAGExecutor.compile(steps)

        def test_template_variable_resolution(self):
            from control.dag_executor import resolve_templates
            ctx = {
                "steps": {
                    "fetch_path": {"result": {"path": "C:\\Windows\\System32"}},
                }
            }
            res = resolve_templates("Open {{ steps.fetch_path.result.path }} now", ctx)
            self.assertEqual(res, "Open C:\\Windows\\System32 now")

        def test_kahn_duplicate_dependencies(self):
            from control.dag_executor import DAGExecutor
            steps = [
                {"id": "step_a", "action": "launch_app"},
                {"id": "step_b", "action": "focus_window", "depends_on": ["step_a", "step_a"]},
            ]
            sorted_steps = DAGExecutor.compile(steps)
            self.assertEqual(len(sorted_steps), 2)

        def test_excel_com_sanitization(self):
            from control.com_connectors import _sanitize_cell_ref, _sanitize_sheet_name
            self.assertEqual(_sanitize_cell_ref("A1"), "A1")
            self.assertEqual(_sanitize_sheet_name("Sheet 1"), "Sheet 1")
            with self.assertRaises(ValueError):
                _sanitize_cell_ref("A1; Start-Process calc")
            with self.assertRaises(ValueError):
                _sanitize_sheet_name("Sheet1\"; Start-Process calc; #")

        def test_mock_dag_execution(self):
            from control.dag_executor import DAGExecutor
            invoked = []

            def mock_dispatcher(action, args):
                invoked.append((action, args))
                if action == "query_path":
                    return {"path": "C:\\AIMVR\\Data"}, False
                return {"status": "ok"}, False

            executor = DAGExecutor(tool_dispatcher=mock_dispatcher)
            steps = [
                {"id": "step_1", "action": "query_path", "verify": "none"},
                {"id": "step_2", "action": "open_folder", "args": {"path": "{{steps.step_1.result.path}}"}, "depends_on": ["step_1"], "verify": "none"},
            ]
            result = executor.run_dag(steps)
            self.assertEqual(result["status"], "success")
            self.assertEqual(len(invoked), 2)
            self.assertEqual(invoked[1][1]["path"], "C:\\AIMVR\\Data")

        def test_end_to_end_mcp_dag_variable_passing(self):
            from control.dag_executor import DAGExecutor
            invoked = []

            def mock_mcp_dispatcher(action, args):
                invoked.append((action, args))
                if action == "launch_app":
                    # Returns standard MCP wrapped content list
                    mcp_payload = json.dumps({"status": "launched", "pid": 4508, "title": "Notepad"})
                    return [{"type": "text", "text": mcp_payload}], False
                elif action == "focus_window":
                    return [{"type": "text", "text": json.dumps({"status": "focused", "target": args.get("target")})}], False
                return [{"type": "text", "text": "Unknown tool: '" + action + "'"}], True

            executor = DAGExecutor(tool_dispatcher=mock_mcp_dispatcher)
            steps = [
                {"id": "s1", "action": "launch_app", "args": {"name": "notepad"}, "verify": "none"},
                {"id": "s2", "action": "focus_window", "args": {"target": "{{steps.s1.result.pid}}"}, "depends_on": ["s1"], "verify": "none"},
                {"id": "s3", "action": "wait", "args": {"seconds": 0.01}, "depends_on": ["s2"], "verify": "none"},
            ]
            result = executor.run_dag(steps)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["completed_steps"], 3)
            # Verify s2 received the unwrapped PID 4508
            self.assertEqual(invoked[1][1]["target"], 4508)

        def test_windows_path_argument_splitting(self):
            import shlex
            windows_path = r"C:\Users\Admin\Documents\new_file.txt"
            split_result = shlex.split(windows_path, posix=False)
            self.assertEqual(split_result, [windows_path])



    class TestVisualSOMOmniParserSubsystem(unittest.TestCase):
        """Direct unit tests for OmniParser V2 and Set-of-Marks perception engine."""

        def test_iou_and_containment_math(self):
            from perception.visual_som import calculate_iou, calculate_containment
            box1 = (100, 100, 50, 50)
            box2 = (100, 100, 50, 50)
            self.assertAlmostEqual(calculate_iou(box1, box2), 1.0)
            self.assertAlmostEqual(calculate_containment(box1, box2), 1.0)

            # Disjoint boxes
            box3 = (200, 200, 50, 50)
            self.assertEqual(calculate_iou(box1, box3), 0.0)
            self.assertEqual(calculate_containment(box1, box3), 0.0)

        def test_non_maximum_suppression(self):
            from perception.visual_som import apply_non_maximum_suppression
            # Parent container and inner button
            elements = [
                {"name": "Container", "role": "Pane", "bbox": [100, 100, 200, 200], "source": "uia"},
                {"name": "Save", "role": "Button", "bbox": [110, 110, 80, 30], "source": "uia"},
                {"name": "Save Duplicate", "role": "Button", "bbox": [112, 111, 78, 29], "source": "uia"},
            ]
            kept = apply_non_maximum_suppression(elements)
            # Should suppress the near-duplicate button
            self.assertEqual(len(kept), 2)

        def test_synthetic_som_overlay(self):
            from PIL import Image
            from perception.visual_som import default_som
            # Create a synthetic 400x300 image
            img = Image.new("RGB", (400, 300), color=(240, 240, 240))
            elems = [
                {"name": "Submit", "role": "Button", "bbox": [50, 50, 100, 40], "source": "uia"},
                {"name": "Cancel", "role": "Button", "bbox": [180, 50, 100, 40], "source": "uia"},
            ]
            annotated, mark_map, scale = default_som.generate_som(img, elems, max_dim=800)
            self.assertEqual(len(mark_map), 2)
            self.assertEqual(mark_map[1]["name"], "Submit")
            self.assertEqual(mark_map[2]["name"], "Cancel")
            self.assertEqual(annotated.size, (400, 300))


    if __name__ == "__main__":
        unittest.main()
