"""Глобальный хоткей: удержание или переключение."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import keyboard

log = logging.getLogger(__name__)

PressHandler = Callable[[str], None]


class HotkeyController:
    def __init__(self, on_press: PressHandler, on_release: PressHandler) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._lock = threading.Lock()
        self._remove: Callable[[], None] | None = None
        self._hotkey: str | None = None
        self._down = False
        self._mode = "ptt"

    def apply(self, hotkey: str, mode: str) -> None:
        if mode != "ptt" and mode != "toggle":
            raise AssertionError(f"unsupported hotkey mode: {mode}")
        with self._lock:
            # keyboard хранит remover и под именем клавиши: старый хук надо снять до нового,
            # иначе его снятие сотрёт запись нового и тот уже не снимется.
            previous = self._hotkey
            self._drop(self._remove)
            self._remove = None
            self._hotkey = None
            try:
                self._remove = self._hook(hotkey)
            except Exception:
                if previous is not None:
                    self._remove = self._hook(previous)
                    self._hotkey = previous
                raise
            self._hotkey = hotkey
            self._mode = mode
            self._down = False
        log.info("хоткей %s, режим %s", hotkey, mode)

    def close(self) -> None:
        with self._lock:
            self._drop(self._remove)
            self._remove = None
            self._hotkey = None
            self._down = False

    def _hook(self, hotkey: str) -> Callable[[], None]:
        # Новая функция на каждую привязку: keyboard хранит хук по идентичности callback.
        def on_event(event: keyboard.KeyboardEvent) -> bool:
            if event.event_type == keyboard.KEY_DOWN:
                self._pressed()
            elif event.event_type == keyboard.KEY_UP:
                self._released()
            return False

        return keyboard.hook_key(hotkey, on_event, suppress=True)

    def _pressed(self) -> None:
        with self._lock:
            if self._down:
                return
            self._down = True
            mode = self._mode
        try:
            self._on_press(mode)
        except Exception:
            log.exception("обработчик нажатия хоткея")

    def _released(self) -> None:
        with self._lock:
            self._down = False
            mode = self._mode
        try:
            self._on_release(mode)
        except Exception:
            log.exception("обработчик отпускания хоткея")

    def _drop(self, remove: Callable[[], None] | None) -> None:
        if remove is None:
            return
        try:
            remove()
        except Exception:
            log.exception("не удалось снять хук")
