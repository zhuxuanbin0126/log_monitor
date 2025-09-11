@echo off
chcp 65001 >nul

echo ========================================
echo 开始打包Log Monitor应用程序
echo ========================================

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

echo 1. 安装PyInstaller...
pip install pyinstaller

REM 检查PyInstaller是否安装成功
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo 错误: PyInstaller安装失败
    pause
    exit /b 1
)

echo 2. 安装项目依赖...
pip install -r requirements.txt

echo 3. 创建打包目录...
if not exist "build" mkdir build
if not exist "dist" mkdir dist

REM 使用PyInstaller打包
REM --onefile: 打包为单个可执行文件
REM --windowed: 不显示控制台窗口
REM --add-data: 添加外部工具文件
REM --hidden-import: 添加隐藏导入

echo 4. 开始打包主程序...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "log_monitor" ^
    --add-data "DeviceId.exe;." ^
    --add-data "bash.exe;." ^
    --add-data "grep.exe;." ^
    --add-data "plink.exe;." ^
    --add-data "config.py;." ^
    --hidden-import "pandas" ^
    --hidden-import "openpyxl" ^
    --hidden-import "PyQt5.QtWidgets" ^
    --hidden-import "PyQt5.QtCore" ^
    --hidden-import "PyQt5.QtGui" ^
    main.py

if errorlevel 1 (
    echo 错误: 打包失败
    pause
    exit /b 1
)

echo 5. 创建发布目录...
if not exist "release" mkdir release

REM 复制可执行文件到发布目录
copy "dist\log_monitor.exe" "release\" >nul

REM 复制支持文件到发布目录
copy "DeviceId.exe" "release\" >nul
copy "bash.exe" "release\" >nul
copy "grep.exe" "release\" >nul
copy "plink.exe" "release\" >nul
copy "config.py" "release\" >nul
copy "README.md" "release\" >nul

REM 创建日志目录结构
if not exist "release\A-B-C-D-H_AgingTest" mkdir "release\A-B-C-D-H_AgingTest"
if not exist "release\A4L_AgingTest" mkdir "release\A4L_AgingTest"
if not exist "release\A5L_AgingTest" mkdir "release\A5L_AgingTest"
if not exist "release\A6L_AgingTest" mkdir "release\A6L_AgingTest"
if not exist "release\C08L_AgingTest" mkdir "release\C08L_AgingTest"
if not exist "release\C16H_AgingTest" mkdir "release\C16H_AgingTest"
if not exist "release\C16L_AgingTest" mkdir "release\C16L_AgingTest"
if not exist "release\C16_AgingTest" mkdir "release\C16_AgingTest"
if not exist "release\D16_AgingTest" mkdir "release\D16_AgingTest"
if not exist "release\H6_AgingTest" mkdir "release\H6_AgingTest"
if not exist "release\H8_AgingTest" mkdir "release\H8_AgingTest"

echo ========================================
echo 打包完成！
echo 可执行文件: release\log_monitor.exe
echo 支持文件已复制到 release\ 目录
echo ========================================

echo.
echo 按任意键退出...
pause >nul