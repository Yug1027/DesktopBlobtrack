"""全屏透明置顶覆盖层：绘制元素描边框 + 鼠标连线动画。

特性：
- 无边框、置顶、工具窗口、不抢焦点、鼠标完全穿透；
- 半透明背景由 Qt 双缓冲绘制，无闪烁；
- 渲染帧率与捕获帧率解耦（渲染 30fps，捕获 10-15fps）。
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from aura import win32_utils
from aura.config import Config
from aura.display import DisplayInfo
from aura.tracker import BlobTracker

Rect = Tuple[float, float, float, float]


class Overlay(QWidget):
    def __init__(self, cfg: Config, tracker: BlobTracker, disp: DisplayInfo, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.tracker = tracker
        self.disp = disp

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowTitle("DesktopBlobtrack Overlay")

        self._apply_geometry()
        self._blobs: List[Tuple[Rect, int, int]] = []  # [(box, hits, src_index)]
        self._fill_by_index: Dict[int, object] = {}    # {src_index: QImage} 框内填充贴图
        self._roi_rect: Optional[Rect] = None
        self._last_payload_at = 0.0
        self._cursor: Tuple[float, float] = (0.0, 0.0)
        self._elapsed = 0.0
        self._last_tick = time.perf_counter()
        self._last_stats = {"fps": 0, "count": 0, "ms": 0.0}
        self._rand_state = 12345
        self._repick_at = 0.0
        self._pick_seed_value = 1
        self._last_affinity_check = 0.0
        self._drawn_count = 0
        self._fill_count = 0
        self._last_click_through: Optional[bool] = None
        # 本帧实际绘制的框 / 光标（捕获像素坐标），供录屏模式自绘抹除使用
        self.drawn_capture: List[Tuple[float, float, float, float]] = []
        self.drawn_cursor_capture: Optional[Tuple[float, float]] = None
        # 本帧实际绘制的框在检测结果里的下标，捕获线程据此只给这些框做填充贴图
        self.drawn_indices: List[int] = []

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._apply_ui_fps()

    # ---------- 几何 / 窗口 ----------
    def _apply_geometry(self) -> None:
        x, y = self.disp.origin
        w, h = self.disp.size
        self.setGeometry(x, y, w, h)

    def _apply_ui_fps(self) -> None:
        fps = max(5, int(self.cfg.general.ui_fps))
        interval = max(8, round(1000 / fps))
        if abs(self._timer.interval() - interval) > 2:
            self._timer.setInterval(interval)

    def start(self) -> None:
        self._timer.start()

    def stop_timer(self) -> None:
        self._timer.stop()

    def apply_click_through(self) -> None:
        # 仅在值真正变化时才改动窗口样式：拖动滑块时每次都 SetWindowLongPtr 会明显卡顿
        value = bool(self.cfg.general.click_through)
        if self._last_click_through != value:
            try:
                win32_utils.set_click_through(int(self.winId()), value)
                self._last_click_through = value
            except Exception:
                pass
        self.apply_capture_exclusion()

    def apply_capture_exclusion(self) -> None:
        """把覆盖层从屏幕捕获中排除。

        这是“框不会闪”的根本前提：覆盖层是分层窗口不能直接设 affinity，
        由 win32_utils 用摘 layered→设置→恢复的方式绕过限制。
        排除成功后自己画的框不会出现在下一次截屏里，杜绝自检测反馈回路，
        同时也保证录屏/截图软件不会录到特效。
        """
        try:
            win32_utils.set_exclude_from_capture(
                int(self.winId()), bool(self.cfg.general.exclude_from_capture))
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_click_through()
        self._last_tick = time.perf_counter()

    def set_display(self, disp: DisplayInfo) -> None:
        self.disp = disp
        self._apply_geometry()

    # ---------- 数据入口 ----------
    def set_payload(self, payload: dict) -> None:
        """接收捕获线程的一帧结果：框 + 填充贴图 + 蒙版区域。"""
        self.set_payload_smoothing()
        self._blobs = self.tracker.update(payload.get("boxes") or [])
        self._fill_by_index = {int(i): img for (i, img) in (payload.get("fills") or [])}
        roi = payload.get("roi")
        self._roi_rect = tuple(float(v) for v in roi) if roi else None
        self._last_payload_at = self._elapsed
        # 录屏模式下立刻同步重绘：屏幕上必须在下一次截屏前就画上本帧的框，
        # 否则“被抹除的位置”与“屏幕上实际画着的位置”错开一帧，反馈回路会重新自激。
        if not self.cfg.general.exclude_from_capture:
            self.repaint()

    def set_payload_smoothing(self) -> None:
        """把面板里的跟踪参数同步给 tracker。

        默认全部关闭：框严格等于检测结果，不插值、不留残影。
        """
        self.tracker.smoothing = float(self.cfg.general.smooth)
        self.tracker.max_missing = 0
        self.tracker.confirm_frames = int(self.cfg.detect.confirm_frames)

    def set_stats(self, stats: dict) -> None:
        self._last_stats = stats

    # ---------- 动画主循环 ----------
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._elapsed += dt
        self._apply_ui_fps()
        self._cursor = self.disp.cursor_logical()
        # 每秒巡检一次 affinity：Qt 若重建了原生窗口，排除属性会丢失
        if now - self._last_affinity_check > 1.0:
            self._last_affinity_check = now
            self.apply_capture_exclusion()
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            # 清空为全透明，避免残影
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            ox, oy = self.disp.origin
            boxes = self._blobs
            # 先挑连线目标，再决定画哪些框 —— 保证“画出来的框 == 正在连线的元素”
            targets = self._collect_targets(boxes, ox, oy) if self.cfg.line.visible else []
            if self.cfg.box.only_connected and self.cfg.line.visible:
                picked = {t[0] for t in targets}
                drawn = [pair for i, pair in enumerate(boxes) if i in picked]
            else:
                drawn = boxes
            self._drawn_count = len(drawn)
            self._fill_count = 0
            painted: List[Tuple[Rect, int, int]] = []
            if self.cfg.roi.show_region and self._roi_rect is not None:
                self._draw_roi_region(painter, ox, oy)
            if self.cfg.fill.mode != "none":
                self._draw_fills(painter, ox, oy, drawn)
            if self.cfg.detect.enabled and self.cfg.box.visible and drawn:
                self._draw_boxes(painter, drawn, ox, oy)
                painted = drawn
            if self.cfg.line.visible and targets:
                self._draw_lines(painter, targets, ox, oy)
            if self.cfg.general.show_hud:
                self._draw_hud(painter)
            self._report_drawn(painted)
        finally:
            painter.end()

    def _report_drawn(self, drawn) -> None:
        """把“这一帧实际画出来的框”换算到捕获坐标并公开出来。

        录屏模式下捕获线程靠它精确抹除自绘内容：画什么就抹什么，
        既不漏（漏了会被再检测成新元素 → 闪），也不多（多了会破坏真实画面 → 也闪）。
        正常模式下不维护，零开销。
        """
        # 位置与下标始终上报：填充贴图要靠它们定位到“下一帧真正会被画出来的框”，
        # 与是否录屏无关（否则正常模式下填充会忽有忽无地闪）
        self.drawn_indices = [int(b[2]) for b in drawn]
        s = self.disp.capture_scale
        self.drawn_capture = [
            (*self.disp.to_capture_from_logical(b[0][0], b[0][1]), b[0][2] * s, b[0][3] * s)
            for b in drawn
        ]
        if self.cfg.general.exclude_from_capture:
            self.drawn_cursor_capture = None
            return
        self.drawn_cursor_capture = (
            self.disp.to_capture_from_cursor(*win32_utils.get_cursor_pos())
            if (self.cfg.line.visible and drawn) else None
        )

    # ---- 蒙版区域边界 ----
    def _draw_roi_region(self, painter: QPainter, ox: float, oy: float) -> None:
        r = self.cfg.roi
        x, y, w, h = self._roi_rect  # type: ignore[misc]
        rect = QRectF(x - ox, y - oy, w, h)
        color = QColor(r.region_color)
        color.setAlpha(int(r.region_opacity))
        pen = QPen(color, 1.2, Qt.PenStyle.DashLine)
        pen.setDashPattern([10.0, 8.0])
        pen.setDashOffset(0.0)  # 静态虚线：不流动，避免任何“框在动”的观感
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10.0, 10.0)

    # ---- 框内填充效果（严格只填在框内部） ----
    def _draw_fills(self, painter: QPainter, ox: float, oy: float, boxes: List[Tuple[Rect, int, int]]) -> None:
        f = self.cfg.fill
        opacity = float(f.opacity) / 255.0
        if opacity <= 0.0 or not boxes:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rounded = self.cfg.box.style == "rounded"
        radius = float(self.cfg.box.radius)

        for (box, _hits, idx) in boxes:
            rect = QRectF(box[0] - ox, box[1] - oy, box[2], box[3])
            if rect.right() < 0 or rect.bottom() < 0 or rect.left() > self.width() or rect.top() > self.height():
                continue
            # 裁剪到框内部：无论贴图尺寸/比例如何，都不会溢出一个像素到框外
            painter.save()
            if rounded:
                clip = QPainterPath()
                clip.addRoundedRect(rect, radius, radius)
                painter.setClipPath(clip)
            else:
                painter.setClipRect(rect)

            if f.mode == "solid":
                color = QColor(f.color)
                color.setAlpha(int(f.opacity))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                if rounded:
                    painter.drawRoundedRect(rect, radius, radius)
                else:
                    painter.drawRect(rect)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                self._fill_count += 1
            else:
                img = self._fill_by_index.get(int(idx))
                if img is not None:
                    painter.setOpacity(opacity)
                    painter.drawImage(
                        rect, img,
                        QRectF(0.0, 0.0, float(img.width()), float(img.height())),
                    )
                    painter.setOpacity(1.0)
                    self._fill_count += 1
            painter.restore()

    # ---- 元素描边框 ----
    def _draw_boxes(self, painter: QPainter, boxes: List[Tuple[Rect, int, int]], ox: float, oy: float) -> None:
        cfg = self.cfg.box
        color = QColor(cfg.color)
        color.setAlpha(int(cfg.opacity))
        pen = QPen(color, float(cfg.width))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)

        # 新元素附加一圈外扩白框（会在同一位置叠加出“两种框”，默认关闭）
        fresh_color = QColor(255, 255, 255)
        fresh_pen = QPen(fresh_color, float(cfg.width) + 1.6)
        fresh_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        for (box, _hits, _idx) in boxes:
            x, y, w, h = box
            rect = QRectF(x - ox, y - oy, w, h)
            if rect.right() < 0 or rect.bottom() < 0 or rect.left() > self.width() or rect.top() > self.height():
                continue
            style = cfg.style
            if style == "rounded":
                painter.drawRoundedRect(rect, cfg.radius, cfg.radius)
            elif style == "bracket":
                c = float(cfg.corner)
                c = min(c, rect.width() / 2.0, rect.height() / 2.0)
                for (px, py, dx, dy) in (
                    (rect.left(), rect.top(), 1, 1),
                    (rect.right(), rect.top(), -1, 1),
                    (rect.left(), rect.bottom(), 1, -1),
                    (rect.right(), rect.bottom(), -1, -1),
                ):
                    painter.drawLine(QPointF(px, py), QPointF(px + dx * c, py))
                    painter.drawLine(QPointF(px, py), QPointF(px, py + dy * c))
            elif style == "dots":
                r = float(cfg.corner) / 2.0
                painter.setBrush(color)
                for (px, py) in (
                    (rect.left(), rect.top()),
                    (rect.right(), rect.top()),
                    (rect.left(), rect.bottom()),
                    (rect.right(), rect.bottom()),
                ):
                    painter.drawEllipse(QPointF(px, py), r, r)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.drawRect(rect)
            if cfg.show_center:
                painter.drawPoint(QPointF(rect.center().x(), rect.center().y()))

            # 仅在用户显式开启时为新出现的元素叠一圈白框
            if cfg.highlight_new and _hits <= 1:
                fresh_color.setAlpha(200)
                painter.setPen(fresh_pen)
                painter.drawRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5))
                painter.setPen(pen)

    # ---- 连线目标挑选（连线与描边框共用，保证两者严格一致） ----
    def _collect_targets(self, boxes: List[Tuple[Rect, int, int]], ox: float, oy: float) -> List[tuple]:
        """返回 [(索引, d2, cx, cy), ...]，即本帧实际连接到的元素中心。"""
        cfg = self.cfg.line
        if not boxes:
            return []
        mx = self._cursor[0] - ox
        my = self._cursor[1] - oy
        max_d2 = float(cfg.max_distance) ** 2

        candidates = []
        for i, (x, y, w, h) in ((i, b[0]) for i, b in enumerate(boxes)):
            cx, cy = x + w / 2.0 - ox, y + h / 2.0 - oy
            d2 = (cx - mx) ** 2 + (cy - my) ** 2
            if d2 <= max_d2:
                candidates.append((i, d2, cx, cy))
        if not candidates:
            return []

        count = min(int(cfg.count), len(candidates))
        mode = cfg.mode
        focus = float(cfg.focus)
        if mode == "nearest" or count >= len(candidates):
            candidates.sort(key=lambda t: t[1])
            picked = candidates[:count]
        elif mode == "random":
            candidates.sort(key=lambda t: (t[2], t[3]))  # 稳定排序，随机结果才不会每帧乱跳
            picked = _seeded_weighted_sample(candidates, count, self._pick_seed(),
                                             focus, float(cfg.max_distance))
        else:  # mixed：一半最近 + 一半随机
            candidates.sort(key=lambda t: t[1])
            half = count // 2
            near = candidates[:half]
            rest = candidates[half:]
            picked = near + _seeded_weighted_sample(rest, count - half, self._pick_seed(),
                                                    focus, float(cfg.max_distance))
        return picked

    # ---- 鼠标连线 ----
    def _draw_lines(self, painter: QPainter, targets: List[tuple], ox: float, oy: float) -> None:
        cfg = self.cfg.line
        mx = self._cursor[0] - ox
        my = self._cursor[1] - oy

        if cfg.cursor_ring:
            self._draw_cursor_ring(painter, mx, my)

        if not targets:
            return

        picked = targets

        # 录屏模式（允许被捕获）下冻结所有"持续变化"的动效：
        # 画面静止时绘制内容也必须完全静止，否则这些动效会被检测成新元素导致框闪烁
        frozen = not self.cfg.general.exclude_from_capture

        base = QColor(cfg.color)
        g = float(cfg.glow)
        layers = max(1, min(6, int(round(g * 2)) + 1))
        dash = [float(cfg.dash_on), float(cfg.dash_off)] if cfg.dash else None
        if dash and cfg.flow and not frozen:
            offset = -self._elapsed * float(cfg.flow_speed)
        else:
            offset = 0.0

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for (_idx, _d2, cx, cy) in picked:
            path = self._line_path(mx, my, cx, cy, cfg)
            for i in range(layers, 0, -1):
                f = (i - 1) / max(1, layers - 1)
                width = max(0.6, float(cfg.width) * (1.0 + 3.0 * g * f))
                if i == 1:
                    alpha = int(cfg.opacity)
                else:
                    alpha = int(cfg.opacity * (1.0 - 0.75 * f) * (0.25 + 0.75 * min(1.0, g / 3.0)))
                color = QColor(base)
                color.setAlpha(max(4, alpha))
                pen = QPen(color, width, Qt.PenStyle.SolidLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                if dash:
                    pen.setDashPattern(dash)
                    pen.setDashOffset(offset)
                painter.setPen(pen)
                painter.drawPath(path)

            if cfg.spark and not frozen:  # 录屏模式下不画跑动光点
                # 相位由线段终点网格量化决定，保证光点沿固定方向平滑跑动
                phase = ((int(cx / 12.0) * 7 + int(cy / 12.0) * 13) % 97) / 97.0
                speed_t = max(0.15, abs(float(cfg.flow_speed)) / 320.0)
                t = (self._elapsed * speed_t + phase) % 1.0
                pos = path.pointAtPercent(t)
                spark = QColor(base)
                spark.setAlpha(min(255, int(cfg.opacity) + 60))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(spark)
                painter.drawEllipse(pos, float(cfg.spark_size), float(cfg.spark_size))
                painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_cursor_ring(self, painter: QPainter, mx: float, my: float) -> None:
        cfg = self.cfg.line
        color = QColor(cfg.ring_color)
        color.setAlpha(180)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 录屏模式下光环不脉动（保持画面静止，避免被检测成变化元素）
        if self.cfg.general.exclude_from_capture:
            pulse = 1.0 + 0.18 * math.sin(self._elapsed * 4.0)
        else:
            pulse = 1.0
        r = float(cfg.ring_size) * pulse
        painter.drawEllipse(QPointF(mx, my), r, r)
        painter.drawEllipse(QPointF(mx, my), 1.6, 1.6)

    def _line_path(self, x0: float, y0: float, x1: float, y1: float, cfg) -> QPainterPath:
        path = QPainterPath(QPointF(x0, y0))
        if cfg.style == "curve":
            mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            dx, dy = x1 - x0, y1 - y0
            length = max(1.0, math.hypot(dx, dy))
            bend = float(cfg.bend) * min(1.0, length / 400.0) * 120.0
            ctrl = QPointF(mx - dy / length * bend, my + dx / length * bend)
            path.quadTo(ctrl, QPointF(x1, y1))
        else:
            path.lineTo(QPointF(x1, y1))
        return path

    def _draw_hud(self, painter: QPainter) -> None:
        stats = self._last_stats
        # 捕获心跳：距上一检测帧的时间（正常应 < 1/fps 秒）
        age = max(0.0, self._elapsed - self._last_payload_at)
        fill = self.cfg.fill.mode
        text = (
            f"DesktopBlobtrack  capture {stats.get('fps', 0)} fps  detect {stats.get('ms', 0):.1f} ms  "
            f"blobs {stats.get('count', 0)}  drawn {self._drawn_count}  ui {self.cfg.general.ui_fps} fps  "
            f"live {age * 1000.0:.0f} ms  roi {'on' if self.cfg.roi.enabled else 'off'}  fill {fill}"
        )
        painter.setPen(QColor(255, 255, 255, 210))
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(14, 22, text)

    # ---- 可复现的伪随机 ----
    def _rand01(self) -> float:
        self._rand_state = (1103515245 * self._rand_state + 12345) & 0x7FFFFFFF
        return self._rand_state / float(0x7FFFFFFF)

    def _pick_seed(self) -> int:
        """随机连线每 1.2 秒重新抽取一次，期间保持稳定。"""
        if self._elapsed >= self._repick_at:
            self._repick_at = self._elapsed + 1.2
            self._pick_seed_value = (int(time.time() * 1000.0) & 0x7FFFFFFF) or 1
        return self._pick_seed_value


def _seeded_sample(items: List, n: int, seed: int) -> List:
    """确定性抽样：同一 seed + 同一顺序的列表 → 同一结果。"""
    if n <= 0:
        return []
    if n >= len(items):
        return list(items)
    indexes = list(range(len(items)))
    out = []
    x = seed or 1
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append(items[indexes.pop(x % len(indexes))])
    return out


def _seeded_weighted_sample(items: List, n: int, seed: int, focus: float, max_d: float) -> List:
    """按“距离权重”做确定性不放回抽样：focus 越大，越偏向近处的元素。

    items 元素为 (索引, d2, cx, cy)。weight = (1 - d/max_d) ** (focus*4)，
    focus=0 时退化为均匀随机，focus=1 时几乎总是最近的几个。
    """
    if n <= 0:
        return []
    if n >= len(items):
        return list(items)
    focus = max(0.0, min(1.0, float(focus)))
    if focus <= 0.001 or max_d <= 0.0:
        return _seeded_sample(items, n, seed)
    power = focus * 4.0
    md = float(max_d)
    pool = []
    for it in items:
        d = math.sqrt(it[1])
        w = max(0.02, (1.0 - min(1.0, d / md))) ** power
        pool.append((it, w))
    out = []
    x = seed or 1
    for _ in range(n):
        total = sum(w for _, w in pool)
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        r = (x / float(0x7FFFFFFF)) * total
        acc = 0.0
        for idx, (it, w) in enumerate(pool):
            acc += w
            if r <= acc:
                out.append(it)
                pool.pop(idx)
                break
        else:
            out.append(pool.pop()[0])
    return out
