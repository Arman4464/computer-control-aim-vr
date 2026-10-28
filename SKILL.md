---
name: computer-control
description: >-
  Direct OS-level desktop automation and computer control for Windows (AIM-VR 3.0).
  Use whenever the user asks to control the computer, interact with desktop applications
  (Notepad, File Explorer, Chrome, Brave, terminals, settings, or desktop software), inspect the screen,
  launch/close applications safely, snap windows, manage clipboard, control media playback, click UI elements,
  type/paste text, press keyboard shortcuts, or automate multi-step workflows.
---

# Windows Computer Control (AIM-VR 3.0)

Industrial-grade OS-level desktop automation guide for AI agents. Provides direct OS control, accessibility tree grounding, native sub-15ms WinRT OCR, Set-of-Marks visual badges, native Win32 clipboard text injection, window snapping and layout management, non-invasive system media control, safe targeted window lifecycle management, and closed-loop multi-step execution.

---

## 1. Cardinal Operating Invariants

> [!CAUTION]
> ### 1. NEVER SEND BLIND DESTRUCTIVE SHORTCUTS (Alt+F4 / Ctrl+W)
> **Never** execute blind `hotkey(["alt", "f4"])` or `hotkey(["ctrl", "w"])` to close an application. Global shortcuts strike whatever window happens to have foreground focus—potentially terminating the user's active browser, music stream (e.g. Brave / YouTube / Spotify), or unsaved code editor.
> **Mandatory Rule**: ALWAYS use `close_window(target="...")` or CLI `python cli.py close "<Title>"`. This sends targeted Win32 `WM_CLOSE` and `SC_CLOSE` messages directly to the target window's HWND without touching the foreground window or interfering with active user applications.

> [!IMPORTANT]
> ### 2. PREFER NATIVE CLIPBOARD FOR LONG TEXT / CODE (`clipboard` or `paste_text`)
> For typing code, paragraphs, multiline scripts, or URLs, **ALWAYS** use `clipboard(action="paste", text="...")` or `paste_text` step. Keystroke-by-keystroke simulation (`type_text`) is slower and vulnerable to layout shifts or dropped keys under system load. Native Win32 clipboard injection is instantaneous and 100% accurate.

> [!IMPORTANT]
> ### 3. VERIFY SCREEN STATE BEFORE ACTING ("Look Before You Touch")
> Call `get_screen_info` to inspect `visible_windows` (all open windows, titles, PIDs, bounds, monitor geometry) and `foreground_window` before initiating window transitions. Never assume an app is focused or running.

> [!TIP]
> ### 4. SINGLE-TURN MULTI-STEP PREFERENCE (`execute_autonomous_task`)
> For tasks requiring 2+ sequential actions (e.g. launch app, snap window, click search, paste query, press enter), **ALWAYS** dispatch them in a single call via `execute_autonomous_task` or CLI `python cli.py execute '<JSON>'`. This executes locally in an in-memory closed loop (sub-30ms reaction checks) rather than consuming slow multi-turn chat round-trips.

> [!IMPORTANT]
> ### 5. WORKSPACE & WINDOW STATE RESTORATION ("Leave No Trace")
> **Always restore the user's desktop to its exact prior state once a task completes:**
> - **Minimized Apps**: If an application was minimized and you unminimized/restored it to extract information or perform an action, **minimize it back** immediately after achieving your goal:
>   `manage_window(target="...", action="state", state="minimize")`
> - **Spawned Apps**: If you opened a new application solely to accomplish a task (e.g., File Explorer, Notepad, Calculator), **close it cleanly** when finished:
>   `close_window(target="...")`
> - **Focus Restoration**: Always return active foreground focus to the user's original working window (e.g., Antigravity IDE / terminal) so their typing and cursor workflow is completely undisturbed.

---

## 2. Tool Selection Matrix

