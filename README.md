# Computer Control (AIM-VR 3.0 - Arch Linux Hyprland Edition)

[![Platform](https://img.shields.io/badge/Platform-Arch%20Linux%20(Hyprland%20Wayland)-blue.svg)](https://archlinux.org)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![MCP Version](https://img.shields.io/badge/MCP-2024--11--05-green.svg)](https://modelcontextprotocol.io/)
[![Tools](https://img.shields.io/badge/MCP%20Tools-35%20Linux%20Tools-blueviolet.svg)](mcp_schemas/)
[![Tests](https://img.shields.io/badge/Tests-Passing%20(100%25)-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> [!NOTE]
> **Dedicated Linux Edition**: This branch (`feat/arch-hyprland`) is engineered 100% natively for **Arch Linux running Hyprland (Wayland)** with zero Windows dependencies.
> For the Windows 10 & 11 edition, see the [`main`](https://github.com/Arman4464/computer-control-aim-vr/tree/main) branch.

**Autonomous In-Memory Vision Runner (AIM-VR 3.0)** is an industrial-grade desktop automation, macro recording, and computer control engine engineered for LLMs and AI agents operating natively on **Arch Linux with Hyprland (Wayland)**.

Unlike standard vision-agent frameworks that suffer from sluggish multi-turn screenshot round-trips, coordinate misalignment, and desktop contention, AIM-VR 3.0 delivers **sub-30ms closed-loop execution**, **rootless unprivileged Wayland virtual pointer injection**, **zero-token AT-SPI2 semantic accessibility trees**, **zero-disk-write Grim screencopy and streaming OCR**, **a 5-tier self-healing Semantic Macro Engine**, and **speculative Action DAG orchestration**.

---

## The Three SOTA Linux Subsystems

### 1. AT-SPI2 Semantic Accessibility Tree Inspector
Zero-token semantic accessibility tree extraction over the FreeDesktop D-Bus session bus (`org.a11y.atspi`). Traverses accessible objects, extracts live screen coordinate extents, and normalizes native roles (`push button` $\rightarrow$ `Button`, `entry` $\rightarrow$ `Edit`, `check box` $\rightarrow$ `CheckBox`, `list item` $\rightarrow$ `ListItem`) for GTK, Qt, Electron, and Firefox applications with zero vision token consumption.

### 2. Unprivileged Wayland Virtual Pointer Protocol Client
Direct binary wire protocol client connecting to the compositor socket at `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY` and binding `zwlr_virtual_pointer_manager_v1`. Provides 100% rootless, unprivileged mouse cursor positioning, clicking, dragging, and axis scrolling without requiring `/dev/uinput` permissions, root rights, or custom udev groups.

### 3. PipeWire 60 FPS Hardware Screen Recording Portal
GPU hardware-accelerated desktop and window recording utilizing `wl-screenrec` / `wf-recorder` via DMA-BUF (VA-API / NVENC) for smooth 60 FPS recording with near-zero CPU utilization. Automatically transcodes to high-compression animated WebP or raw MP4 upon completion.

---

## Linux System Architecture

```
                                      +-----------------------+
                                      |    AI Agent / LLM     |
                                      +-----------------------+
                                                  |
                            +---------------------+---------------------+
                            |                                           |
                   MCP JSON-RPC (Stdio)                                CLI
                   (35 Native Linux Tools)                              |
                            |                                           |
                            +---------------------+---------------------+
                                                  v
                                      +-----------------------+
                                      |   server.py / cli.py  |
                                      +-----------------------+
                                                  |
            +-------------------------------------+-------------------------------------+
            |                                     |                                     |
            v                                     v                                     v
+-------------------------------+ +-------------------------------+ +-------------------------------+
|     Perception Subsystem      | |      Control Subsystem        | |       Hyprland Integration    |
|-------------------------------| |-------------------------------| |-------------------------------|
| * AT-SPI2 D-Bus Tree (<5ms)   | | * zwlr_virtual_pointer_v1     | | * Hyprland UNIX Sockets       |
| * Streaming Tesseract TSV     | | * Kernel /dev/uinput evdev    | | * Dynamic Workspaces          |
| * Grim Zero-Disk RAM Pipe     | | * Wayland Clipboard (wl-copy) | | * Client Address Focusing     |
| * 60 FPS PipeWire DMA-BUF     | | * playerctl MPRIS Audio/Media | | * Floating / Fullscreen Tile  |
| * OmniParser V2 SOM Badging   | | * FreeDesktop notify-send     | | * Visual Servoing (<30ms)     |
| * 32x32 Perceptual Hash       | | * Macro Engine (RDP + 5-Tier) | | * Speculative DAG Engine      |
+-------------------------------+ +-------------------------------+ +-------------------------------+
```

---

## Cardinal Operating Invariants

Every agent or operator using AIM-VR 3.0 must adhere to seven non-negotiable rules:

1. **NEVER FALL INTO THE TURN-BY-TURN "SCREENSHOT & GUESS" ANTI-PATTERN**: Never take a screenshot after every single click. For 2+ actions, dispatch the sequence via `execute_autonomous_task`, `execute_action_dag`, or `macro_play` to execute locally in an in-memory closed loop in <2 seconds.
2. **THE TWO-PHASE MODAL PROTOCOL (NEVER CANCEL WITH "X")**: When dealing with dialogs, flairs, dropdowns, or modals: click the target option $\rightarrow$ locate and click the commit action button (`"Apply"`, `"Save"`, `"Done"`, `"Confirm"`). Never click `X` to exit a modal after selecting an option.
3. **THE CHROMIUM & WEB APP RULE (NO AT-SPI DOM TREES)**: Modern GPU web browsers (Google Chrome, Brave) do not expose DOM elements to Linux accessibility trees. Always use Layer 2 text grounding: `click(text="Label")` or companion `browser_dom_action`.
4. **NEVER SEND BLIND DESTRUCTIVE SHORTCUTS (Alt+F4 / Super+Q)**: Global shortcuts strike whatever window currently has focus. Always use targeted window closing: `close_window(target="...")` or `aimvr close "<Title>"`.
5. **PREFER NATIVE WAYLAND CLIPBOARD FOR ALL TEXT & CODE**: Always use `clipboard(action="paste", text="...")` or `paste_text` step. Keystroke-by-keystroke simulation is vulnerable to dropped keys; native `wl-clipboard` injection is instantaneous.
6. **VERIFY SCREEN STATE BEFORE ACTING ("Look Before You Touch")**: Call `get_screen_info` to inspect `visible_windows`, client addresses, and active workspace before initiating window transitions.
7. **RESTORE USER WORKSPACE STATE ("Leave No Trace")**: When finished, return to the user's active workspace and original focused window.

---

## 35 Native Linux MCP Tools

| Tool | Category | Behavior |
|---|---|---|
| `inspect_ui` | Perception | Traverses `org.a11y.atspi` D-Bus accessibility tree for GTK/Qt/Electron/Firefox. |
| `ocr_screen` | Perception | Zero-disk-write in-memory Tesseract TSV OCR scan. |
| `find_element` | Perception | Locates UI element bounding box `[x, y, w, h]` and center via AT-SPI2 or OCR. |
| `screenshot` | Perception | Fast pipe-streamed `grim` screencopy to RAM. |
| `take_som_screenshot` | Perception | Overlays OmniParser numbered marks for visual grounding. |
| `click_som_mark` | Perception | Clicks an indexed SoM badge by integer ID. |
| `move_cursor` | Control | Moves cursor via `zwlr_virtual_pointer_v1` or Hyprland IPC `movecursor`. |
| `mouse_down` | Control | Presses mouse button via unprivileged Wayland virtual pointer. |
| `mouse_up` | Control | Releases mouse button via unprivileged Wayland virtual pointer. |
| `click` | Control | Atomic click sequence by coordinate, AT-SPI query, or OCR text label. |
| `drag` | Control | Smooth interpolated mouse drag across display. |
| `scroll` | Control | Wayland 24.8 fixed-point axis wheel scroll (-down, +up). |
| `type_text` | Control | Character-by-character keyboard typing via virtual pointer/evdev. |
| `press_key` | Control | Individual key press/release event dispatch. |
| `hotkey` | Control | Multi-key combination dispatch (e.g. `["ctrl", "c"]`). |
| `clipboard` | Control | Native Wayland clipboard get/set/paste via `wl-copy` / `wl-paste`. |
| `focus_window` | Control | Switches workspace and focuses target window by title or client address. |
| `close_window` | Control | Targeted Hyprland `closewindow address:<hex>` dispatch. |
| `manage_window` | Control | Workspace movement, fullscreen, and floating state management. |
| `get_screen_info` | Control | Returns monitor geometries, active workspace, and all Hyprland clients. |
| `launch_app` | Control | Launches application via `dispatch exec` or `xdg-open`. |
| `control_media` | Control | MPRIS track and volume control via `playerctl` / PipeWire `wpctl`. |
| `notify` | Control | FreeDesktop desktop notification dispatch via `notify-send`. |
| `record_screen` | Control | Hardware-accelerated 60 FPS PipeWire DMA-BUF portal recording (`wl-screenrec`). |
| `wait_for` | Control | In-engine condition polling loop eliminating LLM turn-by-turn latency. |
| `configure_safety` | Control | Adjusts speed profiles and user mouse contention governor. |
| `execute_autonomous_task`| Execution | Closed-loop local multi-step workflow runner in <2 seconds. |
| `execute_action_dag` | Execution | High-performance DAG pipeline with topological sorting and variable interpolation. |
| `macro_record` | Execution | Captures repeatable user/agent workflows with RDP trajectory compression. |
| `macro_play` | Execution | Replays macro with 5-tier self-healing fallback. |
| `macro_manage` | Execution | Manages stored macro files (list, get, delete). |
| `browser_bridge_status` | Extension | Checks connection to companion Chrome/Brave extension. |
| `browser_dom_action` | Extension | Direct DOM click/fill dispatch via companion extension. |
| `com_browser_cdp` | Extension | Direct WebSocket Chrome DevTools Protocol tab navigation. |

---

## Installation & Setup on Arch Linux

### Method 1: Arch Linux Pacman Package (`PKGBUILD`)
```bash
git clone -b feat/arch-hyprland https://github.com/Arman4464/computer-control-aim-vr.git
cd computer-control-aim-vr
makepkg -si
```

### Method 2: Python Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
sudo pacman -S grim wl-clipboard libnotify tesseract wl-screenrec playerctl
```

---

## Running MCP Server
Add to your Claude Desktop / Antigravity / Cursor MCP configuration:
```json
{
  "mcpServers": {
    "computer-control": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "/path/to/computer-control-aim-vr"
    }
  }
}
```

---

## License
MIT License. Engineered by Arman (AIM-VR Team).
