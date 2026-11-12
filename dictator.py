"""Вход Dictator: один экземпляр на сессию, хоткей, запись, распознавание, ввод."""

from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import sys
import threading
from dataclasses import asdict

import sounddevice as sd

from dictator.asr import AsrService
from dictator.config import MODES, Config, appdata_dir, config_file, ensure_model_dir
from dictator.hotkey import HotkeyController
from dictator.injector import insert_text
from dictator.instance import SingleInstance
from dictator.polish import PolishService
from dictator.recorder import Recorder, log_input_devices
from dictator.tray import Tray, TrayCallbacks, play_start, play_stop

log = logging.getLogger(__name__)

_MB_ICONINFORMATION = 0x40
_MB_SETFOREGROUND = 0x00010000


class DictatorApp:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._config_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "idle"
        self._ptt_held = False
        self._shutting_down = False
        self._recorder = Recorder(self._end)
        self._hotkey = HotkeyController(self._on_press, self._on_release)
        self._asr = AsrService(self._snapshot, self._notify)
        self._polish = PolishService(self._snapshot, self._notify)
        self._tray = Tray(
            self._snapshot,
            TrayCallbacks(
                set_mode=self.set_mode,
                set_model=self.set_model,
                set_language=self.set_language,
                toggle_sound=self.toggle_sound,
                toggle_llm=self.toggle_llm,
                open_config=self.open_config,
                reload_config=self.reload_config,
                quit_app=self.quit,
            ),
        )

    def run(self) -> None:
        log_input_devices()
        self._prepare_model_dir()
        self._bind_hotkey()
        self._asr.start()
        self._polish.preload()
        self._tray.run()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._hotkey.close()
        try:
            self._recorder.stop()
        except Exception:
            log.exception("остановка записи при выходе")
        self._asr.close()
        self._polish.close()

    def quit(self) -> None:
        self._tray.stop()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise AssertionError(f"unsupported mode: {mode}")
        with self._config_lock:
            self._config.mode = mode
            self._config.save()
            hotkey = self._config.hotkey
        self._bind_hotkey(hotkey, mode)
        self._tray.refresh()

    def set_model(self, model: str) -> None:
        if model != "base" and model != "small":
            raise AssertionError(f"unsupported model: {model}")
        with self._config_lock:
            self._config.model = model
            self._config.save()
        self._asr.preload()
        self._tray.refresh()

    def set_language(self, language: str) -> None:
        if language != "ru" and language != "auto":
            raise AssertionError(f"unsupported language: {language}")
        with self._config_lock:
            self._config.language = language
            self._config.save()
        self._tray.refresh()

    def toggle_sound(self) -> None:
        with self._config_lock:
            self._config.sound = not self._config.sound
            self._config.save()
        self._tray.refresh()

    def toggle_llm(self) -> None:
        with self._config_lock:
            self._config.llm = not self._config.llm
            self._config.save()
            enabled = self._config.llm
        if enabled:
            self._polish.preload()
        self._tray.refresh()

    def open_config(self) -> None:
        path = config_file()
        with self._config_lock:
            if not path.exists():
                self._config.save(path)
        subprocess.Popen(["notepad.exe", str(path)])

    def reload_config(self) -> None:
        try:
            loaded = Config.load()
        except (OSError, json.JSONDecodeError) as exc:
            log.exception("чтение конфига")
            self._notify(f"Конфиг не прочитан: {exc}")
            return
        with self._config_lock:
            self._config = loaded
            hotkey = loaded.hotkey
            mode = loaded.mode
        self._bind_hotkey(hotkey, mode)
        self._prepare_model_dir()
        self._asr.preload()
        self._polish.preload()
        self._tray.refresh()
        self._notify("Настройки применены")

    def _on_press(self, mode: str) -> None:
        if mode == "ptt":
            with self._state_lock:
                self._ptt_held = True
            threading.Thread(target=self._begin, name="record-start", daemon=True).start()
            return
        if mode == "toggle":
            with self._state_lock:
                active = self._state in ("opening", "recording")
            target = self._end if active else self._begin
            threading.Thread(target=target, name="record-toggle", daemon=True).start()
            return
        raise AssertionError(f"unsupported hotkey mode: {mode}")

    def _on_release(self, mode: str) -> None:
        if mode != "ptt":
            if mode != "toggle":
                raise AssertionError(f"unsupported hotkey mode: {mode}")
            return
        with self._state_lock:
            self._ptt_held = False
        threading.Thread(target=self._end, name="record-stop", daemon=True).start()

    def _begin(self) -> None:
        mode = self._snapshot().mode
        with self._state_lock:
            if self._state != "idle":
                return
            if mode == "ptt" and not self._ptt_held:
                return
            self._state = "opening"
        snapshot = self._snapshot()
        try:
            self._recorder.start(snapshot.device, snapshot.silence_seconds, snapshot.vad_threshold)
        except Exception as exc:
            log.exception("микрофон")
            with self._state_lock:
                self._state = "idle"
            self._notify(f"Микрофон недоступен: {exc}")
            return
        with self._state_lock:
            cancel = self._state == "cancel" or (mode == "ptt" and not self._ptt_held)
            self._state = "stopping" if cancel else "recording"
        if cancel:
            recording = self._recorder.stop()
            with self._state_lock:
                self._state = "idle"
            if recording.heard_speech and recording.samples.size:
                self._asr.submit(recording.samples, self._on_text, self._notify)
            return
        self._tray.set_recording(True)
        if snapshot.sound:
            play_start()
        log.info("запись начата")

    def _end(self) -> None:
        with self._state_lock:
            if self._state == "opening":
                self._state = "cancel"
                return
            if self._state != "recording":
                return
            self._state = "stopping"
        snapshot = self._snapshot()
        recording = self._recorder.stop()
        with self._state_lock:
            self._state = "idle"
        self._tray.set_recording(False)
        if snapshot.sound:
            play_stop()
        log.info(
            "запись остановлена, %.2f с, речь=%s",
            recording.samples.size / 16000,
            recording.heard_speech,
        )
        if not recording.heard_speech or recording.samples.size == 0:
            self._notify("Пустая запись")
            return
        self._asr.submit(recording.samples, self._on_text, self._notify)

    def _on_text(self, text: str) -> None:
        text = self._polish.correct(text)
        mode = self._snapshot().insert_mode
        try:
            typed = insert_text(text, mode)
        except Exception as exc:
            log.exception("ввод текста")
            self._notify(f"Не удалось ввести текст: {exc}")
            return
        if not typed:
            self._notify("Ничего не распознано")
            return
        log.info("введён текст, %s символов, режим %s", len(text.strip()), mode)

    def _snapshot(self) -> Config:
        with self._config_lock:
            return Config(**asdict(self._config))

    def _prepare_model_dir(self) -> None:
        path = self._snapshot().resolved_model_dir()
        try:
            ensure_model_dir(path)
        except OSError as exc:
            log.exception("папка моделей")
            self._notify(
                f"Нет доступа к папке моделей {path}. Укажите model_dir в конфиге. {exc}"
            )

    def _bind_hotkey(self, hotkey: str | None = None, mode: str | None = None) -> None:
        snapshot = self._snapshot()
        selected_hotkey = hotkey or snapshot.hotkey
        selected_mode = mode or snapshot.mode
        try:
            self._hotkey.apply(selected_hotkey, selected_mode)
        except Exception as exc:
            log.exception("хоткей")
            self._notify(f"Хоткей {selected_hotkey} не включился: {exc}")

    def _notify(self, message: str) -> None:
        self._tray.notify(message)


