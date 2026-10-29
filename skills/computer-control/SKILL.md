---
name: computer-control
description: >-
  Direct OS-level desktop automation and computer control for Windows (AIM-VR 3.0).
  Use whenever the user asks to control the computer, interact with desktop applications
  (Notepad, File Explorer, Chrome, Brave, terminals, settings, or desktop software), inspect the screen,
  launch/close applications safely, snap windows, manage clipboard, control media playback, click UI elements,
  type/paste text, press keyboard shortcuts, or automate multi-step workflows.
---

# Windows Computer Control & Interaction Engine (AIM-VR 3.0)

Industrial-grade, multi-tier desktop automation and perception subsystem for Windows. Designed specifically for AI agents to achieve **sub-30ms execution, zero hallucination, and massive token savings** over traditional screenshot-and-think computer-use loops.

---

## 1. The 3-Layer Vision & Targeting Hierarchy

```mermaid
flowchart TD
    Task["Incoming User Action / UI Goal"] --> Decision{"What type of element is it?"}
    
    Decision -->|"Native Windows Controls (WinUI/WPF/Win32)"| L1["Layer 1: Semantic UIA\n• inspect_ui / find_element\n• 0 visual tokens | <5ms latency\n• Instant zero-guesswork click"]
    Decision -->|"Webpages, Chrome, Electron, Canvas, Forms"| L2["Layer 2: Local WinRT OCR\n• click(text='...') / find_element\n• 0 visual tokens | 12ms latency\n• Dynamic visual text-grounding"]
    Decision -->|"Unlabeled Icons, Sliders, Games, Graphics"| L3["Layer 3: OmniParser SOM\n• screenshot(som=True)\n• Numbered badges (NMS-filtered)\n• click(mark_id=N)"]

    L1 --> Exec["Layer 3 Execution:\nexecute_autonomous_task / execute_action_dag\n(Single-turn local in-memory closed loop in <2s)"]
    L2 --> Exec
    L3 --> Exec
```

- **Layer 1: Semantic UI Automation (UIA)**:
  - *Best for*: Native Windows desktop apps (Notepad, File Explorer, Calculator, Settings, WinUI dialogs).
  - *Behavior*: Reads the OS accessibility tree directly. Returns zero-token, exact bounding boxes in <5ms.
  - *Tools*: `inspect_ui`, `find_element(role="Button")`.

- **Layer 2: High-Speed Local WinRT OCR (Text Grounding)**:
  - *Best for*: Web browsers (Chrome, Edge, Brave), Electron apps (VSCode, Slack, Discord), web forms, tables, modals.
  - *Behavior*: Executes 100% locally via Windows.Media.Ocr. Automatically resolves text labels (`"Title"`, `"Post"`, `"Discussion"`, `"Apply"`, `"Save"`) to live physical screen coordinates in **12 milliseconds**. **Zero visual tokens burned in the LLM**.
  - *Tools*: `click(text="Submit")`, `find_element(query="Apply")`, `ocr_screen(query="Export")`.

- **Layer 3: OmniParser Set-of-Marks (SOM)**:
  - *Best for*: Unlabeled graphical icons, video players, canvas sliders, games, and pure graphic controls where no text or UIA metadata exists.
  - *Behavior*: Overlays high-contrast, NMS-filtered numbered badges (Yellow=UIA, Green=OCR, Cyan=Icons) for integer clicking (`click(mark_id=5)`).
  - *Rule*: **STRICTLY a fallback**. Never use Layer 3 when Layer 1 or Layer 2 text is present.

---

## 2. Cardinal Operating Invariants (What to Do and What NOT to Do)

