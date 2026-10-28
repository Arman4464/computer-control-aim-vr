"""
Unified CLI Entry Point for Autonomous In-Memory Vision Runner (AIM-VR 3.0).
Allows the AI agent or user to execute single actions, desktop manipulation,
and multi-step autonomous plans instantly from the command line without writing custom scripts.
"""

import sys
import os
import json
import argparse
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from server import MCPServer
from control.safety import default_governor


def parse_flexible_json(content: str) -> Any:
    """Parses JSON with robust multi-stage fallbacks to withstand PowerShell argument unquoting."""
    content = content.strip()
    if os.path.exists(content):
        with open(content, "r", encoding="utf-8") as f:
            return json.load(f)

    # 1. Standard JSON parse
    try:
        return json.loads(content)
    except Exception:
        pass

    # 2. Python ast literal_eval
    try:
        import ast
        return ast.literal_eval(content)
    except Exception:
        pass

    # 3. Clean up PowerShell stripped-quote quirks
    try:
        import re
        fixed = content
        # Remove PowerShell backslash artifacts before quotes or brackets
        fixed = fixed.replace(r'\"', '"').replace(r'\:', ':').replace(r'\,', ',')
        # Quote unquoted dictionary keys: {id: ...} -> {"id": ...}
        fixed = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)\s*:', r'\1"\2":', fixed)
        # Quote unquoted string values after colon: : wait, -> : "wait",
        fixed = re.sub(r':\s*([a-zA-Z_]\w*)(\s*[,}])', r': "\1"\2', fixed)
        # Quote unquoted identifiers inside arrays: [s1] -> ["s1"], [s1, s2] -> ["s1", "s2"]
        fixed = re.sub(r'\[\s*([a-zA-Z_]\w*)\s*\]', r'["\1"]', fixed)
        fixed = re.sub(r'\[\s*([a-zA-Z_]\w*)\s*,', r'["\1",', fixed)
        fixed = re.sub(r',\s*([a-zA-Z_]\w*)\s*\]', r', "\1"]', fixed)
        fixed = re.sub(r',\s*([a-zA-Z_]\w*)\s*,', r', "\1",', fixed)
        return json.loads(fixed)
    except Exception:
        pass

    # 4. Fallback replacing single quotes
    return json.loads(content.replace("'", '"'))


