"""可视化设置面板：深色 macOS 风格。

- 无边框圆角窗口，自定义标题栏（红=关闭 / 黄=全屏 / 绿=最小化，可拖动）；
- 左侧图标导航（预设 / 连线 / 外观 / 检测 / 通用 / 关于），搜索框实时筛选；
- 内容区卡片式分组，滑块/下拉/开关全部紫色高亮；
- 预设：内置 6 套 + 自定义预设的新增/编辑/删除/导入导出/分享链接；
- 自定义颜色选择器：取色器 + 实时预览 + HEX/RGB 输入 + 常用/最近色板；
- 跟当前模式无关的控件自动隐藏；所有改动实时生效并自动保存。
"""

from __future__ import annotations

import base64
import json
import math
import os
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from aura import __version__
from aura import config as cfgmod
from aura.config import Config

# ---------------------------------------------------------------- 主题
BG = "#17171c"
SIDE_BG = "#1d1d24"
CARD_BG = "#212129"
CARD_BORDER = "#2e2e38"
TEXT = "#e6e6ec"
TEXT_DIM = "#9a9aa8"
ACCENT = "#a855f7"
ACCENT_DEEP = "#7c3aed"

# 分享链接前缀
SHARE_PREFIX = "dbt-preset:"

# 稳定度预设：值 = (框坐标吸附步长, 连续出现帧数)
STABILITY_PRESETS = {
    "灵敏": (0, 1),
    "标准": (4, 2),
    "稳定": (8, 3),
}

# 常用色板
COMMON_COLORS = [
    "#FFFFFF", "#C0C0C8", "#808088", "#202026",
    "#3DE1FF", "#8FD3FF", "#4F8DFF", "#A855F7",
    "#FF6BD6", "#FF5F57", "#FFB347", "#FFE066",
    "#7CFFB2", "#2ED573", "#9AE6FF", "#FFC7E8",
]

# 内置推荐预设（只写需要覆盖的字段，其余沿用当前值）
PRESETS = {
    "极简线稿": {
        "desc": "细白框 + 少量直线，安静不抢眼",
        "box": {"visible": True, "color": "#FFFFFF", "width": 1.2, "opacity": 170,
                "style": "bracket", "corner": 10, "only_connected": True},
        "line": {"visible": True, "count": 5, "mode": "nearest", "color": "#FFFFFF",
                 "width": 1.0, "opacity": 190, "glow": 0.3, "style": "straight",
                 "dash": False, "flow": False, "spark": False,
                 "cursor_ring": True, "ring_size": 7.0, "max_distance": 900},
        "fill": {"mode": "none"},
        "detect": {"min_area": 600, "max_blobs": 160},
    },
    "霓虹赛博": {
        "desc": "青框 + 粉紫曲线，发光流动 + 反色填充",
        "box": {"visible": True, "color": "#3DE1FF", "width": 1.8, "opacity": 210,
                "style": "bracket", "corner": 14, "only_connected": True},
        "line": {"visible": True, "count": 8, "mode": "mixed", "color": "#FF6BD6",
                 "width": 1.7, "opacity": 230, "glow": 2.2, "style": "curve", "bend": 0.24,
                 "dash": True, "dash_on": 14.0, "dash_off": 10.0, "flow": True,
                 "flow_speed": 110.0, "spark": True, "spark_size": 3.2,
                 "cursor_ring": True, "ring_color": "#3DE1FF", "ring_size": 10.0,
                 "max_distance": 1500, "focus": 0.55},
        "fill": {"mode": "invert", "opacity": 150},
        "detect": {"min_area": 320, "max_blobs": 220},
        "general": {"ui_fps": 30},
    },
    "柔光点缀": {
        "desc": "低透明暖色调，慢速流动，像呼吸一样",
        "box": {"visible": True, "color": "#9AE6FF", "width": 1.4, "opacity": 120,
                "style": "rounded", "radius": 10.0, "only_connected": True},
        "line": {"visible": True, "count": 6, "mode": "nearest", "color": "#FFC7E8",
                 "width": 1.2, "opacity": 150, "glow": 0.8, "style": "curve", "bend": 0.12,
                 "dash": True, "dash_on": 20.0, "dash_off": 16.0, "flow": True,
                 "flow_speed": 40.0, "spark": False,
                 "cursor_ring": True, "ring_color": "#FFFFFF", "ring_size": 6.0,
                 "max_distance": 1100},
        "fill": {"mode": "hsl", "opacity": 90, "rainbow": True,
                 "saturation": 1.35, "lightness": 1.15},
        "detect": {"min_area": 400},
    },
    "像素故障": {
        "desc": "马赛克填充 + 绿色扫描线，故障艺术风",
        "box": {"visible": True, "color": "#7CFFB2", "width": 1.6, "opacity": 220,
                "style": "rect", "only_connected": True},
        "line": {"visible": True, "count": 10, "mode": "random", "color": "#7CFFB2",
                 "width": 1.4, "opacity": 220, "glow": 1.0, "style": "straight",
                 "dash": True, "dash_on": 6.0, "dash_off": 6.0, "flow": True,
                 "flow_speed": 180.0, "spark": True, "spark_size": 2.4,
                 "cursor_ring": True, "ring_color": "#7CFFB2", "ring_size": 12.0,
                 "max_distance": 1800, "focus": 0.3},
        "fill": {"mode": "pixelate", "opacity": 210, "pixel_size": 16},
        "detect": {"min_area": 300, "min_dist": 24.0},
    },
    "性能优先": {
        "desc": "降低帧率与精细度，长时间挂着也不占资源",
        "box": {"visible": True, "color": "#FFFFFF", "width": 1.2, "opacity": 180,
                "style": "bracket", "corner": 8, "only_connected": True},
        "line": {"visible": True, "count": 5, "mode": "nearest", "color": "#8FD3FF",
                 "width": 1.0, "opacity": 170, "glow": 0.4, "style": "straight",
                 "dash": False, "flow": True, "flow_speed": 60.0, "spark": False,
                 "cursor_ring": True, "ring_size": 6.0, "max_distance": 900},
        "fill": {"mode": "none"},
        "detect": {"downscale": 0.35, "max_blobs": 120},
        "capture": {"fps": 8},
        "general": {"ui_fps": 24},
    },
    "录屏演示": {
        "desc": "允许被录屏/截图捕获（已内置防闪烁处理）",
        "box": {"visible": True, "color": "#3DE1FF", "width": 1.8, "opacity": 230,
                "style": "bracket", "corner": 12, "only_connected": True},
        "line": {"visible": True, "count": 6, "mode": "nearest", "color": "#FF6BD6",
                 "width": 1.6, "opacity": 230, "glow": 1.4, "style": "curve", "bend": 0.18,
                 "dash": True, "dash_on": 14.0, "dash_off": 10.0, "flow": True,
                 "flow_speed": 90.0, "spark": True, "spark_size": 3.0,
                 "cursor_ring": True, "ring_size": 9.0, "max_distance": 1400},
        "fill": {"mode": "invert", "opacity": 140},
        "detect": {"snap": 8, "confirm_frames": 3},
        "general": {"exclude_from_capture": False, "ui_fps": 30},
    },
}


