"""系统托盘图标与菜单：显隐、设置、保存/加载配置、退出。"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap, Qt
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from aura import __version__


def make_app_icon(size: int = 64) -> QIcon:
    """程序化绘制托盘图标（无需外部图片资源）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#3DE1FF"))
    grad.setColorAt(1.0, QColor("#FF6BD6"))
    p.setBrush(grad)
    p.setPen(QPen(QColor(61, 225, 255, 210), max(1.0, size * 0.04)))
    p.drawEllipse(size * 0.18, size * 0.18, size * 0.64, size * 0.64)
    p.setPen(QPen(QColor(255, 107, 214, 200), max(1.0, size * 0.03)))
    p.drawEllipse(size * 0.30, size * 0.30, size * 0.40, size * 0.40)
    p.setPen(QPen(QColor(255, 255, 255, 235), max(1.0, size * 0.05)))
    p.drawPoint(size * 0.5, size * 0.5)
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    toggle_requested = Signal()
    settings_requested = Signal()
    save_requested = Signal()
    reload_requested = Signal()
    restart_capture_requested = Signal()
    about_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: Optional[QObject] = None, callbacks: Optional[Dict[str, Callable]] = None):
        super().__init__(parent)
        self.callbacks = callbacks or {}

        self.icon = QSystemTrayIcon(make_app_icon(), self)
        self.icon.setToolTip("DesktopBlobtrack · 桌面美学引擎")

        menu = QMenu()
        self._act_toggle = QAction("隐藏覆盖层", menu)
        self._act_toggle.triggered.connect(self.toggle_requested.emit)
        menu.addAction(self._act_toggle)

        act_settings = QAction("可视化设置…", menu)
        act_settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(act_settings)

        menu.addSeparator()
        act_save = QAction("保存当前配置", menu)
        act_save.triggered.connect(self.save_requested.emit)
        menu.addAction(act_save)
        act_reload = QAction("重新加载配置文件", menu)
        act_reload.triggered.connect(self.reload_requested.emit)
        menu.addAction(act_reload)
        act_restart = QAction("重新开始屏幕捕获", menu)
        act_restart.triggered.connect(self.restart_capture_requested.emit)
        menu.addAction(act_restart)

        menu.addSeparator()
        act_about = QAction(f"关于 DesktopBlobtrack v{__version__}", menu)
        act_about.triggered.connect(self.about_requested.emit)
        menu.addAction(act_about)
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def _on_activated(self, reason) -> None:
        reason = QSystemTrayIcon.ActivationReason(reason)
        if reason == QSystemTrayIcon.ActivationReason.Trigger:      # 单击：显隐
            self.toggle_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:  # 双击：设置
            self.settings_requested.emit()

    def set_overlay_visible(self, visible: bool) -> None:
        self._act_toggle.setText("显示覆盖层" if not visible else "隐藏覆盖层")
        self.icon.setToolTip(
            "DesktopBlobtrack · 桌面美学引擎（运行中）" if visible else "DesktopBlobtrack · 已隐藏（Ctrl+Alt+A 显示）"
        )

    def show_message(self, title: str, text: str) -> None:
        self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 3000)

    def shutdown(self) -> None:
        self.icon.hide()
        self.menu.deleteLater()
