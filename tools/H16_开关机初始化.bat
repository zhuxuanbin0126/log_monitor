@echo off
chcp 65001 >nul
echo ============================================
echo H16 设备开关机初始化脚本
echo 功能：传输文件 + 创建标志文件
echo ============================================
echo.

REM 设置脚本所在目录为工作目录
cd /d "%~dp0"

REM 设置ADB路径
set "ADB=..\adb.exe"

echo [步骤 0] 断开已有ADB连接...
"%ADB%" disconnect
timeout /t 1 /nobreak >nul

echo.
echo [步骤 1] 等待设备在线...
"%ADB%" devices
echo.

REM 等待用户确认设备在线
set /p CONFIRM="请确认上方设备列表中显示 H16 设备处于 device 状态 (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo 已取消操作。
    pause
    exit /b 1
)

echo.
echo [步骤 2] 推送 boot_counter.sh 到 /system/bin/ ...
"%ADB%" push boot_counter.sh /system/bin/boot_counter.sh
if errorlevel 1 (
    echo [错误] boot_counter.sh 推送失败！
    pause
    exit /b 1
)
echo boot_counter.sh 推送成功。

echo.
echo [步骤 3] 设置 boot_counter.sh 执行权限...
"%ADB%" shell chmod 777 /system/bin/boot_counter.sh
echo 权限设置完成。

echo.
echo [步骤 4] 推送 init.rk3588.rc 到 /vendor/etc/init/hw/ ...
"%ADB%" push init.rk3588.rc /vendor/etc/init/hw/init.rk3588.rc
if errorlevel 1 (
    echo [错误] init.rk3588.rc 推送失败！
    pause
    exit /b 1
)
echo init.rk3588.rc 推送成功。

echo.
echo [步骤 5] 创建 /data/swich_counter_flag 标志文件...
"%ADB%" shell touch /data/swich_counter_flag
echo 标志文件创建成功。

echo.
echo [步骤 6] 执行 sync 同步...
"%ADB%" shell sync
echo 同步完成。

echo.
echo [步骤 7] 验证文件是否存在...
echo.
echo --- 检查 /system/bin/boot_counter.sh ---
"%ADB%" shell ls -l /system/bin/boot_counter.sh

echo.
echo --- 检查 /vendor/etc/init/hw/init.rk3588.rc ---
"%ADB%" shell ls -l /vendor/etc/init/hw/init.rk3588.rc

echo.
echo --- 检查 /data/swich_counter_flag ---
"%ADB%" shell ls -l /data/swich_counter_flag

echo.
echo ============================================
echo 初始化完成！设备断电重启后将自动统计开关机次数。
echo ============================================
pause
