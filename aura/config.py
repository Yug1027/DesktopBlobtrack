"""配置模型：默认值、校验、JSON 序列化与反序列化。

所有参数均可在设置面板中实时调整，并保存到 %APPDATA%\\DesktopBlobtrack\\config.json。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Dict, Optional

APP_NAME = "DesktopBlobtrack"
OLD_APP_NAMES = ("DesktopAura",)  # 旧版目录，存在时自动迁移
CONFIG_NAME = "config.json"
LOG_NAME = "blobtrack.log"


def app_dir() -> str:
    """配置文件目录，优先 %APPDATA%，失败时回落到程序目录。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        if not os.path.isdir(path):
            _migrate_legacy(base)
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return path


def _migrate_legacy(base: str) -> None:
    """把旧名称目录（DesktopAura）下的配置/预设/日志迁移到新目录。"""
    import shutil
    target = os.path.join(base, APP_NAME)
    for old in OLD_APP_NAMES:
        src = os.path.join(base, old)
        if not os.path.isdir(src):
            continue
        try:
            os.makedirs(target, exist_ok=True)
            for name in ("config.json", "presets.json", "aura.log"):
                f = os.path.join(src, name)
                if os.path.isfile(f):
                    shutil.copy2(f, os.path.join(target, name))
        except OSError:
            pass


def config_path() -> str:
    return os.path.join(app_dir(), CONFIG_NAME)


def log_path() -> str:
    return os.path.join(app_dir(), LOG_NAME)


def presets_path() -> str:
    """用户自定义预设文件。"""
    return os.path.join(app_dir(), "presets.json")


def ui_state_path() -> str:
    """界面状态文件（最近使用颜色等）。"""
    return os.path.join(app_dir(), "ui_state.json")


