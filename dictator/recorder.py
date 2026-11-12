"""Захват микрофона 16 кГц и автостоп по тишине."""

from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from faster_whisper.utils import get_assets_path
from faster_whisper.vad import SileroVADModel

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
CONTEXT_SAMPLES = 64
MAX_RECORDING_SECONDS = 120
_LEVEL_FALLBACK = 0.02


@dataclass(frozen=True)
class Recording:
    samples: np.ndarray
    heard_speech: bool


class SilenceTracker:
    """Останавливает запись после тишины, но только если речь уже была."""

    def __init__(self, silence_seconds: float, sample_rate: int = SAMPLE_RATE) -> None:
        if silence_seconds <= 0:
            raise ValueError("silence_seconds must be positive")
        self._limit = int(silence_seconds * sample_rate)
        self._run = 0
        self._heard_speech = False

    @property
    def heard_speech(self) -> bool:
        return self._heard_speech

    def feed(self, is_speech: bool, sample_count: int) -> bool:
        if is_speech:
            self._heard_speech = True
            self._run = 0
            return False
        if not self._heard_speech:
            return False
        self._run += sample_count
        return self._run >= self._limit


class StreamingVad:
    """Та же Silero-модель, что у faster-whisper, по одному окну в 512 сэмплов."""

    def __init__(self) -> None:
        self._model: SileroVADModel | None
        try:
            path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
            self._model = SileroVADModel(path)
        except Exception:
            log.exception("Silero VAD недоступна, автостоп по уровню сигнала")
            self._model = None
        self._threshold = 0.5
        self._neg_threshold = 0.35
        self._in_speech = False
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)

    def reset(self, threshold: float) -> None:
        self._threshold = threshold
        self._neg_threshold = max(threshold - 0.15, 0.01)
        self._in_speech = False
        self._h.fill(0)
        self._c.fill(0)
        self._context.fill(0)

    def is_speech(self, frame: np.ndarray) -> bool:
        if self._model is None:
            return float(np.max(np.abs(frame))) >= _LEVEL_FALLBACK
        window = np.concatenate((self._context, frame)).reshape(1, -1)
        output, self._h, self._c = self._model.session.run(
            None,
            {
                "input": np.ascontiguousarray(window, dtype=np.float32),
                "h": self._h,
                "c": self._c,
            },
        )
        self._context = np.array(frame[-CONTEXT_SAMPLES:], dtype=np.float32, copy=True)
        probability = float(output[0])
        if probability >= self._threshold:
            self._in_speech = True
        elif probability < self._neg_threshold:
            self._in_speech = False
        return self._in_speech


class Recorder:
    def __init__(self, on_auto_stop: Callable[[], None]) -> None:
        self._on_auto_stop = on_auto_stop
        self._vad = StreamingVad()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stream: sd.InputStream | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._chunks: list[np.ndarray] = []
        self._tracker = SilenceTracker(1.5)
        self._channels = 1
        self._actual_rate = SAMPLE_RATE
        self._triggered = False
        self._rate_warned = False

    def start(
        self,
        device: str | int | None,
        silence_seconds: float,
        vad_threshold: float,
    ) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("запись уже идёт")
            self._stop = threading.Event()
            self._queue = queue.Queue()
            self._chunks = []
            self._tracker = SilenceTracker(silence_seconds)
            self._triggered = False
            self._rate_warned = False
            self._vad.reset(vad_threshold)
            self._open_stream(device)
            self._thread = threading.Thread(target=self._loop, name="recorder", daemon=True)
            self._thread.start()

    def stop(self) -> Recording:
        self._stop.set()
        thread = self._thread
        self._close_stream()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._drain()
        with self._lock:
            self._thread = None
            chunks = self._chunks
            self._chunks = []
            heard = self._tracker.heard_speech
        if not chunks:
            return Recording(np.empty(0, dtype=np.float32), heard)
        return Recording(np.concatenate(chunks).astype(np.float32, copy=False), heard)

    def _open_stream(self, device: str | int | None) -> None:
        resolved = resolve_input_device(device)
        native_rate, native_channels = _device_format(resolved)
        extra = wasapi_settings(resolved)
        attempts = _open_attempts(native_rate, native_channels, extra)
        errors: list[str] = []
        for rate, channels, settings in attempts:
            stream: sd.InputStream | None = None
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=channels,
                    dtype="float32",
                    device=resolved,
                    callback=self._on_audio,
                    blocksize=FRAME_SAMPLES,
                    extra_settings=settings,
                )
                stream.start()
            except sd.PortAudioError as exc:
                errors.append(f"{rate} Гц, {channels} кан.: {exc}")
                log.info("не открылся вход %s Гц channels=%s: %s", rate, channels, exc)
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        log.exception("не удалось закрыть неоткрытый микрофон")
                continue
            self._stream = stream
            self._channels = channels
            self._actual_rate = int(stream.samplerate)
            log.info(
                "микрофон открыт: device=%s channels=%s rate=%s",
                resolved,
                channels,
                self._actual_rate,
            )
            return
        detail = "; ".join(errors) if errors else "нет устройства записи"
        raise sd.PortAudioError(detail)

    def _on_audio(self, indata: np.ndarray, _frames: int, _time: object, status: sd.CallbackFlags) -> None:
        if status:
            log.warning("аудиопоток: %s", status)
        self._queue.put(_capture_block(indata, self._channels))

    def _loop(self) -> None:
        pending = np.empty(0, dtype=np.float32)
        total = 0
        max_samples = MAX_RECORDING_SECONDS * SAMPLE_RATE
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                block = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            converted = self._as_16k(block)
            self._chunks.append(converted)
            total += len(converted)
            if total >= max_samples:
                self._fire_auto_stop("max duration")
                break
            if self._stop.is_set():
                continue
            pending = np.concatenate((pending, converted))
            while len(pending) >= FRAME_SAMPLES:
                frame = pending[:FRAME_SAMPLES]
                pending = pending[FRAME_SAMPLES:]
                if self._tracker.feed(self._vad.is_speech(frame), FRAME_SAMPLES):
                    self._fire_auto_stop("silence")
                    return

    def _as_16k(self, block: np.ndarray) -> np.ndarray:
        if self._actual_rate == SAMPLE_RATE or len(block) == 0:
            return block
        if not self._rate_warned:
            self._rate_warned = True
            log.warning(
                "устройство дало %s Гц вместо %s, пересчитываю линейно",
                self._actual_rate,
                SAMPLE_RATE,
            )
        target = max(1, int(round(len(block) * SAMPLE_RATE / self._actual_rate)))
        source_x = np.linspace(0.0, 1.0, num=len(block), endpoint=False)
        target_x = np.linspace(0.0, 1.0, num=target, endpoint=False)
        return np.interp(target_x, source_x, block).astype(np.float32)

    def _fire_auto_stop(self, reason: str) -> None:
        if self._triggered:
            return
        self._triggered = True
        self._stop.set()
        log.info("автостоп: %s", reason)
        threading.Thread(target=self._on_auto_stop, name="auto-stop", daemon=True).start()

    def _drain(self) -> None:
        while True:
            try:
                block = self._queue.get_nowait()
            except queue.Empty:
                return
            self._chunks.append(self._as_16k(block))

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            log.exception("не удалось закрыть микрофон")