def _sens_to_canny(v: int) -> int:
    """检测灵敏度 1~10 -> Canny 低阈值（越高框越多）。"""
    return int(110 - 10 * max(1, min(10, v)))


def _canny_to_sens(low: int) -> int:
    return int(round((110 - low) / 10.0))


# ---------------------------------------------------------------- 预设分享
def encode_preset_link(name: str, params: Dict) -> str:
    """预设 -> 分享链接：dbt-preset:<base64url(json)>。"""
    payload = {"app": "DesktopBlobtrack", "type": "preset", "name": name, "params": params}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SHARE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_preset_link(text: str) -> Dict:
    """分享链接/文件 JSON -> {name, params}。失败抛 ValueError。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("内容为空")
    if text.startswith(SHARE_PREFIX):
        b64 = text[len(SHARE_PREFIX):]
        b64 += "=" * (-len(b64) % 4)
        try:
            text = base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise ValueError(f"分享链接无法解析: {exc}") from exc
    try:
        data = json.loads(text)
    except Exception as exc:
        raise ValueError(f"不是合法的 JSON: {exc}") from exc
    name = data.get("name")
    params = data.get("params")
    if not name or not isinstance(params, dict):
        raise ValueError("缺少预设名称或参数（需要包含 name 和 params 字段）")
    return {"name": str(name)[:40], "params": params}


# ---------------------------------------------------------------- 图标
def _nav_icon(kind: str, color: str = "#c9c9d3", size: int = 22) -> QIcon:
    """程序化绘制导航图标。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QColor(color)
    pen = QPen(c, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    if kind == "line":  # 光标点 + 放射连线
        p.setBrush(c)
        p.drawEllipse(QRectF(s * 0.12, s * 0.40, s * 0.18, s * 0.18))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for ty in (0.18, 0.50, 0.82):
            p.drawLine(QPointF(s * 0.34, s * 0.49), QPointF(s * 0.86, s * ty))
            p.drawEllipse(QRectF(s * 0.80, s * ty - s * 0.06, s * 0.12, s * 0.12))
    elif kind == "look":  # 四角括号
        c_len = s * 0.22
        for (px, py, dx, dy) in ((0.16, 0.16, 1, 1), (0.84, 0.16, -1, 1),
                                 (0.16, 0.84, 1, -1), (0.84, 0.84, -1, -1)):
            x, y = s * px, s * py
            p.drawLine(QPointF(x, y), QPointF(x + dx * c_len, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * c_len))
    elif kind == "preset":  # 星芒
        p.setBrush(c)
        path = QPainterPath()
        path.moveTo(s * 0.5, s * 0.10)
        path.quadTo(s * 0.56, s * 0.44, s * 0.90, s * 0.50)
        path.quadTo(s * 0.56, s * 0.56, s * 0.50, s * 0.90)
        path.quadTo(s * 0.44, s * 0.56, s * 0.10, s * 0.50)
        path.quadTo(s * 0.44, s * 0.44, s * 0.50, s * 0.10)
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "detect":  # 十字准星
        p.drawEllipse(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56))
        p.drawLine(QPointF(s * 0.5, s * 0.06), QPointF(s * 0.5, s * 0.22))
        p.drawLine(QPointF(s * 0.5, s * 0.78), QPointF(s * 0.5, s * 0.94))
        p.drawLine(QPointF(s * 0.06, s * 0.5), QPointF(s * 0.22, s * 0.5))
        p.drawLine(QPointF(s * 0.78, s * 0.5), QPointF(s * 0.94, s * 0.5))
        p.setBrush(c)
        p.drawEllipse(QRectF(s * 0.44, s * 0.44, s * 0.12, s * 0.12))
    elif kind == "about":  # i 信息
        p.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72))
        p.setBrush(c)
        p.drawEllipse(QRectF(s * 0.44, s * 0.26, s * 0.12, s * 0.12))
        p.drawLine(QPointF(s * 0.5, s * 0.46), QPointF(s * 0.5, s * 0.72))
    else:  # misc：齿轮
        p.drawEllipse(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40))
        for i in range(6):
            a = i * math.pi / 3.0
            x0, y0 = s * (0.5 + 0.32 * math.cos(a)), s * (0.5 + 0.32 * math.sin(a))
            x1, y1 = s * (0.5 + 0.46 * math.cos(a)), s * (0.5 + 0.46 * math.sin(a))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.setBrush(c)
        p.drawEllipse(QRectF(s * 0.455, s * 0.455, s * 0.09, s * 0.09))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- 开关