> [!CAUTION]
> ### 1. THE TURN-BY-TURN "SCREENSHOT & GUESS" ANTI-PATTERN (STRICTLY FORBIDDEN)
> **Never fall into the slow, token-burning loop of taking a full screenshot after every single micro-action.**
> - *The Anti-Pattern*: `take_screenshot -> inspect -> click(x, y) -> take_screenshot -> click(x, y)`. This burns 25,000+ tokens, introduces 10-second chat latency per step, and frequently misses when dynamic layouts reflow.
> - *The Mandatory Rule*: For any multi-step workflow (2+ actions), **ALWAYS dispatch the sequence in a single turn** via `execute_autonomous_task` or `execute_action_dag`. The local host engine runs the loop locally at native speed with closed-loop visual servoing in <2 seconds.

> [!IMPORTANT]
> ### 2. THE TWO-PHASE MODAL & DIALOG PROTOCOL (NEVER CANCEL WITH "X")
> When interacting with modals, popups, or dialogs (e.g. flair pickers, "Save As", cookie banners, dropdowns):
> 1. **Phase 1: Selection Phase**: Click the target option, radio button, or tag (e.g. `click(text="Discussion")`).
> 2. **Phase 2: Commit Phase**: You **MUST** locate and click the dialog's commit action button (`"Apply"`, `"Save"`, `"Add"`, `"Done"`, `"Confirm"`, `"OK"`, `"Submit"`).
> - **Strict Prohibition**: **NEVER click `X` (close) after making a selection**. Clicking `X` discards your selection and cancels the dialog!
> - **The Scroll Rule**: If the commit button is below the visible dialog fold, scroll down inside the dialog (`scroll(clicks=-3)`) before trying to close or give up.

> [!IMPORTANT]
> ### 3. THE CHROMIUM & WEB APP RULE (NO UIA DOM TREES)
> Modern GPU/browser applications (Google Chrome, Brave, Edge, Electron apps) do **NOT** expose their web DOM elements to Windows UI Automation by default.
> - **Never** expect `inspect_ui` to find internal webpage buttons.
> - **Always** use Layer 2 text grounding: `click(text="Button Label")` or `find_element(query="Search")`. This triggers local 12ms WinRT OCR directly and resolves the current live physical pixel coordinates without layout drift.

> [!CAUTION]
> ### 4. NEVER SEND BLIND DESTRUCTIVE SHORTCUTS (Alt+F4 / Ctrl+W)
> **Never** execute blind `hotkey(["alt", "f4"])` or `hotkey(["ctrl", "w"])` to close an application. Global shortcuts strike whatever window happens to have foreground focus—potentially terminating the user's active browser, music stream (e.g. YouTube / Spotify), or unsaved editor.
> - **Mandatory Rule**: ALWAYS use `close_window(target="...")` or CLI `python cli.py close "<Title>"`. This sends targeted Win32 `WM_CLOSE` messages directly to the target window's HWND without touching active foreground applications.

> [!IMPORTANT]
> ### 5. PREFER NATIVE CLIPBOARD FOR ALL TEXT & CODE (`clipboard` or `paste_text`)
> For typing code, paragraphs, URLs, or multiline text, **ALWAYS** use `clipboard(action="paste", text="...")` or `paste_text` step. Keystroke-by-keystroke simulation (`type_text`) is slow and vulnerable to layout shifts or dropped keys under system load. Native Win32 clipboard injection is instantaneous and 100% accurate.

> [!IMPORTANT]
> ### 6. VERIFY SCREEN STATE BEFORE ACTING ("Look Before You Touch")
> Call `get_screen_info` to inspect `visible_windows` (all open windows, titles, PIDs, bounds, monitor geometry) and `foreground_window` before initiating window transitions. Never assume an app is focused or running.

> [!IMPORTANT]
> ### 7. WORKSPACE & WINDOW STATE RESTORATION ("Leave No Trace")
> **Always restore the user's desktop to its exact prior state once a task completes:**
> - **Minimized Apps**: If an application was minimized and you restored it to perform an action, **minimize it back** immediately when finished: `manage_window(target="...", action="state", state="minimize")`.
> - **Spawned Apps**: If you opened an application solely to accomplish a task (e.g. Notepad, File Explorer), **close it cleanly** when finished: `close_window(target="...")`.
> - **Focus Restoration**: Always return active foreground focus to the user's original working window (e.g., Antigravity IDE / terminal) so their typing workflow is completely undisturbed.

