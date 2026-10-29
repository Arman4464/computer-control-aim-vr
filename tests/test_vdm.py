"""
Unit tests for the Virtual Desktop Manager (AIM-VR 3.0 Control Subsystem).
"""

import unittest
from control.vdm import VirtualDesktopManager, _guid_from_str


class TestVirtualDesktopManager(unittest.TestCase):

    def test_guid_from_str(self):
        guid = _guid_from_str("{aa509086-5ca9-4c25-8f95-589d3c07b48a}")
        self.assertEqual(guid.Data1, 0xaa509086)
        self.assertEqual(guid.Data2, 0x5ca9)
        self.assertEqual(guid.Data3, 0x4c25)

    def test_invalid_hwnd(self):
        vdm = VirtualDesktopManager()
        self.assertFalse(vdm.is_window_on_current_desktop(0))
        self.assertFalse(vdm.is_window_on_current_desktop(-1))


if __name__ == "__main__":
    unittest.main()
