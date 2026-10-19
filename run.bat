@echo off
rem ============================================================
rem  DesktopBlobtrack 开发模式启动脚本
rem  首次运行自动创建虚拟环境并安装依赖
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.10+ 并加入 PATH。
    pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 首次运行：创建虚拟环境并安装依赖（约 1-3 分钟）...
    python -m venv .venv || (pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -q -U pip
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (pause & exit /b 1)
    echo ok> ".venv\.deps_ok"
)

if not exist ".venv\.deps_ok" (
    echo [2/2] 补装依赖...
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (pause & exit /b 1)
    echo ok> ".venv\.deps_ok"
)

echo 启动 DesktopBlobtrack ...（托盘图标常驻，Ctrl+Alt+A 显隐，Ctrl+Alt+S 设置，Ctrl+Alt+Q 退出）
".venv\Scripts\python.exe" -m aura.main %*
endlocal