---

## 3. Tool Selection Matrix

| User Intent / Scenario | Recommended Tool | Interface & Behavior |
|---|---|---|
| **Multi-step workflow (2+ actions)** | `execute_autonomous_task(steps=[...])` | Autonomous In-Memory Runner. Executes entire sequence locally with closed-loop verification in <2s. |
| **Complex DAG with dependencies** | `execute_action_dag(steps=[...])` | High-performance DAG pipeline with topological sorting, variable interpolation (`{{steps.id.result}}`), and sub-30ms servoing. |
| **Click button / link / form by label** | `click(text="Submit", target="Chrome")` | Resolves live physical center via local WinRT OCR or UIA in 12ms. Auto-activates window before clicking. |
| **Locate element / inspect coordinates** | `find_element(query="Apply", scope="modal")` | Finds exact physical screen bounding box `[x, y, w, h]` and center `(cx, cy)` without taking a full screenshot. |
| **Continuous Screen Recording** | `record_screen(action="start"|"stop"|"status")` | High-speed, continuous 15-30 FPS recording with physical cursor stamping and high-compression 24-bit WebP/GIF export. |
| **Instant paste long text or code** | `clipboard(action="paste", text="...")` | Instant Win32 clipboard text injection followed by atomic `Ctrl+V`. Immune to layout corruption. |
| **Snap / arrange / resize window** | `manage_window(target="...", action="snap", position="left")` | Snaps window to monitor work area (left, right, top, bottom, quadrants, center) or sets exact pixel bounds. |
| **Safely close an app/window** | `close_window(target="Window Title")` | Sends Win32 `WM_CLOSE` directly to target HWND. 100% immune to closing foreground music/browser. |
| **Launch an app or URL** | `launch_app(name="chrome")` | Resolves standard paths, App Paths registry, or system PATH; waits for window to appear. |
| **Non-disruptive background sandbox** | `sandbox_launch(command="notepad.exe")` | Spawns application on isolated sandbox desktop (`AIMVR_Sandbox`). Zero cursor hijacking. |
| **Capture PiP sandbox preview** | `sandbox_capture()` or `screenshot(mode="pip")` | Renders Picture-in-Picture composite preview of all windows open in background sandbox. |
| **Scroll window or element** | `scroll(clicks=-3, x=500, y=400)` | Scrolls mouse wheel (-down, +up) at specified coordinates. |
| **Control audio / media playback** | `control_media(action="volume_up"|"play_pause")` | Adjusts volume or controls media tracks without switching active windows. |
| **Inspect screen, monitors & windows** | `get_screen_info()` | Returns virtual screen bounds, monitor work areas, foreground window, and full `visible_windows` list. |
| **Click unlabeled icons / canvas** | `screenshot(som=True)` ➔ `click(mark_id=N)` | OmniParser V2 Set-of-Marks with NMS, color-coded badges, and cluster auto-zoom for dense toolbars. |

---

## 4. High-Yield Execution Recipes

### Recipe A: Multi-Step Autonomous Web Task (Form + Modal + Submit in 1 Turn)
Use `execute_autonomous_task` to complete an entire multi-step form workflow in **one single tool call** locally:

```json
{
  "name": "execute_autonomous_task",
  "arguments": {
    "steps": [
      {"action": "focus_window", "target": "Chrome"},
      {"action": "click", "text": "Title"},
      {"action": "paste_text", "text": "Announcing AIM-VR 3.0 Computer Control"},
      {"action": "click", "text": "Add flair and tags"},
      {"action": "click", "text": "Discussion"},
      {"action": "click", "text": "Add"},
      {"action": "click", "text": "Body text"},
      {"action": "paste_text", "text": "Here is the full demonstration of autonomous computer control..."},
      {"action": "scroll", "clicks": -3},
      {"action": "click", "text": "Post"}
    ],
    "verify": true
  }
}
```

