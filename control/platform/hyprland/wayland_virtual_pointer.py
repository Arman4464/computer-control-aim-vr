"""
Wayland Virtual Pointer Protocol Client (wlr-virtual-pointer-unstable-v1).
Pure-Python zero-dependency implementation of the Wayland binary wire protocol
for zwlr_virtual_pointer_manager_v1.
Enables 100% unprivileged mouse movement, clicks, drags, and scrolling on Hyprland,
Sway, Wayfire, and River without requiring /dev/uinput permissions, root, or udev rules.
"""

import os
import sys
import time
import socket
import struct
import select
from typing import Optional, Tuple, Dict, Any, List

# Linux input button constants
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

BTN_STATE_RELEASED = 0
BTN_STATE_PRESSED = 1


def _pack_string(s: str) -> bytes:
    """Packs string conforming to Wayland wire format (uint32 len with null, padded to 4 bytes)."""
    b = s.encode("utf-8") + b"\0"
    length = len(b)
    padding = (4 - (length % 4)) % 4
    return struct.pack("<I", length) + b + (b"\0" * padding)


def _unpack_string(data: bytes, offset: int) -> Tuple[str, int]:
    """Unpacks a Wayland wire format string starting at offset. Returns (string, next_offset)."""
    if offset + 4 > len(data):
        return "", offset
    length = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if offset + length > len(data):
        return "", offset
    raw = data[offset : offset + length]
    # Strip trailing null
    s = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    padding = (4 - (length % 4)) % 4
    offset += length + padding
    return s, offset


