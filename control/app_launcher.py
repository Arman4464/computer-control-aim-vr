"""
Application launcher with intelligent binary resolution, ShellExecute,
and robust window readiness polling.
Resolves applications via standard paths, Windows App Paths registry, system PATH,
and opens files/URLs via default system associations.
"""

import os
import sys
import time
import shutil
import subprocess
import winreg
import ctypes
from ctypes import wintypes
from typing import Optional, Dict, Any, List

# Ensure parent directory is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

shell32 = ctypes.windll.shell32
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_int
]
shell32.ShellExecuteW.restype = wintypes.HINSTANCE

# Track spawned background processes to prevent garbage-collection ResourceWarnings
_TRACKED_PROCESSES: List[subprocess.Popen] = []


def _prune_tracked_processes():
    """Prunes terminated Popen objects from _TRACKED_PROCESSES to prevent handle leaks."""
    global _TRACKED_PROCESSES
    _TRACKED_PROCESSES = [p for p in _TRACKED_PROCESSES if p.poll() is None]

KNOWN_APPS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "google chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "brave browser": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe", "cmd.exe"],
    "vscode": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
}


def resolve_binary_path(name: str) -> Optional[str]:
    """Resolves an application name to an absolute binary path or executable command."""
    name_clean = name.strip().lower()

    # 1. Check known explicit paths
    if name_clean in KNOWN_APPS:
        for candidate in KNOWN_APPS[name_clean]:
            if os.path.isabs(candidate) and os.path.exists(candidate):
                return candidate
            which_res = shutil.which(candidate)
            if which_res:
                return which_res

    # 2. Check if name is already an existing path
    if os.path.isfile(name):
        return os.path.abspath(name)

    # 3. Check Windows Registry App Paths
    app_key_name = name if name.endswith(".exe") else f"{name}.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_key_name}"
        try:
            with winreg.OpenKey(root, key_path) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.isfile(val):
                    return val
        except OSError:
            pass

    # 4. Check system PATH
    found = shutil.which(name) or shutil.which(app_key_name)
    if found:
        return found

    return None


def shell_execute(target: str, args: Optional[str] = None) -> Dict[str, Any]:
    """
    Opens a file, directory, or URL using the Windows default shell association.
    Equivalent to double-clicking in File Explorer or running 'start <target>'.
    """
    try:
        # SW_SHOWNORMAL = 1
        res = shell32.ShellExecuteW(None, "open", target, args, None, 1)
        res_val = int(res or 0)
        if res_val > 32:
            return {"status": "opened", "target": target, "args": args}
        else:
            return {"status": "error", "error_code": res_val, "target": target}
    except Exception as e:
        return {"status": "error", "message": str(e), "target": target}


def launch_application(name: str, args: Optional[str] = None, timeout: float = 3.5) -> Dict[str, Any]:
    """
    Launches an application and waits for its top-level window to appear.
    Does not block indefinitely. Returns window details upon activation.
    """
    # If name is a URL or file with extension not ending in .exe, use shell_execute
    if (
        name.startswith("http://")
        or name.startswith("https://")
        or name.startswith("file://")
        or (os.path.isfile(name) and not name.lower().endswith(".exe"))
    ):
        return shell_execute(name, args)

    binary = resolve_binary_path(name) or shutil.which(name) or shutil.which(f"{name}.exe")
    target_cmd = binary if binary else name

    cmd_list = [target_cmd]
    if args:
        import shlex
        # posix=False is mandatory on Windows to prevent stripping backslashes from paths
        cmd_list.extend(shlex.split(args, posix=False))

    try:
        proc = subprocess.Popen(
            cmd_list,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _prune_tracked_processes()
        _TRACKED_PROCESSES.append(proc)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to start process '{name}': {str(e)}",
            "binary": target_cmd,
        }

    # Normalize search term for title matching
    from perception.screen_capture import find_window, focus_window, list_visible_windows

    search_term = name.lower()
    if search_term == "explorer":
        search_term = "file explorer"
    elif search_term == "calc":
        search_term = "calculator"

    matched_win = None
    start_time = time.time()

    while time.time() - start_time < timeout:
        time.sleep(0.15)

        # 1. Check title matching first (most reliable across UWP and desktop apps)
        matched_win = find_window(search_term)
        if not matched_win and args:
            folder_hint = os.path.basename(args.replace("shell:", "").rstrip("\\/")).lower()
            if folder_hint:
                matched_win = find_window(folder_hint)
        if matched_win:
            break

        # 2. Check by process ID if available
        if proc.pid:
            for w in list_visible_windows():
                if w.get("pid") == proc.pid:
                    matched_win = w
                    break
        if matched_win:
            break

    if matched_win:
        focus_window(matched_win["hwnd"])
        return {
            "status": "launched",
            "name": name,
            "binary": target_cmd,
            "pid": proc.pid,
            "window": {
                "title": matched_win["title"],
                "hwnd": matched_win["hwnd"],
                "bounds": matched_win.get("bounds", [0, 0, 0, 0]),
            },
        }

    return {
        "status": "launched_background",
        "name": name,
        "binary": target_cmd,
        "pid": proc.pid,
        "note": f"Process started; top-level window did not register within {timeout}s or runs in background.",
    }
