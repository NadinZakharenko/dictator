"""Пользовательский config.json и общая папка моделей."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Dictator"
MODES = ("ptt", "toggle")
MODELS = ("base", "small")
LANGUAGES = ("ru", "auto")
INSERT_MODES = ("unicode", "paste")


def appdata_dir() -> Path:
    root = os.environ.get("APPDATA")
    if not root:
        root = str(Path.home() / "AppData" / "Roaming")
    return Path(root) / APP_NAME


def default_model_dir() -> Path:
    root = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return Path(root) / APP_NAME / "models"


def config_file() -> Path:
    return appdata_dir() / "config.json"


def ensure_model_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".dictator_write_test"
    probe.write_text("", encoding="utf-8")
    probe.unlink(missing_ok=True)


@dataclass
class Config:
    hotkey: str = "f9"
    mode: str = "ptt"
    model: str = "base"
    language: str = "ru"
    sound: bool = True
    silence_seconds: float = 1.5
    initial_prompt: str = ""
    device: str | int | None = None
    model_dir: str = ""
    insert_mode: str = "unicode"
    vad_threshold: float = 0.5
    llm: bool = False

    def resolved_model_dir(self) -> Path:
        if self.model_dir.strip():
            return Path(self.model_dir).expanduser()
        return default_model_dir()

    def language_code(self) -> str | None:
        if self.language == "ru":
            return "ru"
        if self.language == "auto":
            return None
        raise AssertionError(f"unsupported language: {self.language}")

    def save(self, path: Path | None = None) -> None:
        target = path or config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        target = path or config_file()
        if not target.exists():
            config = cls()
            config.save(target)
            return config
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise json.JSONDecodeError("config root must be an object", str(target), 0)
        return cls(
            hotkey=_hotkey(raw.get("hotkey"), target),
            mode=_choice(raw.get("mode"), MODES, "ptt", "mode", target),
            model=_choice(raw.get("model"), MODELS, "base", "model", target),
            language=_choice(raw.get("language"), LANGUAGES, "ru", "language", target),
            sound=_bool(raw.get("sound"), True, "sound", target),
            silence_seconds=_silence(raw.get("silence_seconds"), target),
            initial_prompt=_text(raw.get("initial_prompt")),
            device=_device(raw.get("device")),
            model_dir=_text(raw.get("model_dir")),
            insert_mode=_choice(
                raw.get("insert_mode"), INSERT_MODES, "unicode", "insert_mode", target
            ),
            vad_threshold=_threshold(raw.get("vad_threshold"), target),
            llm=_bool(raw.get("llm"), False, "llm", target),
        )


def _choice(
    value: object,
    allowed: tuple[str, ...],
    default: str,
    field: str,
    path: Path,
) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    if value is not None:
        log.warning("%s: поле %s=%r заменено на %s", path, field, value, default)
    return default


def _hotkey(value: object, path: Path) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    if value is not None:
        log.warning("%s: поле hotkey=%r заменено на f9", path, value)
    return "f9"


def _bool(value: object, default: bool, field: str, path: Path) -> bool:
    if isinstance(value, bool):
        return value
    if value is not None:
        log.warning("%s: поле %s=%r заменено на %s", path, field, value, default)
    return default


def _silence(value: object, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            log.warning("%s: поле silence_seconds=%r заменено на 1.5", path, value)
        return 1.5
    seconds = float(value)
    if seconds <= 0:
        log.warning("%s: поле silence_seconds=%r заменено на 1.5", path, value)
        return 1.5
    return seconds


def _threshold(value: object, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            log.warning("%s: поле vad_threshold=%r заменено на 0.5", path, value)
        return 0.5
    threshold = float(value)
    if threshold <= 0 or threshold >= 1:
        log.warning("%s: поле vad_threshold=%r заменено на 0.5", path, value)
        return 0.5
    return threshold


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _device(value: object) -> str | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
