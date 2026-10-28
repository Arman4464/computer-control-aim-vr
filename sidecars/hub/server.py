"""
Antigravity Sidecar Web Server for Computer Control (AIM-VR 3.0).
Provides the HTTP bridge and REST APIs for the Auxiliary Side Pane UI extension.
Zero third-party web framework dependencies (built purely on Python standard library http.server).
"""

import sys
import os
import json
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add package root to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from control.safety import default_governor, run_in_interactive_desktop
from control.virtual_desktop import default_virtual_desktop
from control.window_manager import default_window_manager
from control.app_launcher import launch_application
from perception.screen_capture import (
    default_capture_manager,
    list_visible_windows,
    list_monitors,
    get_foreground_window_info,
    focus_window,
    close_window_safely,
)


class ComputerControlSidecarHandler(BaseHTTPRequestHandler):
    """Handles static web UI assets and REST API endpoints for Antigravity Side Pane."""
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Suppress noisy standard request logging to keep console clean
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-codeium-csrf-token")
        self.send_header("Connection", "close")
        self.close_connection = True

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif path == "/styles.css":
            self._serve_file("styles.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self._serve_file("app.js", "application/javascript; charset=utf-8")
        elif path == "/api/status":
            self._handle_api_status()
        elif path == "/api/preview":
            self._handle_api_preview(parsed.query)
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        if path == "/api/settings":
            self._handle_api_settings(payload)
        elif path == "/api/action":
            self._handle_api_action(payload)
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _serve_file(self, filename: str, content_type: str):
        file_path = os.path.join(SCRIPT_DIR, "web", filename)
        if not os.path.exists(file_path):
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(f"File {filename} not found".encode("utf-8"))
            return

        with open(file_path, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _handle_api_status(self):
        try:
            # Query active windows and screen info
            vis_windows = list_visible_windows()
            fg_info = get_foreground_window_info()
            monitors = list_monitors()

            # Query sandbox state
            sb_windows = default_virtual_desktop.list_sandbox_windows()
            desktop_mode = default_virtual_desktop.get_mode()

            status_payload = {
                "status": "ok",
                "settings": {
                    "desktop_mode": desktop_mode,
                    "speed": default_governor.speed,
                    "action_delay": default_governor.action_delay,
                    "failsafe": default_governor.failsafe_enabled,
                    "contention": default_governor.contention_enabled,
                },
                "diagnostics": {
                    "foreground_window": fg_info,
                    "monitors": monitors,
                    "visible_windows_count": len(vis_windows),
                    "visible_windows": vis_windows[:25],
                    "sandbox": {
                        "active": bool(default_virtual_desktop._sandbox_handle),
                        "desktop_name": default_virtual_desktop.sandbox_name,
                        "windows_count": len(sb_windows),
                        "windows": sb_windows,
                    },
                },
            }
            res_data = json.dumps(status_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(res_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(res_data)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_data = json.dumps({"status": "error", "message": str(e), "traceback": tb}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(err_data)

    def _handle_api_settings(self, payload: dict):
        try:
            # 1. Desktop Mode
            if "desktop_mode" in payload:
                new_mode = str(payload["desktop_mode"]).strip().lower()
                if new_mode in ("interactive", "isolated_pip"):
                    default_virtual_desktop.set_mode(new_mode)
                    default_governor.configure(desktop_mode=new_mode)

            # 2. Speed Profile
            if "speed" in payload:
                new_speed = str(payload["speed"]).strip().lower()
                if new_speed in ("fast", "normal", "step-by-step"):
                    default_governor.configure(speed=new_speed)

            # 3. Custom Action Delay
            if "action_delay" in payload:
                try:
                    delay = max(0.0, min(2.0, float(payload["action_delay"])))
                    default_governor.action_delay = delay
                except (ValueError, TypeError):
                    pass

            # 4. Corner Failsafe
            if "failsafe" in payload:
                default_governor.configure(failsafe=bool(payload["failsafe"]))

            # 5. User Mouse Contention
            if "contention" in payload:
                default_governor.configure(contention=bool(payload["contention"]))

            res_payload = {
                "status": "ok",
                "settings": {
                    "desktop_mode": default_virtual_desktop.get_mode(),
                    "speed": default_governor.speed,
                    "action_delay": default_governor.action_delay,
                    "failsafe": default_governor.failsafe_enabled,
                    "contention": default_governor.contention_enabled,
                },
            }
            res_data = json.dumps(res_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(res_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(res_data)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_data = json.dumps({"status": "error", "message": str(e), "traceback": tb}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(err_data)

    def _handle_api_action(self, payload: dict):
        action = payload.get("action", "")
        target = payload.get("target", "")
        result = {}

        try:
            if action == "focus":
                success = focus_window(target)
                result = {"action": "focus", "target": target, "success": success}

            elif action == "snap":
                pos = payload.get("position", "left")
                res = default_window_manager.snap_window(target, pos)
                result = {"action": "snap", "target": target, "position": pos, "result": res}

            elif action == "state":
                st = payload.get("state", "restore")
                res = default_window_manager.set_window_state(target, st)
                result = {"action": "state", "target": target, "state": st, "result": res}

            elif action == "close":
                force = bool(payload.get("force", False))
                success = close_window_safely(target, force=force)
                result = {"action": "close", "target": target, "success": success}

            elif action == "launch":
                name = payload.get("name", "")
                args = payload.get("args", "")
                res = launch_application(name, args=args)
                result = {"action": "launch", "name": name, "result": res}

            elif action == "sandbox_launch":
                cmd = payload.get("command", "")
                res = default_virtual_desktop.launch_in_sandbox(cmd)
                result = {"action": "sandbox_launch", "command": cmd, "result": res}

            elif action == "sandbox_destroy":
                res = default_virtual_desktop.destroy_sandbox()
                result = {"action": "sandbox_destroy", "result": res}

            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}

            res_payload = {"status": "ok", "result": result}
            res_data = json.dumps(res_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(res_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(res_data)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_data = json.dumps({"status": "error", "message": str(e), "traceback": tb}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(err_data)

    def _handle_api_preview(self, query_str: str):
        params = parse_qs(query_str)
        mode = params.get("mode", ["auto"])[0]

        try:
            if mode == "sandbox" or (mode == "auto" and default_virtual_desktop.get_mode() == "isolated_pip"):
                # Composite PiP capture
                pip_res = default_virtual_desktop.capture_pip_composite(max_dim=800, quality=70)
                import base64
                img_bytes = base64.b64decode(pip_res["image_b64"])
            else:
                # Direct capture
                raw_img, _ = default_capture_manager.get_raw_frame()
                raw_img.thumbnail((800, 800))
                buf = io.BytesIO()
                raw_img.save(buf, format="JPEG", quality=70)
                img_bytes = buf.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(img_bytes)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_data = json.dumps({"status": "error", "message": str(e), "traceback": tb}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(err_data)


def main():
    port_str = os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT", "8765")
    port = int(port_str)
    server_address = ("127.0.0.1", port)

    httpd = HTTPServer(server_address, ComputerControlSidecarHandler)
    sys.stderr.write(f"[ComputerControlSidecar] Active on http://127.0.0.1:{port}\n")
    sys.stderr.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
