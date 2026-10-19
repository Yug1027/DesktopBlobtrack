"""全局快捷键：轮询 GetAsyncKeyState 实现组合键沿检测。

不依赖第三方库，60ms 轮询三个组合键的开销可以忽略。
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QObject, QTimer, Signal

from aura import win32_utils


class HotkeyManager(QObject):
    activated = Signal(str)  # 参数为动作名: toggle / panel / quit

    def __init__(self, combos: Dict[str, str], parent=None):
        super().__init__(parent)
        self.set_combos(combos)
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._poll)

    def set_combos(self, combos: Dict[str, str]) -> None:
        self._vks: Dict[str, list] = {}
        self._down: Dict[str, bool] = {}
        for name, text in (combos or {}).items():
            try:
                vks = win32_utils.parse_hotkey(text)
            except ValueError:
                vks = []
            self._vks[name] = vks
            self._down[name] = False

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        for name, vks in self._vks.items():
            if not vks:
                continue
            all_down = all(win32_utils.is_key_down(v) for v in vks)
            if all_down and not self._down.get(name):
                self.activated.emit(name)
            self._down[name] = all_down