def _capture_block(indata: np.ndarray, channels: int) -> np.ndarray:
    # PortAudio переиспользует indata после callback. Срез моноканала уже непрерывный,
    # и ascontiguousarray вернул бы тот же буфер: к моменту распознавания в нём остался
    # только последний кадр, поэтому Silero выбрасывала всю запись.
    source = indata[:, 0] if channels == 1 else indata.mean(axis=1)
    return np.array(source, dtype=np.float32, copy=True)


def _device_format(device: int | str | None) -> tuple[int, int]:
    try:
        info = sd.query_devices(device, "input") if device is not None else sd.query_devices(kind="input")
    except (sd.PortAudioError, ValueError):
        return SAMPLE_RATE, 1
    rate = int(info["default_samplerate"]) or SAMPLE_RATE
    channels = max(1, int(info["max_input_channels"]))
    return rate, channels


def _open_attempts(
    native_rate: int,
    native_channels: int,
    extra: sd.WasapiSettings | None,
) -> list[tuple[int, int, sd.WasapiSettings | None]]:
    rates = [SAMPLE_RATE] if native_rate == SAMPLE_RATE else [SAMPLE_RATE, native_rate]
    channels = [1] if native_channels == 1 else [1, native_channels]
    attempts: list[tuple[int, int, sd.WasapiSettings | None]] = []
    if extra is not None:
        attempts.append((SAMPLE_RATE, 1, extra))
    for rate in rates:
        for count in channels:
            attempts.append((rate, count, None))
    return attempts


def resolve_input_device(device: str | int | None) -> int | str | None:
    if device is None:
        return None
    if isinstance(device, int):
        return device
    partial: list[int] = []
    for index, info in enumerate(sd.query_devices()):
        if int(info["max_input_channels"]) < 1:
            continue
        name = str(info["name"])
        if name == device:
            return index
        if device.lower() in name.lower():
            partial.append(index)
    if len(partial) == 1:
        return partial[0]
    log.warning("устройство %r не найдено, беру устройство по умолчанию", device)
    return None


def wasapi_settings(device: int | str | None) -> sd.WasapiSettings | None:
    try:
        info = sd.query_devices(device, "input") if device is not None else sd.query_devices(kind="input")
        host = sd.query_hostapis(int(info["hostapi"]))
    except (sd.PortAudioError, ValueError):
        log.info("не удалось узнать драйвер устройства, открываю без WASAPI")
        return None
    if "WASAPI" not in str(host["name"]).upper():
        return None
    return sd.WasapiSettings(exclusive=False, auto_convert=True)


def log_input_devices() -> None:
    try:
        devices = sd.query_devices()
    except sd.PortAudioError:
        log.exception("список устройств записи недоступен")
        return
    for index, info in enumerate(devices):
        if int(info["max_input_channels"]) > 0:
            log.info("устройство записи %s: %s", index, info["name"])
