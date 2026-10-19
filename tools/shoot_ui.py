"""截取设置中心各页面，用于视觉检查 / README 展示。

注意：**不要用 QT_QPA_PLATFORM=offscreen** —— 该平台没有系统字体，
中文会全部渲染成方框。这里默认走真实平台，窗口带 -window 参数时才显示。

用法：.venv/Scripts/python.exe tools/shoot_ui.py [输出目录] [--window]
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from aura.config import Config
    from aura.settings_panel import SettingsPanel

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets")
    os.makedirs(out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = Config()
    panel = SettingsPanel(cfg)
    panel.resize(980, 760)
    # 不主动 show()：无边框窗口弹出来会干扰操作，grab() 对未显示窗口同样能取到完整画面
    panel.ensurePolished()
    panel.show()
    panel.hide()
    for _ in range(6):
        app.processEvents()

    for i, (key, label) in enumerate(panel.NAV):
        panel.show_page(key)
        for _ in range(4):
            app.processEvents()
        img = panel.grab().toImage()
        path = os.path.join(out, f"ui_{i}_{key}_{label}.png")
        img.save(path)
        print(f"saved {path} ({img.width()}x{img.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
