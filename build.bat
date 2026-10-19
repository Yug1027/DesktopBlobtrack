@echo off
rem ============================================================
rem  DesktopBlobtrack 一键打包脚本
rem  用法：
rem    build.bat          -> 打包为单文件 dist\DesktopBlobtrack.exe
rem    build.bat file     -> 同上（单文件）
rem    build.bat dir      -> 打包为目录 dist\DesktopBlobtrack\（启动更快）
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=file
if /i "%MODE%"=="file" set DBT_ONEFILE=1
if /i "%MODE%"=="dir"  set DBT_ONEFILE=0

rem ---- 1. 虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/5] 创建虚拟环境...
    python -m venv .venv || goto :fail
) else (
    echo [1/5] 虚拟环境已存在
)

rem ---- 2. 依赖 ----
echo [2/5] 安装依赖...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :fail

rem ---- 3. PyInstaller ----
echo [3/5] 安装 PyInstaller...
".venv\Scripts\python.exe" -m pip install -q "pyinstaller>=6.6" || goto :fail

rem ---- 4. 生成图标 + 冒烟测试 ----
echo [4/5] 生成图标并运行冒烟测试...
".venv\Scripts\python.exe" tools\make_icon.py || goto :fail
".venv\Scripts\python.exe" tools\smoke_test.py || goto :fail

rem ---- 5. 打包 ----
echo [5/5] PyInstaller 打包（%MODE% 模式）...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean build.spec || goto :fail

echo.
echo ============================================================
if /i "%MODE%"=="dir" (
    echo 打包完成: dist\DesktopBlobtrack\DesktopBlobtrack.exe
) else (
    echo 打包完成: dist\DesktopBlobtrack.exe
)
echo ============================================================
endlocal
exit /b 0

:fail
echo.
echo [失败] 打包中断，请检查上方错误信息。
endlocal
exit /b 1
