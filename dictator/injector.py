"""Ввод распознанного текста в активное окно."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import pyperclip

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56
PASTE_SETTLE_SECONDS = 0.2
_BATCH_UNITS = 32

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

_user32 = ctypes.WinDLL("user32", use_last_error=True)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    )


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    )


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUT_UNION(ctypes.Union):
    _fields_ = (
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    )


_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT


def normalize_dictation(text: str) -> str:
    """Убирает переводы строк и табы, чтобы Enter не отправил промпт сам."""
    cleaned = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return cleaned.strip()


def utf16_code_units(text: str) -> list[int]:
    encoded = text.encode("utf-16-le")
    return [
        int.from_bytes(encoded[index : index + 2], "little")
        for index in range(0, len(encoded), 2)
    ]


def insert_text(text: str, mode: str) -> bool:
    """Печатает непустой текст. Пустая строка не трогает активное окно."""
    normalized = normalize_dictation(text)
    if not normalized:
        return False
    if mode == "unicode":
        type_unicode(normalized)
        return True
    if mode == "paste":
        paste_text(normalized)
        return True
    raise AssertionError(f"unsupported insert mode: {mode}")


def type_unicode(text: str) -> None:
    units = utf16_code_units(text)
    for start in range(0, len(units), _BATCH_UNITS):
        chunk = units[start : start + _BATCH_UNITS]
        _send(_unicode_inputs(chunk), len(chunk) * 2)


def paste_text(text: str) -> None:
    """Запасной путь: в буфере сохраняется и восстанавливается только текст."""
    previous = pyperclip.paste()
    try:
        pyperclip.copy(text)
        _send(_ctrl_v_inputs(), 4)
        time.sleep(PASTE_SETTLE_SECONDS)
    finally:
        try:
            pyperclip.copy(previous)
        except Exception:
            log.exception("не удалось вернуть текст в буфер обмена")


def _unicode_inputs(units: list[int]) -> ctypes.Array[INPUT]:
    events = (INPUT * (len(units) * 2))()
    for index, unit in enumerate(units):
        events[index * 2].type = INPUT_KEYBOARD
        events[index * 2].ki.wScan = unit
        events[index * 2].ki.dwFlags = KEYEVENTF_UNICODE
        events[index * 2 + 1].type = INPUT_KEYBOARD
        events[index * 2 + 1].ki.wScan = unit
        events[index * 2 + 1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    return events


def _ctrl_v_inputs() -> ctypes.Array[INPUT]:
    sequence = (
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )
    events = (INPUT * len(sequence))()
    for index, (virtual_key, flags) in enumerate(sequence):
        events[index].type = INPUT_KEYBOARD
        events[index].ki.wVk = virtual_key
        events[index].ki.dwFlags = flags
    return events


def _send(events: ctypes.Array[INPUT], expected: int) -> None:
    sent = _user32.SendInput(expected, events, ctypes.sizeof(INPUT))
    if sent != expected:
        error = ctypes.get_last_error()
        raise OSError(error, f"SendInput отправил {sent} из {expected}")
