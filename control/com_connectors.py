"""
Windows WinCOM & Native Shell Automation Connectors (AIM-VR 3.0 Tier 0 Grounding).
Provides instantaneous, zero-token, zero-latency direct object-model manipulation:
  - File Explorer: Shell.Application folder navigation, window enumeration, and selected item retrieval.
  - Microsoft Excel: Direct worksheet cell/range reading, formula writing, and workbook state.
  - Chrome / Edge CDP: Browser DevTools Protocol connector for tab enumeration, URL navigation, and script evaluation.
"""

import subprocess
import json
import os
import sys
import re
import urllib.request
import urllib.parse
import urllib.error
import socket
import secrets
import base64
import time
from typing import Optional, Dict, Any, List


def _sanitize_cell_ref(cell_ref: str) -> str:
    """Validates and sanitizes Excel cell references (e.g. 'A1', 'Z99')."""
    clean = str(cell_ref).strip().upper()
    if not re.match(r"^[A-Z]{1,3}[0-9]{1,7}$", clean):
        raise ValueError(f"Invalid Excel cell reference: '{cell_ref}'. Expected format like 'A1', 'B20'.")
    return clean


def _sanitize_sheet_name(sheet_name: Optional[str]) -> Optional[str]:
    """Validates and sanitizes Excel worksheet names."""
    if not sheet_name:
        return None
    clean = str(sheet_name).strip()
    if not re.match(r"^[A-Za-z0-9_\-\. ]{1,100}$", clean):
        raise ValueError(f"Invalid Excel sheet name: '{sheet_name}'. Only alphanumeric characters, dots, and spaces permitted.")
    return clean


class ExplorerCOMConnector:
    """
    Win32 Shell.Application COM interface for File Explorer.
    Instantaneous folder opening, path navigation, and selection inspection.
    """

    @staticmethod
    def _run_ps_json(script: str) -> Any:
        """Executes a PowerShell script and returns parsed JSON output."""
        if sys.platform != "win32":
            return None
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            out = res.stdout.strip()
            if not out:
                return None
            return json.loads(out)
        except Exception as e:
            sys.stderr.write(f"[ExplorerCOM] PowerShell error: {e}\n")
            return None

    def list_open_explorers(self) -> List[Dict[str, Any]]:
        """
        Enumerates all currently open File Explorer windows, returning their
        HWNDs, window titles, and currently displayed filesystem folder paths.
        """
        ps = r"""
        $shell = New-Object -ComObject Shell.Application
        $windows = $shell.Windows()
        $results = @()
        foreach ($w in $windows) {
            try {
                $path = $w.Document.Folder.Self.Path
                if ($path) {
                    $results += @{
                        title = $w.LocationName
                        url = $w.LocationURL
                        path = $path
                        hwnd = [int64]$w.HWND
                    }
                }
            } catch {}
        }
        if ($results.Count -eq 0) {
            Write-Output "[]"
        } else {
            $results | ConvertTo-Json -Compress
        }
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, list) else ([res] if res else [])

    def open_folder(self, folder_path: str) -> Dict[str, Any]:
        """
        Opens a folder path directly in File Explorer using Shell.Application.
        Creates a new window or navigates existing window instantaneously (5ms).
        """
        abs_path = os.path.abspath(os.path.expandvars(folder_path))
        if not os.path.exists(abs_path):
            return {"status": "error", "message": f"Path not found: {abs_path}"}

        if sys.platform != "win32":
            from control.platform import get_platform_driver
            return get_platform_driver().app_launcher.open_file_or_url(abs_path)

        escaped_abs_path = abs_path.replace('\\', '\\\\')
        ps = f"""
        $shell = New-Object -ComObject Shell.Application
        $shell.Open('{abs_path.replace("'", "''")}')
        Write-Output '{{"status":"opened","path":"{escaped_abs_path}"}}'
        """
        res = self._run_ps_json(ps)
        if res and isinstance(res, dict):
            return res
        return {"status": "opened", "path": abs_path}

    def get_selected_items(self) -> List[Dict[str, Any]]:
        """
        Retrieves all currently highlighted / selected files and folders
        across any open File Explorer window.
        """
        ps = r"""
        $shell = New-Object -ComObject Shell.Application
        $windows = $shell.Windows()
        $results = @()
        foreach ($w in $windows) {
            try {
                $sel = $w.Document.SelectedItems()
                foreach ($item in $sel) {
                    $results += @{
                        name = $item.Name
                        path = $item.Path
                        size = $item.Size
                        is_folder = $item.IsFolder
                        window = $w.LocationName
                    }
                }
            } catch {}
        }
        if ($results.Count -eq 0) {
            Write-Output "[]"
        } else {
            $results | ConvertTo-Json -Compress
        }
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, list) else ([res] if res else [])


