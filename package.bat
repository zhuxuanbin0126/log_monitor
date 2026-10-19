@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 统一发布入口：版本校验 -> PyInstaller -> release 资源 -> SHA256 -> zip
python tools\build_release.py %*

if errorlevel 1 (
    echo.
    echo [error] 发布构建失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo [done] 发布目录: %~dp0release
pause
