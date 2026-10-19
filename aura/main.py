"""DesktopBlobtrack 程序入口：装配覆盖层、捕获线程、设置面板、托盘与快捷键。

用法：
    python -m aura.main [--settings] [--reset] [--no-tray]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback

# 允许 `python aura/main.py` 直接运行
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from aura import __version__, win32_utils
from aura.capture import CaptureWorker
from aura.config import Config, config_path, log_path
from aura.display import DisplayInfo
from aura.hotkey import HotkeyManager
from aura.overlay import Overlay
from aura.settings_panel import SettingsPanel
from aura.tracker import BlobTracker
from aura.tray import TrayController, make_app_icon

logger = logging.getLogger("aura")

SINGLE_INSTANCE_KEY = "DesktopBlobtrack.SingleInstance.v1"


def setup_logging() -> None:
    handler = logging.FileHandler(log_path(), encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    def _hook(exc_type, exc, tb):
        logger.error("未捕获异常:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _hook


def single_instance_guard(app: QApplication) -> bool:
    """返回 True 表示这是唯一实例（守卫成功）。"""
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(200):
        sock.disconnectFromServer()
        return False
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)
    app.setProperty("aura_local_server", server)  # 防止被 GC
    return True


class AuraApp:
    def __init__(self, args):
        self.args = args
        self.cfg = Config.load()
        if args.reset:
            self.cfg = Config()
            self.cfg.save()

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("DesktopBlobtrack")
        self.app.setApplicationVersion(__version__)
        self.app.setWindowIcon(make_app_icon())

        # 探测显示器（mss 坐标系 + Qt 逻辑坐标系）
        from aura.capture import probe_capture_rect
        self.disp = DisplayInfo.probe(probe_capture_rect())

        self.tracker = BlobTracker(smoothing=float(self.cfg.general.smooth))
        self._worker_wanted = False
        self.overlay = Overlay(self.cfg, self.tracker, self.disp)
        self.worker = CaptureWorker(self.cfg, self.disp)
        # 录屏模式：捕获线程通过它拿到“此刻屏幕上真实画着的框”，精确抹除自绘内容
        self.worker.drawn_provider = lambda: (self.overlay.drawn_capture,
                                              self.overlay.drawn_cursor_capture,
                                              self.overlay.drawn_indices)
        self.worker.blobs.connect(self.on_payload)
        self.worker.stats.connect(self.overlay.set_stats)
        self.worker.failed.connect(self.on_capture_failed)

        self.panel = SettingsPanel(self.cfg, on_change=self.on_config_changed)

        self.tray = TrayController()
        self.tray.toggle_requested.connect(self.toggle_overlay)
        self.tray.settings_requested.connect(self.show_settings)
        self.tray.save_requested.connect(self.save_config)
        self.tray.reload_requested.connect(self.reload_config)
        self.tray.restart_capture_requested.connect(self.restart_capture)
        self.tray.about_requested.connect(self.show_about)
        self.tray.quit_requested.connect(self.quit)

        self.hotkeys = HotkeyManager({
            "toggle": self.cfg.general.hotkey_toggle,
            "panel": self.cfg.general.hotkey_panel,
            "quit": self.cfg.general.hotkey_quit,
        })
        self.hotkeys.activated.connect(self.on_hotkey)
        self.hotkeys.start()

        # 参数自动保存（防抖 2s）
        self._save_timer = QTimer(self.app)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self.save_config)

        # 显示器热插拔/分辨率变化自动适配
        self._disp_timer = QTimer(self.app)
        self._disp_timer.setInterval(3000)
        self._disp_timer.timeout.connect(self._check_display)
        self._disp_timer.start()

        if self.cfg.general.overlay_visible and not args.hidden:
            self.show_overlay()
        else:
            # 观赏工具重启后默认显示；--hidden 显式隐藏（旧配置残留的 False 不再生效）
            if not args.hidden:
                self.show_overlay()
            else:
                self.tray.set_overlay_visible(False)

        if args.settings:
            self.show_settings()

    # ---------- 捕获线程（异步，绝不阻塞 UI） ----------
    def start_worker(self, retry: bool = False) -> None:
        """启动捕获线程。若线程还在结束中，稍后重试而不是卡住等待。"""
        if not retry:
            self._worker_wanted = True
        if not self._worker_wanted:
            return  # 等待期间用户已隐藏覆盖层，取消启动
        if self.worker.isRunning():
            QTimer.singleShot(120, lambda: self.start_worker(True))
            return
        if self.overlay.isVisible():
            try:
                self.worker.start()
            except Exception as exc:
                logger.warning("启动捕获线程失败: %s", exc)

    def stop_worker(self) -> None:
        """请求停止捕获线程，立即返回（不阻塞 UI 线程）。"""
        self._worker_wanted = False
        try:
            self.worker.stop(0)
        except Exception as exc:
            logger.debug("停止捕获线程失败: %s", exc)

    # ---------- 可见性 ----------
    def show_overlay(self) -> None:
        self.overlay.show()
        self.overlay.start()
        self.overlay.apply_click_through()
        self.start_worker()
        self.tray.set_overlay_visible(True)

    def hide_overlay(self) -> None:
        self.overlay.hide()
        self.overlay.stop_timer()
        self.tracker.reset()
        self.stop_worker()
        self.tray.set_overlay_visible(False)

    def toggle_overlay(self) -> None:
        if self.overlay.isVisible():
            self.hide_overlay()
        else:
            self.show_overlay()

    def show_settings(self) -> None:
        # 面板可能首次 show，避免任何阻塞操作；延迟到事件循环空闲再刷新 UI 状态
        self.panel.show()
        QTimer.singleShot(0, self._finish_show_settings)

    def show_about(self) -> None:
        self.panel.show_page("about")
        self.show_settings()

    def _finish_show_settings(self) -> None:
        self.panel.refresh()
        self.panel.raise_()
        self.panel.activateWindow()

    # ---------- 信号处理 ----------
    def on_payload(self, payload: dict) -> None:
        self.overlay.set_payload(payload)

    def on_capture_failed(self, message: str) -> None:
        logger.error("%s", message)
        self.tray.show_message("DesktopBlobtrack 捕获异常", message)
        if "自动暂停" in message or "异常退出" in message:
            self.hide_overlay()

    def on_hotkey(self, name: str) -> None:
        if name == "toggle":
            self.toggle_overlay()
        elif name == "panel":
            self.show_settings()
        elif name == "quit":
            self.quit()

    def on_config_changed(self) -> None:
        g = self.cfg.general
        self.tracker.smoothing = float(g.smooth)
        self.hotkeys.set_combos({
            "toggle": g.hotkey_toggle,
            "panel": g.hotkey_panel,
            "quit": g.hotkey_quit,
        })
        self.overlay.apply_click_through()
        self._save_timer.start()

    def save_config(self) -> None:
        try:
            self.cfg.general.overlay_visible = True  # 重启后默认显示（--hidden / 托盘隐藏仅当次有效）
            self.cfg.save()
            logger.info("配置已保存到 %s", config_path())
        except Exception as exc:
            logger.error("保存配置失败: %s", exc)

    def reload_config(self) -> None:
        fresh = Config.load()
        for section in ("capture", "detect", "roi", "box", "fill", "line", "general"):
            setattr(self.cfg, section, getattr(fresh, section))
        self.panel.refresh()
        self.on_config_changed()
        self.tray.show_message("DesktopBlobtrack", "已重新加载配置文件")

    def restart_capture(self) -> None:
        self.stop_worker()
        self.tracker.reset()
        self.start_worker()
        self.tray.show_message("DesktopBlobtrack", "屏幕捕获已重新开始")

    def _check_display(self) -> None:
        try:
            fresh = DisplayInfo.probe(probe_capture_rect())
            if fresh.key() != self.disp.key():
                logger.info("显示器布局变化，重新适配: %s", fresh.key())
                self.disp = fresh
                self.overlay.set_display(fresh)
                self.worker.set_display(fresh)
                self.tracker.reset()
        except Exception as exc:
            logger.debug("显示器检测失败: %s", exc)

    # ---------- 退出 ----------
    def quit(self) -> None:
        logger.info("退出程序")
        self.save_config()
        self.stop_worker()
        try:
            if self.worker.isRunning():
                self.worker.wait(1200)  # 退出时允许短暂等待，确保磁盘/资源释放干净
        except Exception:
            pass
        self.hotkeys.stop()
        self.tray.shutdown()
        self.overlay.hide()
        self.panel.hide()
        self.app.quit()

    def run(self) -> int:
        return self.app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description="DesktopBlobtrack —— Windows 桌面美学观赏工具")
    parser.add_argument("--settings", action="store_true", help="启动时打开设置面板")
    parser.add_argument("--reset", action="store_true", help="恢复默认配置后启动")
    parser.add_argument("--hidden", action="store_true", help="启动时隐藏覆盖层（仅托盘）")
    args = parser.parse_args()

    win32_utils.set_dpi_awareness(2)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    setup_logging()
    logger.info("DesktopBlobtrack v%s 启动，配置文件: %s", __version__, config_path())

    app = QApplication.instance() or QApplication(sys.argv)
    if not single_instance_guard(app):
        QMessageBox.information(
            None, "DesktopBlobtrack",
            "DesktopBlobtrack 已在运行中（请查看系统托盘）。\n如需多开请先退出现有实例。",
        )
        return 0

    try:
        aura = AuraApp(args)
    except Exception as exc:
        logger.exception("初始化失败")
        QMessageBox.critical(None, "DesktopBlobtrack 启动失败", f"{exc}\n\n日志: {log_path()}")
        return 1

    try:
        return aura.run()
    finally:
        aura.stop_worker()


if __name__ == "__main__":
    sys.exit(main())
