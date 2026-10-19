"""冒烟测试：不弹窗、不常驻，验证核心链路可运行。

覆盖：模块导入、配置读写往返、合成图像斑点检测、坐标换算、
离屏渲染覆盖层（描边框 + 连线 + 光环）、设置面板构建。

用法：python tools/smoke_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = []
FAIL = []


def check(name, fn):
    try:
        result = fn()
        PASS.append(name)
        print(f"[PASS] {name}" + (f"  -> {result}" if result is not None else ""))
        return True
    except Exception as exc:
        FAIL.append((name, exc))
        import traceback
        traceback.print_exc()
        print(f"[FAIL] {name}: {exc}")
        return False


def t_imports():
    from aura import capture, config, detector, display, hotkey, main, overlay  # noqa: F401
    from aura import settings_panel, tracker, tray, win32_utils  # noqa: F401
    return "11 modules"


def t_config_roundtrip():
    from aura.config import Config

    cfg = Config()
    cfg.detect.min_area = 678
    cfg.line.count = 9
    cfg.general.hotkey_toggle = "ctrl+shift+d"
    path = os.path.join(tempfile.mkdtemp(), "cfg.json")
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded.detect.min_area == 678
    assert loaded.line.count == 9
    assert loaded.general.hotkey_toggle == "ctrl+shift+d"
    # 容错：未知键 / 坏值
    import json
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"detect": {"min_area": "abc", "mode": "xxx", "downscale": 5.0},
                   "unknown_section": {}}, fp)
    fresh = Config.load(path)
    assert fresh.detect.min_area == Config().detect.min_area  # 坏值回落默认
    assert fresh.detect.mode == "contour"
    assert fresh.detect.downscale == 1.0  # clamp
    return "save/load/clamp ok"


def t_hotkey_parse():
    from aura import win32_utils
    assert win32_utils.parse_hotkey("ctrl+alt+a") == [0x11, 0x12, 0x41]
    assert win32_utils.parse_hotkey("Ctrl+Shift+F5") == [0x11, 0x10, 0x74]
    try:
        win32_utils.parse_hotkey("ctrl+what")
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        pass
    return "parse ok"


def t_detector():
    import numpy as np
    from aura.config import Config
    from aura.detector import detect_blobs, nms, iou

    # 合成“桌面”：几个亮色按钮块 + 图标 + 大窗口区域
    img = np.full((600, 900), 40, dtype=np.uint8)
    import cv2
    cv2.rectangle(img, (60, 60), (200, 140), 220, -1)      # 按钮
    cv2.rectangle(img, (300, 80), (360, 140), 235, -1)     # 图标
    cv2.rectangle(img, (500, 300), (850, 520), 90, -1)     # 窗口
    cv2.rectangle(img, (520, 320), (580, 360), 210, -1)    # 窗口内按钮
    cv2.circle(img, (420, 200), 30, 230, -1)               # 圆形图标

    cfg = Config()
    cfg.detect.min_area = 200
    cfg.detect.max_area = 500000
    boxes = detect_blobs(img, cfg.detect, px_per_logical=0.5)
    assert 2 <= len(boxes) <= 20, f"检出数量异常: {len(boxes)}"
    # simpleblob 模式
    cfg.detect.mode = "simpleblob"
    cfg.detect.blob_bright = True
    boxes2 = detect_blobs(img, cfg.detect, px_per_logical=0.5)
    assert len(boxes2) >= 1, "simpleblob 未检出任何斑点"
    # nms / iou：交 25 / 并 175 ≈ 0.143
    a, b = (0, 0, 10, 10), (5, 5, 10, 10)
    assert 0.13 < iou(a, b) < 0.16
    assert len(nms([a, b], 0.1, 10)) == 1
    return f"contour={len(boxes)} simpleblob={len(boxes2)}"


def t_fill_effects():
    import numpy as np
    from aura.capture import apply_effect_bgr, to_qimage_bgra
    from aura.config import Config

    cfg = Config()
    rng = np.random.default_rng(7)
    bgr = rng.integers(0, 255, (60, 80, 3), dtype=np.uint8)
    for mode in ("invert", "grayscale", "sepia", "hsl", "edge", "pixelate"):
        out = apply_effect_bgr(bgr, mode, cfg.fill)
        assert out.shape == bgr.shape and out.dtype == np.uint8, mode
        assert not np.array_equal(out, bgr), f"{mode} 无效果"
    bgra = np.dstack([bgr, np.full((60, 80), 255, dtype=np.uint8)])
    img = to_qimage_bgra(bgra)
    assert img.width() == 80 and img.height() == 60 and not img.isNull()
    # rainbow 逐框 HSL
    from aura.capture import apply_hsl
    shifted = apply_hsl(bgr, 25.0, 1.0, 1.0)
    assert shifted.shape == bgr.shape
    return "7 effect modes ok"


def t_roi_logic():
    from aura.config import Config
    from aura.display import DisplayInfo
    from aura.capture import CaptureWorker

    cfg = Config()
    assert cfg.roi.enabled is False  # 默认全屏检测，靠“只画连线的框”控制画面
    disp = DisplayInfo.probe(None)
    w = CaptureWorker(cfg, disp)
    base = {"left": disp.capture_rect[0], "top": disp.capture_rect[1],
            "width": disp.capture_rect[2], "height": disp.capture_rect[3]}
    cfg.roi.enabled = True
    x, y, rw, rh = w._target_roi(base, cfg)
    assert 0 < rw <= disp.capture_rect[2] and 0 < rh <= disp.capture_rect[3]
    assert base["left"] <= x <= base["left"] + base["width"] - rw
    # 蒙版位置必须吸附到 snap 网格，否则光标微动会让画面整体平移 → 框全变
    snap = cfg.roi.snap
    assert (x - base["left"]) % snap == 0, f"未吸附到网格: {x}"
    return f"roi {rw}x{rh} at ({x},{y}) snap={snap}"


def t_tracker():
    from aura.tracker import BlobTracker

    # 默认行为：框严格等于检测结果，不做缓动
    tr = BlobTracker()
    out1 = tr.update([(10, 10, 50, 50)])
    assert len(out1) == 1 and tuple(out1[0][0]) == (10, 10, 50, 50)
    out2 = tr.update([(14, 10, 50, 50)])
    assert tuple(out2[0][0]) == (14, 10, 50, 50), "smoothing=0 时应立即到位"
    assert len(tr.update([])) == 0, "元素消失后不应残留（否则会出现两层框）"

    # 可选的老行为：指数平滑
    tr2 = BlobTracker(smoothing=0.8)
    tr2.update([(10, 10, 50, 50)])
    x2 = tr2.update([(11, 10, 50, 50)])[0][0][0]
    assert abs(x2 - 10) < 1.0 and abs(x2 - 11) > 0.0

    # 可选的出现确认：连续 N 帧才画，滤掉一闪而过的噪声
    tr3 = BlobTracker(confirm_frames=2)
    assert len(tr3.update([(0, 0, 20, 20)])) == 0, "首帧不应立即出现"
    assert len(tr3.update([(0, 0, 20, 20)])) == 1, "第二帧应确认出现"
    assert len(tr3.update([])) == 0
    return "strict / smoothing / confirm ok"


def t_stability():
    """反闪烁：同样的元素在 1px 抖动下，输出必须完全一致。"""
    from aura.detector import iou, nms, snap_boxes

    a = (100.0, 100.0, 60.0, 40.0)
    b = (101.0, 100.0, 59.0, 41.0)   # 同一元素的两帧：亚像素抖动
    sa, sb = snap_boxes([a], 2.0)[0], snap_boxes([b], 2.0)[0]
    assert sa == sb, f"snap 后应完全一致: {sa} vs {sb}"

    # NMS 排序稳定：面积微变不得翻转保留哪一组
    base = [(10, 10, 40, 40), (60, 60, 30, 30), (12, 12, 38, 38)]
    jitter = [(x + 1, y + 1, w - 1, h + 1) for (x, y, w, h) in base]
    k1 = nms(base, 0.45, 10, 2.0)
    k2 = nms(jitter, 0.45, 10, 2.0)
    assert len(k1) == len(k2), f"NMS 结果数量发生跳变: {len(k1)} -> {len(k2)}"
    return f"snap 稳定, nms keep={len(k1)}"


def t_display():
    from aura.display import DisplayInfo

    d = DisplayInfo.probe(None)
    assert d.size[0] > 0 and d.size[1] > 0
    x, y = d.to_logical_from_capture(0, 0)
    assert abs(x - d.origin[0]) < 0.001
    cx, cy = d.cursor_logical()
    assert -100000 < cx < 100000
    return f"virtual {d.size} capture_scale={d.capture_scale:.2f}"


def t_gui_offscreen():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from aura.config import Config
    from aura.display import DisplayInfo
    from aura.overlay import Overlay
    from aura.settings_panel import SettingsPanel
    from aura.tracker import BlobTracker
    from aura.tray import make_app_icon

    cfg = Config()
    cfg.general.smooth = 0.0
    cfg.detect.confirm_frames = 1   # 离屏单帧测试：不等第二帧确认
    disp = DisplayInfo.probe(None)
    tracker = BlobTracker(0.0)
    ov = Overlay(cfg, tracker, disp)
    ov.resize(800, 600)
    boxes = [(50, 50, 120, 60), (300, 200, 200, 150), (600, 100, 80, 80)]
    # 构造带填充贴图的 payload（模拟捕获线程输出）
    import numpy as np
    from aura.capture import to_qimage_bgra
    fills = []
    for i, b in enumerate(boxes):
        patch = np.zeros((int(b[3]), int(b[2]), 4), dtype=np.uint8)
        patch[..., 0] = 120
        patch[..., 3] = 255
        fills.append((i, to_qimage_bgra(patch)))   # (源索引, 贴图)
    ov.set_payload({"boxes": boxes, "fills": fills, "roi": (100, 80, 700, 460)})
    cfg.fill.mode = "invert"     # 走 drawImage 分支
    cfg.roi.show_region = True   # 走蒙版边界绘制分支
    ov._cursor = (400.0, 300.0)
    ov._tick()
    pm = ov.grab()  # 触发一次完整 paintEvent
    assert not pm.isNull()

    # 只画被连线连接到的框：3 个元素 + 连线数 1 → 只应画出 1 个框
    cfg.line.count = 1
    cfg.line.max_distance = 8000
    ov.set_payload({"boxes": boxes, "fills": fills, "roi": (100, 80, 700, 460)})
    cfg.box.only_connected = True
    ov.grab()
    assert ov._drawn_count == 1, f"only_connected 未生效: drawn={ov._drawn_count}"
    # 关键：填充必须严格等于被画出来的框，绝不填到没连到的框里
    assert ov._fill_count == 1, f"填充范围越界: fills={ov._fill_count} drawn={ov._drawn_count}"
    cfg.box.only_connected = False
    ov.grab()
    assert ov._drawn_count == 3, f"关闭 only_connected 后应画全部框: {ov._drawn_count}"
    assert ov._fill_count == 3, f"关闭 only_connected 后应填充全部框: {ov._fill_count}"
    # 关闭填充后不应再有任何填充绘制
    cfg.fill.mode = "none"
    ov.grab()
    assert ov._fill_count == 0, f"mode=none 时仍有填充: {ov._fill_count}"
    cfg.fill.mode = "invert"
    cfg.box.only_connected = True

    panel = SettingsPanel(cfg, on_change=lambda: None)
    panel.show()
    app.processEvents()

    icon = make_app_icon()
    assert not icon.isNull()
    return f"overlay rendered {pm.width()}x{pm.height()}"


def t_focus_sampling():
    """集中程度：focus 越高，随机挑选的元素应越靠近光标。"""
    from aura.overlay import _seeded_weighted_sample
    from aura.detector import _enforce_min_dist

    # 10 个候选，d2 从 10^2 到 1000^2
    items = [(i, float((i + 1) * 100) ** 2, (i + 1) * 100.0, 0.0) for i in range(10)]

    def avg_dist(focus):
        total, n = 0.0, 0
        for seed in range(1, 60):
            picked = _seeded_weighted_sample(items, 4, seed, focus, 1100.0)
            assert len(picked) == 4 and len({p[0] for p in picked}) == 4  # 不放回
            total += sum(p[1] ** 0.5 for p in picked)
            n += 4
        return total / n

    spread = avg_dist(0.0)
    focused = avg_dist(1.0)
    assert focused < spread * 0.75, f"集中程度未生效: focus0={spread:.0f} focus1={focused:.0f}"
    # 数量边界
    assert _seeded_weighted_sample(items, 0, 1, 0.5, 1100.0) == []
    assert len(_seeded_weighted_sample(items, 99, 1, 0.5, 1100.0)) == len(items)

    # 最小间距（BlobTrack Delete Nearby）：近处只保留大的
    boxes = [(0.0, 0.0, 10.0, 10.0), (2.0, 2.0, 50.0, 50.0), (200.0, 200.0, 20.0, 20.0)]
    kept = _enforce_min_dist(boxes, 40.0)
    assert len(kept) == 2, f"min_dist 过滤错误: {kept}"
    assert (2.0, 2.0, 50.0, 50.0) in kept, "应保留较大的框"
    assert len(_enforce_min_dist(boxes, 0.0)) == 3, "0 = 不限制"
    return f"focus: {spread:.0f} -> {focused:.0f} px, min_dist ok"


def t_fill_scope():
    """像素级验证：填充只能出现在框内部，框外必须完全透明。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from aura.config import Config
    from aura.display import DisplayInfo
    from aura.overlay import Overlay
    from aura.tracker import BlobTracker

    import numpy as np
    from aura.capture import to_qimage_bgra

    cfg = Config()
    cfg.general.smooth = 0.0
    cfg.detect.confirm_frames = 1
    cfg.box.visible = False          # 不画边框，画面上只剩下填充
    cfg.line.visible = False         # 不画连线
    cfg.roi.show_region = False
    cfg.box.only_connected = False
    cfg.fill.mode = "invert"
    cfg.fill.opacity = 255

    disp = DisplayInfo.probe(None)
    ov = Overlay(cfg, BlobTracker(0.0), disp)
    ov.resize(600, 400)
    boxes = [(40.0, 40.0, 120.0, 80.0), (300.0, 200.0, 160.0, 100.0)]
    fills = []
    for i, b in enumerate(boxes):
        patch = np.full((int(b[3]), int(b[2]), 4), 200, dtype=np.uint8)
        patch[..., 3] = 255
        fills.append((i, to_qimage_bgra(patch)))
    ov.set_payload({"boxes": boxes, "fills": fills, "roi": None})
    ov._cursor = (0.0, 0.0)

    img = ov.grab().toImage()
    ox, oy = disp.origin
    inside = [(
        b[0] - ox, b[1] - oy, b[2], b[3]
    ) for b in boxes]
    leaked = 0
    painted = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if img.pixelColor(x, y).alpha() <= 8:
                continue
            painted += 1
            if not any(rx <= x <= rx + rw and ry <= y <= ry + rh for (rx, ry, rw, rh) in inside):
                leaked += 1
    assert painted > 500, f"填充根本没画出来: painted={painted}"
    assert leaked == 0, f"填充溢出到框外: {leaked}/{painted} 个采样点"
    return f"框内 {painted} 采样点, 框外泄漏 0"


