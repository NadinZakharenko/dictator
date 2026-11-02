import json
import tempfile
import unittest
from pathlib import Path

from dictator.config import Config, ensure_model_dir


class ConfigTests(unittest.TestCase):
    def test_roundtrip_keeps_russian_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = Config(initial_prompt="ZCode, Kubernetes", mode="toggle", model="small")
            original.save(path)
            loaded = Config.load(path)
        self.assertEqual(loaded.initial_prompt, "ZCode, Kubernetes")
        self.assertEqual(loaded.mode, "toggle")
        self.assertEqual(loaded.model, "small")
        self.assertEqual(loaded.language_code(), "ru")

    def test_invalid_fields_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "hold",
                        "model": "large",
                        "language": "de",
                        "silence_seconds": 0,
                        "vad_threshold": 2,
                        "insert_mode": "keys",
                        "sound": "yes",
                        "hotkey": "",
                    }
                ),
                encoding="utf-8",
            )
            loaded = Config.load(path)
        self.assertEqual(loaded.mode, "ptt")
        self.assertEqual(loaded.model, "base")
        self.assertEqual(loaded.language, "ru")
        self.assertEqual(loaded.silence_seconds, 1.5)
        self.assertEqual(loaded.vad_threshold, 0.5)
        self.assertEqual(loaded.insert_mode, "unicode")
        self.assertTrue(loaded.sound)
        self.assertEqual(loaded.hotkey, "f9")
        self.assertEqual(loaded.language_code(), "ru")

    def test_auto_language_has_no_code(self) -> None:
        self.assertIsNone(Config(language="auto").language_code())

    def test_missing_file_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "config.json"
            loaded = Config.load(path)
            self.assertTrue(path.exists())
        self.assertEqual(loaded.hotkey, "f9")

    def test_model_dir_is_created_and_writable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models"
            ensure_model_dir(path)
            self.assertTrue(path.is_dir())
            self.assertEqual(list(path.iterdir()), [])

    def test_custom_model_dir_expands(self) -> None:
        config = Config(model_dir="")
        self.assertTrue(config.resolved_model_dir().name == "models")


if __name__ == "__main__":
    unittest.main()
