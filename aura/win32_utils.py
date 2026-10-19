"""Windows 原生 API 轻量封装（纯 ctypes，无 pywin32 依赖）。

提供：进程 DPI 感知、虚拟桌面尺寸、光标位置、窗口点击穿透、按键状态查询。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:  # Win8.1+ 才有 shcore
    shcore = ctypes.WinDLL("shcore")
except OSError:  # pragma: no cover - 老系统
    shcore = None

# ---- 窗口扩展样式 ----
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# ---- 系统度量 ----
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# ---- 虚拟键码 ----
VK_MAP = {
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "menu": 0x12,
    "shift": 0x10,
    "win": 0x5B, "super": 0x5B, "meta": 0x5B,
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "printscreen": 0x2C,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}

for _i in range(1, 25):  # F1 ~ F24
    VK_MAP[f"f{_i}"] = 0x6F + _i
for _i in range(10):  # 小键盘 / 主键盘数字
    VK_MAP[str(_i)] = 0x30 + _i
    VK_MAP[f"num{_i}"] = 0x60 + _i


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDisplayAffinity.restype = wintypes.BOOL

# 窗口显示亲和性：把窗口从系统截屏/捕获中排除（Win10 2004+）
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def get_window_display_affinity(hwnd: int) -> int:
    if not hwnd:
        return WDA_NONE
    value = wintypes.DWORD(0)
    try:
        user32.GetWindowDisplayAffinity(wintypes.HWND(hwnd), ctypes.byref(value))
    except Exception:
        return WDA_NONE
    return int(value.value)


def set_exclude_from_capture(hwnd: int, enabled: bool = True) -> bool:
    """让窗口不出现在屏幕捕获中（防覆盖层自反馈，也不污染录屏/截图）。

    关键点（踩过的坑）：Windows **不允许对 WS_EX_LAYERED 窗口直接设置 affinity**，
    直接调用会失败（GetLastError=8），而透明覆盖层必然是 layered 窗口。
    解决办法是临时摘掉 WS_EX_LAYERED → 设置 affinity → 立刻恢复样式，
    affinity 会保留下来，Qt 后续的 UpdateLayeredWindow 重绘也不会清除它。
    """
    if not hwnd:
        return False
    handle = wintypes.HWND(hwnd)
    target = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
    if get_window_display_affinity(hwnd) == target:
        return True  # 已是目标状态，避免无意义的样式切换
    try:
        style = _GetWindowLongPtr(handle, GWL_EXSTYLE)
        layered = bool(int(style) & WS_EX_LAYERED)
        if layered:
            _SetWindowLongPtr(handle, GWL_EXSTYLE, int(style) & ~WS_EX_LAYERED)
        ok = bool(user32.SetWindowDisplayAffinity(handle, target))
        if layered:
            _SetWindowLongPtr(handle, GWL_EXSTYLE, int(style))
        return ok and get_window_display_affinity(hwnd) == target
    except Exception:
        return False

LONG_PTR = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
_GetWindowLongPtr = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
_SetWindowLongPtr = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
_GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongPtr.restype = LONG_PTR
_SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
_SetWindowLongPtr.restype = LONG_PTR


def set_dpi_awareness(level: int = 2) -> bool:
    """设置进程 DPI 感知。2 = PER_MONITOR_AWARE_V2（Win10 1703+）。"""
    if shcore is None:
        try:
            return bool(user32.SetProcessDPIAware())
        except Exception:
            return False
    try:
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        return shcore.SetProcessDpiAwareness(level) >= 0
    except Exception:
        return False


def get_cursor_pos() -> Tuple[int, int]:
    """返回光标位置（物理像素）。"""
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def virtual_screen_rect() -> Tuple[int, int, int, int]:
    """虚拟桌面矩形 (x, y, w, h)，DPI 感知进程下为物理像素。"""
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def get_window_exstyle(hwnd: int) -> int:
    if not hwnd:
        return 0
    return int(_GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE))


def set_window_exstyle(hwnd: int, style: int) -> bool:
    if not hwnd:
        return False
    return bool(_SetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE, LONG_PTR(style)))


def set_click_through(hwnd: int, enabled: bool) -> bool:
    """开启/关闭鼠标点击穿透（同时确保分层窗口属性存在）。"""
    if not hwnd:
        return False
    style = get_window_exstyle(hwnd)
    if enabled:
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        style &= ~WS_EX_TRANSPARENT
    ok = set_window_exstyle(hwnd, style)
    # 强制刷新窗口属性
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None, 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0004 | 0x0020 | 0x0100,  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED|NOACTIVATE
    )
    return ok


def is_key_down(vk: int) -> bool:
    """按键当前是否被按下（GetAsyncKeyState 最高位）。"""
    return (user32.GetAsyncKeyState(int(vk)) & 0x8000) != 0


def parse_hotkey(text: str) -> list:
    """把 'ctrl+alt+a' 解析为虚拟键码列表。"""
    vks = []
    for raw in str(text or "").replace("+", " ").split():
        part = raw.strip().lower()
        if not part:
            continue
        if part in VK_MAP:
            vks.append(VK_MAP[part])
        elif len(part) == 1:
            vks.append(ord(part.upper()))
        else:
            raise ValueError(f"无法识别的按键: {raw}")
    return vks


def is_admin() -> bool:  # pragma: no cover - 仅用于提示
    try:
        return bool(kernel32.GetCurrentProcessToken is not None and ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def app_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
