@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

pyinstaller --onefile --windowed --add-data "DeviceId.exe;." --add-data "*.exe;." main.py

REM ===== 配置参数 =====
set config_file=config.py
set source_dir=dist
set base_name=设备监控系统
set tools_dir=tools

echo %base_name%

REM ===== 读取 VERSION 配置 =====
for /f "delims=" %%i in ('python -c "from config import VERSION;print(VERSION)"') do set "version=V%%i"
echo %version%
if not defined version (
    echo [错误] 无法读取 config.py 中的 VERSION 配置
    pause
    exit /b 1
)
echo "Version :%version%"
REM ===== 创建目标文件夹 =====
set "dest_dir=output\%base_name%_%version%"
if exist "%dest_dir%" (
    echo [警告] 文件夹 "%dest_dir%" 已存在，将覆盖内容
    rmdir /s /q "%dest_dir%"
)
md "%dest_dir%" 2>&1 || (
    echo [错误] 无法创建文件夹 "%dest_dir%"
    pause
    exit /b 2
)

REM ===== 复制并重命名 main.exe =====
if exist "%source_dir%\main.exe" (
    copy "%source_dir%\main.exe" "%dest_dir%\设备监控系统_%version%.exe" >nul
    echo [完成] 复制并重命名 main.exe 到 "设备监控系统_%version%.exe"
) else (
    echo [错误] 文件 "%source_dir%\main.exe" 不存在
    pause
    exit /b 3
)

REM ===== 复制 tools 文件夹 =====
if exist "%tools_dir%" (
    xcopy "%tools_dir%" "%dest_dir%\%tools_dir%" /E /H /C /I /Y >nul
    echo [完成] 复制文件夹 .\%tools_dir% 到目标目录 %dest_dir%\%tools_dir%
) else (
    echo [警告] 文件夹 "%tools_dir%" 不存在，跳过复制
)

echo ===== 操作完成 =====
pause