| User Intent / Scenario | Recommended Tool | Interface & Behavior |
|---|---|---|
| **Speculative Action DAG execution** | `execute_action_dag(steps=[...])` | High-performance DAG pipeline with topological sorting, variable interpolation (`{{steps.id.result}}`), and sub-30ms closed-loop micro-servoing. |
| **Multi-step workflow** (2+ actions) | `execute_autonomous_task(steps=[...])` | Autonomous In-Memory Vision Runner. Executes entire sequence locally with closed-loop verification. |
| **Snap / arrange / resize window** | `manage_window(target="...", action="snap", position="left")` | Snaps window to monitor work area (left, right, top, bottom, quadrants, center) or sets exact pixel bounds. |
| **Instant paste long text or code** | `clipboard(action="paste", text="...")` | Instant Win32 clipboard text injection followed by atomic `Ctrl+V`. Immune to layout corruption. |
| **Read clipboard contents** | `clipboard(action="get")` | Retrieves current text on Windows clipboard. |
| **Control audio / media playback** | `control_media(action="volume_up"|"play_pause"|...)` | Adjusts volume or controls media tracks without switching active windows. |
| **Safely close an app/window** | `close_window(target="Window Title")` | Sends Win32 `WM_CLOSE` directly to target HWND. 100% immune to closing foreground music/browser. |
| **Launch an app or file/URL** | `launch_app(name="chrome")` | Resolves standard paths, App Paths registry, or system PATH; waits for window to appear. |
| **Non-disruptive background app launch** | `sandbox_launch(command="notepad.exe")` | Spawns application on isolated sandbox desktop (`AIMVR_Sandbox`). Zero cursor hijacking. |
| **Capture PiP sandbox preview** | `sandbox_capture()` or `screenshot(mode="pip")` | Renders Picture-in-Picture composite preview of all windows open in background sandbox. |
| **Manage sandbox desktop** | `sandbox_manage(action="status"|"close_window"|"destroy")` | Queries open windows, targets closing, or terminates sandbox session cleanly. |
| **Switch automation mode** | `configure_safety(desktop_mode="isolated_pip"|"interactive")` | Toggles between background non-disruptive PiP sandbox and foreground interactive execution. |
| **Navigate or list File Explorer** | `com_explorer(action="list"|"open"|"get_selected")` | Direct Shell.Application COM interface. Navigates or lists open folders and selected items in 5ms. |
| **Read or write Excel directly** | `com_excel(action="read_cell"|"write_cell"|"read_range")` | Direct Excel COM object manipulation. Reads/writes cells and formulas instantaneously without clicking. |
| **Inspect or navigate browser tabs** | `com_browser_cdp(action="list_tabs"|"navigate")` | Direct Chrome/Edge CDP protocol bridge. Inspects open tabs and URLs without vision tokens. |
| **Inspect screen, monitors & windows** | `get_screen_info()` | Returns virtual screen bounds, monitor work areas, foreground window, and full `visible_windows` list. |
| **Click named button / menu / tab** | `click(query="Save", target="App")` | Resolves physical center via UIA accessibility tree with WinRT OCR fallback in <0.2s. |
| **Hover to trigger flyout / tooltip** | `hover(query="Menu", duration=0.25)` | Moves cursor to target and hovers to activate hover-only UI dropdowns and tooltips. |
| **Spot canvas / web text** | `ocr_screen(query="Export", target="App")` | Native WinRT OCR finds text bounding boxes in ~15ms when accessibility trees are absent. |
| **Click unlabeled icons / canvas** | `screenshot(som=True, cluster_zoom=True)` ➔ `click(mark_id=N)` | OmniParser V2 Set-of-Marks with NMS, color-coded badges (Yellow=UIA, Green=OCR, Cyan=Icons), and auto-zoom for dense toolbars. |
| **Switch / restore window** | `focus_window(target="App Title")` | Restores minimized windows (`SW_RESTORE`) and brings target window to verified foreground. |
| **Short input / form typing** | `type_text(text="...")` | Hardware-independent `KEYEVENTF_UNICODE` typing for short inputs. |
| **System shortcuts** | `hotkey(keys=["ctrl", "s"])` | Hardware scan-code simulation for application hotkeys. |

---

## 3. High-Yield Execution Recipes

### Recipe A: Multi-Step Autonomous Task (`execute_autonomous_task`)
Use for complete user tasks. Executes locally with zero inter-turn latency.

```json
{
  "name": "execute_autonomous_task",
  "arguments": {
    "steps": [
      {"action": "launch_app", "name": "notepad"},
      {"action": "wait", "seconds": 0.3},
      {"action": "manage_window", "target": "Notepad", "sub_action": "snap", "position": "left"},
      {"action": "paste_text", "text": "AIM-VR 3.0 In-Memory Automation Ready!\n"},
      {"action": "hotkey", "keys": ["ctrl", "s"]}
    ],
    "verify": true
  }
}
```

