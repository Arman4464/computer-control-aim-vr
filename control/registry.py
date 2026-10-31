"""
High-Speed Native Windows Registry Manager (AIM-VR 3.0 Control Subsystem).
Provides direct, zero-dependency access to the Windows Registry (HKCU, HKLM, HKCR, HKU, HKCC)
using Python's native winreg module on Windows, and structured diagnostic responses on Linux.
"""

import os
import sys
from typing import Dict, Any, List, Optional, Tuple, Union

IS_WINDOWS = (sys.platform == "win32")

if IS_WINDOWS:
    import winreg

    # Root key mapping
    HKEY_MAP = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKU": winreg.HKEY_USERS,
        "HKEY_USERS": winreg.HKEY_USERS,
        "HKCC": winreg.HKEY_CURRENT_CONFIG,
        "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
    }

    # Type string to winreg constant mapping
    TYPE_MAP = {
        "sz": winreg.REG_SZ,
        "string": winreg.REG_SZ,
        "expand_sz": winreg.REG_EXPAND_SZ,
        "multi_sz": winreg.REG_MULTI_SZ,
        "dword": winreg.REG_DWORD,
        "qword": winreg.REG_QWORD,
        "binary": winreg.REG_BINARY,
        "none": winreg.REG_NONE,
    }

    REV_TYPE_MAP = {
        winreg.REG_SZ: "REG_SZ",
        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
        winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
        winreg.REG_DWORD: "REG_DWORD",
        winreg.REG_QWORD: "REG_QWORD",
        winreg.REG_BINARY: "REG_BINARY",
        winreg.REG_NONE: "REG_NONE",
    }
else:
    winreg = None
    HKEY_MAP = {}
    TYPE_MAP = {}
    REV_TYPE_MAP = {}


def _parse_reg_path(full_path: str) -> Tuple[int, str]:
    """Splits 'HKCU\\Software\\Microsoft' into (winreg.HKEY_CURRENT_USER, 'Software\\Microsoft')."""
    if not IS_WINDOWS:
        return 0, ""

    if not full_path or not isinstance(full_path, str):
        raise ValueError("Registry path must be a non-empty string.")

    clean_path = full_path.replace("/", "\\").strip("\\")
    parts = clean_path.split("\\", 1)
    root_str = parts[0].upper()
    sub_key = parts[1] if len(parts) > 1 else ""

    if root_str not in HKEY_MAP:
        raise ValueError(f"Unknown registry root key '{root_str}'. Valid roots: {list(HKEY_MAP.keys())}")

    return HKEY_MAP[root_str], sub_key


