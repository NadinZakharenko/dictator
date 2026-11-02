import unittest
import winreg

from dictator.tray import autostart_enabled, set_autostart

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Dictator"


def _saved_autostart() -> tuple[object, int] | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, _RUN_VALUE)
    except FileNotFoundError:
        return None
    return value, kind


def _restore_autostart(saved: tuple[object, int] | None) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if saved is None:
            try:
                winreg.DeleteValue(key, _RUN_VALUE)
            except FileNotFoundError:
                return
            return
        winreg.SetValueEx(key, _RUN_VALUE, 0, saved[1], saved[0])


class AutostartTests(unittest.TestCase):
    def test_toggle_restores_the_previous_run_value(self) -> None:
        saved = _saved_autostart()
        self.addCleanup(_restore_autostart, saved)
        set_autostart(True)
        self.assertTrue(autostart_enabled())
        set_autostart(False)
        self.assertFalse(autostart_enabled())
        _restore_autostart(saved)
        self.assertEqual(_saved_autostart(), saved)


if __name__ == "__main__":
    unittest.main()