**Supported step actions**: `click`, `double_click`, `right_click`, `triple_click`, `hover`, `move`, `type_text`, `paste_text`, `press_key`, `hotkey`, `wait`, `focus_window`, `close_window`, `launch_app`, `manage_window`, `control_media`, `invoke_element`, `set_value`.

---

### Recipe B: Window Management & Layout Snapping (`manage_window`)
Organize windows cleanly on any monitor without triggering Windows Snap popup grids.

```json
// Snap Notepad to left half of screen:
{"name": "manage_window", "arguments": {"target": "Notepad", "action": "snap", "position": "left"}}

// Snap Browser to right half of screen:
{"name": "manage_window", "arguments": {"target": "Brave", "action": "snap", "position": "right"}}

// Maximize, minimize, or restore:
{"name": "manage_window", "arguments": {"target": "Notepad", "action": "state", "state": "maximize"}}
```

---

### Recipe C: Media & Volume Control (`control_media`)
Adjust volume or control music playback seamlessly in the background.

```json
// Volume up 3 steps:
{"name": "control_media", "arguments": {"action": "volume_up", "steps": 3}}

// Toggle play/pause for active music (Spotify / YouTube):
{"name": "control_media", "arguments": {"action": "play_pause"}}

// Toggle mute:
{"name": "control_media", "arguments": {"action": "toggle_mute"}}
```

---

### Recipe D: Fast Clipboard Injection (`clipboard`)
Inject multiline code blocks, Markdown, or JSON instantaneously.

```json
// 1. Instant paste into active window:
{"name": "clipboard", "arguments": {"action": "paste", "text": "const greeting = 'Hello World';\nconsole.log(greeting);"}}

// 2. Read clipboard contents:
{"name": "clipboard", "arguments": {"action": "get"}}
```

---

### Recipe E: Speculative Action DAG Runner (`execute_action_dag`)
Compile complex compound pipelines with dependencies, variable passing, and automatic reflection:

```json
{
  "name": "execute_action_dag",
  "arguments": {
    "steps": [
      {"id": "step_launch", "action": "launch_app", "args": {"name": "notepad"}},
      {"id": "step_focus", "action": "focus_window", "args": {"target": "Notepad"}, "depends_on": ["step_launch"]},
      {"id": "step_type", "action": "paste_text", "args": {"text": "Speculative DAG pipeline running!"}, "depends_on": ["step_focus"]},
      {"id": "step_save", "action": "hotkey", "args": {"keys": ["ctrl", "s"]}, "depends_on": ["step_type"]}
    ],
    "auto_verify": true
  }
}
```

---

### Recipe F: CLI Unified Runner (`cli.py`)
Direct testing and shell execution:

```powershell
cd C:\Users\rango\OneDrive\Desktop\ComputerControl_Skill_Package

# Run a DAG plan:
python cli.py dag dag_plan.json

# Inspect screen, monitors, and open windows:
python cli.py info

# Snap a window to the left half:
python cli.py window "Notepad" --snap left

# Instant paste text:
python cli.py clipboard --paste "Hello from CLI"

# Control volume or media:
python cli.py media volume_up --steps 2
python cli.py media play_pause

# Safely close an application:
python cli.py close "Notepad"
```

---

## 4. Troubleshooting & Deterministic Recovery

| Symptom / Error | Root Cause | Deterministic Fix |
|---|---|---|
| Accidental window close / Music terminated | Blind `Alt+F4` was sent while another window was active. | **NEVER send Alt+F4**. Always use `close_window(target="...")` which uses targeted `WM_CLOSE` to the specific HWND. |
| Dropped keys or slow text insertion | Simulating keystrokes for large text. | Use `clipboard(action="paste", text="...")` or `paste_text` step. |
| `Target window matching 'X' not found` | App not running, minimized under different name, or ghost handle. | 1. Check `get_screen_info()` to see all running titles.<br>2. Launch via `launch_app(name="X")`. |
| `Element matching 'X' not found` | Element offscreen or rendered in custom GPU canvas. | 1. Scope search via `ocr_screen(query="X")`.<br>2. Scroll into view via `scroll(clicks=-3)`.<br>3. Overlay visual badges via `screenshot(som=true)`. |
| Failsafe triggered at (0, 0) | Physical mouse was parked in corner. | Move cursor: `move_cursor(x=500, y=500)` or `configure_safety(failsafe=false)`. |
| User mouse contention yield | User touched the mouse during automation. | The engine yields automatically for 0.5s. Do not fight user input; resume when idle. |
