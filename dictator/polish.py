"""Локальная правка уже распознанного текста. Аудио сюда не передаётся."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable

from llama_cpp import Llama

from dictator.config import Config

log = logging.getLogger(__name__)

_MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
_SYSTEM = (
    "Ты фильтр диктовки. Удали латинские обрывки и знаки-мусор. "
    "Неразборчивый кусок замени ближайшим русским словом по остаткам букв. "
    "Ответ — только готовая фраза."
)
_EXAMPLES = (
    ("создать приложениеg/n/d*.bd", "создать приложение"),
    ("меню навив.ю.+", "меню навигации"),
)
_CYRILLIC_WORD = re.compile(r"[А-Яа-яЁё]{4,}")
_PREFIXES = (
    "исправленный текст:",
    "исправлено:",
    "текст:",
)


Notice = Callable[[str], None]


class PolishService:
    def __init__(self, get_config: Callable[[], Config], on_notice: Notice) -> None:
        self._get_config = get_config
        self._on_notice = on_notice
        self._lock = threading.Lock()
        self._model: Llama | None = None
        self._closed = False

    def preload(self) -> None:
        if not self._get_config().llm or self._closed:
            return
        threading.Thread(target=self._preload, name="polish-load", daemon=True).start()

    def correct(self, text: str) -> str:
        source = text.strip()
        if not source or not self._get_config().llm or self._closed:
            return text
        try:
            with self._lock:
                self._ensure()
                raw = self._generate(source)
        except Exception:
            log.exception("правка текста")
            self._on_notice("Правка не выполнена, ввожу текст как распознан")
            return text
        cleaned = keep_dictation(source, raw)
        if cleaned == source:
            log.info("правка оставлена без изменений, %s символов", len(source))
        else:
            log.info("правка: %s → %s символов", len(source), len(cleaned))
        return cleaned

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._model = None

    def _preload(self) -> None:
        try:
            with self._lock:
                if self._closed or not self._get_config().llm:
                    return
                self._ensure()
        except Exception:
            log.exception("загрузка модели правки")
            self._on_notice("Модель правки не загрузилась. Ввожу текст как распознан")

    def _ensure(self) -> None:
        if self._model is not None:
            return
        path = self._get_config().resolved_model_dir() / "llm" / _MODEL_FILE
        if not path.is_file():
            raise FileNotFoundError(path)
        log.info("загружаю модель правки: %s", path)
        self._on_notice("Загружаю модель правки…")
        self._model = Llama(
            model_path=str(path),
            n_ctx=2048,
            n_threads=4,
            n_gpu_layers=0,
            verbose=False,
        )
        log.info("модель правки готова")

    def _generate(self, text: str) -> str:
        if self._model is None:
            raise RuntimeError("модель правки не загружена")
        messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
        for sample, answer in _EXAMPLES:
            messages.append({"role": "user", "content": sample})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": text})
        result = self._model.create_chat_completion(
            messages=messages,
            temperature=0.0,
            max_tokens=min(400, max(64, len(text))),
        )
        choices = result["choices"]
        message = choices[0]["message"]["content"]
        if not isinstance(message, str):
            return ""
        return message


def keep_dictation(source: str, candidate: str) -> str:
    """Принимает правку только если она похожа на ту же фразу, а не на пересказ."""
    cleaned = _unwrap(candidate)
    if not cleaned:
        return source
    if len(cleaned) > max(len(source) + 80, int(len(source) * 1.6)):
        return source
    if len(source) > 20 and len(cleaned) < int(len(source) * 0.45):
        return source
    source_words = _cyrillic_words(source)
    if source_words and len(source_words & _cyrillic_words(cleaned)) * 2 < len(source_words):
        return source
    return cleaned


def _cyrillic_words(text: str) -> set[str]:
    return {word.lower() for word in _CYRILLIC_WORD.findall(text)}


def _unwrap(candidate: str) -> str:
    cleaned = candidate.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.strip("`").strip()
    lowered = cleaned.lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lowered = cleaned.lower()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("«") and cleaned.endswith("»"):
        cleaned = cleaned[1:-1].strip()
    if "\n" in cleaned:
        cleaned = cleaned.splitlines()[0].strip()
    return cleaned
