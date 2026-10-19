"""屏幕捕获 + 检测工作线程。

独立于 GUI 线程运行。两种捕获范围：
1. 光标区域蒙版（默认）：只截取光标周围 width x height 的画面，蒙版平滑跟随光标，
   框随光标实时变化，且检测/特效计算量大幅降低；
2. 全屏/指定显示器：捕获整个虚拟桌面。

捕获 → 灰度 → 斑点检测 → 框内填充效果（反色/HSL/灰度/棕褐/边缘/像素化）→
统一打包为 payload 发给 GUI 线程。所有参数每帧实时读取配置，改了立刻生效。
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from aura import win32_utils
from aura.config import Config
from aura.detector import detect_blobs
from aura.display import DisplayInfo

logger = logging.getLogger(__name__)

# 单个填充贴图的最大像素数（防止巨框拖慢绘制）。
# 之前是 1.6M，而 1920×1080 的整屏框就有 2.07M —— 大窗口一旦超过阈值就没有填充，
# 尺寸在阈值附近抖动时表现为“填充忽有忽无”。放宽到 8M（约 4K 全屏）。
MAX_FILL_PIXELS = 8_000_000


def make_sct():
    """兼容 mss 9/10：优先 mss.MSS（10+），回落 mss.mss（9.x）。"""
    import mss
    factory = getattr(mss, "MSS", None)
    if factory is not None:
        return factory()
    return mss.mss()


def probe_capture_rect():
    """返回 mss 虚拟桌面矩形，失败返回 None。"""
    try:
        with make_sct() as sct:
            m = sct.monitors[0]
            return (m["left"], m["top"], m["width"], m["height"])
    except Exception as exc:
        logger.warning("mss 初始化失败: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 框内填充效果
# ---------------------------------------------------------------------------

def apply_hsl(bgr: "np.ndarray", hue_deg: float, sat_mult: float, light_mult: float) -> "np.ndarray":
    """HSL 风格调色（OpenCV HSV 实现：H∈[0,180)，S/V∈[0,255]）。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    h = (h.astype(np.int32) + int(round(hue_deg / 2.0))) % 180
    s = np.clip(s.astype(np.float32) * sat_mult, 0, 255).astype(np.uint8)
    v = np.clip(v.astype(np.float32) * light_mult, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([h.astype(np.uint8), s, v]), cv2.COLOR_HSV2BGR)


