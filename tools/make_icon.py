"""生成应用图标（assets/aura.png + assets/aura.ico）。

仅使用 PySide6（QImage 生成 PNG，再手工封装 ICO 头，Vista+ 支持 PNG 内嵌），
不依赖 Pillow。打包脚本 build.bat 会在 PyInstaller 之前自动调用本脚本。
"""

from __future__ import annotations

import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ASSETS = os.path.join(ROOT, "assets")


def build_png(size: int) -> bytes:
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, qRgba

    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(qRgba(0, 0, 0, 0))
    p = QPainter(img)
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

    buf = QBuffer_wrap()
    img.save(buf, "PNG")
    return bytes(buf.data().data())


def QBuffer_wrap():
    from PySide6.QtCore import QBuffer, QIODevice

    class _Buf(QBuffer):
        def __init__(self):
            super().__init__()
            self.open(QIODevice.OpenModeFlag.WriteOnly)

        def data(self):
            return self.buffer()

    return _Buf()


def png_to_ico(png_bytes: bytes, width: int, height: int) -> bytes:
    """把 PNG 封装为单图像 ICO（Windows Vista+ 支持 PNG 压缩目录项）。"""
    header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=icon, count=1
    entry = struct.pack(
        "<BBBBHHII",
        width % 256, height % 256,     # 尺寸（0 表示 256）
        0, 0,                          # 调色板数 / 保留
        1, 32,                         # 平面数 / 位深
        len(png_bytes),                # 数据大小
        6 + 16,                        # 数据偏移 = 头 6 + 目录项 16
    )
    return header + entry + png_bytes


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)

    # PNG（256px，用于文档/托盘等场景）
    png = build_png(256)
    with open(os.path.join(ASSETS, "aura.png"), "wb") as fp:
        fp.write(png)

    # ICO：包含多尺寸
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        images.append((size, build_png(size)))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blob = b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            size % 256, size % 256, 0, 0, 1, 32, len(data), offset,
        )
        blob += data
        offset += len(data)
    with open(os.path.join(ASSETS, "aura.ico"), "wb") as fp:
        fp.write(header + entries + blob)

    print("OK  assets/aura.png + assets/aura.ico 已生成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