class WaylandVirtualPointerClient:
    """
    Direct Wayland socket client binding zwlr_virtual_pointer_manager_v1.
    """

    INTERFACE_NAME = "zwlr_virtual_pointer_manager_v1"

    def __init__(self, display_name: Optional[str] = None):
        self.display_name = display_name or os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        self.runtime_dir = os.environ.get(
            "XDG_RUNTIME_DIR",
            f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else "/tmp"
        )
        self.socket_path = os.path.join(self.runtime_dir, self.display_name)
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._manager_id = 0
        self._manager_name = 0
        self._manager_version = 2
        self._pointer_id = 0
        self._next_id = 2
        self._last_time = int(time.time() * 1000) & 0xFFFFFFFF
        self._cursor_x = 0
        self._cursor_y = 0

    def _get_time_ms(self) -> int:
        return int(time.time() * 1000) & 0xFFFFFFFF

    def is_available(self) -> bool:
        """Returns True if Wayland socket is reachable and virtual pointer manager can be bound."""
        if self._connected and self._pointer_id > 0:
            return True
        return self.connect()

    def connect(self) -> bool:
        """Establishes connection to $WAYLAND_DISPLAY and binds zwlr_virtual_pointer_manager_v1."""
        if not sys.platform.startswith("linux"):
            return False
        if not hasattr(socket, "AF_UNIX") or not os.path.exists(self.socket_path):
            return False

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(2.0)
            self._sock.connect(self.socket_path)

            # 1. wl_display.get_registry(new_id=2)
            # wl_display is object 1, opcode 1 = get_registry
            registry_id = self._next_id
            self._next_id += 1
            self._send_message(1, 1, struct.pack("<I", registry_id))

            # 2. wl_display.sync(new_id=3)
            # opcode 0 = sync
            sync_callback_id = self._next_id
            self._next_id += 1
            self._send_message(1, 0, struct.pack("<I", sync_callback_id))

            # Read events until sync callback completes
            globals_dict = self._read_initial_registry(sync_callback_id)

            if self.INTERFACE_NAME not in globals_dict:
                sys.stderr.write(f"[WaylandVirtualPointer] {self.INTERFACE_NAME} not advertised by compositor.\n")
                self.disconnect()
                return False

            self._manager_name, version = globals_dict[self.INTERFACE_NAME]
            self._manager_version = min(version, 2)
            self._manager_id = self._next_id
            self._next_id += 1

            # 3. wl_registry.bind(name, interface, version, new_id)
            # registry is object 2, opcode 0 = bind
            bind_payload = (
                struct.pack("<I", self._manager_name)
                + _pack_string(self.INTERFACE_NAME)
                + struct.pack("<II", self._manager_version, self._manager_id)
            )
            self._send_message(registry_id, 0, bind_payload)

            # 4. zwlr_virtual_pointer_manager_v1.create_virtual_pointer(suggested_seat=0, new_id=5)
            # opcode 0 = create_virtual_pointer
            self._pointer_id = self._next_id
            self._next_id += 1
            pointer_payload = struct.pack("<II", 0, self._pointer_id)
            self._send_message(self._manager_id, 0, pointer_payload)

            # Flush sync
            sync_2 = self._next_id
            self._next_id += 1
            self._send_message(1, 0, struct.pack("<I", sync_2))

            self._connected = True
            sys.stderr.write(f"[WaylandVirtualPointer] Successfully initialized unprivileged virtual pointer (id={self._pointer_id}).\n")
            return True

        except Exception as e:
            sys.stderr.write(f"[WaylandVirtualPointer] Connection failed: {e}\n")
            self.disconnect()
            return False

    def disconnect(self):
        """Closes the Wayland socket and resets state."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._connected = False
        self._pointer_id = 0
        self._manager_id = 0

    def destroy(self):
        """
        Sends protocol destroy request (opcode 8) to virtual pointer and disconnects socket.
        """
        if self._sock and self._pointer_id:
            try:
                # opcode 8 = destroy()
                self._send_message(self._pointer_id, 8, b"")
            except Exception:
                pass
        self.disconnect()

    def _send_message(self, obj_id: int, opcode: int, payload: bytes = b""):
        """Sends a framed Wayland wire protocol packet (8-byte header + payload)."""
        if not self._sock:
            raise ConnectionError("Wayland socket not connected.")
        msg_size = 8 + len(payload)
        header = struct.pack("<II", obj_id, (msg_size << 16) | (opcode & 0xFFFF))
        self._sock.sendall(header + payload)

    def _read_initial_registry(self, sync_callback_id: int) -> Dict[str, Tuple[int, int]]:
        """Reads registry.global events from compositor until sync callback fires."""
        globals_found = {}
        buffer = b""

        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            buffer += chunk

            offset = 0
            done = False
            while offset + 8 <= len(buffer):
                obj_id, size_opcode = struct.unpack_from("<II", buffer, offset)
                size = (size_opcode >> 16) & 0xFFFF
                opcode = size_opcode & 0xFFFF

                if offset + size > len(buffer):
                    break  # Incomplete message, await next chunk

                msg_payload = buffer[offset + 8 : offset + size]
                offset += size

                if obj_id == sync_callback_id:
                    # wl_callback.done event
                    done = True
                    break

                # wl_registry is object 2, opcode 0 is 'global'
                if obj_id == 2 and opcode == 0:
                    if len(msg_payload) >= 8:
                        name = struct.unpack_from("<I", msg_payload, 0)[0]
                        interface_str, next_off = _unpack_string(msg_payload, 4)
                        if next_off + 4 <= len(msg_payload):
                            version = struct.unpack_from("<I", msg_payload, next_off)[0]
                            globals_found[interface_str] = (name, version)

            buffer = buffer[offset:]
            if done:
                break

        return globals_found

    def move_absolute(
        self,
        x: int,
        y: int,
        x_extent: Optional[int] = None,
        y_extent: Optional[int] = None,
    ):
        """
        Moves virtual pointer to absolute screen coordinates using motion_absolute.
        Dispatches motion_absolute followed immediately by frame().
        If extents are not passed or None, dynamically queries active desktop bounds via
        get_platform_driver().window_manager.get_virtual_desktop_bounds() (fallback to 1920x1080).
        """
        if not self.is_available():
            raise RuntimeError("Wayland Virtual Pointer is not connected.")

        if x_extent is None or y_extent is None:
            try:
                from control.platform import get_platform_driver
                driver = get_platform_driver()
                wm = getattr(driver, "window_manager", None)
                bounds = None
                if wm is not None:
                    if hasattr(wm, "get_virtual_desktop_bounds"):
                        bounds = wm.get_virtual_desktop_bounds()
                    elif hasattr(wm, "get_virtual_screen_bounds"):
                        bounds = wm.get_virtual_screen_bounds()
                if bounds:
                    if len(bounds) >= 4 and bounds[2] > 0 and bounds[3] > 0:
                        w, h = bounds[2], bounds[3]
                    elif len(bounds) >= 2 and bounds[0] > 0 and bounds[1] > 0:
                        w, h = bounds[0], bounds[1]
                    else:
                        w, h = 1920, 1080
                    if x_extent is None:
                        x_extent = int(w)
                    if y_extent is None:
                        y_extent = int(h)
            except Exception:
                pass

        if not x_extent or x_extent <= 0:
            x_extent = 1920
        if not y_extent or y_extent <= 0:
            y_extent = 1080

        self._cursor_x = int(x)
        self._cursor_y = int(y)
        t_ms = self._get_time_ms()

        # opcode 7 = motion_absolute(time: uint32, x: uint32, y: uint32, x_extent: uint32, y_extent: uint32)
        payload = struct.pack(
            "<IIIII",
            t_ms,
            max(0, int(x)),
            max(0, int(y)),
            max(1, int(x_extent)),
            max(1, int(y_extent)),
        )
        self._send_message(self._pointer_id, 7, payload)
        self.frame()

    def motion(self, dx: int, dy: int, time_ms: int = 0):
        """
        Sends relative pointer motion event (opcode 0) followed by frame() (opcode 3).
        Coordinates dx and dy are 24.8 fixed-point numbers.
        """
        if not self.is_available():
            raise RuntimeError("Wayland Virtual Pointer is not connected.")

        t_ms = int(time_ms) if time_ms > 0 else self._get_time_ms()
        dx_fixed = int(dx * 256.0)
        dy_fixed = int(dy * 256.0)

        # opcode 0 = motion(time: uint32, dx: fixed, dy: fixed)
        payload = struct.pack("<Iii", t_ms, dx_fixed, dy_fixed)
        self._send_message(self._pointer_id, 0, payload)
        self._cursor_x += int(dx)
        self._cursor_y += int(dy)
        self.frame()

    def button_down(self, button: int = BTN_LEFT):
        """Sends button pressed event."""
        if not self.is_available():
            return
        t_ms = self._get_time_ms()
        # opcode 1 = button(time: uint32, button: uint32, state: uint32)
        payload = struct.pack("<III", t_ms, button, BTN_STATE_PRESSED)
        self._send_message(self._pointer_id, 1, payload)
        self.frame()

    def button_up(self, button: int = BTN_LEFT):
        """Sends button released event."""
        if not self.is_available():
            return
        t_ms = self._get_time_ms()
        payload = struct.pack("<III", t_ms, button, BTN_STATE_RELEASED)
        self._send_message(self._pointer_id, 1, payload)
        self.frame()

    def click(self, button: int = BTN_LEFT, clicks: int = 1):
        """Executes atomic click sequence."""
        for i in range(max(1, clicks)):
            if i > 0:
                time.sleep(0.04)
            self.button_down(button=button)
            time.sleep(0.02)
            self.button_up(button=button)

    def axis_scroll(self, clicks: int):
        """Sends vertical axis scroll event."""
        if not self.is_available():
            return
        t_ms = self._get_time_ms()
        # opcode 2 = axis(time: uint32, axis: uint32, value: fixed)
        # 15.0 in fixed-point 24.8 is 15 * 256 = 3840
        # Positive clicks = up (negative value in Wayland axis), negative clicks = down
        val_fixed = int(-clicks * 15.0 * 256.0)
        payload = struct.pack("<IIi", t_ms, 0, val_fixed)
        self._send_message(self._pointer_id, 2, payload)
        self.frame()

    def frame(self):
        """Commits pending pointer event sequence (opcode 3 = frame)."""
        if self._sock and self._pointer_id:
            try:
                self._send_message(self._pointer_id, 3, b"")
            except Exception:
                pass

    def get_position(self) -> Tuple[int, int]:
        """Returns last known cursor position."""
        return self._cursor_x, self._cursor_y


# Default singleton instance
default_virtual_pointer = WaylandVirtualPointerClient()
