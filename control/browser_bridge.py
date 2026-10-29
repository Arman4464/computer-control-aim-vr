"""
Zero-Flag Companion Browser Bridge Server (AIM-VR 3.0 Control Subsystem).
Runs a local HTTP loopback server on 127.0.0.1:9224 to communicate with the
companion Manifest V3 Chrome/Edge extension.
Enables sub-5ms DOM queries, element clicking, and form filling without
requiring browser restarts or --remote-debugging-port flags.
"""

import json
import time
import uuid
import queue
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_PORT = 9224


class BrowserBridgeHandler(BaseHTTPRequestHandler):
    """Handles incoming HTTP requests from the companion browser extension."""

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP access logs
        return

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        bridge = getattr(self.server, "bridge_instance", None)
        path = self.path.split("?")[0]

        if path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            status_data = {
                "status": "online",
                "connected": bridge.is_connected() if bridge else False,
                "active_tab": bridge.active_tab_info if bridge else None,
                "pending_commands": bridge.pending_queue.qsize() if bridge else 0,
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))

        elif path == "/poll":
            # Extension polls for next command to execute
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()

            cmd = None
            if bridge:
                try:
                    cmd = bridge.pending_queue.get(timeout=2.0)
                except queue.Empty:
                    cmd = None

            if cmd:
                self.wfile.write(json.dumps(cmd).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"status": "idle"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        bridge = getattr(self.server, "bridge_instance", None)
        path = self.path.split("?")[0]

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if path == "/register":
            # Extension announces connection
            if bridge:
                bridge.mark_connected(data.get("tab"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "registered"}).encode("utf-8"))

        elif path == "/response":
            # Extension delivers execution result for a correlation ID
            cmd_id = data.get("id")
            if bridge and cmd_id:
                bridge.deliver_response(cmd_id, data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "acknowledged"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class BrowserBridge:
    """Manages the local bridge server and async command dispatches."""

    def __init__(self, port: int = DEFAULT_BRIDGE_PORT):
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.pending_queue: queue.Queue = queue.Queue()
        self.responses: Dict[str, Dict[str, Any]] = {}
        self.events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.last_heartbeat: float = 0
        self.active_tab_info: Optional[Dict[str, Any]] = None
        self._running = False

    def start(self) -> bool:
        """Starts the local bridge server in a background daemon thread."""
        with self._lock:
            if self._running and self.server:
                return True

            try:
                self.server = HTTPServer(("127.0.0.1", self.port), BrowserBridgeHandler)
                self.server.bridge_instance = self
                self._running = True
                self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                self.server_thread.start()
                logger.info(f"Browser bridge server started on 127.0.0.1:{self.port}")
                return True
            except Exception as e:
                logger.error(f"Failed to start browser bridge on port {self.port}: {e}")
                self._running = False
                return False

    def stop(self):
        """Stops the bridge server."""
        with self._lock:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def mark_connected(self, tab_info: Optional[Dict[str, Any]] = None):
        with self._lock:
            self.last_heartbeat = time.time()
            if tab_info:
                self.active_tab_info = tab_info

    def is_connected(self) -> bool:
        with self._lock:
            return (time.time() - self.last_heartbeat) < 15.0

    def deliver_response(self, cmd_id: str, data: Dict[str, Any]):
        with self._lock:
            self.last_heartbeat = time.time()
            self.responses[cmd_id] = data
            event = self.events.get(cmd_id)
            if event:
                event.set()

    def dispatch_command(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        Dispatches a DOM command to the connected browser extension and waits for response.
        Supported actions: 'click', 'type', 'query', 'get_dom_tree', 'scroll', 'eval'.
        """
        if not self.is_running():
            self.start()

        if not self.is_connected():
            return {
                "status": "error",
                "message": "Browser extension companion is not connected. Load unpacked extension in Chrome/Edge.",
            }

        cmd_id = str(uuid.uuid4())
        cmd = {
            "id": cmd_id,
            "action": action,
            "params": params or {},
            "timestamp": time.time(),
        }

        event = threading.Event()
        with self._lock:
            self.events[cmd_id] = event
            self.pending_queue.put(cmd)

        finished = event.wait(timeout=max(0.1, timeout))

        with self._lock:
            res = self.responses.pop(cmd_id, None)
            self.events.pop(cmd_id, None)

        if not finished or res is None:
            return {
                "status": "timeout",
                "message": f"Browser extension command '{action}' timed out after {timeout}s.",
            }

        return res.get("result", res)


default_browser_bridge = BrowserBridge()
