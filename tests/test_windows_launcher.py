import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "hotspot_logger_windows_launcher",
    Path(__file__).parents[1] / "windows" / "launcher.py",
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
ROOT = Path(__file__).parents[1]


class WindowsLauncherTests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        version = re.search(r'^VERSION = "([^"]+)"$', app_source, re.MULTILINE).group(1)
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-beta\.(\d+)", version)
        self.assertIsNotNone(match)
        numeric = ", ".join(match.groups())

        version_info = (ROOT / "windows" / "version_info.txt").read_text(encoding="utf-8")
        self.assertIn(f"filevers=({numeric})", version_info)
        self.assertIn(f"prodvers=({numeric})", version_info)
        self.assertIn(f"StringStruct('ProductVersion', '{version}')", version_info)

        for relative in ("README.md", "windows/README-WINDOWS.txt", ".github/workflows/windows.yml"):
            with self.subTest(relative=relative):
                self.assertIn(version, (ROOT / relative).read_text(encoding="utf-8"))

    def test_data_directory_prefers_local_app_data(self):
        self.assertEqual(
            launcher.data_directory({"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}),
            Path(r"C:\Users\Test\AppData\Local") / "Hotspot Logger",
        )

    def test_data_directory_has_home_fallback(self):
        self.assertEqual(
            launcher.data_directory({}, home="/tmp/test-home"),
            Path("/tmp/test-home") / "Hotspot Logger",
        )

    def test_launcher_setting_is_strict_and_defaults_to_local_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertEqual(launcher.load_launcher_settings(path), {"lan_access": False})
            path.write_text(json.dumps({"lan_access": "yes"}), encoding="utf-8")
            self.assertEqual(launcher.load_launcher_settings(path), {"lan_access": False})
            launcher.save_launcher_settings(path, {"lan_access": True})
            self.assertEqual(launcher.load_launcher_settings(path), {"lan_access": True})

    def test_startup_command_for_packaged_app(self):
        self.assertEqual(
            launcher.startup_command(r"C:\Apps\HotspotLogger.exe", frozen=True),
            '"C:\\Apps\\HotspotLogger.exe" --startup',
        )

    def test_startup_command_for_source_run(self):
        self.assertEqual(
            launcher.startup_command(r"C:\Python\python.exe", r"C:\Logger\launcher.py", frozen=False),
            '"C:\\Python\\python.exe" "C:\\Logger\\launcher.py" --startup',
        )

    def test_startup_registry_round_trip(self):
        class Key:
            def __init__(self, values):
                self.values = values

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Registry:
            HKEY_CURRENT_USER = object()
            REG_SZ = 1
            KEY_QUERY_VALUE = 1
            KEY_SET_VALUE = 2

            def __init__(self):
                self.values = {}

            def CreateKey(self, _root, _path):
                return Key(self.values)

            def OpenKey(self, _root, _path, *_args):
                if launcher.STARTUP_VALUE not in self.values:
                    raise FileNotFoundError
                return Key(self.values)

            @staticmethod
            def SetValueEx(key, name, _reserved, _kind, value):
                key.values[name] = value

            @staticmethod
            def QueryValueEx(key, name):
                return key.values[name], Registry.REG_SZ

            @staticmethod
            def DeleteValue(key, name):
                del key.values[name]

        registry = Registry()
        command = '"C:\\Apps\\HotspotLogger.exe" --startup'
        with mock.patch.object(launcher, "startup_command", return_value=command):
            self.assertFalse(launcher.startup_enabled(registry))
            launcher.set_startup_enabled(True, registry)
            self.assertTrue(launcher.startup_enabled(registry))
            launcher.set_startup_enabled(False, registry)
            self.assertFalse(launcher.startup_enabled(registry))


if __name__ == "__main__":
    unittest.main()