def t_app_name():
    """应用名称统一为 DesktopBlobtrack：代码、配置目录、打包名都不能再有旧名。"""
    from aura import __app_name__
    from aura import config as cfgmod

    assert __app_name__ == "DesktopBlobtrack", __app_name__
    assert cfgmod.APP_NAME == "DesktopBlobtrack", cfgmod.APP_NAME
    assert cfgmod.app_dir().replace("\\", "/").endswith("/DesktopBlobtrack"), cfgmod.app_dir()
    assert cfgmod.presets_path().endswith("presets.json")
    assert cfgmod.ui_state_path().endswith("ui_state.json")

    root = ROOT
    offenders = []
    for rel in ("aura/config.py", "aura/main.py", "aura/tray.py", "aura/overlay.py",
                "build.spec", "README.md", "requirements.txt", "run.bat", "build.bat"):
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", errors="ignore") as fp:
            text = fp.read()
        if "DesktopAura" in text and rel != "aura/config.py":
            offenders.append(rel)
    assert not offenders, f"仍残留旧名称: {offenders}"
    return "DesktopBlobtrack"


def t_preset_share_link():
    """分享链接往返：名称与全部参数必须完整保留（含中文名）。"""
    from aura.settings_panel import SHARE_PREFIX, encode_preset_link, decode_preset_link

    params = {
        "line": {"count": 9, "color": "#FF6BD6", "dash": True, "focus": 0.75},
        "box": {"style": "rounded", "width": 2.5},
        "detect": {"min_area": 640},
    }
    link = encode_preset_link("我的预设 ✨", params)
    assert link.startswith(SHARE_PREFIX), link[:20]
    got = decode_preset_link(link)
    assert got["name"] == "我的预设 ✨", got["name"]
    assert got["params"] == params, got["params"]

    # 裸 JSON（导出文件的内容）也能导入
    import json
    raw = json.dumps({"app": "DesktopBlobtrack", "type": "preset",
                      "name": "导出预设", "params": params}, ensure_ascii=False)
    got2 = decode_preset_link(raw)
    assert got2["name"] == "导出预设"

    for bad in ("", "hello", SHARE_PREFIX + "!!!", "{}"):
        try:
            decode_preset_link(bad)
        except ValueError:
            continue
        raise AssertionError(f"坏数据没有被拒绝: {bad!r}")
    return "往返一致, 坏数据被拒"


