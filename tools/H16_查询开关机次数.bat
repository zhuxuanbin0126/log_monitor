@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ============================================
echo H16 设备查询开关机次数脚本
echo ============================================
echo.

cd /d "%~dp0"

set "ADB=..\adb.exe"

echo [步骤 0] 断开已有ADB连接...
"%ADB%" disconnect
timeout /t 1 /nobreak >nul

echo.
echo [步骤 1] 确认设备在线...
"%ADB%" devices
echo.

set /p CONFIRM="请确认上方设备列表中显示 H16 设备处于 device 状态 (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo 已取消操作。
    pause
    exit /b 1
)

echo.
echo [步骤 2] 查询开关机次数...
echo.

echo --- 开关机次数 (swich_counter.csv) ---
for /f "tokens=1" %%a in ('"%ADB%" shell "cat /data/swich_counter.csv ^| wc -l" 2^>nul') do (
    set /a SWITCH_COUNT=%%a - 1
    if !SWITCH_COUNT! lss 0 set SWITCH_COUNT=0
)
echo 开关机次数: !SWITCH_COUNT! 次

echo.
echo --- 网络开关机次数 (network_counter.csv) ---
for /f "tokens=1" %%a in ('"%ADB%" shell "cat /data/network_counter.csv ^| wc -l" 2^>nul') do (
    set /a NETWORK_COUNT=%%a - 1
    if !NETWORK_COUNT! lss 0 set NETWORK_COUNT=0
)
echo 网络开关机次数: !NETWORK_COUNT! 次

echo.
echo ============================================
echo 查询完成！
echo ============================================
pause
