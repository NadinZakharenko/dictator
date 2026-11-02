"""Ввод Unicode в собственное поле, без чужих окон."""

from __future__ import annotations

import ctypes
import time
import unittest
from ctypes import wintypes

from dictator.injector import type_unicode

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetFocus.argtypes = (wintypes.HWND,)
user32.SetFocus.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = ()
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.PeekMessageW.argtypes = (
    ctypes.c_void_p,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
)
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = (ctypes.c_void_p,)
user32.DispatchMessageW.argtypes = (ctypes.c_void_p,)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WS_OVERLAPPED = 0x00000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
PM_REMOVE = 0x0001


class MSG(ctypes.Structure):
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    )


def _pump() -> None:
    message = MSG()
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


class OwnWindowTypingTests(unittest.TestCase):
    def test_unicode_reaches_an_edit_control_we_own(self) -> None:
        hwnd = user32.CreateWindowExW(
            0,
            "Edit",
            "",
            WS_OVERLAPPED | WS_VISIBLE | WS_BORDER,
            80,
            80,
            480,
            80,
            None,
            None,
            None,
            None,
        )
        self.assertTrue(hwnd)
        self.addCleanup(lambda: user32.DestroyWindow(hwnd))
        user32.ShowWindow(hwnd, 5)
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        current = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(current, foreground_thread, True)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        user32.AttachThreadInput(current, foreground_thread, False)
        _pump()
        time.sleep(0.2)
        if user32.GetForegroundWindow() != hwnd:
            self.skipTest("собственное окно не стало активным, ввод в чужие окна не проверялся")
        type_unicode("Привет 15")
        time.sleep(0.2)
        _pump()
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        self.assertEqual(buffer.value, "Привет 15")


if __name__ == "__main__":
    unittest.main()