---

### Recipe B: Continuous Screen Recording for Live Demos (`record_screen`)
Capture fluid demonstration videos with hardware mouse cursor overlay:

```json
// 1. Start continuous 15 FPS recording:
{
  "name": "record_screen",
  "arguments": {
    "action": "start",
    "fps": 15,
    "include_cursor": true,
    "max_dim": 960,
    "quality": 80
  }
}

// 2. Perform actions... (via execute_autonomous_task or MCP tools)

// 3. Stop recording and compile animated WebP / GIF:
{
  "name": "record_screen",
  "arguments": {
    "action": "stop",
    "output_path": "assets/demo_recording.webp",
    "format": "webp"
  }
}
```

---

### Recipe C: Window Management & Layout Snapping (`manage_window`)
Organize windows cleanly on any monitor without triggering Windows Snap popup grids:

```json
// Snap Notepad to left half of screen:
{"name": "manage_window", "arguments": {"target": "Notepad", "action": "snap", "position": "left"}}

// Maximize Chrome:
{"name": "manage_window", "arguments": {"target": "Chrome", "action": "state", "state": "maximize"}}
```

---

### Recipe D: In-Engine Condition Waiting (`wait_for`)
Wait locally for an app to launch, a window to become active, or text to appear without slow LLM polling:

```json
// Wait up to 10s for Chrome to launch and open:
{"name": "wait_for", "arguments": {"condition": "window_exists", "target": "Chrome", "timeout": 10.0}}

// Wait for a submit button to become visible on page:
{"name": "wait_for", "arguments": {"condition": "text_exists", "query": "Submit", "timeout": 5.0}}
```

---

### Recipe E: Native Toast Notifications & System Registry (`notify`, `registry`)
Notify the user when a long task completes, or read/write system configurations directly:

```json
// Send native Windows Action Center toast:
{"name": "notify", "arguments": {"title": "Task Finished", "message": "All items compiled successfully!"}}

// Read a Windows Registry setting:
{"name": "registry", "arguments": {"mode": "get", "path": "HKCU\\Software\\MyApp", "name": "Version"}}
```

---

## 5. Deterministic Troubleshooting & Recovery

| Symptom / Error | Root Cause | Deterministic Fix |
|---|---|---|
| First click swallowed / button doesn't fire | Window was inactive (`WM_MOUSEACTIVATE` consumed click). | In `MouseEngine`, target windows are now auto-activated with a 20ms message tick before click dispatch. |
| Coordinate drift after typing / scrolling | Hardcoding coordinates from stale OCR dumps. | **Use `click(text="Button Label")`**. It runs a 12ms WinRT OCR scan and resolves live physical pixel centers on the current visual frame. |
| Modal closes without applying changes | Agent clicked `X` (close) instead of commit button. | **Follow Invariant #2**: Click selection $\rightarrow$ Click `"Apply"` / `"Save"` / `"Add"`. Never click `X` to exit a modal after selecting an option. |
| Empty UIA tree on Chrome / web browser | Chromium apps do not expose DOM nodes to Windows UIA. | **Follow Invariant #3**: Web browsers automatically bypass UIA and use Layer 2 sub-15ms WinRT OCR text grounding. |
| Failsafe triggered at (0, 0) in background script | Thread was not attached to interactive input desktop. | `ensure_interactive_desktop()` now compares thread desktop against `OpenInputDesktop()` and attaches cleanly. |
| Dropped keys or slow text insertion | Simulating keystrokes for large text. | **Use `clipboard(action="paste", text="...")`** or `paste_text` step. |
