@echo off
chcp 65001 >nul
echo ============================================
echo H16 设备清空开关机次数脚本
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
echo [步骤 2] 删除开关机记录文件...
echo.

echo --- 删除 /data/swich_counter.csv ---
"%ADB%" shell rm /data/swich_counter.csv
echo 已删除 swich_counter.csv

echo.
echo --- 删除 /data/network_counter.csv ---
"%ADB%" shell rm /data/network_counter.csv
echo 已删除 network_counter.csv

echo.
echo --- 删除 /data/logcat 目录 ---
"%ADB%" shell rm -rf /data/logcat
echo 已删除 logcat 目录

echo.
echo [步骤 3] 执行 sync 同步...
"%ADB%" shell sync
echo 同步完成。

echo.
echo [步骤 4] 验证文件已删除...
echo.
echo --- 检查 /data/swich_counter.csv ---
"%ADB%" shell ls /data/swich_counter.csv 2>&1

echo.
echo --- 检查 /data/network_counter.csv ---
"%ADB%" shell ls /data/network_counter.csv 2>&1

echo.
echo ============================================
echo 清空完成！开关机次数已归零。
echo （swich_counter_flag 标志文件保留，确保重启后继续计数）
echo ============================================
pause
