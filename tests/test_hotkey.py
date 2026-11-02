import unittest

import keyboard

from dictator.hotkey import HotkeyController


class HotkeyTests(unittest.TestCase):
    def test_rebind_removes_the_previous_key(self) -> None:
        controller = HotkeyController(lambda _mode: None, lambda _mode: None)
        self.addCleanup(controller.close)
        controller.apply("f9", "ptt")
        controller.apply("f8", "toggle")
        for code in keyboard.key_to_scan_codes("f9"):
            self.assertEqual(list(keyboard._listener.blocking_keys[code]), [])
        for code in keyboard.key_to_scan_codes("f8"):
            self.assertTrue(keyboard._listener.blocking_keys[code])
        controller.close()
        for code in keyboard.key_to_scan_codes("f8"):
            self.assertEqual(list(keyboard._listener.blocking_keys[code]), [])

    def test_same_key_rebind_can_still_be_removed(self) -> None:
        controller = HotkeyController(lambda _mode: None, lambda _mode: None)
        self.addCleanup(controller.close)
        controller.apply("f9", "ptt")
        controller.apply("f9", "toggle")
        controller.apply("f8", "ptt")
        for code in keyboard.key_to_scan_codes("f9"):
            self.assertEqual(list(keyboard._listener.blocking_keys[code]), [])
        controller.close()
        for code in keyboard.key_to_scan_codes("f8"):
            self.assertEqual(list(keyboard._listener.blocking_keys[code]), [])


if __name__ == "__main__":
    unittest.main()
