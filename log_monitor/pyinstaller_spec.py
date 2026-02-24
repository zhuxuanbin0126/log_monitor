# -*- coding: utf-8 -*-

# PyInstaller spec文件

block_cipher = None

# 需要包含的数据文件
data_files = [
    ('DeviceId.exe', '.', 'DATA'),
    ('bash.exe', '.', 'DATA'),
    ('grep.exe', '.', 'DATA'),
    ('plink.exe', '.', 'DATA'),
    ('config.py', '.', 'DATA'),
    ('requirements.txt', '.', 'DATA'),
    ('adb.exe', '.', 'DATA'),
    ('AdbWinApi.dll', '.', 'DATA'),
    ('pscp.exe', '.', 'DATA'),
    ('AdbWinUsbApi.dll', '.', 'DATA')
]

# 需要包含的隐藏导入（PyQt5相关）
hiddenimports = [
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'pandas',
    'openpyxl',
    'numpy',  # pandas依赖
    'pytz',   # pandas依赖
]

# 分析的主脚本
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 创建单个可执行文件
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='log_monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 设置为True可显示控制台窗口
    icon=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 如果需要创建单文件夹分发
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='log_monitor',
)