class ExcelCOMConnector:
    """
    Microsoft Excel COM Object Interface.
    Provides direct worksheet reading, cell queries, and formula injection without GUI clicks.
    """

    @staticmethod
    def _run_ps_json(script: str) -> Any:
        if sys.platform != "win32":
            return None
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=6.0,
            )
            out = res.stdout.strip()
            if not out:
                return None
            return json.loads(out)
        except Exception as e:
            sys.stderr.write(f"[ExcelCOM] PowerShell error: {e}\n")
            return None

    def get_status(self) -> Dict[str, Any]:
        """Checks if Microsoft Excel is currently running and has an open workbook."""
        if sys.platform != "win32":
            return {"status": "unsupported_platform", "message": "Microsoft Excel COM automation is only available on Windows"}
        ps = r"""
        try {
            $excel = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            if ($excel) {
                $wbCount = $excel.Workbooks.Count
                $activeWb = if ($excel.ActiveWorkbook) { $excel.ActiveWorkbook.Name } else { $null }
                $activeSheet = if ($excel.ActiveSheet) { $excel.ActiveSheet.Name } else { $null }
                Write-Output (ConvertTo-Json -Compress @{
                    status = "active"
                    workbooks_count = $wbCount
                    active_workbook = $activeWb
                    active_sheet = $activeSheet
                })
            } else {
                Write-Output '{"status":"not_running"}'
            }
        } catch {
            Write-Output '{"status":"not_running","message":"Excel not active"}'
        }
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, dict) else {"status": "not_running"}

    def read_cell(self, cell_ref: str, sheet_name: Optional[str] = None) -> Dict[str, Any]:
        """Reads value and formula from a cell (e.g. 'A1', 'C15')."""
        if sys.platform != "win32":
            return {"status": "unsupported_platform", "message": "Microsoft Excel COM automation is only available on Windows"}
        clean_cell = _sanitize_cell_ref(cell_ref)
        clean_sheet = _sanitize_sheet_name(sheet_name)
        sheet_selector = f'$excel.Sheets.Item("{clean_sheet}")' if clean_sheet else "$excel.ActiveSheet"
        ps = f"""
        try {{
            $excel = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            $sheet = {sheet_selector}
            $cell = $sheet.Range("{clean_cell}")
            Write-Output (ConvertTo-Json -Compress @{{
                status = "ok"
                cell = "{clean_cell}"
                value = $cell.Value2
                text = $cell.Text
                formula = $cell.Formula
            }})
        }} catch {{
            Write-Output (ConvertTo-Json -Compress @{{
                status = "error"
                message = $_.Exception.Message
            }})
        }}
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, dict) else {"status": "error", "message": "Failed to read cell"}

    def write_cell(self, cell_ref: str, value: Any, sheet_name: Optional[str] = None) -> Dict[str, Any]:
        """Writes value or formula into a cell (e.g. 'B2', '=SUM(A1:A10)')."""
        if sys.platform != "win32":
            return {"status": "unsupported_platform", "message": "Microsoft Excel COM automation is only available on Windows"}
        clean_cell = _sanitize_cell_ref(cell_ref)
        clean_sheet = _sanitize_sheet_name(sheet_name)
        sheet_selector = f'$excel.Sheets.Item("{clean_sheet}")' if clean_sheet else "$excel.ActiveSheet"
        val_str = str(value).replace("'", "''").replace('"', '`"').replace('$', '`$')
        ps = f"""
        try {{
            $excel = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            $sheet = {sheet_selector}
            $cell = $sheet.Range("{clean_cell}")
            $cell.Value2 = '{val_str}'
            Write-Output (ConvertTo-Json -Compress @{{
                status = "ok"
                cell = "{clean_cell}"
                written_value = '{val_str}'
                text = $cell.Text
            }})
        }} catch {{
            Write-Output (ConvertTo-Json -Compress @{{
                status = "error"
                message = $_.Exception.Message
            }})
        }}
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, dict) else {"status": "error", "message": "Failed to write cell"}

    def read_range(
        self,
        start_cell: str = "A1",
        rows: int = 10,
        cols: int = 10,
        sheet_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reads a 2D matrix of cell values starting at start_cell in a single COM call."""
        if sys.platform != "win32":
            return {"status": "unsupported_platform", "message": "Microsoft Excel COM automation is only available on Windows"}
        clean_cell = _sanitize_cell_ref(start_cell)
        clean_sheet = _sanitize_sheet_name(sheet_name)
        rows_clean = max(1, min(1000, int(rows)))
        cols_clean = max(1, min(100, int(cols)))
        sheet_selector = f'$excel.Sheets.Item("{clean_sheet}")' if clean_sheet else "$excel.ActiveSheet"
        ps = f"""
        try {{
            $excel = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            $sheet = {sheet_selector}
            $start = $sheet.Range("{clean_cell}")
            $r1 = $start.Row
            $c1 = $start.Column
            $r2 = $r1 + {rows_clean} - 1
            $c2 = $c1 + {cols_clean} - 1
            $end = $sheet.Cells.Item($r2, $c2)
            $rng = $sheet.Range($start, $end)
            $vals = $rng.Value2
            $data = @()
            if ($vals -is [System.Array]) {{
                for ($r = 1; $r -le $vals.GetLength(0); $r++) {{
                    $rowVals = @()
                    for ($c = 1; $c -le $vals.GetLength(1); $c++) {{
                        $v = [string]$vals[$r, $c]
                        $rowVals += $v
                    }}
                    $data += ,$rowVals
                }}
            }} else {{
                $data = @(@([string]$vals))
            }}
            Write-Output (ConvertTo-Json -Compress @{{
                status = "ok"
                start_cell = "{clean_cell}"
                rows = {rows_clean}
                cols = {cols_clean}
                data = $data
            }})
        }} catch {{
            Write-Output (ConvertTo-Json -Compress @{{
                status = "error"
                message = $_.Exception.Message
            }})
        }}
        """
        res = self._run_ps_json(ps)
        return res if isinstance(res, dict) else {"status": "error", "message": "Failed to read range"}


