"""
Speculative Action DAG Engine & Closed-Loop Servoing (AIM-VR 3.0).
Compiles multi-step action graphs, resolves dependencies via topological sorting,
executes micro-servoing verification between steps (<30ms), and provides adaptive
reflection and error recovery without round-trip latency.
"""

import time
import re
import json
from typing import Dict, Any, List, Optional, Tuple, Union, Callable
from PIL import Image

from control.safety import default_governor, ensure_interactive_desktop, FailsafeException, UserContentionException
from control.visual_servoing import default_servoing, VisualServoing
from control.mouse_engine import default_mouse
from control.keyboard_engine import default_keyboard
from control.clipboard import default_clipboard
from control.window_manager import default_window_manager
from control.media_control import default_media_controller
from control.app_launcher import launch_application
from control.com_connectors import default_com_manager
from control.virtual_desktop import default_virtual_desktop


class DAGCycleException(Exception):
    """Raised when an action dependency cycle is detected."""
    pass


class DAGExecutionError(Exception):
    """Raised when an unrecoverable DAG step failure occurs."""
    def __init__(self, step_id: str, action: str, message: str, trace: List[Dict[str, Any]], snapshot: Dict[str, Any]):
        super().__init__(f"DAG Step '{step_id}' ({action}) failed: {message}")
        self.step_id = step_id
        self.action = action
        self.trace = trace
        self.snapshot = snapshot


def _lookup_path(obj: Any, path: str) -> Any:
    """Helper to look up nested dotted path in a dict or object with list unwrapping and JSON parsing."""
    tokens = path.split(".")
    curr = obj
    for tok in tokens:
        if curr is None:
            return None

        # If curr is a string that looks like serialized JSON, parse it on-the-fly
        if isinstance(curr, str):
            curr_str = curr.strip()
            if (curr_str.startswith("{") and curr_str.endswith("}")) or (curr_str.startswith("[") and curr_str.endswith("]")):
                try:
                    curr = json.loads(curr_str)
                except Exception:
                    pass

        # If curr is a list, support index access or auto-unwrap single MCP text block
        if isinstance(curr, list):
            if tok.isdigit():
                idx = int(tok)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            elif len(curr) == 1 and isinstance(curr[0], dict) and "text" in curr[0]:
                text_val = curr[0]["text"]
                try:
                    curr = json.loads(text_val)
                except Exception:
                    curr = text_val

                # Continue resolving 'tok' on the unwrapped object
                if isinstance(curr, dict):
                    curr = curr.get(tok)
                elif hasattr(curr, tok):
                    curr = getattr(curr, tok)
                else:
                    return None
            else:
                return None
        elif isinstance(curr, dict):
            curr = curr.get(tok)
        elif hasattr(curr, tok):
            curr = getattr(curr, tok)
        else:
            return None

    # After path traversal, if the leaf value is an MCP text block or JSON string, unwrap it
    if isinstance(curr, list) and len(curr) == 1 and isinstance(curr[0], dict) and "text" in curr[0]:
        text_val = curr[0]["text"]
        try:
            return json.loads(text_val)
        except Exception:
            return text_val

    return curr