def setup_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.handlers.clear()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    try:
        directory = appdata_dir()
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(directory / "dictator.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        stream.stream.write(f"не удалось открыть журнал: {exc}\n")


def _write_line(message: str) -> None:
    stream = sys.stdout or sys.stderr
    if stream is None:
        log.info("%s", message)
        return
    try:
        stream.write(message + "\n")
        stream.flush()
    except Exception:
        log.info("%s", message)


def run_check() -> int:
    setup_logging()
    try:
        config = Config.load()
        ensure_model_dir(config.resolved_model_dir())
        sd.query_devices()
    except Exception as exc:
        log.exception("проверка")
        _write_line(f"check failed: {exc}")
        return 1
    log.info("проверка пройдена, модель: %s", config.resolved_model_dir())
    _write_line("ok")
    return 0


def _already_running_notice() -> None:
    ctypes.windll.user32.MessageBoxW(
        None,
        "Dictator уже запущен в этой сессии.",
        "Dictator",
        _MB_ICONINFORMATION | _MB_SETFOREGROUND,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        return run_check()
    setup_logging()
    instance = SingleInstance()
    if instance.already_running:
        log.info("второй экземпляр закрывается")
        _already_running_notice()
        return 0
    try:
        config = Config.load()
    except (OSError, json.JSONDecodeError):
        log.exception("конфиг повреждён, беру значения по умолчанию")
        config = Config()
    app = DictatorApp(config)
    try:
        app.run()
    finally:
        app.shutdown()
        instance.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