class RegistryManager:
    """Manages reading, writing, and enumerating Windows Registry keys and values."""

    def get_value(self, path: str, name: str = "", view64: bool = True) -> Dict[str, Any]:
        """Reads a value from the specified registry path."""
        if not IS_WINDOWS:
            return {
                "status": "unsupported_platform",
                "message": "Windows Registry is Windows-specific. On Arch Linux Hyprland, system and app configurations are managed via dotfiles (~/.config), dconf, or /etc.",
            }

        try:
            root_hkey, sub_key = _parse_reg_path(path)
            access = winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if view64 else winreg.KEY_WOW64_32KEY)

            with winreg.OpenKey(root_hkey, sub_key, 0, access) as key:
                val, val_type = winreg.QueryValueEx(key, name)
                type_name = REV_TYPE_MAP.get(val_type, f"TYPE_{val_type}")
                return {
                    "status": "success",
                    "path": path,
                    "name": name or "(Default)",
                    "value": val,
                    "type": type_name,
                }
        except FileNotFoundError:
            return {"status": "error", "message": f"Registry path or value not found: {path}\\{name}"}
        except PermissionError:
            return {"status": "error", "message": f"Access denied reading registry: {path}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_value(
        self,
        path: str,
        name: str,
        value: Any,
        val_type: str = "string",
        view64: bool = True
    ) -> Dict[str, Any]:
        """Creates or updates a registry value, creating the parent key path if it does not exist."""
        if not IS_WINDOWS:
            return {
                "status": "unsupported_platform",
                "message": "Windows Registry is Windows-specific. On Arch Linux Hyprland, system and app configurations are managed via dotfiles (~/.config), dconf, or /etc.",
            }

        try:
            root_hkey, sub_key = _parse_reg_path(path)
            access = winreg.KEY_WRITE | (winreg.KEY_WOW64_64KEY if view64 else winreg.KEY_WOW64_32KEY)

            reg_type = TYPE_MAP.get(val_type.lower(), winreg.REG_SZ)

            # Type conversions
            converted_value = value
            if reg_type in (winreg.REG_DWORD, winreg.REG_QWORD):
                converted_value = int(value)
            elif reg_type == winreg.REG_SZ:
                converted_value = str(value)
            elif reg_type == winreg.REG_BINARY and isinstance(value, str):
                converted_value = bytes.fromhex(value.replace(" ", "").replace(",", ""))

            with winreg.CreateKeyEx(root_hkey, sub_key, 0, access) as key:
                winreg.SetValueEx(key, name, 0, reg_type, converted_value)
                return {
                    "status": "success",
                    "path": path,
                    "name": name,
                    "value": value,
                    "type": val_type,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_value(self, path: str, name: str, view64: bool = True) -> Dict[str, Any]:
        """Deletes a named value from a registry key."""
        if not IS_WINDOWS:
            return {"status": "unsupported_platform", "message": "Windows Registry is Windows-specific."}

        try:
            root_hkey, sub_key = _parse_reg_path(path)
            access = winreg.KEY_SET_VALUE | (winreg.KEY_WOW64_64KEY if view64 else winreg.KEY_WOW64_32KEY)
            with winreg.OpenKey(root_hkey, sub_key, 0, access) as key:
                winreg.DeleteValue(key, name)
                return {"status": "success", "message": f"Deleted value '{name}' from '{path}'"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_key(self, path: str, view64: bool = True) -> Dict[str, Any]:
        """Deletes a registry key (must be empty of subkeys)."""
        if not IS_WINDOWS:
            return {"status": "unsupported_platform", "message": "Windows Registry is Windows-specific."}

        try:
            root_hkey, sub_key = _parse_reg_path(path)
            access = winreg.KEY_WRITE | (winreg.KEY_WOW64_64KEY if view64 else winreg.KEY_WOW64_32KEY)
            if hasattr(winreg, "DeleteKeyEx"):
                winreg.DeleteKeyEx(root_hkey, sub_key, access, 0)
            else:
                winreg.DeleteKey(root_hkey, sub_key)
            return {"status": "success", "message": f"Deleted key '{path}'"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_key(self, path: str, view64: bool = True) -> Dict[str, Any]:
        """Lists all values and subkeys under a registry key."""
        if not IS_WINDOWS:
            return {"status": "unsupported_platform", "message": "Windows Registry is Windows-specific."}

        try:
            root_hkey, sub_key = _parse_reg_path(path)
            access = winreg.KEY_READ | (winreg.KEY_WOW64_64KEY if view64 else winreg.KEY_WOW64_32KEY)

            with winreg.OpenKey(root_hkey, sub_key, 0, access) as key:
                num_subkeys, num_values, _ = winreg.QueryInfoKey(key)

                values = []
                for i in range(num_values):
                    v_name, v_val, v_type = winreg.EnumValue(key, i)
                    values.append({
                        "name": v_name or "(Default)",
                        "value": v_val if not isinstance(v_val, bytes) else v_val.hex(),
                        "type": REV_TYPE_MAP.get(v_type, f"TYPE_{v_type}")
                    })

                subkeys = []
                for i in range(num_subkeys):
                    subkeys.append(winreg.EnumKey(key, i))

                return {
                    "status": "success",
                    "path": path,
                    "values_count": len(values),
                    "subkeys_count": len(subkeys),
                    "values": values,
                    "subkeys": subkeys,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    list_values = list_key


default_registry = RegistryManager()

