"""录屏模式闪烁「实机」诊断。

真实启动 CaptureWorker + 真实可见的 Overlay，让覆盖层确实被 mss 捕获到，
统计每帧框集合的新增/消失数量，量化录屏时的闪烁程度。

用法：.venv/Scripts/python.exe tools/diag_flicker_live.py [秒数] [exclude_from_capture]
    例：python tools/diag_flicker_live.py 4 0     # 录屏模式
        python tools/diag_flicker_live.py 4 1     # 正常模式（对照）
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from aura.capture import CaptureWorker
    from aura.config import Config
    from aura.detector import iou
    from aura.display import DisplayInfo
    from aura.overlay import Overlay
    from aura.tracker import BlobTracker

    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    exclude = bool(int(sys.argv[2])) if len(sys.argv) > 2 else False
    mode = sys.argv[3] if len(sys.argv) > 3 else "all"
    fill_mode = sys.argv[4] if len(sys.argv) > 4 else "none"
    tag_extra = ""

    app = QApplication.instance() or QApplication(sys.argv)
    disp = DisplayInfo.probe()
    cfg = Config()
    cfg.general.exclude_from_capture = exclude
    cfg.capture.fps = 15
    cfg.general.ui_fps = 30

    if fill_mode and fill_mode != "none":
        cfg.fill.mode = fill_mode
        tag_extra += f" [填充={fill_mode}]"

    if mode == "none":
        cfg.box.visible = False
        cfg.line.visible = False
        tag_extra = " [不绘制]"
    elif mode == "nobox":
        cfg.box.visible = False
        tag_extra = " [只画连线]"
    elif mode == "noline":
        cfg.line.visible = False
        cfg.box.only_connected = False
        tag_extra = " [只画框]"

    if mode == "eraseoff":     # 正常绘制但不抹除：纯自反馈泄漏量
        from aura.capture import CaptureWorker
        CaptureWorker._erase_self_drawing = lambda self, g, m, c: g
        tag_extra = " [绘制但不抹除]"
    if mode == "erasedry":     # 不绘制但仍按“要画的框”抹除：抹除动作本身的破坏量
        Overlay._draw_boxes = lambda self, p, d, ox, oy: None
        Overlay._draw_lines = lambda self, p, t, ox, oy: None
        tag_extra = " [只抹除不绘制]"
    if mode == "noboxfn":      # 只画框（连线不画），衡量“框”的抹除质量
        ov_draw_lines = Overlay._draw_lines
        Overlay._draw_lines = lambda self, p, t, ox, oy: None
        tag_extra = " [只画框]"
    if mode == "nolinefn":     # 只画连线（框不画），衡量“连线”的抹除质量
        Overlay._draw_boxes = lambda self, p, d, ox, oy: None
        tag_extra = " [只画连线]"

    tracker = BlobTracker()
    ov = Overlay(cfg, tracker, disp)
    ov.show()

    worker = CaptureWorker(cfg, disp)
    worker.drawn_provider = lambda: (ov.drawn_capture, ov.drawn_cursor_capture, ov.drawn_indices)
    frames: list = []
    fills: list = []
    cover: list = []
    costs: list = []
    worker.blobs.connect(lambda p: (frames.append(list(p.get("boxes") or [])),
                                    fills.append(list(p.get("fills") or []))))
    worker.stats.connect(lambda s: costs.append(float(s.get("ms", 0.0))))
    worker.start()
    ov.start()

    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if frames:
            ov.set_payload({"boxes": frames[-1], "fills": fills[-1] if fills else [], "roi": None})
            cover.append((ov._drawn_count, ov._fill_count))
        time.sleep(0.005)

    worker.stop()
    worker.wait(3000)
    ov.stop_timer()
    ov.hide()
    ov.close()

    sets = [[tuple(round(v, 1) for v in b) for b in f] for f in frames]
    new_l, lost_l, cnt_l = [], [], []
    for i in range(1, len(sets)):
        prev, cur = sets[i - 1], sets[i]
        new_l.append(sum(1 for b in cur if not any(iou(b, p) > 0.5 for p in prev)))
        lost_l.append(sum(1 for p in prev if not any(iou(b, p) > 0.5 for b in cur)))
        cnt_l.append(len(cur))

    tag = ("正常模式(排除捕获)" if exclude else "录屏模式(允许捕获)") + tag_extra
    if new_l:
        n = len(new_l)
        stable = sum(1 for i in range(n) if new_l[i] == 0 and lost_l[i] == 0)
        print(f"\n{tag} {len(sets)} 帧:")
        print(f"  平均每帧新增 {sum(new_l)/n:.2f} / 消失 {sum(lost_l)/n:.2f} 个框")
        print(f"  完全稳定帧 {stable}/{n}")
        print(f"  框数量 min={min(cnt_l)} max={max(cnt_l)} avg={sum(cnt_l)/n:.1f}")
        print(f"  逐帧新增: {new_l}")
        if costs:
            print(f"  单帧耗时 avg={sum(costs)/len(costs):.1f}ms max={max(costs):.1f}ms")
        if cover:
            full = sum(1 for d, fc in cover if d and fc >= d)
            miss = sum(d - fc for d, fc in cover)
            print(f"  填充覆盖: {full}/{len(cover)} 帧全填充, 累计缺填 {miss} 个框次"
                  f" (绘制数 {cover[-1][0]}, 填充数 {cover[-1][1]})")
    else:
        print("没有采集到足够的帧")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
