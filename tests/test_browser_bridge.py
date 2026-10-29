"""
Unit tests for Companion Browser Extension Loopback Bridge.
Runs on an ephemeral port (19225) to test local HTTP server lifecycle,
command queuing, extension polling, and response correlation headlessly.
"""

import json
import time
import urllib.request
import unittest

from control.browser_bridge import BrowserBridge


class TestBrowserBridge(unittest.TestCase):

    def setUp(self):
        # Use isolated ephemeral port to prevent conflict
        self.bridge = BrowserBridge(port=19225)
        self.assertTrue(self.bridge.start())
        time.sleep(0.1)

    def tearDown(self):
        self.bridge.stop()
        time.sleep(0.05)

    def test_status_endpoint(self):
        req = urllib.request.Request("http://127.0.0.1:19225/status")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "online")
            self.assertFalse(data["connected"])

    def test_registration_and_command_cycle(self):
        # 1. Simulate extension registering
        reg_payload = json.dumps({
            "status": "alive",
            "tab": {"id": 101, "title": "Reddit - Dive into anything", "url": "https://reddit.com"}
        }).encode("utf-8")

        reg_req = urllib.request.Request(
            "http://127.0.0.1:19225/register",
            data=reg_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(reg_req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)

        self.assertTrue(self.bridge.is_connected())
        self.assertEqual(self.bridge.active_tab_info["title"], "Reddit - Dive into anything")

        # 2. In a background thread, simulate the extension polling and answering
        import threading

        def mock_extension_worker():
            # Wait for command in poll
            poll_req = urllib.request.Request("http://127.0.0.1:19225/poll")
            for _ in range(10):
                try:
                    with urllib.request.urlopen(poll_req, timeout=2.0) as p_resp:
                        cmd = json.loads(p_resp.read().decode("utf-8"))
                        if cmd.get("action") == "click":
                            cmd_id = cmd["id"]
                            # Post response back
                            ans_payload = json.dumps({
                                "id": cmd_id,
                                "result": {"status": "success", "message": "Element clicked"}
                            }).encode("utf-8")
                            ans_req = urllib.request.Request(
                                "http://127.0.0.1:19225/response",
                                data=ans_payload,
                                headers={"Content-Type": "application/json"}
                            )
                            with urllib.request.urlopen(ans_req, timeout=2.0) as a_resp:
                                pass
                            return
                except Exception:
                    pass
                time.sleep(0.05)

        th = threading.Thread(target=mock_extension_worker, daemon=True)
        th.start()

        # 3. Dispatch command from Python side
        res = self.bridge.dispatch_command("click", {"selector": "button.post-submit"}, timeout=4.0)
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("message"), "Element clicked")


if __name__ == "__main__":
    unittest.main()
