# -*- mode: python ; coding: utf-8 -*-
# DesktopBlobtrack PyInstaller 打包配置
#
#   单文件 exe： set DBT_ONEFILE=1 && pyinstaller build.spec   -> dist/DesktopBlobtrack.exe
#   目录版：     set DBT_ONEFILE=0 && pyinstaller build.spec   -> dist/DesktopBlobtrack/
#
# 目录版启动更快（无需解压临时目录），单文件版更易分发。

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(SPECPATH)
ONEFILE = os.environ.get("DBT_ONEFILE", os.environ.get("AURA_ONEFILE", "1")) == "1"

ICON = os.path.join(ROOT, "assets", "aura.ico")
if not os.path.exists(ICON):
    ICON = None  # 图标缺失时使用默认图标

hiddenimports = ["cv2", "numpy", "mss"]
try:
    hiddenimports += collect_submodules("mss")
except Exception:
    pass

# 排除用不到的重型 Qt 模块，显著减小体积（如遇 ImportError 可从此列表移除对应项）
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtVirtualKeyboard", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtUiTools", "PySide6.QtConcurrent", "PySide6.QtPdfWidgets",
    "matplotlib", "scipy", "pandas", "PIL", "tkinter",
]

a = Analysis(
    ["aura/main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[("README.md", "."), ("assets/douyin.jpg", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="DesktopBlobtrack",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,          # 无控制台窗口
        disable_windowed_traceback=False,
        icon=ICON,
        version=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DesktopBlobtrack",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="DesktopBlobtrack",
    )