def resolve_templates(value: Any, context: Dict[str, Any]) -> Any:
    """
    Interpolates {{steps.step_id.key}} or {{variable}} syntax inside parameters.
    """
    if isinstance(value, str):
        pattern = r"\{\{\s*([\w\.\_]+)\s*\}\}"
        matches = re.findall(pattern, value)
        if not matches:
            return value
        full_match = re.fullmatch(r"\{\{\s*([\w\.\_]+)\s*\}\}", value.strip())
        if full_match:
            resolved = _lookup_path(context, full_match.group(1))
            return resolved if resolved is not None else value
        result_str = value
        for m in matches:
            resolved = _lookup_path(context, m)
            sub_pattern = r"\{\{\s*" + re.escape(m) + r"\s*\}\}"
            repl_val = str(resolved) if resolved is not None else ""
            result_str = re.sub(sub_pattern, lambda _, r=repl_val: r, result_str)
        return result_str
    elif isinstance(value, dict):
        return {k: resolve_templates(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_templates(item, context) for item in value]
    return value


class DAGExecutor:
    """
    High-performance Speculative Action DAG execution engine.
    Executes compound action pipelines with topological ordering,
    variable passing between steps, sub-30ms closed-loop micro-servoing,
    and adaptive reflection snapshots upon failure.
    """

    def __init__(
        self,
        servoing: Optional[VisualServoing] = None,
        tool_dispatcher: Optional[Callable[[str, Dict[str, Any]], Tuple[Any, bool]]] = None,
        governor: Optional[Any] = None,
    ):
        self.servoing = servoing or default_servoing
        self.tool_dispatcher = tool_dispatcher
        self.governor = governor or default_governor

    @staticmethod
    def compile(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validates dependencies and produces a topologically sorted execution sequence.
        Raises DAGCycleException or ValueError if the graph is malformed.
        """
        if not steps:
            return []

        step_dict: Dict[str, Dict[str, Any]] = {}
        in_degree: Dict[str, int] = {}
        adj: Dict[str, List[str]] = {}

        for idx, s in enumerate(steps):
            s_id = str(s.get("id") or f"step_{idx + 1}")
            s_copy = dict(s)
            s_copy["id"] = s_id
            step_dict[s_id] = s_copy
            in_degree[s_id] = 0
            adj[s_id] = []

        for s_id, s in step_dict.items():
            deps = s.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            # Deduplicate dependencies to avoid in_degree corruption
            for dep in sorted(set(str(d) for d in deps)):
                dep_str = str(dep)
                if dep_str not in step_dict:
                    raise ValueError(f"Step '{s_id}' depends on undefined step '{dep_str}'")
                adj[dep_str].append(s_id)
                in_degree[s_id] += 1

        queue = [s_id for s_id, deg in in_degree.items() if deg == 0]
        ordered: List[Dict[str, Any]] = []

        while queue:
            u = queue.pop(0)
            ordered.append(step_dict[u])
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(ordered) != len(step_dict):
            raise DAGCycleException(f"Cyclic dependency detected among steps: {list(step_dict.keys())}")

        return ordered

    def capture_reflection_snapshot(self, failed_step_id: str, error_msg: str) -> Dict[str, Any]:
        """
        Captures an instantaneous diagnostic reflection snapshot of the Windows desktop
        when an action fails, identifying the foreground window and potential blocking modals.
        """
        from perception.screen_capture import get_foreground_window_info, list_visible_windows
        fg = get_foreground_window_info()
        visible = list_visible_windows()

        # Check for common blocking modals (UAC, alert dialogs, crash dialogs)
        modal_alert = None
        for w in visible[:10]:
            title_lower = (w.get("title") or "").lower()
            if any(k in title_lower for k in ["error", "warning", "confirm", "user account control", "prompt", "dialog"]):
                modal_alert = {
                    "hwnd": w.get("hwnd"),
                    "title": w.get("title"),
                    "pid": w.get("pid"),
                }
                break

        return {
            "timestamp": time.time(),
            "failed_step_id": failed_step_id,
            "error": error_msg,
            "foreground_window": fg,
            "modal_alert_detected": modal_alert,
            "visible_windows_count": len(visible),
            "recommendation": (
                f"Modal alert '{modal_alert['title']}' may be blocking execution."
                if modal_alert
                else f"Active window is '{fg.get('title') if fg else 'None'}'. Ensure required window is in foreground."
            ),
        }

    def execute_step(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
        auto_verify: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a single step with parameter interpolation, safety enforcement,
        and micro-servoing verification.
        """
        step_id = step["id"]
        action = step.get("action") or step.get("tool")
        if not action:
            raise ValueError(f"Step '{step_id}' has no action/tool specified.")

        raw_args = step.get("args") or step.get("params") or {}
        # Merge top-level action parameters if flat format was passed
        merged_args = dict(raw_args)
        for k, v in step.items():
            if k not in ["id", "action", "tool", "args", "params", "depends_on", "verify", "retries", "retry_delay_s", "timeout_s", "on_failure"]:
                merged_args.setdefault(k, v)

        # Interpolate variables from prior step outputs
        args = resolve_templates(merged_args, context)

        # Safety checks
        self.governor.check_failsafe()
        self.governor.check_and_handle_contention()

        verify_policy = step.get("verify", "auto" if auto_verify else "none")
        retries = int(step.get("retries", 0))
        retry_delay = float(step.get("retry_delay_s", 0.05))

        # Sample pre-state for verification if requested
        target_bbox = args.get("bbox")
        pre_state = None
        if verify_policy in ["visual", "auto"] and action in ["click", "double_click", "right_click", "press_key", "hotkey"]:
            try:
                pre_state = self.servoing.sample_state(bbox=tuple(target_bbox) if target_bbox else None)
            except Exception:
                pre_state = None

        t0 = time.time()
        last_error = None

        for attempt in range(retries + 1):
            try:
                native_actions = {"wait", "move", "paste_text", "double_click", "right_click", "triple_click"}
                # 1. Native action or missing tool_dispatcher
                if action in native_actions or not self.tool_dispatcher:
                    result_data = self._native_dispatch(action, args)
                else:
                    res, is_err = self.tool_dispatcher(action, args)
                    if is_err:
                        err_text = str(res)
                        # Fallback to native dispatch if tool is unknown to the external dispatcher
                        if "Unknown tool" in err_text:
                            try:
                                result_data = self._native_dispatch(action, args)
                            except Exception:
                                raise RuntimeError(f"Tool '{action}' returned error: {err_text}")
                        else:
                            raise RuntimeError(f"Tool '{action}' returned error: {err_text}")
                    else:
                        result_data = res

                # Automatically unwrap and parse MCP serialized JSON text blocks into structured data
                parsed_data = result_data
                if isinstance(result_data, list) and len(result_data) == 1 and isinstance(result_data[0], dict):
                    if result_data[0].get("type") == "text":
                        raw_text = result_data[0].get("text", "")
                        try:
                            parsed_data = json.loads(raw_text)
                        except Exception:
                            parsed_data = raw_text

                elapsed_ms = round((time.time() - t0) * 1000, 2)

                # Micro-servoing closed loop verification
                reaction = None
                verified = True
                if pre_state and verify_policy in ["visual", "auto"]:
                    ver_res = self.servoing.verify_reaction(pre_state, bbox=tuple(target_bbox) if target_bbox else None)
                    reaction = ver_res
                    verified = ver_res.get("verified", False)
                    # If verification failed and we have retries remaining, retry
                    if not verified and attempt < retries:
                        time.sleep(retry_delay)
                        continue

                return {
                    "status": "success",
                    "step_id": step_id,
                    "action": action,
                    "attempt": attempt + 1,
                    "latency_ms": elapsed_ms,
                    "result": parsed_data,
                    "raw_result": result_data,
                    "verified": verified,
                    "reaction": reaction,
                }

            except Exception as e:
                last_error = e
                if attempt < retries:
                    time.sleep(retry_delay)
                    continue

        raise last_error or RuntimeError(f"Step '{step_id}' failed.")

    def _native_dispatch(self, action: str, args: Dict[str, Any]) -> Any:
        """Native direct engine dispatch when tool_dispatcher is not provided."""
        ensure_interactive_desktop()
        from perception.screen_capture import find_window, focus_window

        if action in ["click", "double_click", "right_click", "triple_click"]:
            x = args.get("x")
            y = args.get("y")
            target = args.get("target")
            if target:
                w = find_window(target)
                if w:
                    focus_window(w["hwnd"])
            clicks = 1
            if action == "double_click":
                clicks = 2
            elif action == "triple_click":
                clicks = 3
            btn = "right" if action == "right_click" else args.get("button", "left")
            cx, cy = default_mouse.click(x=x, y=y, button=btn, clicks=clicks)
            return {"clicked_x": cx, "clicked_y": cy, "button": btn, "clicks": clicks}

        elif action in ["move", "move_cursor"]:
            cx, cy = default_mouse.move(int(args["x"]), int(args["y"]))
            return {"x": cx, "y": cy}

        elif action == "hover":
            cx, cy = default_mouse.hover(int(args["x"]), int(args["y"]), duration=float(args.get("duration", 0.2)))
            return {"hover_x": cx, "hover_y": cy}

        elif action == "mouse_down":
            default_mouse.mouse_down(args.get("button", "left"))
            return {"mouse_down": args.get("button", "left")}

        elif action == "mouse_up":
            default_mouse.mouse_up(args.get("button", "left"))
            return {"mouse_up": args.get("button", "left")}

        elif action == "drag":
            default_mouse.drag(int(args["start_x"]), int(args["start_y"]), int(args["end_x"]), int(args["end_y"]), float(args.get("duration", 0.3)))
            return {"dragged_to": [int(args["end_x"]), int(args["end_y"])]}

        elif action == "scroll":
            default_mouse.scroll(int(args.get("delta_y", 0)), int(args.get("delta_x", 0)))
            return {"scroll": [args.get("delta_x", 0), args.get("delta_y", 0)]}

        elif action == "type_text":
            text = args.get("text", "")
            interval = float(args.get("interval", 0.01))
            default_keyboard.type_text(text, interval=interval)
            return {"typed_chars": len(text)}

        elif action == "paste_text":
            text = args.get("text", "")
            rst = bool(args.get("restore", False))
            ok = default_clipboard.paste(text, restore_clipboard=rst)
            return {"pasted_chars": len(text), "success": ok}

        elif action == "press_key":
            key = args.get("key", "enter")
            default_keyboard.press_key(key)
            return {"pressed_key": key}

        elif action == "hotkey":
            keys = args.get("keys", [])
            default_keyboard.hotkey(*keys)
            return {"hotkey": keys}

        elif action == "wait":
            sec = float(args.get("seconds", args.get("duration", 0.25)))
            time.sleep(sec)
            return {"waited_s": sec}

        elif action == "focus_window":
            target = args.get("target")
            win = find_window(target)
            if not win:
                raise ValueError(f"Window matching '{target}' not found.")
            ok = focus_window(win["hwnd"])
            return {"hwnd": win["hwnd"], "title": win["title"], "success": ok}

        elif action == "launch_app":
            app = args.get("name") or args.get("command")
            res = launch_application(app, args.get("args"))
            if res.get("status") == "error":
                raise RuntimeError(res.get("message", "App launch failed."))
            return res

        elif action == "com_explorer":
            act = args.get("action", "list")
            if act == "list":
                return default_com_manager.explorer.list_open_explorers()
            elif act == "open":
                return default_com_manager.explorer.open_folder(args["path"])
            elif act == "get_selected":
                return default_com_manager.explorer.get_selected_items()
            raise ValueError(f"Unknown com_explorer action: {act}")

        elif action == "com_excel":
            act = args.get("action", "status")
            sheet = args.get("sheet")
            if act == "status":
                return default_com_manager.excel.get_status()
            elif act == "read_cell":
                return default_com_manager.excel.read_cell(args["cell"], sheet_name=sheet)
            elif act == "write_cell":
                return default_com_manager.excel.write_cell(args["cell"], args["value"], sheet_name=sheet)
            elif act == "read_range":
                cell = args.get("cell", "A1")
                rows = int(args.get("rows", 10))
                cols = int(args.get("cols", 10))
                return default_com_manager.excel.read_range(start_cell=cell, rows=rows, cols=cols, sheet_name=sheet)
            raise ValueError(f"Unknown com_excel action: {act}")

        elif action == "com_browser_cdp":
            act = args.get("action", "status")
            if act == "status":
                return {"cdp_available": default_com_manager.cdp.is_available()}
            elif act == "list_tabs":
                return default_com_manager.cdp.list_tabs()
            elif act == "navigate":
                return default_com_manager.cdp.navigate_tab(args["tab_id"], args["url"])
            raise ValueError(f"Unknown com_browser_cdp action: {act}")

        elif action == "sandbox_launch":
            cmd = args.get("command") or args.get("name")
            return default_virtual_desktop.launch_in_sandbox(cmd, cwd=args.get("cwd"))

        elif action == "sandbox_capture":
            scale_val = float(args.get("scale", 0.5)) if args.get("scale") is not None else None
            return default_virtual_desktop.capture_pip_composite(scale=scale_val)

        elif action == "sandbox_manage":
            act = args.get("action", "status")
            if act == "status":
                return {
                    "desktop": default_virtual_desktop.sandbox_name,
                    "windows": default_virtual_desktop.list_sandbox_windows(),
                }
            elif act == "destroy":
                return default_virtual_desktop.destroy_sandbox()
            raise ValueError(f"Unknown sandbox_manage action: {act}")

        else:
            raise ValueError(f"Unknown action: '{action}'")

    def run_dag(
        self,
        steps: List[Dict[str, Any]],
        stop_on_error: bool = True,
        auto_verify: bool = True,
    ) -> Dict[str, Any]:
        """
        Compiles and executes the Action DAG end-to-end.
        Accumulates execution trace, interpolates dynamic outputs,
        and provides adaptive reflection upon failure.
        """
        start_total = time.time()
        compiled_steps = self.compile(steps)

        context: Dict[str, Any] = {
            "steps": {},
        }
        trace: List[Dict[str, Any]] = []

        for idx, step in enumerate(compiled_steps, 1):
            step_id = step["id"]
            step_on_failure = step.get("on_failure", "abort" if stop_on_error else "continue")

            try:
                record = self.execute_step(step, context, auto_verify=auto_verify)
                trace.append(record)
                context["steps"][step_id] = record
                context[step_id] = record
            except Exception as exc:
                err_msg = str(exc)
                failed_record = {
                    "status": "failed",
                    "step_id": step_id,
                    "action": step.get("action") or step.get("tool"),
                    "error": err_msg,
                    "latency_ms": round((time.time() - start_total) * 1000, 2),
                }
                trace.append(failed_record)
                context["steps"][step_id] = failed_record
                context[step_id] = failed_record

                if step_on_failure == "abort":
                    # Capture adaptive diagnostic reflection
                    reflection = self.capture_reflection_snapshot(step_id, err_msg)
                    return {
                        "status": "partial_failure",
                        "total_steps": len(compiled_steps),
                        "completed_steps": idx - 1,
                        "failed_step_id": step_id,
                        "error": err_msg,
                        "total_time_ms": round((time.time() - start_total) * 1000, 2),
                        "reflection": reflection,
                        "trace": trace,
                    }

        return {
            "status": "success",
            "total_steps": len(compiled_steps),
            "completed_steps": len(compiled_steps),
            "total_time_ms": round((time.time() - start_total) * 1000, 2),
            "trace": trace,
        }


default_dag_executor = DAGExecutor()