def resource_path(rel: str) -> str:
    """打包/开发两用的资源路径（PyInstaller 单文件解压到 _MEIPASS）。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _coerce(value: Any, example: Any) -> Any:
    try:
        if isinstance(example, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if isinstance(example, int):
            return int(float(value))
        if isinstance(example, float):
            return float(value)
        if isinstance(example, str):
            return str(value)
    except (TypeError, ValueError):
        return example
    return value


@dataclass
class CaptureCfg:
    """屏幕捕获参数。"""
    fps: int = 12              # 捕获+检测帧率（1~30）
    monitor: int = 0           # 0 = 全部显示器（虚拟桌面），1..n = 指定显示器
    grab_timeout_ms: int = 200 # 单次捕获软超时（毫秒，仅用于统计告警）


@dataclass
class DetectCfg:
    """斑点检测参数。"""
    enabled: bool = True
    mode: str = "contour"      # contour = 连通域/轮廓；simpleblob = OpenCV SimpleBlobDetector
    downscale: float = 0.5     # 检测前缩放比例（越小越快）
    blur: int = 5              # 高斯模糊核（奇数，1 = 关闭）
    canny_low: int = 50        # Canny 低阈值
    canny_high: int = 150      # Canny 高阈值
    morph_kernel: int = 3      # 形态学核大小
    morph_iterations: int = 1  # 闭运算次数（连接断裂边缘）
    dilate_iterations: int = 1 # 膨胀次数（让斑点更饱满）
    min_area: int = 300        # 最小面积（屏幕逻辑像素²）
    max_area: int = 300000     # 最大面积
    min_aspect: float = 0.20   # 最小宽高比
    max_aspect: float = 5.0    # 最大宽高比
    min_extent: float = 0.25   # 轮廓面积 / 外接矩形面积 下限（过滤细长噪声）
    padding: int = 4           # 外边框外扩像素
    max_blobs: int = 220       # 最多保留的斑点数量（性能上限）
    nms_iou: float = 0.45      # 重叠框合并阈值（IoU）
    min_dist: float = 0.0      # 元素中心最小间距（屏幕逻辑像素，0=不限制）。即 BlobTrack 的 Delete Nearby
    snap: int = 4              # 结果框坐标吸附到该像素网格（0=关闭）。消抖动的关键
    confirm_frames: int = 2    # 元素需连续出现多少帧才绘制（1=立即，2~3 可滤掉一闪而过的噪声）
    # ---- SimpleBlobDetector 专用 ----
    blob_min_threshold: int = 40
    blob_max_threshold: int = 220
    blob_step: int = 20
    blob_bright: bool = True   # True = 检测亮斑，False = 检测暗斑
    blob_min_dist: float = 8.0
    filter_circularity: bool = False
    min_circularity: float = 0.30
    filter_convexity: bool = False
    min_convexity: float = 0.60
    filter_inertia: bool = False
    min_inertia: float = 0.20


@dataclass
class BoxCfg:
    """元素描边框样式。"""
    visible: bool = True
    color: str = "#3DE1FF"
    width: float = 1.8
    opacity: int = 200
    style: str = "bracket"     # rect / rounded / bracket / dots
    radius: float = 8.0        # rounded 圆角
    corner: float = 12.0       # bracket 角长 / dots 尺寸
    show_center: bool = False
    only_connected: bool = True  # 只绘制被连线连接到的元素框（没连到的不出现）
    highlight_new: bool = False  # 新出现的元素叠加一圈白色闪现框（会产生“两种框”的观感）


@dataclass
class RoiCfg:
    """光标区域蒙版：只截取/检测光标周围的画面（可选功能，默认关闭）。"""
    enabled: bool = False
    width: int = 960           # 蒙版宽（屏幕逻辑像素）
    height: int = 640          # 蒙版高
    smooth: float = 0.0        # 蒙版跟随平滑（0 = 瞬间跟随；>0 会让整组框缓慢漂移）
    snap: int = 16             # 蒙版左上角吸附到该像素网格：光标小幅移动时蒙版完全不动，框就不会变
    show_region: bool = False  # 绘制蒙版边界
    region_color: str = "#3DE1FF"
    region_opacity: int = 110


@dataclass
class FillCfg:
    """框内填充效果。"""
    mode: str = "none"         # none/solid/invert/hsl/grayscale/sepia/edge/pixelate
    color: str = "#3DE1FF"     # solid 纯色
    opacity: int = 170         # 效果整体不透明度
    hue: int = 160             # hsl 色相偏移 0-360
    saturation: float = 1.2    # hsl 饱和度倍率
    lightness: float = 1.1     # hsl 亮度倍率
    rainbow: bool = True       # hsl 逐框色相渐变
    pixel_size: int = 14       # pixelate 像素块大小
    max_boxes: int = 48        # 应用填充的框数上限（性能保护）


@dataclass
class LineCfg:
    """连线样式。"""
    visible: bool = True
    count: int = 7             # 连线数量（需求：5~10，可调至 20）
    mode: str = "nearest"      # nearest / random / mixed
    max_distance: int = 1400   # 连接范围：只连接该距离内的元素
    focus: float = 0.5         # 集中程度 0~1：随机/混合模式下，越大越偏向连接近处的元素
    color: str = "#FF6BD6"
    width: float = 1.6
    opacity: int = 220
    glow: float = 1.4          # 发光强度 0~3
    style: str = "straight"    # straight / curve
    bend: float = 0.18         # curve 弯曲程度
    dash: bool = True
    dash_on: float = 14.0
    dash_off: float = 10.0
    flow: bool = True
    flow_speed: float = 90.0   # 流动速度 px/s
    spark: bool = True         # 沿线跑动的光点
    spark_size: float = 3.0
    cursor_ring: bool = True
    ring_color: str = "#FFFFFF"
    ring_size: float = 9.0


@dataclass
class GeneralCfg:
    """通用行为。"""
    ui_fps: int = 30                  # 画面刷新帧率
    click_through: bool = True        # 鼠标穿透
    exclude_from_capture: bool = True # 覆盖层不被截屏/录屏捕获（防自反馈）
    show_hud: bool = False            # 左上角调试信息
    smooth: float = 0.0               # 框位置平滑（0 = 框严格等于检测结果；>0 会有缓动缩放感）
    overlay_visible: bool = True
    hotkey_toggle: str = "ctrl+alt+a"
    hotkey_panel: str = "ctrl+alt+s"
    hotkey_quit: str = "ctrl+alt+q"


@dataclass
class Config:
    capture: CaptureCfg = None  # type: ignore[assignment]
    detect: DetectCfg = None    # type: ignore[assignment]
    roi: RoiCfg = None          # type: ignore[assignment]
    box: BoxCfg = None          # type: ignore[assignment]
    fill: FillCfg = None        # type: ignore[assignment]
    line: LineCfg = None        # type: ignore[assignment]
    general: GeneralCfg = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.capture is None:
            self.capture = CaptureCfg()
        if self.detect is None:
            self.detect = DetectCfg()
        if self.roi is None:
            self.roi = RoiCfg()
        if self.box is None:
            self.box = BoxCfg()
        if self.fill is None:
            self.fill = FillCfg()
        if self.line is None:
            self.line = LineCfg()
        if self.general is None:
            self.general = GeneralCfg()

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "capture": _asdict(self.capture),
            "detect": _asdict(self.detect),
            "roi": _asdict(self.roi),
            "box": _asdict(self.box),
            "fill": _asdict(self.fill),
            "line": _asdict(self.line),
            "general": _asdict(self.general),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        obj = cls()
        if not isinstance(data, dict):
            return obj
        for f in fields(obj):
            sub = getattr(obj, f.name)
            if is_dataclass(sub):
                _fill(sub, data.get(f.name) or {})
        obj.validate()
        return obj

    def save(self, path: Optional[str] = None) -> str:
        path = path or config_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        path = path or config_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    return cls.from_dict(json.load(fp))
            except Exception:
                pass  # 配置损坏时静默回落到默认值
        return cls()

    # ---------- 校验 ----------
    def validate(self) -> None:
        c, d = self.capture, self.detect
        r, f = self.roi, self.fill
        b, l, g = self.box, self.line, self.general
        c.fps = int(_clamp(c.fps, 1, 30))
        c.monitor = int(_clamp(c.monitor, 0, 8))
        c.grab_timeout_ms = int(_clamp(c.grab_timeout_ms, 20, 5000))

        d.downscale = float(_clamp(d.downscale, 0.15, 1.0))
        d.blur = int(_clamp(d.blur, 1, 31)) | 1
        d.canny_low = int(_clamp(d.canny_low, 0, 500))
        d.canny_high = int(_clamp(max(d.canny_high, d.canny_low + 1), 1, 800))
        d.morph_kernel = int(_clamp(d.morph_kernel, 0, 15))
        d.morph_iterations = int(_clamp(d.morph_iterations, 0, 6))
        d.dilate_iterations = int(_clamp(d.dilate_iterations, 0, 6))
        d.min_area = int(_clamp(d.min_area, 4, 2_000_000))
        d.max_area = int(_clamp(max(d.max_area, d.min_area + 1), 5, 8_000_000))
        d.min_aspect = float(_clamp(d.min_aspect, 0.02, 1.0))
        d.max_aspect = float(_clamp(max(d.max_aspect, d.min_aspect + 0.01), 0.03, 40.0))
        d.min_extent = float(_clamp(d.min_extent, 0.0, 1.0))
        d.padding = int(_clamp(d.padding, 0, 60))
        d.max_blobs = int(_clamp(d.max_blobs, 1, 600))
        d.nms_iou = float(_clamp(d.nms_iou, 0.0, 0.95))
        d.min_dist = float(_clamp(d.min_dist, 0.0, 500.0))
        d.snap = int(_clamp(d.snap, 0, 32))
        d.confirm_frames = int(_clamp(d.confirm_frames, 1, 10))
        if d.mode not in ("contour", "simpleblob"):
            d.mode = "contour"
        d.blob_min_threshold = int(_clamp(d.blob_min_threshold, 0, 254))
        d.blob_max_threshold = int(_clamp(max(d.blob_max_threshold, d.blob_min_threshold + 1), 1, 255))
        d.blob_step = int(_clamp(d.blob_step, 1, 100))
        d.blob_min_dist = float(_clamp(d.blob_min_dist, 0.0, 500.0))
        d.min_circularity = float(_clamp(d.min_circularity, 0.0, 1.0))
        d.min_convexity = float(_clamp(d.min_convexity, 0.0, 1.0))
        d.min_inertia = float(_clamp(d.min_inertia, 0.0, 1.0))

        b.width = float(_clamp(b.width, 0.2, 12.0))
        b.opacity = int(_clamp(b.opacity, 0, 255))
        b.radius = float(_clamp(b.radius, 0.0, 60.0))
        b.corner = float(_clamp(b.corner, 2.0, 80.0))
        if b.style not in ("rect", "rounded", "bracket", "dots"):
            b.style = "bracket"
        _ensure_color(self, "box", "color", "#3DE1FF")

        r.width = int(_clamp(r.width, 200, 5120))
        r.height = int(_clamp(r.height, 200, 3200))
        r.smooth = float(_clamp(r.smooth, 0.0, 0.95))
        r.snap = int(_clamp(r.snap, 0, 256))
        r.region_opacity = int(_clamp(r.region_opacity, 0, 255))
        _ensure_color(self, "roi", "region_color", "#3DE1FF")

        f.opacity = int(_clamp(f.opacity, 0, 255))
        f.hue = int(_clamp(f.hue, 0, 360))
        f.saturation = float(_clamp(f.saturation, 0.0, 2.0))
        f.lightness = float(_clamp(f.lightness, 0.0, 2.0))
        f.pixel_size = int(_clamp(f.pixel_size, 2, 80))
        f.max_boxes = int(_clamp(f.max_boxes, 1, 200))
        if f.mode not in ("none", "solid", "invert", "hsl", "grayscale", "sepia", "edge", "pixelate"):
            f.mode = "none"
        _ensure_color(self, "fill", "color", "#3DE1FF")

        l.count = int(_clamp(l.count, 1, 20))
        l.focus = float(_clamp(l.focus, 0.0, 1.0))
        l.width = float(_clamp(l.width, 0.2, 12.0))
        l.opacity = int(_clamp(l.opacity, 0, 255))
        l.glow = float(_clamp(l.glow, 0.0, 3.0))
        l.max_distance = int(_clamp(l.max_distance, 50, 8000))
        l.bend = float(_clamp(l.bend, -1.0, 1.0))
        l.dash_on = float(_clamp(l.dash_on, 0.5, 200.0))
        l.dash_off = float(_clamp(l.dash_off, 0.0, 200.0))
        l.flow_speed = float(_clamp(l.flow_speed, -600.0, 600.0))
        l.spark_size = float(_clamp(l.spark_size, 0.5, 20.0))
        l.ring_size = float(_clamp(l.ring_size, 2.0, 60.0))
        if l.mode not in ("nearest", "random", "mixed"):
            l.mode = "nearest"
        if l.style not in ("straight", "curve"):
            l.style = "straight"
        _ensure_color(self, "line", "color", "#FF6BD6")
        _ensure_color(self, "line", "ring_color", "#FFFFFF")

        g.ui_fps = int(_clamp(g.ui_fps, 5, 120))
        g.smooth = float(_clamp(g.smooth, 0.0, 0.95))
        for key in ("hotkey_toggle", "hotkey_panel", "hotkey_quit"):
            value = str(getattr(g, key) or "").strip()
            if not value:
                value = {"hotkey_toggle": "ctrl+alt+a",
                         "hotkey_panel": "ctrl+alt+s",
                         "hotkey_quit": "ctrl+alt+q"}[key]
            setattr(g, key, value)


def _ensure_color(cfg: Config, section: str, attr: str, default: str) -> None:
    obj = getattr(cfg, section)
    value = str(getattr(obj, attr) or "").strip()
    if not value.startswith("#") or len(value) not in (4, 7, 9):
        value = default
    try:
        int(value[1:], 16)
    except ValueError:
        value = default
    setattr(obj, attr, value)


def _asdict(obj: Any) -> Dict[str, Any]:
    out = {}
    for f in fields(obj):
        out[f.name] = getattr(obj, f.name)
    return out


def _fill(obj: Any, data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        value = data[f.name]
        if is_dataclass(cur):
            _fill(cur, value or {})
        else:
            setattr(obj, f.name, _coerce(value, cur))
