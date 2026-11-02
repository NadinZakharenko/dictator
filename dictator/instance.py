"""Один экземпляр Dictator на сессию Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    """Держит мьютекс, пока живёт объект. Второй экземпляр в сессии его не получает."""

    def __init__(self, name: str = "Local\\Dictator") -> None:
        handle = _kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, "CreateMutexW failed")
        self._handle = handle
        self.already_running = error == ERROR_ALREADY_EXISTS
        if self.already_running:
            self.close()

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            _kernel32.CloseHandle(handle)