class BrowserCDPConnector:
    """
    Direct Chrome / Edge Chrome DevTools Protocol (CDP) Bridge.
    Connects to browser debugging ports (e.g. http://localhost:9222)
    to query open tabs, titles, URLs, and execute scripts without vision tokens.
    """

    def __init__(self, port: int = 9222):
        self.port = port
        self.base_url = f"http://127.0.0.1:{self.port}"

    def is_available(self) -> bool:
        """Returns True if a browser CDP endpoint is responsive."""
        try:
            req = urllib.request.Request(f"{self.base_url}/json/version", headers={"User-Agent": "AIMVR/3.0"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_tabs(self) -> List[Dict[str, Any]]:
        """Returns list of open browser tabs (titles, URLs, IDs, and types)."""
        try:
            req = urllib.request.Request(f"{self.base_url}/json", headers={"User-Agent": "AIMVR/3.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tabs = []
                for item in data:
                    if item.get("type") == "page":
                        tabs.append({
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "ws_url": item.get("webSocketDebuggerUrl"),
                        })
                return tabs
        except Exception as e:
            sys.stderr.write(f"[BrowserCDP] Failed to query tabs: {e}\n")
            return []

    def get_active_tab(self) -> Optional[Dict[str, Any]]:
        """Returns the first visible page tab."""
        tabs = self.list_tabs()
        return tabs[0] if tabs else None

    def _send_cdp_ws(self, ws_url: str, method: str, params: Dict[str, Any], timeout: float = 2.0) -> bool:
        """Sends a JSON-RPC command over raw TCP WebSocket (RFC 6455) to a CDP endpoint."""
        try:
            parsed = urllib.parse.urlparse(ws_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or self.port
            path = parsed.path

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))

            nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {nonce}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            s.sendall(handshake.encode("utf-8"))

            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = s.recv(1024)
                if not chunk:
                    break
                resp += chunk

            if b"101" not in resp:
                s.close()
                return False

            payload = json.dumps({"id": 1, "method": method, "params": params}).encode("utf-8")
            mask_key = secrets.token_bytes(4)
            length = len(payload)
            if length < 126:
                header = bytes([0x81, 0x80 | length]) + mask_key
            elif length < 65536:
                header = bytes([0x81, 0xFE, (length >> 8) & 0xFF, length & 0xFF]) + mask_key
            else:
                header = bytes([0x81, 0xFF]) + length.to_bytes(8, "big") + mask_key

            masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            s.sendall(header + masked)
            time.sleep(0.05)
            try:
                s.settimeout(0.5)
                s.recv(1024)
            except Exception:
                pass
            s.close()
            return True
        except Exception as e:
            sys.stderr.write(f"[BrowserCDP] WS command failed: {e}\n")
            return False

    def navigate_tab(self, tab_id: str, url: str) -> Dict[str, Any]:
        """Navigates an existing browser tab to url via CDP WebSocket protocol."""
        try:
            # 1. Activate tab
            target_url = f"{self.base_url}/json/activate/{tab_id}"
            req = urllib.request.Request(target_url, headers={"User-Agent": "AIMVR/3.0"})
            urllib.request.urlopen(req, timeout=1.5)

            # 2. Query tab's WebSocket URL
            tabs = self.list_tabs()
            target_tab = next((t for t in tabs if t.get("id") == tab_id), None)
            ws_url = target_tab.get("ws_url") if target_tab else None

            if ws_url:
                ok = self._send_cdp_ws(ws_url, "Page.navigate", {"url": url})
                if ok:
                    return {"status": "navigated", "tab_id": tab_id, "url": url}

            # 3. Fallback: navigate via /json/new
            encoded_url = urllib.parse.quote(url, safe=":/#?=&")
            new_req = urllib.request.Request(f"{self.base_url}/json/new?{encoded_url}", headers={"User-Agent": "AIMVR/3.0"})
            urllib.request.urlopen(new_req, timeout=1.5)
            return {"status": "opened_new_tab", "url": url}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class COMManager:
    """Unified coordinator for Tier 0 direct COM and protocol connectors."""

    def __init__(self):
        self.explorer = ExplorerCOMConnector()
        self.excel = ExcelCOMConnector()
        self.cdp = BrowserCDPConnector()

    def get_system_com_summary(self) -> Dict[str, Any]:
        """Returns status of open File Explorers, Excel workbooks, and browser CDP tabs."""
        explorers = self.explorer.list_open_explorers()
        excel_status = self.excel.get_status()
        cdp_active = self.cdp.is_available()
        tabs = self.cdp.list_tabs() if cdp_active else []

        return {
            "explorer_windows": len(explorers),
            "explorers": explorers,
            "excel": excel_status,
            "browser_cdp_available": cdp_active,
            "browser_tabs_count": len(tabs),
            "browser_tabs": tabs,
        }


# Global default instance
default_com_manager = COMManager()
