"""Распознавание в одном фоновом потоке. Модель загружается один раз и остаётся в памяти."""

from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

from dictator.config import Config

log = logging.getLogger(__name__)

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

Notice = Callable[[str], None]


@dataclass(frozen=True)
class _Job:
    audio: np.ndarray
    on_text: Callable[[str], None]
    on_error: Callable[[str], None]


class _Warmup:
    pass


class _Stop:
    pass


_WARMUP = _Warmup()
_STOP = _Stop()


class AsrService:
    def __init__(self, get_config: Callable[[], Config], on_notice: Notice) -> None:
        self._get_config = get_config
        self._on_notice = on_notice
        self._queue: queue.Queue[_Job | _Warmup | _Stop] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="asr", daemon=True)
        self._model: WhisperModel | None = None
        self._key: tuple[str, str] | None = None
        self._closed = False

    def start(self) -> None:
        self._thread.start()
        self._queue.put(_WARMUP)

    def preload(self) -> None:
        self._queue.put(_WARMUP)

    def submit(
        self,
        audio: np.ndarray,
        on_text: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._queue.put(_Job(np.ascontiguousarray(audio, dtype=np.float32), on_text, on_error))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(_STOP)
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if isinstance(item, _Stop):
                return
            try:
                self._ensure_model()
            except Exception as exc:
                log.exception("загрузка модели")
                if isinstance(item, _Job):
                    item.on_error(f"Не удалось загрузить модель: {exc}")
                else:
                    self._on_notice(f"Не удалось загрузить модель: {exc}")
                continue
            if isinstance(item, _Warmup):
                log.info("модель готова: %s", self._key)
                continue
            if isinstance(item, _Job):
                self._run_job(item)
                continue
            raise AssertionError(f"unsupported asr item: {type(item)!r}")

    def _run_job(self, job: _Job) -> None:
        try:
            text = self._transcribe(job.audio)
        except Exception as exc:
            log.exception("распознавание")
            job.on_error(f"Ошибка распознавания: {exc}")
            return
        try:
            job.on_text(text)
        except Exception:
            log.exception("обработчик текста")

    def _ensure_model(self) -> None:
        config = self._get_config()
        directory = config.resolved_model_dir()
        key = (config.model, str(directory))
        if self._model is not None and self._key == key:
            return
        common = {
            "device": "cpu",
            "compute_type": "int8",
            "download_root": str(directory),
            "cpu_threads": 4,
        }
        try:
            model = WhisperModel(config.model, local_files_only=True, **common)
        except Exception:
            log.info("модели %s нет в %s, скачиваю один раз", config.model, directory)
            self._on_notice(f"Скачиваю модель «{config.model}». Это один раз.")
            model = WhisperModel(config.model, local_files_only=False, **common)
        self._model = model
        self._key = key

    def _transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("модель не загружена")
        config = self._get_config()
        prompt = config.initial_prompt.strip() or None
        segments, _info = self._model.transcribe(
            audio,
            language=config.language_code(),
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return "".join(segment.text for segment in segments)
