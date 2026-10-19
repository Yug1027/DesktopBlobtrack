"""显示器几何信息：统一“捕获像素 / 物理像素 / Qt 逻辑像素”三种坐标系。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from aura import win32_utils


@dataclass
class DisplayInfo:
    origin: Tuple[int, int] = (0, 0)          # 虚拟桌面原点（Qt 逻辑坐标）
    size: Tuple[int, int] = (1920, 1080)      # 虚拟桌面尺寸（Qt 逻辑坐标）
    capture_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)   # mss 坐标系
    physical_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)  # GetSystemMetrics 坐标系
    capture_scale: float = 1.0   # 捕获像素 / 逻辑像素
    cursor_scale: float = 1.0    # 物理像素 / 逻辑像素

    @staticmethod
    def probe(capture_rect: Optional[Tuple[int, int, int, int]] = None) -> "DisplayInfo":
        from PySide6.QtGui import QGuiApplication

        screens = QGuiApplication.screens() or []
        rects = [s.geometry() for s in screens] or []
        if rects:
            x0 = min(r.x() for r in rects)
            y0 = min(r.y() for r in rects)
            x1 = max(r.x() + r.width() for r in rects)
            y1 = max(r.y() + r.height() for r in rects)
            origin = (int(x0), int(y0))
            size = (max(64, int(x1 - x0)), max(64, int(y1 - y0)))
        else:  # 极端兜底
            p = win32_utils.virtual_screen_rect()
            origin, size = (p[0], p[1]), (p[2], p[3])

        phys = win32_utils.virtual_screen_rect()
        cap = capture_rect or phys

        def ratio(num: float) -> float:
            value = num / float(size[0]) if size[0] else 1.0
            return value if 0.2 < value < 8.0 else 1.0

        return DisplayInfo(
            origin=origin,
            size=size,
            capture_rect=tuple(int(v) for v in cap),  # type: ignore[arg-type]
            physical_rect=phys,
            capture_scale=ratio(float(cap[2])),
            cursor_scale=ratio(float(phys[2])),
        )

    def to_logical_from_capture(self, x: float, y: float) -> Tuple[float, float]:
        return (
            self.origin[0] + (float(x) - self.capture_rect[0]) / self.capture_scale,
            self.origin[1] + (float(y) - self.capture_rect[1]) / self.capture_scale,
        )

    def to_logical_from_cursor(self, x: float, y: float) -> Tuple[float, float]:
        return (
            self.origin[0] + (float(x) - self.physical_rect[0]) / self.cursor_scale,
            self.origin[1] + (float(y) - self.physical_rect[1]) / self.cursor_scale,
        )

    def to_capture_from_logical(self, x: float, y: float) -> Tuple[float, float]:
        """Qt 逻辑坐标 -> mss 捕获坐标系（to_logical_from_capture 的逆变换）。"""
        return (
            self.capture_rect[0] + (float(x) - self.origin[0]) * self.capture_scale,
            self.capture_rect[1] + (float(y) - self.origin[1]) * self.capture_scale,
        )

    def to_capture_from_cursor(self, x: float, y: float) -> Tuple[float, float]:
        """物理像素（光标） -> mss 捕获坐标系。"""
        ratio = self.capture_scale / self.cursor_scale if self.cursor_scale else 1.0
        return (
            self.capture_rect[0] + (float(x) - self.physical_rect[0]) * ratio,
            self.capture_rect[1] + (float(y) - self.physical_rect[1]) * ratio,
        )

    def cursor_logical(self) -> Tuple[float, float]:
        return self.to_logical_from_cursor(*win32_utils.get_cursor_pos())

    def key(self) -> tuple:
        return (self.origin, self.size, self.capture_rect, self.physical_rect)
