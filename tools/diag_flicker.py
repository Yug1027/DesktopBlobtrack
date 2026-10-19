"""录屏模式闪烁离线诊断。

离线重放「截屏 -> 检测 -> 画框 -> 再截屏」的反馈回路：
屏幕内容固定为一张基准截图，只有覆盖层自绘内容逐帧叠加。
若回路收敛（框集合稳定），说明录屏时不会闪；若每帧新增/消失大量框，说明回路自激。

用法：
    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/diag_flicker.py [帧数]
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


def qimage_to_rgba(img) -> "np.ndarray":
    img = img.convertToFormat(img.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    arr = np.asarray(img.constBits(), dtype=np.uint8).reshape(h, w, 4).copy()  # BGRA
    return arr[:, :, [2, 1, 0, 3]]  # -> RGBA


def main() -> int:
    from PySide6.QtWidgets import QApplication
    import mss

    from aura.config import Config
    from aura.detector import detect_blobs, iou
    from aura.display import DisplayInfo
    from aura.overlay import Overlay
    from aura.tracker import BlobTracker

    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    app = QApplication.instance() or QApplication(sys.argv)
    with mss.MSS() as sct:
        mon = sct.monitors[1]
        shot = np.asarray(sct.grab(mon))
    base_bgr = shot[:, :, :3].copy()
    H, W = base_bgr.shape[:2]
    # 诊断用固定 1:1 坐标（offscreen 平台的虚拟屏尺寸不可信）
    disp = DisplayInfo(origin=(0, 0), size=(W, H), capture_rect=(0, 0, W, H),
                       physical_rect=(0, 0, W, H), capture_scale=1.0, cursor_scale=1.0)
    print(f"base frame: {W}x{H}")

    cfg = Config()
    cfg.general.exclude_from_capture = False     # 录屏模式
    if cfg.detect.snap < 8:
        cfg.detect.snap = 8
    cfg.box.only_connected = bool(cfg.box.only_connected)
    cfg.line.visible = True

    tracker = BlobTracker()
    tracker.max_missing = 0
    tracker.smoothing = 0.0
    tracker.confirm_frames = int(cfg.detect.confirm_frames)

    ov = Overlay(cfg, tracker, disp)
    ov.setGeometry(disp.origin[0], disp.origin[1], disp.size[0], disp.size[1])
    ov.show()
    app.processEvents()

    import cv2

    scale = float(cfg.detect.downscale)
    k = disp.capture_scale * scale
    cursor_cap = disp.to_capture_from_cursor(*disp.origin)  # 光标固定在屏幕左上附近，稳定

    prev_boxes_cap: list = []
    prev_gray = cv2.cvtColor(base_bgr, cv2.COLOR_BGR2GRAY)
    prev_sets: list = []
    stats = {"new": [], "lost": [], "count": []}

    for f in range(frames):
        # 1) 上一帧绘制内容合成到基准画面上（= 录屏软件看到的画面）
        pm = ov.grab()
        ov_rgba = qimage_to_rgba(pm.toImage())
        if ov_rgba.shape[1] != base_bgr.shape[1] or ov_rgba.shape[0] != base_bgr.shape[0]:
            ov_rgba = cv2.resize(ov_rgba, (base_bgr.shape[1], base_bgr.shape[0]),
                                 interpolation=cv2.INTER_NEAREST)
        a = ov_rgba[:, :, 3:4].astype(np.float32) / 255.0
        rgb = ov_rgba[:, :, :3].astype(np.float32)
        comp = base_bgr.astype(np.float32) * (1.0 - a) + rgb[:, :, ::-1] * a
        comp = np.clip(comp, 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(comp, cv2.COLOR_BGR2GRAY)

        # 2) 抹除上一帧自绘内容（capture.py 的逻辑）
        from aura.capture import CaptureWorker
        eraser = CaptureWorker.__new__(CaptureWorker)   # 只借用 _erase_self_drawing
        eraser.disp = disp
        eraser._prev_boxes_cap = prev_boxes_cap
        eraser._prev_cursor_cap = cursor_cap
        mon_d = {"left": disp.capture_rect[0], "top": disp.capture_rect[1],
                 "width": disp.capture_rect[2], "height": disp.capture_rect[3]}
        cfg.general.exclude_from_capture = False
        erased = eraser._erase_self_drawing(gray, mon_d, cfg)
        if os.environ.get("DBT_DIAG_NOFREEZE"):
            # 对照组：不冻结动效（= 修复前的行为）
            cfg.general.exclude_from_capture = True

        # 3) 检测
        boxes = detect_blobs(erased, cfg.detect, k)

        # 4) 统计抖动
        cur = [tuple(round(v, 1) for v in b) for b in boxes]
        if prev_sets:
            prev = prev_sets[-1]
            new = sum(1 for b in cur if not any(iou(b, p) > 0.5 for p in prev))
            lost = sum(1 for p in prev if not any(iou(b, p) > 0.5 for b in cur))
            stats["new"].append(new)
            stats["lost"].append(lost)
        stats["count"].append(len(cur))
        prev_sets.append(cur)

        # 5) 画下一帧
        payload = {"boxes": boxes, "fills": [], "roi": None}
        ov._cursor = (disp.origin[0] + 40.0, disp.origin[1] + 40.0)
        ov._elapsed += 1.0 / 15.0
        ov.set_payload(payload)
        app.processEvents()
        ov.repaint()
        app.processEvents()

        s = disp.capture_scale
        prev_boxes_cap = [(disp.capture_rect[0] + bx * s, disp.capture_rect[1] + by * s,
                           bw * s, bh * s) for (bx, by, bw, bh) in boxes]

    n = len(stats["new"])
    if n:
        print(f"\n录屏模式 {frames} 帧:")
        print(f"  平均每帧新增 {sum(stats['new'])/n:.2f} / 消失 {sum(stats['lost'])/n:.2f} 个框")
        stable = sum(1 for i in range(n) if stats["new"][i] == 0 and stats["lost"][i] == 0)
        print(f"  完全稳定帧 {stable}/{n}")
        print(f"  框数量 min={min(stats['count'])} max={max(stats['count'])} avg={sum(stats['count'])/len(stats['count']):.1f}")
        print(f"  逐帧新增: {stats['new']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
