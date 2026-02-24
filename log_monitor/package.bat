@echo off
cls

REM 打包脚本 - 确保能正确处理工具目录调用
set "PROJECT_DIR=%~dp0"
set "UPX_PATH=%PROJECT_DIR%upx\upx-5.0.2-win64\upx.exe"
set "SPEC_FILE=%PROJECT_DIR%log_monitor.spec"
set "OUTPUT_DIR=%PROJECT_DIR%dist"
set "RELEASE_DIR=%PROJECT_DIR%release"

echo ==========================================
echo Packaging log_monitor application
echo ==========================================

REM Clean previous files
echo 1. Cleaning previous build files...
if exist "%OUTPUT_DIR%" rd /s /q "%OUTPUT_DIR%"
if exist "%RELEASE_DIR%" rd /s /q "%RELEASE_DIR%"
mkdir "%RELEASE_DIR%"

REM Build application
echo 2. Building application with PyInstaller...
echo Using spec file: %SPEC_FILE%
pyinstaller "%SPEC_FILE%"

if %errorlevel% neq 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo Build successful!

REM Copy files to release directory
echo 3. Copying files to release directory...

REM Check if log_monitor.exe exists in dist
if exist "%OUTPUT_DIR%\log_monitor.exe" (
    echo Found log_monitor.exe in dist directory
    copy "%OUTPUT_DIR%\log_monitor.exe" "%RELEASE_DIR%" /y
) else (
    echo Error: log_monitor.exe not found in dist directory!
    pause
    exit /b 1
)

REM Check if executable exists
if not exist "%RELEASE_DIR%\log_monitor.exe" (
    echo Error: log_monitor.exe not found in release directory!
    pause
    exit /b 1
)

echo 4. Compressing executable with UPX...
"%UPX_PATH%" --best --force "%RELEASE_DIR%\log_monitor.exe"

if %errorlevel% neq 0 (
    echo UPX compression failed!
    pause
    exit /b 1
)

echo UPX compression successful!

REM Show file size
for %%F in ("%RELEASE_DIR%\log_monitor.exe") do set "FILE_SIZE=%%~zF"
echo Compressed file size: %FILE_SIZE% bytes

echo 5. Packaging completed!
echo ==========================================
echo Application is available at: %RELEASE_DIR%
echo Please test all application functions manually.
echo ==========================================
pause
