import ctypes
import unittest

from dictator.injector import INPUT, insert_text, normalize_dictation, utf16_code_units


class InjectorTests(unittest.TestCase):
    def test_newlines_and_tabs_become_spaces(self) -> None:
        self.assertEqual(normalize_dictation(" а\nб\tв\r "), "а б в")

    def test_empty_text_is_not_typed(self) -> None:
        self.assertFalse(insert_text(" \n\t", "unicode"))
        self.assertFalse(insert_text("", "paste"))

    def test_bmp_text_is_one_unit_per_character(self) -> None:
        self.assertEqual(utf16_code_units("Привет"), [ord(char) for char in "Привет"])

    def test_non_bmp_uses_surrogate_pair(self) -> None:
        units = utf16_code_units("🙂")
        self.assertEqual(len(units), 2)
        self.assertTrue(all(0 <= unit <= 0xFFFF for unit in units))

    def test_input_struct_matches_win64(self) -> None:
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            self.skipTest("проверка размера INPUT только для 64-bit")
        self.assertEqual(ctypes.sizeof(INPUT), 40)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(AssertionError):
            insert_text("текст", "keys")


if __name__ == "__main__":
    unittest.main()
