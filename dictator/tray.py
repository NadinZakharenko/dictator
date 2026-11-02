"""Иконка в трее, подменю настроек, звук и автозапуск."""

from __future__ import annotations

import logging
import sys
import threading
import winreg
import winsound
from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from dictator.config import Config

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Dictator"


class TrayCallbacks:
    def __init__(
        self,
        set_mode: Callable[[str], None],
        set_model: Callable[[str], None],
        set_language: Callable[[str], None],
        toggle_sound: Callable[[], None],
        open_config: Callable[[], None],
        reload_config: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        self.set_mode = set_mode
        self.set_model = set_model
        self.set_language = set_language
        self.toggle_sound = toggle_sound
        self.open_config = open_config
        self.reload_config = reload_config
        self.quit_app = quit_app


class Tray:
    def __init__(self, get_config: Callable[[], Config], callbacks: TrayCallbacks) -> None:
        self._get_config = get_config
        self._callbacks = callbacks
        self._recording = False
        self._ready = False
        self._lock = threading.Lock()
        self._ready_icon = _icon(False)
        self._recording_icon = _icon(True)
        self._icon: pystray.Icon | None = None
        self._pending: list[str] = []

    def run(self) -> None:
        icon = pystray.Icon("Dictator", self._ready_icon, "Dictator", self._menu())
        self._icon = icon
        icon.run(setup=self._setup)

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        with self._lock:
            icon = self._icon if self._ready else None
        if icon is None:
            return
        self._paint(icon)

    def notify(self, message: str) -> None:
        text = message.replace("\n", " ").strip()
        if len(text) > 200:
            text = text[:197] + "..."
        log.info("уведомление: %s", text)
        with self._lock:
            if not self._ready or self._icon is None:
                self._pending.append(text)
                return
            icon = self._icon
        try:
            icon.notify(text, "Dictator")
        except Exception:
            log.exception("уведомление не показано")

    def refresh(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.update_menu()
        except Exception:
            log.exception("не удалось обновить меню")

    def stop(self) -> None:
        icon = self._icon
        if icon is not None:
            icon.stop()

    def _setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        self._paint(icon)
        with self._lock:
            pending = self._pending
            self._pending = []
            self._ready = True
        for message in pending:
            try:
                icon.notify(message, "Dictator")
            except Exception:
                log.exception("отложенное уведомление не показано")

    def _paint(self, icon: pystray.Icon) -> None:
        try:
            icon.icon = self._recording_icon if self._recording else self._ready_icon
            icon.title = "Dictator — запись" if self._recording else "Dictator"
            icon.update_menu()
        except Exception:
            log.exception("не удалось обновить иконку")

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _item: "Идёт запись" if self._recording else "Готов", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Режим",
                pystray.Menu(
                    pystray.MenuItem(
                        "Удержание",
                        lambda _icon, _item: self._callbacks.set_mode("ptt"),
                        checked=lambda _item: self._get_config().mode == "ptt",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "Переключение",
                        lambda _icon, _item: self._callbacks.set_mode("toggle"),
                        checked=lambda _item: self._get_config().mode == "toggle",
                        radio=True,
                    ),
                ),
            ),
            pystray.MenuItem(
                "Модель",
                pystray.Menu(
                    pystray.MenuItem(
                        "base",
                        lambda _icon, _item: self._callbacks.set_model("base"),
                        checked=lambda _item: self._get_config().model == "base",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "small",
                        lambda _icon, _item: self._callbacks.set_model("small"),
                        checked=lambda _item: self._get_config().model == "small",
                        radio=True,
                    ),
                ),
            ),
            pystray.MenuItem(
                "Язык",
                pystray.Menu(
                    pystray.MenuItem(
                        "Русский",
                        lambda _icon, _item: self._callbacks.set_language("ru"),
                        checked=lambda _item: self._get_config().language == "ru",
                        radio=True,
                    ),
                    pystray.MenuItem(
                        "Авто",
                        lambda _icon, _item: self._callbacks.set_language("auto"),
                        checked=lambda _item: self._get_config().language == "auto",
                        radio=True,
                    ),
                ),
            ),
            pystray.MenuItem(
                "Звук",
                lambda _icon, _item: self._callbacks.toggle_sound(),
                checked=lambda _item: self._get_config().sound,
            ),
            pystray.MenuItem(
                "Автозапуск",
                self._toggle_autostart,
                checked=lambda _item: autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Открыть конфиг", lambda _icon, _item: self._callbacks.open_config()),
            pystray.MenuItem("Перечитать", lambda _icon, _item: self._callbacks.reload_config()),
            pystray.MenuItem("Выход", self._quit),
        )

    def _toggle_autostart(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            set_autostart(not autostart_enabled())
        except OSError as exc:
            log.exception("автозапуск")
            self.notify(f"Автозапуск не изменился: {exc}")
            return
        self.refresh()

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._callbacks.quit_app()


def play_start() -> None:
    _play("SystemAsterisk")


def play_stop() -> None:
    _play("SystemExclamation")


def _play(alias: str) -> None:
    try:
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    except RuntimeError:
        log.exception("звук %s", alias)


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    entry = Path(sys.argv[0]).resolve()
    return f'"{sys.executable}" "{entry}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
    except FileNotFoundError:
        return False
    return True


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            log.info("автозапуск включён: %s", launch_command())
            return
        try:
            winreg.DeleteValue(key, _RUN_VALUE)
        except FileNotFoundError:
            return
        log.info("автозапуск выключен")


def _icon(recording: bool) -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill = (196, 48, 43, 255) if recording else (47, 52, 59, 255)
    draw.ellipse((2, 2, 62, 62), fill=fill)
    draw.rounded_rectangle((26, 14, 38, 36), radius=6, fill=(255, 255, 255, 255))
    draw.arc((20, 24, 44, 46), 20, 160, fill=(255, 255, 255, 255), width=3)
    draw.line((32, 46, 32, 52), fill=(255, 255, 255, 255), width=3)
    draw.line((24, 52, 40, 52), fill=(255, 255, 255, 255), width=3)
    return image