class ToggleSwitch(QAbstractButton):
    """iOS 风格开关。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT) if on else QColor("#3c3c48"))
        p.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        d = rect.height() - 6.0
        x = rect.right() - d - 3.0 if on else rect.left() + 3.0
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, rect.top() + 3.0, d, d))
        p.end()


# ---------------------------------------------------------------- 取色器
class _SVSquare(QWidget):
    """饱和度(横) × 明度(纵) 取色方块。"""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self.hue = 0.0
        self.sat = 255
        self.val = 255
        self.on_change = on_change
        self.setFixedSize(190, 190)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._img: Optional[QImage] = None

    def set_hsv(self, h: float, s: int, v: int, notify: bool = False) -> None:
        self.hue, self.sat, self.val = float(h), int(s), int(v)
        self._img = None
        self.update()
        if notify and self.on_change:
            self.on_change()

    def _render(self) -> QImage:
        if self._img is not None:
            return self._img
        w, h = self.width(), self.height()
        img = QImage(w, h, QImage.Format.Format_RGB32)
        for y in range(h):
            v = round((1.0 - y / max(1, h - 1)) * 255)
            for x in range(w):
                s = round(x / max(1, w - 1) * 255)
                img.setPixelColor(x, y, QColor.fromHsv(int(self.hue), s, v))
        self._img = img
        return img

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawImage(0, 0, self._render())
        x = self.sat / 255.0 * (self.width() - 1)
        y = (1.0 - self.val / 255.0) * (self.height() - 1)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(QRectF(x - 5, y - 5, 10, 10))
        p.setPen(QPen(QColor("#202026"), 1))
        p.drawEllipse(QRectF(x - 6, y - 6, 12, 12))
        p.end()

    def _pick(self, pos) -> None:
        s = max(0, min(255, round(pos.x() / max(1, self.width() - 1) * 255)))
        v = max(0, min(255, round((1.0 - pos.y() / max(1, self.height() - 1)) * 255)))
        self.sat, self.val = s, v
        self.update()
        if self.on_change:
            self.on_change()

    def mousePressEvent(self, event) -> None:
        self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class _HueStrip(QWidget):
    """垂直色相条。"""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self.hue = 0.0
        self.on_change = on_change
        self.setFixedSize(22, 190)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        for i in range(7):
            grad.setColorAt(i / 6.0, QColor.fromHsv(i * 60, 255, 255))
        p.fillRect(self.rect(), grad)
        y = self.hue / 359.0 * (self.height() - 1)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        p.end()

    def _pick(self, y: float) -> None:
        self.hue = max(0.0, min(359.0, y / max(1, self.height() - 1) * 359.0))
        self.update()
        if self.on_change:
            self.on_change()

    def mousePressEvent(self, event) -> None:
        self._pick(event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position().y())


class ColorPickerDialog(QDialog):
    """深色风格取色器：SV 方块 + 色相条 + 实时预览 + HEX/RGB + 常用/最近色板。"""

    def __init__(self, initial: str, recent: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择颜色")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{ background:{BG}; }}
            QLabel {{ color:{TEXT}; font-size:12px; }}
            QLabel#dim {{ color:{TEXT_DIM}; font-size:11px; }}
            QLineEdit, QSpinBox {{ background:#2a2a33; border:1px solid #3a3a46;
                border-radius:6px; padding:5px 8px; color:{TEXT}; }}
            QPushButton {{ background:#2a2a33; border:1px solid #3a3a46; border-radius:7px;
                padding:7px 16px; color:{TEXT}; }}
            QPushButton:hover {{ background:#33323e; }}
            QPushButton#primary {{ background:{ACCENT}; color:#fff; border:none; font-weight:600; }}
            QPushButton#primary:hover {{ background:#c084fc; }}
        """)
        initial_color = QColor(initial) if QColor(initial).isValid() else QColor("#3DE1FF")
        self._initial = initial_color
        self._color = initial_color

        self.sv = _SVSquare(self._on_sv)
        self.hue_strip = _HueStrip(self._on_hue)
        h, s, v, _a = initial_color.getHsv()
        self.sv.set_hsv(float(h if h >= 0 else 0), s, v)
        self.hue_strip.hue = float(h if h >= 0 else 0)

        # 预览
        self._preview_old = QPushButton()
        self._preview_new = QPushButton()
        for btn in (self._preview_old, self._preview_new):
            btn.setFixedSize(46, 30)
            btn.setEnabled(False)
            btn.setStyleSheet("border:1px solid #3a3a46; border-radius:5px;")

        # HEX / RGB
        self.hex_edit = QLineEdit(initial_color.name().upper())
        self.hex_edit.setPlaceholderText("#RRGGBB")
        self.hex_edit.editingFinished.connect(self._on_hex)
        self.spins: List[QSpinBox] = []
        rgb_row = QHBoxLayout()
        for i, name in enumerate(("R", "G", "B")):
            sp = QSpinBox()
            sp.setRange(0, 255)
            sp.setPrefix(name + " ")
            sp.setValue(initial_color.getRgb()[i])
            sp.valueChanged.connect(self._on_rgb)
            self.spins.append(sp)
            rgb_row.addWidget(sp)

        right = QVBoxLayout()
        right.setSpacing(8)
        prev_row = QHBoxLayout()
        prev_row.addWidget(self._preview_old)
        prev_row.addWidget(QLabel("→"))
        prev_row.addWidget(self._preview_new)
        prev_row.addStretch(1)
        right.addLayout(prev_row)
        right.addWidget(QLabel("HEX"))
        right.addWidget(self.hex_edit)
        right.addWidget(QLabel("RGB"))
        right.addLayout(rgb_row)

        # 色板
        right.addWidget(self._swatch_row(COMMON_COLORS, "常用"))
        self._recent = list(recent)
        self._recent_box = self._swatch_row(self._recent[-10:][::-1], "最近使用")
        right.addWidget(self._recent_box)
        right.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        right.addLayout(btns)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)
        root.addWidget(self.sv)
        root.addWidget(self.hue_strip)
        root.addLayout(right, 1)
        self.adjustSize()

        self._refresh(initial_color)

    def _swatch_row(self, colors: List[str], title: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lab = QLabel(title)
        lab.setObjectName("dim")
        lay.addWidget(lab)
        grid = QHBoxLayout()
        grid.setSpacing(4)
        if colors:
            for c in colors[:10]:
                btn = QPushButton()
                btn.setFixedSize(22, 22)
                btn.setStyleSheet(
                    f"QPushButton{{background:{c}; border:1px solid #3a3a46; border-radius:5px;}}"
                    "QPushButton:hover{border:2px solid #ffffff;}")
                btn.setToolTip(c)
                btn.clicked.connect(lambda _=False, cc=c: self._set_color(QColor(cc)))
                grid.addWidget(btn)
        else:
            empty = QLabel("（暂无）")
            empty.setObjectName("dim")
            grid.addWidget(empty)
        grid.addStretch(1)
        lay.addLayout(grid)
        return box

    def _on_sv(self) -> None:
        self._refresh(QColor.fromHsv(int(self.sv.hue), self.sv.sat, self.sv.val))

    def _on_hue(self) -> None:
        self.sv.set_hsv(self.hue_strip.hue, self.sv.sat, self.sv.val)
        self._refresh(QColor.fromHsv(int(self.sv.hue), self.sv.sat, self.sv.val))

    def _on_hex(self) -> None:
        text = self.hex_edit.text().strip()
        if text and not text.startswith("#"):
            text = "#" + text
        color = QColor(text)
        if color.isValid():
            self._set_color(color)
        else:
            self.hex_edit.setStyleSheet("border:1px solid #e74c3c;")

    def _on_rgb(self, _v=None) -> None:
        self._set_color(QColor(self.spins[0].value(), self.spins[1].value(), self.spins[2].value()))

    def _set_color(self, color: QColor) -> None:
        h, s, v, _a = color.getHsv()
        self.sv.set_hsv(float(h if h >= 0 else 0), s, v)
        self.hue_strip.hue = float(h if h >= 0 else 0)
        self.hue_strip.update()
        self._refresh(color)

    def _refresh(self, color: QColor) -> None:
        self._color = color
        self._preview_old.setStyleSheet(
            f"background:{self._initial.name()}; border:1px solid #3a3a46; border-radius:5px;")
        self._preview_new.setStyleSheet(
            f"background:{color.name()}; border:1px solid #ffffff; border-radius:5px;")
        self.hex_edit.blockSignals(True)
        self.hex_edit.setStyleSheet("")
        self.hex_edit.setText(color.name().upper())
        self.hex_edit.blockSignals(False)
        r, g, b, _a = color.getRgb()
        for sp, val in zip(self.spins, (r, g, b)):
            sp.blockSignals(True)
            sp.setValue(val)
            sp.blockSignals(False)

    def color(self) -> QColor:
        return self._color


def pick_color(parent, initial: str, recent: List[str]) -> Optional[str]:
    dlg = ColorPickerDialog(initial, recent, parent)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.color().name().upper()
    return None


# ---------------------------------------------------------------- 标题栏
class _TitleBar(QWidget):
    """自定义标题栏：红绿灯圆点（关闭 / 全屏 / 最小化）+ 标题 + 搜索，可拖动窗口。"""

    def __init__(self, panel: "SettingsPanel"):
        super().__init__(panel)
        self.panel = panel
        self.setFixedHeight(44)
        self._drag_pos: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        for name, color, slot, tip in (
            ("close", "#ff5f57", panel.hide, "关闭"),
            ("max", "#febc2e", panel.toggle_maximize, "全屏 / 还原"),
            ("min", "#28c840", panel.minimize, "最小化"),
        ):
            dot = QPushButton()
            dot.setObjectName("dot")
            dot.setFixedSize(12, 12)
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.setStyleSheet(
                f"QPushButton#dot{{background:{color};border-radius:6px;border:none;}}"
                f"QPushButton#dot:hover{{border:1px solid rgba(255,255,255,0.35);}}"
            )
            dot.setToolTip(tip)
            dot.clicked.connect(slot)
            layout.addWidget(dot)

        title = QLabel("DesktopBlobtrack · 设置")
        title.setStyleSheet(f"color:{TEXT_DIM}; font-size:13px; font-weight:600;")
        layout.addSpacing(6)
        layout.addWidget(title)
        layout.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜索设置")
        self.search.setFixedWidth(170)
        self.search.textChanged.connect(panel.filter_nav)
        layout.addWidget(self.search)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.panel.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.panel.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.panel.toggle_maximize()


# ---------------------------------------------------------------- 主面板
class SettingsPanel(QWidget):
    # 图标在 __init__ 中延迟创建（类定义时还没有 QApplication，QPixmap 会崩）
    NAV = [
        ("preset", "预设"),
        ("line", "连线"),
        ("look", "外观"),
        ("detect", "检测"),
        ("misc", "通用"),
        ("about", "关于"),
    ]

    def __init__(self, cfg: Config, on_change: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_change = on_change
        self._sync_fns: List[Callable[[], None]] = []
        self._dyn: List[tuple] = []
        self._nav_buttons: List[QPushButton] = []
        self._normal_geom = None

        self.setWindowTitle("DesktopBlobtrack 设置")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(760, 560)
        self.resize(820, 640)
        self.setStyleSheet(self._qss())

        root = QFrame()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 12)
        root_layout.setSpacing(0)

        win_layout = QVBoxLayout(self)
        win_layout.setContentsMargins(0, 0, 0, 0)
        win_layout.addWidget(root)

        root_layout.addWidget(_TitleBar(self))

        body = QHBoxLayout()
        body.setContentsMargins(12, 8, 12, 0)
        body.setSpacing(12)
        root_layout.addLayout(body, 1)

        # ---- 侧栏 ----
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(160)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(8, 10, 8, 10)
        side_layout.setSpacing(2)

        self._stack = QStackedWidget()
        pages = [self._page_preset(), self._page_line(), self._page_look(),
                 self._page_detect(), self._page_misc(), self._page_about()]
        from PySide6.QtCore import QSize
        for i, (key, label) in enumerate(self.NAV):
            btn = QPushButton(_nav_icon(key), label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIconSize(QSize(20, 20))
            btn.setProperty("nav_key", key)
            btn.clicked.connect(lambda _c=False, idx=i: self._select_nav(idx))
            side_layout.addWidget(btn)
            self._nav_buttons.append(btn)
            self._stack.addWidget(pages[i])

        side_layout.addStretch(1)
        for text, slot, primary in (
            ("恢复默认", self._reset, False),
            ("保存", self._save, True),
        ):
            b = QPushButton(text)
            b.setObjectName("primary" if primary else "ghostBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            side_layout.addWidget(b)
        hint = QLabel("改动即时生效并自动保存")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        side_layout.addWidget(hint)

        body.addWidget(sidebar)
        body.addWidget(self._stack, 1)

        self._rebuild_custom_presets()
        self._select_nav(0)
        self._update_dynamic()

    # ================= 全局样式 =================
    def _qss(self) -> str:
        return f"""
        QFrame#root {{ background:{BG}; border-radius:12px; border:1px solid #2c2c36; }}
        QFrame#sidebar {{ background:{SIDE_BG}; border-radius:10px; }}
        QWidget {{ color:{TEXT}; font-size:13px; background:transparent; }}
        QFrame#card {{ background:{CARD_BG}; border:1px solid {CARD_BORDER}; border-radius:10px; }}
        QLabel#sectionTitle {{ color:{TEXT}; font-size:15px; font-weight:600; }}
        QLabel#cardTitle {{ color:#cfcfe0; font-size:12px; font-weight:600; }}
        QLabel#bigTitle {{ color:{TEXT}; font-size:16px; font-weight:700; }}
        QLabel#dim {{ color:{TEXT_DIM}; font-size:11px; }}
        QLabel#value {{ color:#c9c9d3; font-size:12px; min-width:48px; }}
        QPushButton#navBtn {{ text-align:left; padding:8px 10px; border-radius:8px;
            color:#c9c9d3; background:transparent; border:none; font-size:13px; }}
        QPushButton#navBtn:hover {{ background:#2a2a34; }}
        QPushButton#navBtn:checked {{ background:{ACCENT_DEEP}; color:#ffffff; font-weight:600; }}
        QPushButton#primary {{ background:{ACCENT}; color:#fff; border:none;
            border-radius:8px; padding:8px 0; font-weight:600; }}
        QPushButton#primary:hover {{ background:#c084fc; }}
        QPushButton#ghostBtn {{ background:transparent; color:#c9c9d3;
            border:1px solid #3a3a46; border-radius:8px; padding:8px 0; }}
        QPushButton#ghostBtn:hover {{ background:#2a2a34; }}
        QPushButton#miniBtn {{ background:#2a2a33; border:1px solid #3a3a46;
            border-radius:6px; padding:4px 10px; color:#c9c9d3; font-size:12px; }}
        QPushButton#miniBtn:hover {{ border:1px solid {ACCENT}; }}
        QPushButton#miniDanger {{ background:#2a2a33; border:1px solid #3a3a46;
            border-radius:6px; padding:4px 10px; color:#ff8a80; font-size:12px; }}
        QPushButton#miniDanger:hover {{ border:1px solid #ff5f57; }}
        QPushButton#colorBtn {{ border:1px solid #3a3a46; border-radius:6px; }}
        QPushButton#presetBtn {{ text-align:left; padding:10px 14px; background:#2a2a33;
            border:1px solid #3a3a46; border-radius:9px; color:{TEXT}; }}
        QPushButton#presetBtn:hover {{ border:1px solid {ACCENT}; background:#302f3c; }}
        QSlider::groove:horizontal {{ height:5px; background:#35353f; border-radius:2px; }}
        QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:#ffffff; border:2px solid {ACCENT};
            width:14px; height:14px; margin:-7px 0; border-radius:9px; }}
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
            background:#2a2a33; border:1px solid #3a3a46; border-radius:7px;
            padding:5px 10px; min-height:16px; color:{TEXT}; }}
        QComboBox:hover, QSpinBox:hover, QLineEdit:focus {{ border:1px solid {ACCENT}; }}
        QComboBox::drop-down {{ border:none; width:22px; }}
        QComboBox QAbstractItemView {{ background:#26262e; color:{TEXT};
            selection-background-color:{ACCENT_DEEP}; border:1px solid #3a3a46; }}
        QScrollArea {{ background:transparent; border:none; }}
        QScrollBar:vertical {{ background:transparent; width:8px; }}
        QScrollBar::handle:vertical {{ background:#3a3a46; border-radius:4px; min-height:30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        QToolTip {{ background:#26262e; color:{TEXT}; border:1px solid #3a3a46; padding:4px 8px; }}
        """

    # ================= 窗口控制 =================
    def toggle_maximize(self) -> None:
        """全屏 / 还原（无边框窗口手动处理，避免 showMaximized 撑掉圆角）。"""
        from PySide6.QtGui import QGuiApplication
        if self._normal_geom is not None:
            self.setGeometry(self._normal_geom)
            self._normal_geom = None
            return
        self._normal_geom = self.geometry()
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry() if screen else None
        if g is not None:
            self.setGeometry(g)

    def minimize(self) -> None:
        self.showMinimized()

    # ================= 导航 =================
    def _select_nav(self, idx: int) -> None:
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)

    def show_page(self, key: str) -> None:
        """按导航 key 切页（供托盘「关于」等入口调用）。"""
        for i, (k, _label) in enumerate(self.NAV):
            if k == key:
                self._select_nav(i)
                return

    def filter_nav(self, text: str) -> None:
        text = (text or "").strip().lower()
        for btn, (_key, label) in zip(self._nav_buttons, self.NAV):
            btn.setVisible(not text or text in label.lower())
        current = self._stack.currentIndex()
        if not self._nav_buttons[current].isVisible():
            for i, btn in enumerate(self._nav_buttons):
                if btn.isVisible():
                    self._select_nav(i)
                    break

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    # ================= 基础控件 =================
    def _changed(self) -> None:
        self.cfg.validate()
        self._update_dynamic()
        if self.on_change:
            self.on_change()

    def _update_dynamic(self) -> None:
        for widget, predicate in self._dyn:
            try:
                widget.setVisible(bool(predicate()))
            except Exception:
                pass

    def _page(self) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(10)
        area.setWidget(inner)
        area._inner_layout = layout  # type: ignore[attr-defined]
        return area

    def _card(self, layout: QVBoxLayout, title: str) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(4)
        lab = QLabel(title)
        lab.setObjectName("cardTitle")
        inner.addWidget(lab)
        inner.addSpacing(2)
        layout.addWidget(card)
        return inner

    def _row(self, layout, label: str, widget: QWidget, extra: Optional[QWidget] = None) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)
        lab = QLabel(label)
        lab.setMinimumWidth(110)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        if extra is not None:
            row.addWidget(extra)
        layout.addWidget(container)
        return container

    def _slider(self, layout, label, lo, hi, step=1, decimals=0, scale=100, suffix="",
                obj=None, attr=None, get_fn=None, set_fn=None, show_when=None):
        is_float = decimals > 0
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(int(round(lo * scale)), int(round(hi * scale)))
        s.setSingleStep(max(1, int(round(step * scale))))
        val = QLabel()
        val.setObjectName("value")
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def get() -> float:
            return float(get_fn()) if get_fn else float(getattr(obj, attr))

        def set(v: float) -> None:
            if set_fn:
                set_fn(v)
            else:
                setattr(obj, attr, v if is_float else int(round(v)))

        def fmt(v) -> str:
            if decimals > 0:
                return ("%." + str(decimals) + "f") % v
            return "%d%s" % (int(round(v)), suffix)

        def sync() -> None:
            cur = get()
            s.blockSignals(True)
            s.setValue(int(round(cur * scale)))
            s.blockSignals(False)
            val.setText(fmt(cur))

        def on_slider(v) -> None:
            set(v / float(scale))
            val.setText(fmt(get()))
            self._changed()

        s.valueChanged.connect(on_slider)
        sync()
        self._sync_fns.append(sync)
        container = self._row(layout, label, s, val)
        if show_when is not None:
            self._dyn.append((container, show_when))
        return container

    def _spin(self, layout, label, obj, attr, lo, hi, step=1, suffix="",
              mirror=None, show_when=None):
        cur = getattr(obj, attr)
        s = QSpinBox() if isinstance(cur, int) else QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        if suffix:
            s.setSuffix(suffix)
        if isinstance(s, QDoubleSpinBox):
            s.setDecimals(0)
        s.setFixedWidth(110)

        def sync() -> None:
            s.blockSignals(True)
            s.setValue(getattr(obj, attr))
            s.blockSignals(False)

        def on_change(v) -> None:
            setattr(obj, attr, type(getattr(obj, attr))(v))
            for m_obj, m_attr in (mirror or ()):
                setattr(m_obj, m_attr, getattr(obj, attr))
            self._changed()

        s.valueChanged.connect(on_change)
        sync()
        self._sync_fns.append(sync)
        container = self._row(layout, label, s)
        if show_when is not None:
            self._dyn.append((container, show_when))
        return container

    def _check(self, layout, label, obj, attr, show_when=None,
               get_fn=None, set_fn=None) -> QWidget:
        sw = ToggleSwitch()

        def sync() -> None:
            sw.blockSignals(True)
            sw.setChecked(bool(get_fn()) if get_fn else bool(getattr(obj, attr)))
            sw.blockSignals(False)

        def on_change(v) -> None:
            if set_fn:
                set_fn(bool(v))
            else:
                setattr(obj, attr, bool(v))
            self._changed()

        sw.toggled.connect(on_change)
        sync()
        self._sync_fns.append(sync)
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 3, 0, 3)
        row.addWidget(QLabel(label), 1)
        row.addWidget(sw)
        layout.addWidget(container)
        if show_when is not None:
            self._dyn.append((container, show_when))
        return container

    def _combo(self, layout, label, options, obj=None, attr=None,
               get_fn=None, set_fn=None, show_when=None):
        c = QComboBox()
        for key, text in options:
            c.addItem(text, key)

        def sync() -> None:
            key = get_fn() if get_fn else getattr(obj, attr)
            idx = c.findData(key)
            c.blockSignals(True)
            c.setCurrentIndex(idx if idx >= 0 else 0)
            c.blockSignals(False)

        def on_change(_) -> None:
            value = c.currentData()
            if set_fn:
                set_fn(value)
            else:
                setattr(obj, attr, value)
            self._changed()

        c.currentIndexChanged.connect(on_change)
        sync()
        self._sync_fns.append(sync)
        container = self._row(layout, label, c)
        if show_when is not None:
            self._dyn.append((container, show_when))
        return container

    # ---- 最近使用颜色 ----
    def _load_recent_colors(self) -> List[str]:
        try:
            with open(cfgmod.ui_state_path(), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            colors = data.get("recent_colors")
            return [c for c in colors if isinstance(c, str)] if isinstance(colors, list) else []
        except Exception:
            return []

    def _save_recent_color(self, color: str) -> None:
        colors = self._load_recent_colors()
        if color in colors:
            colors.remove(color)
        colors.append(color)
        try:
            with open(cfgmod.ui_state_path(), "w", encoding="utf-8") as fp:
                json.dump({"recent_colors": colors[-16:]}, fp, ensure_ascii=False)
        except OSError:
            pass

    def _color(self, layout, label, obj, attr, show_when=None) -> QWidget:
        btn = QPushButton()
        btn.setObjectName("colorBtn")
        btn.setFixedSize(84, 26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("点击选择颜色")

        def sync() -> None:
            btn.setStyleSheet(f"background:{getattr(obj, attr)}; border-radius:6px;")

        def pick() -> None:
            chosen = pick_color(self, str(getattr(obj, attr)), self._load_recent_colors())
            if chosen:
                setattr(obj, attr, chosen)
                self._save_recent_color(chosen)
                sync()
                self._changed()

        btn.clicked.connect(pick)
        sync()
        self._sync_fns.append(sync)
        container = self._row(layout, label, btn)
        if show_when is not None:
            self._dyn.append((container, show_when))
        return container

    def _note(self, layout, text: str) -> None:
        lab = QLabel(text)
        lab.setObjectName("dim")
        lab.setWordWrap(True)
        layout.addWidget(lab)

    # ================= 预设 =================
    def _page_preset(self):
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        # 我的预设（自定义 CRUD）
        card = self._card(layout, "我的预设")
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for text, slot in (
            ("＋ 存为新预设", self._save_current_as_preset),
            ("导入文件…", self._import_preset_file),
            ("粘贴分享链接…", self._import_preset_link),
        ):
            b = QPushButton(text)
            b.setObjectName("miniBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        card.addLayout(actions)
        self._custom_container = QWidget()
        self._custom_layout = QVBoxLayout(self._custom_container)
        self._custom_layout.setContentsMargins(0, 2, 0, 0)
        self._custom_layout.setSpacing(4)
        card.addWidget(self._custom_container)

        # 内置预设
        card = self._card(layout, "内置预设")
        self._note(card, "点一下即可整套套用（只覆盖这套风格需要的参数，其余保持你当前的值）")
        card.addSpacing(4)
        for name, data in PRESETS.items():
            btn = QPushButton(f"{name}\n{data['desc']}")
            btn.setObjectName("presetBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(66)
            btn.clicked.connect(lambda _c=False, n=name: self._apply_preset(n))
            card.addWidget(btn)
        layout.addStretch(1)
        return area

    def _apply_preset(self, name: str) -> None:
        data = PRESETS.get(name)
        if not data:
            return
        self._apply_params(data)
        self._toast(f"已应用预设「{name}」")

    def _apply_params(self, data: Dict) -> None:
        for section, values in data.items():
            if section == "desc" or not isinstance(values, dict):
                continue
            obj = getattr(self.cfg, section, None)
            if obj is None:
                continue
            for attr, value in values.items():
                if hasattr(obj, attr):
                    setattr(obj, attr, value)
        self.refresh()
        self._changed()

    # ---- 自定义预设持久化 ----
    def _load_custom(self) -> Dict[str, Dict]:
        try:
            with open(cfgmod.presets_path(), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                return {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            pass
        return {}

    def _save_custom(self, presets: Dict[str, Dict]) -> None:
        try:
            with open(cfgmod.presets_path(), "w", encoding="utf-8") as fp:
                json.dump(presets, fp, ensure_ascii=False, indent=2)
        except OSError as exc:
            self._toast(f"保存预设失败: {exc}")
        self._rebuild_custom_presets()

    def _current_params(self) -> Dict:
        """当前全部可调参数（不含快捷键等环境项）。"""
        cfg = self.cfg
        cfg.validate()
        d = cfg.to_dict()
        for key in ("hotkey_toggle", "hotkey_panel", "hotkey_quit"):
            d.get("general", {}).pop(key, None)
        return d

    def _save_current_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "存为新预设", "预设名称：")
        name = (name or "").strip()[:40]
        if not ok or not name:
            return
        presets = self._load_custom()
        if name in presets and QMessageBox.question(
                self, "覆盖预设", f"已存在同名预设「{name}」，覆盖它？") != QMessageBox.StandardButton.Yes:
            return
        presets[name] = self._current_params()
        self._save_custom(presets)

    def _update_preset(self, name: str) -> None:
        if QMessageBox.question(self, "更新预设",
                                f"用当前参数覆盖「{name}」？") != QMessageBox.StandardButton.Yes:
            return
        presets = self._load_custom()
        presets[name] = self._current_params()
        self._save_custom(presets)

    def _rename_preset(self, name: str) -> None:
        new, ok = QInputDialog.getText(self, "重命名预设", "新名称：", text=name)
        new = (new or "").strip()[:40]
        if not ok or not new or new == name:
            return
        presets = self._load_custom()
        if new in presets:
            self._toast(f"「{new}」已存在")
            return
        if name in presets:
            presets[new] = presets.pop(name)
            self._save_custom(presets)

    def _delete_preset(self, name: str) -> None:
        if QMessageBox.question(self, "删除预设",
                                f"确定删除「{name}」？此操作不可恢复。") != QMessageBox.StandardButton.Yes:
            return
        presets = self._load_custom()
        presets.pop(name, None)
        self._save_custom(presets)

    def _share_preset(self, name: str) -> None:
        params = self._load_custom().get(name)
        if not params:
            return
        link = encode_preset_link(name, params)
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(link)
        self._toast(f"「{name}」的分享链接已复制到剪贴板：\n\n{link[:80]}…\n\n"
                    "对方在「我的预设 → 粘贴分享链接」里粘贴即可导入。")

    def _export_preset(self, name: str) -> None:
        params = self._load_custom().get(name)
        if not params:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出预设", f"{name}.dbtpreset.json", "预设文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump({"app": "DesktopBlobtrack", "type": "preset",
                           "name": name, "params": params}, fp, ensure_ascii=False, indent=2)
            self._toast(f"已导出到\n{path}")
        except OSError as exc:
            self._toast(f"导出失败: {exc}")

    def _import_preset_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入预设", "", "预设文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fp:
                text = fp.read()
            self._finish_import(decode_preset_link(text))
        except (OSError, ValueError) as exc:
            self._toast(f"导入失败: {exc}")

    def _import_preset_link(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "粘贴分享链接", f"粘贴以 {SHARE_PREFIX} 开头的分享链接，或预设 JSON：")
        if not ok or not (text or "").strip():
            return
        try:
            self._finish_import(decode_preset_link(text))
        except ValueError as exc:
            self._toast(f"导入失败: {exc}")

    def _finish_import(self, data: Dict) -> None:
        name, params = data["name"], data["params"]
        presets = self._load_custom()
        if name in presets and QMessageBox.question(
                self, "覆盖预设", f"已存在同名预设「{name}」，覆盖它？") != QMessageBox.StandardButton.Yes:
            return
        presets[name] = params
        self._save_custom(presets)
        self._toast(f"已导入预设「{name}」")

    def _rebuild_custom_presets(self) -> None:
        """重建「我的预设」列表。"""
        if not hasattr(self, "_custom_layout"):
            return
        while self._custom_layout.count():
            item = self._custom_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        presets = self._load_custom()
        if not presets:
            empty = QLabel("还没有自定义预设 —— 调好参数后点上方「存为新预设」")
            empty.setObjectName("dim")
            self._custom_layout.addWidget(empty)
            return
        for name in presets:
            row = QFrame()
            row.setObjectName("card")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(10, 6, 10, 6)
            lay.setSpacing(6)
            lab = QLabel(name)
            lab.setStyleSheet("font-weight:600;")
            lay.addWidget(lab, 1)
            for text, slot, danger in (
                ("应用", lambda _=False, n=name: self._apply_params(self._load_custom()[n]), False),
                ("更新", lambda _=False, n=name: self._update_preset(n), False),
                ("重命名", lambda _=False, n=name: self._rename_preset(n), False),
                ("分享", lambda _=False, n=name: self._share_preset(n), False),
                ("导出", lambda _=False, n=name: self._export_preset(n), False),
                ("删除", lambda _=False, n=name: self._delete_preset(n), True),
            ):
                b = QPushButton(text)
                b.setObjectName("miniDanger" if danger else "miniBtn")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(slot)
                lay.addWidget(b)
            self._custom_layout.addWidget(row)

    # ================= 连线 =================
    def _page_line(self):
        l = self.cfg.line
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        card = self._card(layout, "连接目标")
        self._slider(card, "连线数量", 1, 20, 1, obj=l, attr="count")
        self._note(card, "连几条线，画面上就出现几个框")
        self._combo(card, "连线策略", [
            ("nearest", "连接最近的元素"),
            ("random", "随机挑选元素"),
            ("mixed", "一半最近 + 一半随机"),
        ], obj=l, attr="mode")
        self._slider(card, "连接范围", 200, 3000, 50, suffix=" px", obj=l, attr="max_distance")
        self._note(card, "只连接光标这个距离内的元素 —— 调小可让连线更集中")
        self._slider(card, "集中程度", 0, 100, 5, suffix="%",
                     get_fn=lambda: l.focus * 100.0,
                     set_fn=lambda v: setattr(l, "focus", v / 100.0),
                     show_when=lambda: l.mode != "nearest")
        self._note(card, "随机策略下越“集中”，线越偏向近处的元素；0% 为完全均匀随机")

        card = self._card(layout, "线条样式")
        self._color(card, "连线颜色", l, "color")
        self._slider(card, "粗细", 0.2, 6.0, 0.1, 1, obj=l, attr="width")
        self._slider(card, "不透明度", 0, 100, 5, suffix="%",
                     get_fn=lambda: l.opacity * 100.0 / 255.0,
                     set_fn=lambda v: setattr(l, "opacity", int(round(v * 255.0 / 100.0))))
        self._slider(card, "发光强度", 0.0, 3.0, 0.1, 1, obj=l, attr="glow")
        self._combo(card, "线条形状", [("straight", "直线"), ("curve", "曲线")], obj=l, attr="style")
        self._slider(card, "弯曲程度", -1.0, 1.0, 0.05, 2, obj=l, attr="bend",
                     show_when=lambda: l.style == "curve")

        card = self._card(layout, "动效")
        self._check(card, "虚线", l, "dash")
        self._slider(card, "实段长度", 1, 60, 1, obj=l, attr="dash_on",
                     show_when=lambda: l.dash)
        self._slider(card, "间隔长度", 0, 60, 1, obj=l, attr="dash_off",
                     show_when=lambda: l.dash)
        self._check(card, "流动动画", l, "flow")
        self._slider(card, "流动速度", -400, 400, 10, obj=l, attr="flow_speed",
                     show_when=lambda: l.flow)
        self._check(card, "沿线光点", l, "spark")
        self._slider(card, "光点大小", 0.5, 12.0, 0.5, 1, obj=l, attr="spark_size",
                     show_when=lambda: l.spark)
        self._check(card, "光标光环", l, "cursor_ring")
        self._color(card, "光环颜色", l, "ring_color",
                    show_when=lambda: l.cursor_ring)
        self._slider(card, "光环大小", 2, 40, 1, obj=l, attr="ring_size",
                     show_when=lambda: l.cursor_ring)
        layout.addStretch(1)
        return area

    # ================= 外观 =================
    def _page_look(self):
        b = self.cfg.box
        f = self.cfg.fill
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        card = self._card(layout, "元素框")
        self._check(card, "显示元素框", b, "visible")
        self._color(card, "框颜色", b, "color")
        self._slider(card, "粗细", 0.2, 8.0, 0.1, 1, obj=b, attr="width")
        self._slider(card, "不透明度", 0, 100, 5, suffix="%",
                     get_fn=lambda: b.opacity * 100.0 / 255.0,
                     set_fn=lambda v: setattr(b, "opacity", int(round(v * 255.0 / 100.0))))
        self._combo(card, "框样式", [
            ("bracket", "四角括号（科技感）"),
            ("rect", "完整矩形"),
            ("rounded", "圆角矩形"),
            ("dots", "四角圆点"),
        ], obj=b, attr="style")
        self._slider(card, "圆角大小", 0, 40, 1, obj=b, attr="radius",
                     show_when=lambda: b.style == "rounded")
        self._slider(card, "角长度", 2, 60, 1, obj=b, attr="corner",
                     show_when=lambda: b.style in ("bracket", "dots"))
        self._check(card, "只标注连线连到的元素（推荐）", b, "only_connected")

        card = self._card(layout, "框内填充")
        self._combo(card, "填充效果", [
            ("none", "不填充"),
            ("invert", "反色（负片）"),
            ("hsl", "调色（色相/鲜艳/明暗）"),
            ("solid", "纯色覆盖"),
            ("grayscale", "黑白"),
            ("sepia", "复古棕黄"),
            ("edge", "边缘线稿"),
            ("pixelate", "马赛克"),
        ], obj=f, attr="mode")
        self._slider(card, "填充强度", 0, 100, 5, suffix="%",
                     get_fn=lambda: f.opacity * 100.0 / 255.0,
                     set_fn=lambda v: setattr(f, "opacity", int(round(v * 255.0 / 100.0))))
        self._color(card, "填充颜色", f, "color",
                    show_when=lambda: f.mode == "solid")
        self._slider(card, "色相", 0, 360, 5, obj=f, attr="hue",
                     show_when=lambda: f.mode == "hsl")
        self._slider(card, "鲜艳度", 0.0, 2.0, 0.05, 2, obj=f, attr="saturation",
                     show_when=lambda: f.mode == "hsl")
        self._slider(card, "明暗", 0.0, 2.0, 0.05, 2, obj=f, attr="lightness",
                     show_when=lambda: f.mode == "hsl")
        self._check(card, "每个框颜色渐变（彩虹）", f, "rainbow",
                    show_when=lambda: f.mode == "hsl")
        self._slider(card, "马赛克颗粒", 2, 60, 1, obj=f, attr="pixel_size",
                     show_when=lambda: f.mode == "pixelate")
        self._note(card, "填充只作用于框内部的真实画面，框外不会有任何变化")
        layout.addStretch(1)
        return area

    # ================= 检测 =================
    def _page_detect(self):
        d = self.cfg.detect
        c = self.cfg.capture
        r = self.cfg.roi
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        card = self._card(layout, "检测范围")
        self._combo(card, "范围", [
            (False, "整个屏幕"),
            (True, "只看光标周围"),
        ], obj=r, attr="enabled")
        self._combo(card, "显示器", [
            (0, "全部显示器"), (1, "显示器 1"), (2, "显示器 2"), (3, "显示器 3"),
        ], obj=c, attr="monitor")
        self._spin(card, "范围大小", r, "width", 200, 5120, 40, " px",
                   mirror=((r, "height"),), show_when=lambda: r.enabled)

        card = self._card(layout, "识别灵敏度")
        self._slider(card, "灵敏度", 1, 10, 1,
                     get_fn=lambda: _canny_to_sens(d.canny_low),
                     set_fn=lambda v: self._set_sensitivity(int(round(v))))
        self._note(card, "越高框越多（太满就调低），越低只保留轮廓最分明的元素")
        self._spin(card, "最小元素", d, "min_area", 20, 20000, 50, " px²")
        self._spin(card, "最大元素", d, "max_area", 2000, 2000000, 5000, " px²")
        self._slider(card, "最小间距", 0, 200, 5, suffix=" px", obj=d, attr="min_dist")
        self._note(card, "两个元素中心距离小于该值时只保留较大的那个（防止框挤成一团），0 = 不限制")
        self._slider(card, "最多候选元素", 20, 400, 10, obj=d, attr="max_blobs")

        card = self._card(layout, "稳定与性能")
        self._combo(card, "框的稳定度", [
            ("灵敏", "灵敏（画面一动就更新）"),
            ("标准", "标准"),
            ("稳定", "稳定（画面不变框就不动）"),
        ], get_fn=self._get_stability, set_fn=self._set_stability)
        self._slider(card, "检测帧率", 1, 30, 1, suffix=" fps", obj=c, attr="fps")
        self._slider(card, "检测精细度", 0.15, 1.0, 0.05, 2, obj=d, attr="downscale")
        self._note(card, "卡顿时把“检测帧率”和“检测精细度”调低")
        layout.addStretch(1)
        return area

    # ================= 通用 =================
    def _page_misc(self):
        g = self.cfg.general
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        card = self._card(layout, "录屏与截屏")
        self._check(card, "允许被录屏 / 截图捕获", g, "exclude_from_capture",
                    get_fn=lambda: not g.exclude_from_capture,
                    set_fn=lambda v: setattr(g, "exclude_from_capture", not v))
        self._note(card, "默认关闭（特效不出现在任何录屏/截图里）。打开后程序会自动抹除"
                         "上一帧自己画的内容并提高稳定性档位，避免录制时框闪烁。")

        card = self._card(layout, "快捷键")
        hot = QHBoxLayout()
        for label, attr, placeholder in (
            ("显示/隐藏", "hotkey_toggle", "ctrl+alt+a"),
            ("打开设置", "hotkey_panel", "ctrl+alt+s"),
            ("退出程序", "hotkey_quit", "ctrl+alt+q"),
        ):
            box = QVBoxLayout()
            lab = QLabel(label)
            lab.setObjectName("dim")
            box.addWidget(lab)
            box.addWidget(_HotkeyEdit(g, attr, placeholder))
            hot.addLayout(box)
        card.addLayout(hot)
        self._note(card, "格式：ctrl+alt+a（改完按回车生效）")

        card = self._card(layout, "行为")
        self._slider(card, "画面刷新率", 5, 60, 1, suffix=" fps", obj=g, attr="ui_fps")
        self._check(card, "鼠标点击穿透（务必开启，否则挡住操作）", g, "click_through")
        self._check(card, "左上角显示运行状态", g, "show_hud")

        card = self._card(layout, "配置文件")
        path = QLabel(cfgmod.config_path())
        path.setObjectName("dim")
        path.setWordWrap(True)
        card.addWidget(path)
        layout.addStretch(1)
        return area

    # ================= 关于 =================
    def _page_about(self):
        area = self._page()
        layout = area._inner_layout  # type: ignore[attr-defined]

        card = self._card(layout, "DesktopBlobtrack")
        title = QLabel(f"DesktopBlobtrack v{__version__}")
        title.setObjectName("bigTitle")
        card.addWidget(title)
        desc = QLabel(
            "一个 Windows 桌面美学观赏类工具：实时识别屏幕上的界面元素，"
            "用描边框与鼠标连线把它们点缀出来。\n\n"
            "完全由 AI 编写制作，开源免费。"
        )
        desc.setWordWrap(True)
        card.addWidget(desc)

        card = self._card(layout, "联系方式")
        card.addWidget(QLabel("QQ：1524645067"))

        card = self._card(layout, "抖音主页")
        img_path = cfgmod.resource_path(os.path.join("assets", "douyin.jpg"))
        if os.path.isfile(img_path):
            img = QLabel()
            pm = QPixmap(img_path)
            if not pm.isNull():
                w = min(340, pm.width())
                img.setPixmap(pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation))
                card.addWidget(img)
        else:
            missing = QLabel("（图片资源缺失）")
            missing.setObjectName("dim")
            card.addWidget(missing)
        tip = QLabel("抖音号：67G_ · 邪恶小猫（薄肌版）\n保存上图后，打开抖音「扫一扫」即可直达主页")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        card.addWidget(tip)
        layout.addStretch(1)
        return area

    # ---- 组合参数的读写 ----
    def _set_sensitivity(self, v: int) -> None:
        low = _sens_to_canny(v)
        self.cfg.detect.canny_low = low
        self.cfg.detect.canny_high = max(low + 20, low * 3)

    def _get_stability(self) -> str:
        snap = int(self.cfg.detect.snap)
        confirm = int(self.cfg.detect.confirm_frames)
        best, best_diff = "标准", 999
        for name, (s, cf) in STABILITY_PRESETS.items():
            diff = abs(snap - s) + abs(confirm - cf) * 2
            if diff < best_diff:
                best, best_diff = name, diff
        return best

    def _set_stability(self, name: str) -> None:
        snap, confirm = STABILITY_PRESETS.get(name, STABILITY_PRESETS["标准"])
        self.cfg.detect.snap = snap
        self.cfg.detect.confirm_frames = confirm
        self.cfg.roi.snap = snap * 4

    # ================= 配置操作 =================
    def _save(self) -> None:
        try:
            path = self.cfg.save()
            self._toast("已保存到\n" + path)
        except Exception as exc:
            self._toast("保存失败: %s" % exc)

    def _reset(self) -> None:
        if QMessageBox.question(self, "恢复默认", "确定要恢复全部默认设置吗？") != QMessageBox.StandardButton.Yes:
            return
        fresh = Config()
        for section in ("capture", "detect", "roi", "box", "fill", "line", "general"):
            setattr(self.cfg, section, getattr(fresh, section))
        self.refresh()
        self._changed()

    def refresh(self) -> None:
        for fn in self._sync_fns:
            try:
                fn()
            except Exception:
                pass
        self._update_dynamic()

    def _toast(self, text: str) -> None:
        QMessageBox.information(self, "DesktopBlobtrack", text)


class _HotkeyEdit(QWidget):
    """快捷键输入框：格式校验 + 回车应用。"""

    def __init__(self, obj, attr, placeholder, parent=None):
        super().__init__(parent)
        self.obj = obj
        self.attr = attr
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(str(getattr(obj, attr)))
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(self._apply)
        layout.addWidget(self.edit)

    def _apply(self) -> None:
        from aura import win32_utils
        text = self.edit.text().strip().lower()
        try:
            vks = win32_utils.parse_hotkey(text)
        except ValueError:
            self._warn("无法识别的按键组合")
            self.edit.setText(str(getattr(self.obj, self.attr)))
            return
        if len(vks) < 2:
            self._warn("建议至少包含一个修饰键（ctrl / alt / shift）")
        setattr(self.obj, self.attr, text)
        panel = self.window()
        if isinstance(panel, SettingsPanel):
            panel._changed()

    def _warn(self, text: str) -> None:
        self.edit.setToolTip(text)
        self.edit.setStyleSheet("border:1px solid #e74c3c;")
