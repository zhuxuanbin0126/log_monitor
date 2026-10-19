# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 工具文件 - 打包后放在 tools/bin 目录
        ('tools/bin/DeviceId.exe', 'tools/bin'),
        ('tools/bin/bash.exe', 'tools/bin'),
        ('tools/bin/grep.exe', 'tools/bin'),
        ('tools/bin/plink.exe', 'tools/bin'),
        ('tools/bin/pscp.exe', 'tools/bin'),
        ('tools/bin/adb.exe', 'tools/bin'),
        ('tools/bin/AdbWinApi.dll', 'tools/bin'),
        ('tools/bin/AdbWinUsbApi.dll', 'tools/bin'),
        ('tools/bin/HPassword.exe', 'tools/bin'),
        ('tools/bin/HSDKCmd.exe', 'tools/bin'),
        ('tools/bin/scrcpy.dll', 'tools/bin'),
        # 脚本文件 - 打包后放在 tools 目录
        ('tools/getdeviceinfo.sh', 'tools'),
        ('tools/boot_counter.sh', 'tools'),
        ('tools/run.sh', 'tools'),
        ('tools/ntpdate', 'tools'),
        # RC配置文件 - 打包后放在 tools 目录
        ('tools/init.huidu.rc', 'tools'),
        ('tools/init.rk3399.rc', 'tools'),
        ('tools/init.rk356x.rc', 'tools'),
        ('tools/init.rk3588.rc', 'tools'),
        # 配置文件 - 打包后放在根目录
        ('config.py', '.'),
        ('version_info.txt', '.'),
        ('device_info.json', '.'),
    ],
    hiddenimports=['pandas', 'openpyxl', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'paramiko'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'pywin32_testutil', 'setuptools', 'pkg_resources'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('O', None, 'OPTION'), ('O', None, 'OPTION')],
    name='log_monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'msvcp140.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
)
