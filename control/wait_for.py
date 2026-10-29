"""
High-Speed In-Engine UI Condition Waiter (AIM-VR 3.0 Control Subsystem).
Polls UI state, window existence, text spotting, and element readiness locally
inside the engine to eliminate slow multi-turn chat loops.
"""

import time
from typing import Dict, Any, Optional
from perception.screen_capture import find_window, get_foreground_window_info, capture_screen, capture_window
from perception.element_locator import default_locator
from perception.winrt_ocr import default_ocr


def wait_for_condition(
    condition: str,
    target: Optional[str] = None,
    query: Optional[str] = None,
    timeout: float = 10.0,
    interval: float = 0.25,
) -> Dict[str, Any]:
    """
    Waits locally until a UI condition is satisfied or timeout expires.

    Supported conditions:
      - 'text_exists': Target text query appears on screen or within target window.
      - 'window_exists': A window matching target title substring exists.
      - 'window_active': A window matching target title substring is in the active foreground.
      - 'element_exists': A semantic element matching query is located via UIA or OCR.

    Args:
        condition: Condition name.
        target: Optional window title substring.
        query: Text or element label to search for.
        timeout: Maximum seconds to wait (default 10.0s).
        interval: Seconds between evaluation attempts (default 0.25s).

    Returns:
        {"status": "satisfied" | "timeout", "elapsed_s": float, "attempts": int, "details": str}
    """
    cond = condition.lower().strip()
    started_at = time.monotonic()
    deadline = started_at + max(0.1, timeout)
    attempts = 0
    target_q = (query or "").strip()
    safe_interval = max(0.05, interval)

    while time.monotonic() < deadline:
        attempts += 1

        if cond == "window_exists":
            if not target:
                return {"status": "error", "message": "Condition 'window_exists' requires 'target' parameter."}
            win = find_window(target)
            if win:
                return {
                    "status": "satisfied",
                    "condition": cond,
                    "elapsed_s": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "window": win
                }

        elif cond == "window_active":
            if not target:
                return {"status": "error", "message": "Condition 'window_active' requires 'target' parameter."}
            fg = get_foreground_window_info()
            if fg and target.lower() in (fg.get("title") or "").lower():
                return {
                    "status": "satisfied",
                    "condition": cond,
                    "elapsed_s": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "window": fg
                }

        elif cond == "text_exists":
            if not target_q:
                return {"status": "error", "message": "Condition 'text_exists' requires 'query' parameter."}
            
            img = None
            if target:
                win = find_window(target)
                if win:
                    img = capture_window(win["hwnd"])
                else:
                    time.sleep(safe_interval)
                    continue
            else:
                img = capture_screen()

            if img is not None:
                match = default_ocr.find_text(img, target_q)
                if match:
                    return {
                        "status": "satisfied",
                        "condition": cond,
                        "elapsed_s": round(time.monotonic() - started_at, 3),
                        "attempts": attempts,
                        "match": match
                    }

        elif cond == "element_exists":
            if not target_q:
                return {"status": "error", "message": "Condition 'element_exists' requires 'query' parameter."}
            elem = default_locator.locate(query=target_q, target_window=target)
            if elem:
                return {
                    "status": "satisfied",
                    "condition": cond,
                    "elapsed_s": round(time.monotonic() - started_at, 3),
                    "attempts": attempts,
                    "element": elem
                }
        else:
            return {
                "status": "error",
                "message": f"Unknown condition '{condition}'. Supported: 'text_exists', 'window_exists', 'window_active', 'element_exists'."
            }

        time.sleep(safe_interval)

    return {
        "status": "timeout",
        "condition": cond,
        "elapsed_s": round(time.monotonic() - started_at, 3),
        "attempts": attempts,
        "details": f"Condition '{cond}' not satisfied within {timeout}s timeout."
    }
