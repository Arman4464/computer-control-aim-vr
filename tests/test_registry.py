"""
Unit tests for the Windows Registry Manager (AIM-VR 3.0 Control Subsystem).
"""

import unittest
from control.registry import default_registry, _parse_reg_path
import winreg


class TestRegistryManager(unittest.TestCase):

    def setUp(self):
        self.test_path = "HKCU\\Software\\AIMVR_TestKey"
        self.reg = default_registry

    def tearDown(self):
        # Clean up test key
        try:
            self.reg.delete_value(self.test_path, "TestVal")
        except Exception:
            pass
        try:
            self.reg.delete_key(self.test_path)
        except Exception:
            pass

    def test_parse_reg_path(self):
        hkey, sub = _parse_reg_path("HKCU\\Software\\Microsoft")
        self.assertEqual(hkey, winreg.HKEY_CURRENT_USER)
        self.assertEqual(sub, "Software\\Microsoft")

        with self.assertRaises(ValueError):
            _parse_reg_path("INVALID_ROOT\\Key")

    def test_set_and_get_value(self):
        # 1. Set string value
        set_res = self.reg.set_value(self.test_path, "TestVal", "HelloRegistry")
        self.assertEqual(set_res["status"], "success")

        # 2. Get value
        get_res = self.reg.get_value(self.test_path, "TestVal")
        self.assertEqual(get_res["status"], "success")
        self.assertEqual(get_res["value"], "HelloRegistry")

    def test_list_key(self):
        self.reg.set_value(self.test_path, "TestVal1", "Val1")
        self.reg.set_value(self.test_path, "TestVal2", 1234, val_type="dword")

        list_res = self.reg.list_key(self.test_path)
        self.assertEqual(list_res["status"], "success")
        self.assertGreaterEqual(list_res["values_count"], 2)

    def test_delete_value_and_key(self):
        self.reg.set_value(self.test_path, "ToDelete", "Bye")
        del_v = self.reg.delete_value(self.test_path, "ToDelete")
        self.assertEqual(del_v["status"], "success")

        del_k = self.reg.delete_key(self.test_path)
        self.assertEqual(del_k["status"], "success")


if __name__ == "__main__":
    unittest.main()