def t_preset_crud():
    """自定义预设 增/改/删/持久化。"""
    import tempfile

    from aura.config import Config
    from aura.settings_panel import SettingsPanel

    tmp = tempfile.mkdtemp()
    cfg = Config()
    panel = SettingsPanel(cfg)
    panel._presets_file = os.path.join(tmp, "presets.json")   # 不污染真实预设库
    panel._load_custom = lambda: SettingsPanel._load_custom.__get__(panel)()

    # 直接走持久化层：新增
    params = panel._current_params()
    assert params, "当前参数为空"
    panel._save_custom({"测试预设": params})
    loaded = panel._load_custom()
    assert "测试预设" in loaded, loaded.keys()

    # 改名 / 删除
    data = panel._load_custom()
    data["改后名字"] = data.pop("测试预设")
    panel._save_custom(data)
    assert "改后名字" in panel._load_custom()
    data = panel._load_custom()
    data.pop("改后名字")
    panel._save_custom(data)
    assert panel._load_custom() == {} or "改后名字" not in panel._load_custom()
    return "增/改/删/持久化 ok"


def t_record_erase():
    """录屏模式自绘抹除：把画上去的笔画从检测输入里抹掉且不破坏画面。"""
    import cv2
    import numpy as np

    from aura.capture import CaptureWorker
    from aura.config import Config
    from aura.detector import detect_blobs
    from aura.display import DisplayInfo

    rng = np.random.default_rng(7)
    h, w = 240, 320
    base = rng.integers(0, 255, (h, w), dtype=np.uint8)
    gray = cv2.GaussianBlur(base, (0, 0), 1.2)

    worker = CaptureWorker.__new__(CaptureWorker)
    worker.disp = DisplayInfo(origin=(0, 0), size=(w, h), capture_rect=(0, 0, w, h),
                              physical_rect=(0, 0, w, h), capture_scale=1.0, cursor_scale=1.0)
    worker._clean_prev = None
    worker.drawn_provider = None
    worker._prev_drawn_boxes, worker._prev_drawn_cursor = [], None
    worker._prev2_boxes_cap, worker._prev2_cursor_cap = [], None
    worker._last_drawn_boxes, worker._last_drawn_cursor = [], None
    worker._last_drawn_indices, worker._pending_drawn = [], None
    worker._frame_origin = (0.0, 0.0)

    cfg = Config()
    cfg.general.exclude_from_capture = False
    boxes = [(40.0, 40.0, 60.0, 40.0), (180.0, 140.0, 50.0, 50.0)]
    worker._prev_boxes_cap = [tuple(map(float, b)) for b in boxes]
    worker._prev_cursor_cap = (10.0, 10.0)

    mon = {"left": 0, "top": 0, "width": w, "height": h}
    clean = worker._erase_self_drawing(gray, mon, cfg)
    assert clean.shape == gray.shape and clean.dtype == np.uint8

    # 抹除区域必须被改动；区域外必须逐像素不变
    changed = (clean != gray)
    assert changed.any(), "抹除没有生效"
    ys, xs = np.nonzero(changed)
    assert changed.sum() > 200, f"抹除面积过小: {int(changed.sum())}"
    # 远离自绘内容（框 + 光标→框中心连线）的区域必须逐像素不变
    far = changed[:, 260:]
    assert not far.any(), f"改动溢出到无关区域: {int(far.sum())} 像素, x 最大 {xs.max()}"

    # 连续两帧：稳定后检测输入不再变化（回路收敛）
    worker._prev_boxes_cap = [tuple(map(float, b)) for b in boxes]
    worker._prev_cursor_cap = (10.0, 10.0)
    clean2 = worker._erase_self_drawing(clean, mon, cfg)
    drift = int(np.abs(clean2.astype(int) - clean.astype(int)).mean())
    assert drift <= 1, f"回路未收敛, 平均漂移 {drift}"
    detect_blobs(clean2, cfg.detect, 1.0)
    return f"抹除 {int(changed.sum())} 像素, 二次漂移 {drift}"


def main() -> int:
    print("== DesktopBlobtrack 冒烟测试 ==")
    check("模块导入", t_imports)
    check("配置读写", t_config_roundtrip)
    check("快捷键解析", t_hotkey_parse)
    check("斑点检测", t_detector)
    check("填充效果", t_fill_effects)
    check("蒙版逻辑", t_roi_logic)
    check("时序跟踪", t_tracker)
    check("反闪烁稳定性", t_stability)
    check("显示器探测", t_display)
    check("离屏渲染", t_gui_offscreen)
    check("填充范围", t_fill_scope)
    check("集中程度/最小间距", t_focus_sampling)
    check("应用名称统一", t_app_name)
    check("预设分享链接", t_preset_share_link)
    check("预设增删改", t_preset_crud)
    check("录屏自绘抹除", t_record_erase)

    print(f"\n结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
