# -*- mode: python ; coding: utf-8 -*-

# 打包策略（体积与可靠性取舍）：
# 1) **工具二进制不再塞进 exe**：发布包（build_release.py）会把整个 tools/ 复制到
#    exe 旁边，运行时由 service/device_utils.get_tool_path 优先使用**外部真实路径**。
#    这样既解决了「部分电脑从 %TEMP%\_MEIxxx 调不起 adb/plink」的问题，也避免
#    tools/bin 在 exe 内外各存一份（约 4.4MB 冗余）。
# 2) 仅保留纯文本资源（脚本 / rc / ntpdate 之外的小文件）作为**兜底副本**：
#    外部 tools/ 意外缺失时仍能读到它们。
# 3) excludes 里去掉本项目未用到的 Qt 组件与调试符号，进一步压缩体积。


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 脚本文件 - 兜底副本（外部 tools/ 优先，见 config._external_or_bundled）
        ('tools/getdeviceinfo.sh', 'tools'),
        ('tools/boot_counter.sh', 'tools'),
        ('tools/run.sh', 'tools'),
        ('tools/ntpdate', 'tools'),
        # RC配置文件 - 兜底副本
        ('tools/init.huidu.rc', 'tools'),
        ('tools/init.rk3399.rc', 'tools'),
        ('tools/init.rk356x.rc', 'tools'),
        ('tools/init.rk3588.rc', 'tools'),
        # 配置文件
        ('version_info.txt', '.'),
        ('device_info.json', '.'),
    ],
    hiddenimports=['openpyxl', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'paramiko'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', 'unittest', 'pywin32_testutil', 'setuptools',
        'pkg_resources',
        # Excel 导出已改为 openpyxl 直写，pandas/numpy 不再需要（约 40~60MB）
        'pandas', 'numpy', 'matplotlib', 'scipy', 'IPython', 'jupyter',
        # 未使用的 Qt 组件（PyInstaller 会连带打入大量插件/DLL）
        'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets',
        'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
        'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets', 'PyQt5.QtBluetooth',
        'PyQt5.QtNetwork', 'PyQt5.QtSql', 'PyQt5.QtTest', 'PyQt5.QtXml',
        'PyQt5.QtDesigner', 'PyQt5.QtHelp', 'PyQt5.QtOpenGL',
        'PyQt5.QtPrintSupport', 'PyQt5.QtSvg', 'PyQt5.QtDBus',
    ],
    noarchive=False,
    optimize=2,
)

# 进一步剔除无用体积：Qt 翻译文件、QML 运行时、软件 OpenGL 兜底 DLL
# （本项目是纯 Widgets 界面，不使用这些资源；它们通常合计 10~20MB）
_BIN_DROP = ('opengl32sw.dll', 'd3dcompiler_', 'qt5quick', 'qt5qml')
_DATA_DROP = ('/translations/', '\\translations\\', '/qml/', '\\qml\\')
a.binaries = [item for item in a.binaries
              if not any(token in item[0].lower() for token in _BIN_DROP)]
a.datas = [item for item in a.datas
           if not any(token in item[0].lower() for token in _DATA_DROP)]

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
    # UPX 保持开启（对外分享看重体积）；若某台机器出现
    # 「Failed to load Python DLL / 杀软拦截」，把这里改为 False 再发一版即可。
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