def apply_effect_bgr(bgr: "np.ndarray", mode: str, fcfg) -> "np.ndarray":
    """对 BGR 三通道应用整帧效果，返回 BGR。"""
    if mode == "invert":
        return cv2.bitwise_not(bgr)
    if mode == "grayscale":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if mode == "sepia":
        kernel = np.array([
            [0.393, 0.769, 0.189],
            [0.349, 0.686, 0.168],
            [0.272, 0.534, 0.131],
        ], dtype=np.float32)
        out = cv2.transform(bgr, kernel)
        return np.clip(out, 0, 255).astype(np.uint8)
    if mode == "hsl":
        return apply_hsl(bgr, fcfg.hue, fcfg.saturation, fcfg.lightness)
    if mode == "edge":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 180)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    if mode == "pixelate":
        h, w = bgr.shape[:2]
        ps = max(2, int(fcfg.pixel_size))
        nw, nh = max(1, w // ps), max(1, h // ps)
        small = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return bgr


def to_qimage_bgra(bgra: "np.ndarray") -> QImage:
    """numpy BGRA(HxWx4, 连续) -> 拥有独立数据的 QImage。"""
    h, w = bgra.shape[:2]
    data = np.ascontiguousarray(bgra)
    return QImage(data.tobytes(), w, h, w * 4, QImage.Format.Format_ARGB32).copy()


class CaptureWorker(QThread):
    """payload 结构：
    {
        "boxes":  [(x, y, w, h), ...]    # 屏幕逻辑坐标（未平滑）
        "fills":  [(index, QImage), ...] # 框内填充贴图，index = boxes 里的下标
        "roi":    (x, y, w, h) or None  # 蒙版区域（屏幕逻辑坐标）
    }
    """
    blobs = Signal(dict)
    stats = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: Config, disp: DisplayInfo, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.disp = disp
        self._stop = threading.Event()
        self._consecutive_failures = 0
        self._roi_x: Optional[float] = None  # 蒙版平滑位置（捕获像素坐标）
        self._roi_y: Optional[float] = None
        # 最近两帧“我们画过的东西”（捕获像素坐标），用于录屏模式下从检测输入中抹除。
        # 保留两帧是因为捕获与绘制异步：屏幕上可能还留着上一帧的绘制残留。
        self._prev_boxes_cap: List[Tuple[float, float, float, float]] = []
        self._prev_cursor_cap: Optional[Tuple[float, float]] = None
        self._prev2_boxes_cap: List[Tuple[float, float, float, float]] = []
        self._prev2_cursor_cap: Optional[Tuple[float, float]] = None
        # 覆盖层回调：返回“此刻屏幕上真实画着的框 + 光标”（捕获像素坐标）。
        # 由 main.py 装配，比在捕获线程里推算准确得多（only_connected / 随机挑选都在 GUI 侧）。
        self.drawn_provider: Optional[Callable[[], Tuple[List[Tuple[float, float, float, float]],
                                                         Optional[Tuple[float, float]]]]] = None
        self._last_drawn_boxes: List[Tuple[float, float, float, float]] = []
        self._last_drawn_cursor: Optional[Tuple[float, float]] = None
        self._prev_drawn_boxes: List[Tuple[float, float, float, float]] = []
        self._prev_drawn_cursor: Optional[Tuple[float, float]] = None
        # 上一帧“已抹除自绘内容”的干净灰度图：用来回填被抹除的像素，
        # 比模糊/修复更能还原真实画面，从而不伤检测
        self._clean_prev: Optional["np.ndarray"] = None
        # 上一帧覆盖层实际画出来的框下标，用来决定给哪些框生成填充贴图
        self._last_drawn_indices: List[int] = []
        self._pending_drawn: Optional[Tuple[List[Tuple[float, float, float, float]],
                                            Optional[Tuple[float, float]]]] = None
        # 当前捕获矩形原点（捕获像素坐标）：把覆盖层上报的框换算到帧坐标时需要
        self._frame_origin: Tuple[float, float] = (0.0, 0.0)

    # ---- 生命周期 ----
    def stop(self, wait_ms: int = 0) -> None:
        """请求停止。

        默认 wait_ms=0：**不阻塞调用线程**。捕获循环可能在一次 mss grab 中
        （GDI 忙时会阻塞数百毫秒），若在 GUI 线程里 wait，托盘菜单/按钮就会“假死”。
        """
        self._stop.set()
        if wait_ms and wait_ms > 0 and self.isRunning():
            self.wait(wait_ms)

    def set_display(self, disp: DisplayInfo) -> None:
        self.disp = disp
        self._roi_x = None
        self._roi_y = None
        self._prev_boxes_cap = []
        self._prev_cursor_cap = None
        self._prev2_boxes_cap = []
        self._prev2_cursor_cap = None
        self._clean_prev = None

    # ---- 蒙版区域 ----
    def _target_roi(self, base: dict, cfg: Config) -> Tuple[int, int, int, int]:
        """计算以光标为中心、限制在 base 区域内的捕获矩形（捕获像素坐标）。"""
        r = cfg.roi
        vx, vy = int(base["left"]), int(base["top"])
        vw, vh = int(base["width"]), int(base["height"])

        rw = int(min(r.width * self.disp.capture_scale, vw))
        rh = int(min(r.height * self.disp.capture_scale, vh))

        cx, cy = self.disp.to_capture_from_cursor(*win32_utils.get_cursor_pos())
        tx = min(max(cx - rw / 2.0, vx), vx + vw - rw)
        ty = min(max(cy - rh / 2.0, vy), vy + vh - rh)

        if self._roi_x is None or r.smooth <= 0.0:
            self._roi_x, self._roi_y = tx, ty
        else:
            a = 1.0 - float(r.smooth)
            self._roi_x += (tx - self._roi_x) * a
            self._roi_y += (ty - self._roi_y) * a

        x = int(round(self._roi_x))
        y = int(round(self._roi_y))
        # 关键：把蒙版左上角吸附到固定网格（相对虚拟桌面原点）。
        # 光标小幅移动时蒙版完全不动 → 截取到的画面逐像素一致 → 检测结果不变、框不闪。
        snap = int(r.snap)
        if snap > 1:
            x = vx + int(round((x - vx) / snap) * snap)
            y = vy + int(round((y - vy) / snap) * snap)
        x = min(max(x, vx), vx + vw - rw)
        y = min(max(y, vy), vy + vh - rh)
        return x, y, rw, rh

    # ---- 录屏模式的自绘抹除 ----
    def _erase_self_drawing(self, gray: "np.ndarray", mon: dict, cfg: Config) -> "np.ndarray":
        """录屏/截图允许捕获覆盖层时，把自己画的描边/连线/光环从检测输入里抹掉。

        原理：覆盖层被截屏后，自己画的框边和连线会被检测成“新元素”，再画再截，
        形成反馈回路 → 框抖动/闪烁。这里把「屏幕上真实存在的自绘像素」用平滑后的
        画面覆盖掉，检测看到的是干净画面，反馈回路被切断。

        三个关键点（缺一个都会继续闪）：
        1. 只抹“真正画出来的框”：only_connected 时覆盖层只画被连线的少数几个框，
           若把全部检测结果（几十个）都抹掉，会大面积破坏检测输入、反而制造新元素。
        2. 抹最近两帧的内容：捕获与绘制是异步的，屏幕上可能还留着上一帧的绘制，
           只抹一帧会漏掉。
        3. 用“模糊 + 羽化”而不是 inpaint：inpaint 会重建出新的边缘，被 Canny 当成
           新元素；模糊区域梯度接近 0，检测不到任何东西，且羽化边界不产生新边。
        """
        h, w = gray.shape[:2]
        ox, oy = int(mon["left"]), int(mon["top"])
        s = max(0.1, self.disp.capture_scale)

        groups = self._drawn_groups(cfg, s)
        if not groups:
            return gray

        # 描边框：只遮边线环，不遮框内（否则真实元素会从检测中消失）
        bw = max(3, int(cfg.box.width * s) + 3)
        lw = max(3, int(cfg.line.width * (1.0 + 3.0 * cfg.line.glow) * s) + 5)
        pad = bw + 8

        # 先在“自绘内容的外接矩形”这张小图上画掩膜：全屏模糊太贵，
        # 实际要处理的往往只有屏幕的一小块。
        xmin = ymin = 1 << 30
        xmax = ymax = -(1 << 30)
        for boxes, cursor in groups:
            for (x, y, bw_, bh_) in boxes:
                xmin = min(xmin, int(x - ox))
                ymin = min(ymin, int(y - oy))
                xmax = max(xmax, int(x - ox + bw_))
                ymax = max(ymax, int(y - oy + bh_))
            if cursor is not None and cfg.line.visible and boxes:
                xmin = min(xmin, int(cursor[0] - ox))
                ymin = min(ymin, int(cursor[1] - oy))
                xmax = max(xmax, int(cursor[0] - ox))
                ymax = max(ymax, int(cursor[1] - oy))
        if xmin > xmax:
            self._clean_prev = gray
            return gray
        xmin = max(0, xmin - pad)
        ymin = max(0, ymin - pad)
        xmax = min(w - 1, xmax + pad)
        ymax = min(h - 1, ymax + pad)
        if xmax <= xmin or ymax <= ymin:
            self._clean_prev = gray
            return gray

        rw = xmax - xmin + 1
        rh = ymax - ymin + 1
        mask = np.zeros((rh, rw), dtype=np.uint8)
        # 填充是一整块改造过的画面，也会被检测当成新元素 —— 一并回填。
        # 注意抹除只作用于“检测输入”，录制下来的画面依然带完整特效。
        fill_on = str(getattr(cfg.fill, "mode", "none")) not in ("none",)
        for boxes, cursor in groups:
            for (x, y, bw_, bh_) in boxes:
                cv2.rectangle(mask,
                              (int(x - ox) - 1 - xmin, int(y - oy) - 1 - ymin),
                              (int(x - ox + bw_) + 1 - xmin, int(y - oy + bh_) + 1 - ymin),
                              255, bw)
                if fill_on:
                    cv2.rectangle(mask,
                                  (int(x - ox) - xmin, int(y - oy) - ymin),
                                  (int(x - ox + bw_) - xmin, int(y - oy + bh_) - ymin),
                                  255, -1)
            # 连线：光标到被连接框的中心（与覆盖层实际画的一致）
            if cursor is not None and cfg.line.visible and boxes:
                mx, my = int(cursor[0] - ox) - xmin, int(cursor[1] - oy) - ymin
                for (x, y, bw_, bh_) in boxes:
                    cv2.line(mask, (mx, my),
                             (int(x - ox + bw_ / 2.0) - xmin, int(y - oy + bh_ / 2.0) - ymin),
                             255, lw)
                if cfg.line.cursor_ring:
                    r = max(2, int(cfg.line.ring_size * s) + 3)
                    cv2.circle(mask, (mx, my), r, 255, 3)

        if not mask.any():
            self._clean_prev = gray
            return gray
        try:
            # 先膨胀让笔画核心处权重达到 1（否则会残留亮边被 Canny 抓到）
            hard = cv2.dilate(mask, np.ones((5, 5), dtype=np.uint8), iterations=2)
            # 羽化：边界平滑过渡，不会像直接替换那样产生新的锐利边缘
            soft = cv2.blur(hard, (11, 11)).astype(np.uint16)

            g = gray[ymin:ymax + 1, xmin:xmax + 1]
            prev = getattr(self, "_clean_prev", None)
            if prev is None or prev.shape != gray.shape:
                p = cv2.blur(g, (13, 13))
            else:
                p = prev[ymin:ymax + 1, xmin:xmax + 1]
            # 用“上一帧已抹除的干净画面”回填，而不是模糊掉：
            # 笔画下面的真实内容基本不变，回填能最大程度还原原画面、几乎不伤检测
            blend = (g.astype(np.uint16) * (255 - soft) + p.astype(np.uint16) * soft) >> 8
            blend = blend.astype(np.uint8)

            clean = gray.copy()
            clean[ymin:ymax + 1, xmin:xmax + 1] = blend
            self._clean_prev = clean
            return clean
        except Exception:
            return gray

    def _poll_drawn(self) -> None:
        """每帧读一次覆盖层的绘制报告（框 / 光标 / 下标）。

        无论是否处于录屏模式都要读：填充贴图要靠“上一帧画了哪些框”来定位，
        否则只能退化成“前 N 个检测结果”，导致被连线的框一会儿有填充一会儿没有。
        """
        if self.drawn_provider is None:
            return
        try:
            report = self.drawn_provider()
        except Exception:
            return
        try:
            self._last_drawn_indices = [int(i) for i in (report[2] or [])]
            self._last_drawn_boxes = [tuple(float(v) for v in b) for b in (report[0] or [])]
            self._pending_drawn = (list(report[0] or []), report[1])
        except Exception:
            pass

    def _drawn_groups(self, cfg: Config, s: float):
        """返回 [(框列表, 光标), ...]：此刻与上一刻屏幕上真实画着的内容。"""
        live = getattr(self, "_pending_drawn", None)
        self._pending_drawn = None
        if live is not None:
            self._last_drawn_boxes, self._last_drawn_cursor = live
            groups = [live]
            if self._prev_drawn_boxes:
                groups.append((self._prev_drawn_boxes, self._prev_drawn_cursor))
            self._prev_drawn_boxes, self._prev_drawn_cursor = live
            return groups
        # 兜底：没有回调时（单测/诊断）按捕获线程自己的记录推算
        return [(b, c) for (b, c) in ((self._prev_boxes_cap, self._prev_cursor_cap),
                                      (self._prev2_boxes_cap, self._prev2_cursor_cap))
                if b or c is not None]

    # ---- 填充贴图 ----
    def _build_fills(self, frame_bgra: "np.ndarray", boxes_img: List[Tuple[float, float, float, float]],
                     scale: float, cfg: Config) -> List[Tuple[int, QImage]]:
        """为每个检测框生成“框内画面 + 效果”的贴图。

        返回 [(源索引, QImage), ...]：源索引 = 该框在 payload["boxes"] 里的下标，
        覆盖层据此只给“真正画出来的框”填充，绝不画到框外面去。
        """
        f = cfg.fill
        if f.mode in ("none", "solid") or not boxes_img:
            return []

        # 只给“真正会被画出来的框”做贴图（按位置匹配上一帧覆盖层上报的框）。
        # 以前是给检测结果的前 N 个做，而 only_connected 实际只画被连线的少数几个，
        # 于是这几个框会因为排序抖动一会儿落在 N 以内、一会儿落到外面 → 填充忽有忽无地乱闪。
        wanted = self._wanted_fill_indices(boxes_img, scale)

        fh, fw = frame_bgra.shape[:2]
        # rainbow 模式需要逐框处理，其余模式整帧处理一次再裁剪
        whole: Optional["np.ndarray"] = None
        if not (f.mode == "hsl" and f.rainbow):
            bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
            whole = apply_effect_bgr(bgr, f.mode, f)

        fills: List[Tuple[int, QImage]] = []
        for i, box_img in enumerate(boxes_img):
            if i not in wanted:
                continue
            # 检测图坐标 -> 全分辨率帧坐标
            x = int(round(box_img[0] / scale))
            y = int(round(box_img[1] / scale))
            w = int(round(box_img[2] / scale))
            h = int(round(box_img[3] / scale))
            x = max(0, min(fw - 2, x))
            y = max(0, min(fh - 2, y))
            w = max(2, min(fw - x, w))
            h = max(2, min(fh - y, h))
            if w * h > MAX_FILL_PIXELS:
                continue
            crop = frame_bgra[y:y + h, x:x + w]
            if f.mode == "hsl" and f.rainbow:
                bgr = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)
                # 色相由“框在屏幕上的位置”决定，而不是检测序号：
                # 序号会随排序变化，位置不会 —— 否则彩虹色每帧乱跳
                eff = apply_hsl(bgr, f.hue + (x + y) * 0.35, f.saturation, f.lightness)
            else:
                eff = whole[y:y + h, x:x + w]  # type: ignore[index]
            bgra = np.dstack([eff, np.full(eff.shape[:2], 255, dtype=np.uint8)])
            fills.append((i, to_qimage_bgra(bgra)))
        return fills

    def _wanted_fill_indices(self, boxes_img, scale: float) -> set:
        """挑出“下一帧大概率会被画出来”的框下标。

        用**位置**匹配上一帧覆盖层上报的框，而不是复用下标：
        检测结果每帧会增减，同一个下标在不同帧指向的很可能不是同一个框，
        用下标会让填充贴错框 / 漏框，表现为忽有忽无地乱闪。
        拿不到上一帧位置时（首帧）退化为前 max_boxes 个，保证功能不残。
        """
        box_count = len(boxes_img)
        f = self.cfg.fill
        fallback = set(range(min(box_count, max(1, int(f.max_boxes)))))
        prev = self._last_drawn_boxes
        if not prev or scale <= 0:
            return fallback

        ox, oy = self._frame_origin
        # 上一帧画过的框中心（全分辨率帧坐标）
        targets = [(b[0] - ox + b[2] / 2.0, b[1] - oy + b[3] / 2.0,
                    max(4.0, (b[2] + b[3]) / 4.0)) for b in prev]
        wanted: set = set()
        centers = []
        for i, (bx, by, bw, bh) in enumerate(boxes_img):
            cx = bx / scale + bw / scale / 2.0
            cy = by / scale + bh / scale / 2.0
            centers.append((cx, cy))
            for (tx, ty, tol) in targets:
                if abs(cx - tx) <= tol and abs(cy - ty) <= tol:
                    wanted.add(i)
                    break

        # 补上“离光标最近的几个框”：刚被连线连上的新框没有上一帧位置可匹配，
        # 不补的话它会空一帧没填充，看起来就是闪一下。
        cur = self._prev_cursor_cap
        if cur is not None and self.cfg.line.visible and self.cfg.box.only_connected:
            mx, my = cur[0] - ox, cur[1] - oy
            near = sorted(range(len(centers)),
                          key=lambda i: (centers[i][0] - mx) ** 2 + (centers[i][1] - my) ** 2)
            wanted.update(near[: max(1, int(self.cfg.line.count))])
        return wanted or fallback

    # ---- 主循环 ----
    def run(self) -> None:  # noqa: C901 - 线程入口，保持直观
        # 线程可被多次 start（隐藏覆盖层后再显示），必须清掉上一轮的停止标志
        self._stop.clear()
        self._consecutive_failures = 0
        self._prev_boxes_cap = []
        self._prev_cursor_cap = None
        try:
            import mss  # noqa: F401 - 仅验证可用性
        except Exception as exc:  # pragma: no cover
            self.failed.emit(f"无法加载 mss: {exc}")
            return

        try:
            with make_sct() as sct:
                while not self._stop.is_set():
                    frame_start = time.perf_counter()
                    cfg = self.cfg
                    self._poll_drawn()
                    payload: dict = {"boxes": [], "fills": [], "roi": None}
                    try:
                        monitors = sct.monitors
                        idx = int(cfg.capture.monitor)
                        if cfg.roi.enabled:
                            # 蒙版模式：光标周围的局部区域（跨显示器跟随）
                            base = monitors[0]
                            if 0 < idx < len(monitors):
                                base = monitors[idx]
                            x, y, rw, rh = self._target_roi(base, cfg)
                            mon = {"left": x, "top": y, "width": rw, "height": rh}
                        else:
                            mon = monitors[0] if (idx <= 0 or idx >= len(monitors)) else monitors[idx]

                        self._frame_origin = (float(mon["left"]), float(mon["top"]))
                        shot = sct.grab(mon)
                        h, w = shot.height, shot.width
                        raw = shot.raw
                        if len(raw) == h * w * 4:
                            frame = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        else:  # 兜底：走 mss 的 RGB 数组接口
                            frame = np.asarray(shot)  # type: ignore[arg-type]
                            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

                        # 录屏模式（允许被捕获）：检测输入先抹掉屏幕上的自绘内容
                        if cfg.general.exclude_from_capture:
                            gray_detect = gray
                            self._clean_prev = None      # 切回正常模式，丢弃回填缓存
                        else:
                            gray_detect = self._erase_self_drawing(gray, mon, cfg)

                        roi_logical = None
                        if cfg.roi.enabled:
                            lx, ly = self.disp.to_logical_from_capture(mon["left"], mon["top"])
                            roi_logical = (lx, ly, rw / self.disp.capture_scale, rh / self.disp.capture_scale)

                        scale = float(cfg.detect.downscale)
                        k = self.disp.capture_scale * scale
                        if k <= 0:
                            k = 1.0
                        # 录屏模式下自动加大坐标吸附，进一步抑制自反馈抖动
                        if not cfg.general.exclude_from_capture and cfg.detect.snap < 8:
                            detect_cfg = dataclasses.replace(cfg.detect, snap=8)
                        else:
                            detect_cfg = cfg.detect
                        if cfg.detect.enabled:
                            boxes_img = detect_blobs(gray_detect, detect_cfg, k)
                        else:
                            boxes_img = []

                        # 检测图坐标 -> 屏幕逻辑坐标
                        boxes: List[Tuple[float, float, float, float]] = []
                        for (bx, by, bw, bh) in boxes_img:
                            px = mon["left"] + bx / scale
                            py = mon["top"] + by / scale
                            sx, sy = self.disp.to_logical_from_capture(px, py)
                            sw = (bw / scale) / self.disp.capture_scale
                            sh = (bh / scale) / self.disp.capture_scale
                            boxes.append((sx, sy, sw, sh))

                        fills = self._build_fills(frame, boxes_img, scale, cfg) \
                            if cfg.detect.enabled else []

                        payload = {"boxes": boxes, "fills": fills, "roi": roi_logical}
                        self.blobs.emit(payload)
                        self._consecutive_failures = 0

                        # 记录本帧画过的内容（捕获坐标系），供后续帧自绘抹除使用
                        cs = self.disp.capture_scale
                        self._prev2_boxes_cap = self._prev_boxes_cap
                        self._prev2_cursor_cap = self._prev_cursor_cap
                        self._prev_boxes_cap = [
                            (*self.disp.to_capture_from_logical(bx, by), bw * cs, bh * cs)
                            for (bx, by, bw, bh) in boxes
                        ]
                        self._prev_cursor_cap = self.disp.to_capture_from_cursor(
                            *win32_utils.get_cursor_pos())

                        cost_ms = (time.perf_counter() - frame_start) * 1000.0
                        self.stats.emit({
                            "fps": cfg.capture.fps,
                            "count": len(boxes),
                            "ms": round(cost_ms, 2),
                        })
                    except Exception as exc:
                        self._consecutive_failures += 1
                        logger.warning("捕获/检测失败(%d): %s", self._consecutive_failures, exc)
                        if self._consecutive_failures in (3, 20):
                            self.failed.emit(f"屏幕捕获连续失败 {self._consecutive_failures} 次: {exc}")
                        if self._consecutive_failures >= 60:
                            self.failed.emit("屏幕捕获持续失败，已自动暂停（可通过托盘菜单重新开始）")
                            return
                        self._sleep(0.5)
                        continue

                    # 保持目标帧率（处理耗时长于帧间隔时不睡眠）
                    target = 1.0 / max(1, int(cfg.capture.fps))
                    spent = time.perf_counter() - frame_start
                    if spent < target:
                        self._sleep(target - spent)
        except Exception as exc:  # pragma: no cover - 严重错误
            logger.exception("捕获线程崩溃")
            self.failed.emit(f"捕获线程异常退出: {exc}")

    def _sleep(self, seconds: float) -> None:
        # 分片睡眠，保证 stop() 能快速响应
        deadline = time.perf_counter() + max(0.0, seconds)
        while not self._stop.is_set():
            remain = deadline - time.perf_counter()
            if remain <= 0:
                break
            time.sleep(min(0.05, remain))
