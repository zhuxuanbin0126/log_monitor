@echo off

REM Check Python environment
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

echo 1. Installing PyInstaller...
pip install pyinstaller

REM Check if PyInstaller installed successfully
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo Error: PyInstaller installation failed
    pause
    exit /b 1
)

echo 2. Installing project dependencies...
pip install -r requirements.txt

echo 3. Creating build directories...
if not exist "build" mkdir build
if not exist "dist" mkdir dist

echo 4. Building main application...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "log_monitor" ^
    --add-data "DeviceId.exe;" ^
    --add-data "bash.exe;" ^
    --add-data "grep.exe;" ^
    --add-data "plink.exe;" ^
    --add-data "pscp.exe;" ^
    --add-data "adb.exe;" ^
    --add-data "AdbWinApi.dll;" ^
    --add-data "AdbWinUsbApi.dll;" ^
    --add-data "config.py;" ^
    --hidden-import "pandas" ^
    --hidden-import "openpyxl" ^
    --hidden-import "PyQt5.QtWidgets" ^
    --hidden-import "PyQt5.QtCore" ^
    --hidden-import "PyQt5.QtGui" ^
    --upx ^
    --exclude-module "tkinter" ^
    main.py

if errorlevel 1 (
    echo Error: Build failed
    pause
    exit /b 1
)

echo 5. Creating release directory...
if not exist "release" mkdir release

REM Copy executable to release directory
copy "dist\log_monitor.exe" "release\" >nul

REM Copy support files to release directory
copy "DeviceId.exe" "release\" >nul
copy "bash.exe" "release\" >nul
copy "grep.exe" "release\" >nul
copy "plink.exe" "release\" >nul
copy "config.py" "release\" >nul
copy "README.md" "release\" >nul

REM Create log directory structure
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
echo Build completed successfully!
echo Executable: release\log_monitor.exe
echo Support files copied to release\ directory
echo ========================================

echo.
echo Press any key to exit...
pause >nul