def main():
    parser = argparse.ArgumentParser(description="AIM-VR 3.0 Computer Control CLI Runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. execute: multi-step JSON plan
    exec_parser = subparsers.add_parser("execute", help="Execute multi-step JSON action plan")
    exec_parser.add_argument("steps_json", nargs="+", help="JSON string or file containing list of action steps")
    exec_parser.add_argument("--no-verify", action="store_true", help="Disable visual servoing verification")
    exec_parser.add_argument("--allow-failsafe", action="store_true", help="Keep corner failsafe enabled")

    # 1b. dag: Speculative Action DAG execution
    dag_parser = subparsers.add_parser("dag", help="Execute Speculative Action DAG with closed-loop verification")
    dag_parser.add_argument("dag_json", nargs="+", help="JSON string or file containing action DAG")
    dag_parser.add_argument("--no-verify", action="store_true", help="Disable micro-servoing verification")
    dag_parser.add_argument("--continue-on-error", action="store_true", help="Do not halt DAG when a step fails")
    dag_parser.add_argument("--allow-failsafe", action="store_true", help="Keep corner failsafe enabled")

    # 2. click: semantic query or coordinates
    click_parser = subparsers.add_parser("click", help="Click an element by name, query, or coordinates")
    click_parser.add_argument("--query", "-q", help="Semantic element name or text to click")
    click_parser.add_argument("--target", "-t", help="Scope action to target window")
    click_parser.add_argument("--mark-id", "-m", type=int, help="Set-of-Marks integer badge ID")
    click_parser.add_argument("--x", type=float, help="Explicit X coordinate")
    click_parser.add_argument("--y", type=float, help="Explicit Y coordinate")
    click_parser.add_argument("--double", action="store_true", help="Double-click")
    click_parser.add_argument("--triple", action="store_true", help="Triple-click (select full line/paragraph)")
    click_parser.add_argument("--right", action="store_true", help="Right-click")

    # 3. hover: hover cursor over element or coordinates
    hover_parser = subparsers.add_parser("hover", help="Hover cursor to trigger tooltip or hover menu")
    hover_parser.add_argument("--query", "-q", help="Element name to hover over")
    hover_parser.add_argument("--target", "-t", help="Window title substring")
    hover_parser.add_argument("--x", type=float, help="Explicit X coordinate")
    hover_parser.add_argument("--y", type=float, help="Explicit Y coordinate")
    hover_parser.add_argument("--duration", "-d", type=float, default=0.25, help="Hover duration in seconds")

    # 4. close: close window by target title
    close_parser = subparsers.add_parser("close", help="Close window by title substring")
    close_parser.add_argument("target", help="Window title substring (e.g. 'File Explorer', 'Notepad')")
    close_parser.add_argument("--force", action="store_true", help="Force terminate process if close unresponsive")

    # 5. window: layout and window management
    win_parser = subparsers.add_parser("window", help="Manage window snapping, layout, and state")
    win_parser.add_argument("target", help="Window title substring")
    win_parser.add_argument("--snap", choices=["left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right", "center"], help="Snap to monitor region")
    win_parser.add_argument("--state", choices=["maximize", "minimize", "restore"], help="Set window state")
    win_parser.add_argument("--bounds", nargs=4, type=int, metavar=("X", "Y", "W", "H"), help="Explicit pixel bounds")

    # 6. media: audio volume and media playback
    media_parser = subparsers.add_parser("media", help="Control volume and media playback")
    media_parser.add_argument("action", choices=["volume_up", "volume_down", "toggle_mute", "play_pause", "next_track", "prev_track", "stop"], help="Media action")
    media_parser.add_argument("--steps", type=int, default=1, help="Steps for volume change")

    # 7. clipboard: clipboard text and instant paste
    clip_parser = subparsers.add_parser("clipboard", help="Win32 native clipboard operations")
    clip_parser.add_argument("--get", action="store_true", help="Get clipboard text")
    clip_parser.add_argument("--set", help="Set clipboard text")
    clip_parser.add_argument("--paste", help="Instant paste text via simulated Ctrl+V")
    clip_parser.add_argument("--restore", action="store_true", help="Restore clipboard after pasting")

    # 8. launch: launch application
    launch_parser = subparsers.add_parser("launch", help="Launch application or URL")
    launch_parser.add_argument("app", help="Application name or executable (e.g. 'chrome', 'notepad', 'calc')")
    launch_parser.add_argument("--args", help="Arguments to pass to application")

    # 9. type: type text
    type_parser = subparsers.add_parser("type", help="Type Unicode text")
    type_parser.add_argument("text", help="Text to type")

    # 10. hotkey: press key combination
    hotkey_parser = subparsers.add_parser("hotkey", help="Press hotkey combo")
    hotkey_parser.add_argument("keys", nargs="+", help="Keys to press (e.g. ctrl s, win r, alt tab)")

    # 11. focus: focus window
    focus_parser = subparsers.add_parser("focus", help="Focus window by title")
    focus_parser.add_argument("target", help="Window title substring")

    # 12. ocr: inspect text on screen
    ocr_parser = subparsers.add_parser("ocr", help="Run local WinRT OCR")
    ocr_parser.add_argument("--target", "-t", help="Window title substring")
    ocr_parser.add_argument("--query", "-q", help="Text to search for")

    # 13. info: get screen and visible windows info
    info_parser = subparsers.add_parser("info", help="Get screen, foreground, and visible windows info")

    # 14. sandbox: Picture-in-Picture virtual desktop
    sb_parser = subparsers.add_parser("sandbox", help="Manage Picture-in-Picture (PiP) isolated desktop")
    sb_parser.add_argument("--launch", help="Launch command in isolated sandbox (e.g. 'notepad.exe')")
    sb_parser.add_argument("--capture", action="store_true", help="Capture PiP preview of sandbox windows")
    sb_parser.add_argument("--status", action="store_true", help="Report status and windows in sandbox")
    sb_parser.add_argument("--close", help="Close window in sandbox by title")
    sb_parser.add_argument("--destroy", action="store_true", help="Destroy sandbox desktop and kill processes")
    sb_parser.add_argument("--mode", choices=["interactive", "isolated_pip"], help="Switch desktop mode")

    # 15. explorer: File Explorer COM connector
    exp_parser = subparsers.add_parser("explorer", help="Direct File Explorer Shell COM interface")
    exp_parser.add_argument("--list", action="store_true", help="List open Explorer windows and paths")
    exp_parser.add_argument("--open", help="Open/navigate to folder path")
    exp_parser.add_argument("--selected", action="store_true", help="Get currently selected items")

    # 16. excel: Microsoft Excel COM connector
    excel_parser = subparsers.add_parser("excel", help="Direct Microsoft Excel COM interface")
    excel_parser.add_argument("--status", action="store_true", help="Check active Excel status")
    excel_parser.add_argument("--read", help="Read cell (e.g. 'A1')")
    excel_parser.add_argument("--write", nargs=2, metavar=("CELL", "VAL"), help="Write value/formula to cell (e.g. --write A1 1234)")
    excel_parser.add_argument("--range", help="Read 2D range starting at cell (e.g. 'A1')")
    excel_parser.add_argument("--rows", type=int, default=10, help="Row count for range")
    excel_parser.add_argument("--cols", type=int, default=10, help="Col count for range")
    excel_parser.add_argument("--sheet", help="Optional sheet name")

    # 17. record: High-speed screen recording
    rec_parser = subparsers.add_parser("record", help="High-speed continuous screen recorder")
    rec_parser.add_argument("--start", action="store_true", help="Start recording loop")
    rec_parser.add_argument("--stop", metavar="OUTPUT_PATH", help="Stop recording and compile video file")
    rec_parser.add_argument("--status", action="store_true", help="Check active recorder telemetry")
    rec_parser.add_argument("--fps", type=int, default=15, help="Capture frame rate (default 15)")
    rec_parser.add_argument("--target", help="Scope capture to target window title")
    rec_parser.add_argument("--format", choices=["webp", "gif"], default="webp", help="Video output format")
    rec_parser.add_argument("--max-dim", type=int, default=800, help="Downscale max resolution (default 800)")
    rec_parser.add_argument("--no-cursor", action="store_true", help="Disable physical cursor stamping")

    args = parser.parse_args()

    # Disable corner failsafe by default during CLI execution to avoid false-positives on parked cursor
    if not getattr(args, "allow_failsafe", False):
        default_governor.configure(failsafe=False)

    server = MCPServer()

    if args.command == "execute":
        content = " ".join(args.steps_json).strip() if isinstance(args.steps_json, list) else args.steps_json.strip()
        steps_data = parse_flexible_json(content)

        if isinstance(steps_data, dict) and "steps" in steps_data:
            steps = steps_data["steps"]
        elif isinstance(steps_data, list):
            steps = steps_data
        else:
            sys.stderr.write("Invalid steps format: must be list or object with 'steps' key.\n")
            sys.exit(1)

        res, is_err = server.execute_tool(
            "execute_autonomous_task",
            {"steps": steps, "verify": not args.no_verify}
        )
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "dag":
        content = " ".join(args.dag_json).strip() if isinstance(args.dag_json, list) else args.dag_json.strip()
        dag_data = parse_flexible_json(content)

        if isinstance(dag_data, dict) and "steps" in dag_data:
            steps = dag_data["steps"]
        elif isinstance(dag_data, list):
            steps = dag_data
        else:
            sys.stderr.write("Invalid DAG format: must be list or object with 'steps' key.\n")
            sys.exit(1)

        res, is_err = server.execute_tool(
            "execute_action_dag",
            {
                "steps": steps,
                "stop_on_error": not args.continue_on_error,
                "auto_verify": not args.no_verify,
            }
        )
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "click":
        clicks = 3 if args.triple else (2 if args.double else 1)
        btn = "right" if args.right else "left"
        call_args = {
            "query": args.query,
            "target": args.target,
            "mark_id": args.mark_id,
            "x": args.x,
            "y": args.y,
            "clicks": clicks,
            "button": btn,
        }
        res, is_err = server.execute_tool("click", call_args)
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "hover":
        res, is_err = server.execute_tool(
            "hover",
            {
                "query": args.query,
                "target": args.target,
                "x": args.x,
                "y": args.y,
                "duration": args.duration,
            }
        )
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "close":
        res, is_err = server.execute_tool("close_window", {"target": args.target, "force": args.force})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "window":
        if args.snap:
            res, is_err = server.execute_tool(
                "manage_window",
                {"target": args.target, "action": "snap", "position": args.snap}
            )
        elif args.state:
            res, is_err = server.execute_tool(
                "manage_window",
                {"target": args.target, "action": "state", "state": args.state}
            )
        elif args.bounds:
            res, is_err = server.execute_tool(
                "manage_window",
                {"target": args.target, "action": "move_resize", "bounds": args.bounds}
            )
        else:
            sys.stderr.write("Please specify --snap, --state, or --bounds for window command.\n")
            sys.exit(1)
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "media":
        res, is_err = server.execute_tool(
            "control_media",
            {"action": args.action, "steps": args.steps}
        )
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "clipboard":
        if args.get:
            res, is_err = server.execute_tool("clipboard", {"action": "get"})
        elif args.set is not None:
            res, is_err = server.execute_tool("clipboard", {"action": "set", "text": args.set})
        elif args.paste is not None:
            res, is_err = server.execute_tool("clipboard", {"action": "paste", "text": args.paste, "restore": args.restore})
        else:
            sys.stderr.write("Please specify --get, --set, or --paste for clipboard command.\n")
            sys.exit(1)
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "launch":
        res, is_err = server.execute_tool("launch_app", {"name": args.app, "args": args.args})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "type":
        res, is_err = server.execute_tool("type_text", {"text": args.text})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "hotkey":
        res, is_err = server.execute_tool("hotkey", {"keys": args.keys})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "focus":
        res, is_err = server.execute_tool("focus_window", {"target": args.target})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "ocr":
        res, is_err = server.execute_tool(
            "ocr_screen",
            {"target": args.target, "query": args.query}
        )
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "info":
        res, is_err = server.execute_tool("get_screen_info", {})
        print(res[0]["text"])
        sys.exit(1 if is_err else 0)

    elif args.command == "sandbox":
        if args.mode:
            res, is_err = server.execute_tool("configure_safety", {"desktop_mode": args.mode})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.launch:
            res, is_err = server.execute_tool("sandbox_launch", {"command": args.launch})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.capture:
            res, is_err = server.execute_tool("sandbox_capture", {})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.status:
            res, is_err = server.execute_tool("sandbox_manage", {"action": "status"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.close:
            res, is_err = server.execute_tool("sandbox_manage", {"action": "close_window", "target": args.close})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.destroy:
            res, is_err = server.execute_tool("sandbox_manage", {"action": "destroy"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        else:
            sys.stderr.write("Please specify --status, --launch, --capture, --close, --destroy, or --mode.\n")
            sys.exit(1)

    elif args.command == "explorer":
        if args.list:
            res, is_err = server.execute_tool("com_explorer", {"action": "list"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.open:
            res, is_err = server.execute_tool("com_explorer", {"action": "open", "path": args.open})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.selected:
            res, is_err = server.execute_tool("com_explorer", {"action": "get_selected"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        else:
            sys.stderr.write("Please specify --list, --open <path>, or --selected for explorer.\n")
            sys.exit(1)

    elif args.command == "excel":
        if args.status:
            res, is_err = server.execute_tool("com_excel", {"action": "status"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.read:
            res, is_err = server.execute_tool("com_excel", {"action": "read_cell", "cell": args.read, "sheet": args.sheet})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.write:
            res, is_err = server.execute_tool("com_excel", {"action": "write_cell", "cell": args.write[0], "value": args.write[1], "sheet": args.sheet})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.range:
            res, is_err = server.execute_tool("com_excel", {"action": "read_range", "cell": args.range, "rows": args.rows, "cols": args.cols, "sheet": args.sheet})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        else:
            sys.stderr.write("Please specify --status, --read <cell>, --write <cell> <val>, or --range <cell>.\n")
            sys.exit(1)

    elif args.command == "record":
        if args.start:
            res, is_err = server.execute_tool(
                "record_screen",
                {
                    "action": "start",
                    "fps": args.fps,
                    "target": args.target,
                    "max_dim": args.max_dim,
                    "include_cursor": not args.no_cursor,
                }
            )
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.stop:
            res, is_err = server.execute_tool(
                "record_screen",
                {
                    "action": "stop",
                    "output_path": args.stop,
                    "format": args.format,
                }
            )
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        elif args.status:
            res, is_err = server.execute_tool("record_screen", {"action": "status"})
            print(res[0]["text"])
            sys.exit(1 if is_err else 0)
        else:
            sys.stderr.write("Please specify --start, --stop <path>, or --status for record.\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
