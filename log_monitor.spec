# -*- mode: python ; coding: utf-8 -*-

# 打包策略（体积与可靠性取舍）：
# 1) **工具二进制不再塞进 exe**：发布包（build_release.py）会把整个 tools/ 复制到
#    exe 旁边，运行时由 service/device_utils.get_tool_path 优先使用**外部真实路径**。
#    这样既解决了「部分电脑从 %TEMP%\_MEIxxx 调不起 adb/plink」的问题，也避免
#    tools/bin 在 exe 内外各存一份（约 4.4MB 冗余）。
# 2) 仅保留纯文本资源（脚本 / rc / ntpdate 之外的小文件）作为**兜底副本**：
#    外部 tools/ 意外缺失时仍能读到它们。
# 3) 界面为 PySide6/Qt6 纯 Widgets：只保留 platforms / styles / imageformats
#    三个插件目录的最小集合，其余 Qt 插件、翻译、QML 全部剔除。
# 4) excludes 里去掉本项目未用到的 Qt 组件与调试符号，进一步压缩体积。

import os

from PySide6.QtCore import QLibraryInfo

# ---------------------------------------------------------------------------
# Qt6 插件最小集（纯 Widgets 应用）
#   platforms      : qwindows.dll —— Windows 平台插件，必需
#   styles         : qmodernwindowsstyle.dll —— 原生窗口样式，必需
#   imageformats   : 仅保留 gif / ico / jpeg 解码器；svg/webp/tiff/pdf 等不用
# 其余插件目录（qmltooling / sqldrivers / multimedia / webview / tls / ...）
# 在下方统一过滤掉。
# ---------------------------------------------------------------------------
_QT_PLUGIN_ROOT = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
_PLUGIN_KEEP = {
    "platforms": {"qwindows.dll"},
    "styles": {"qmodernwindowsstyle.dll"},
    "imageformats": {"qgif.dll", "qico.dll", "qjpeg.dll"},
}

qt_plugin_datas = []
for _group, _names in _PLUGIN_KEEP.items():
    for _name in sorted(_names):
        _src = os.path.join(_QT_PLUGIN_ROOT, _group, _name)
        if os.path.isfile(_src):
            qt_plugin_datas.append((_src, os.path.join("PySide6", "plugins", _group)))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=qt_plugin_datas + [
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
    hiddenimports=[
        'openpyxl', 'paramiko',
        'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', 'unittest', 'pywin32_testutil', 'setuptools',
        'pkg_resources', 'pytest', '_pytest',
        # 旧绑定（迁移后不再使用）
        'PyQt5', 'PyQt6', 'sip',
        # Excel 导出已改为 openpyxl 直写，pandas/numpy 不再需要（约 40~60MB）
        'pandas', 'numpy', 'matplotlib', 'scipy', 'IPython', 'jupyter',
        # 未使用的 Qt 组件（PyInstaller 会连带打入大量插件/DLL）
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtQuickControls2', 'PySide6.QtQuick3D',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtSpatialAudio', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
        'PySide6.QtPositioning', 'PySide6.QtSensors', 'PySide6.QtSerialPort',
        'PySide6.QtSerialBus', 'PySide6.QtSql', 'PySide6.QtTest',
        'PySide6.QtXml', 'PySide6.QtDesigner', 'PySide6.QtHelp',
        'PySide6.QtUiTools', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtPrintSupport', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
        'PySide6.QtDBus', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtStateMachine', 'PySide6.QtScxml', 'PySide6.QtTextToSpeech',
        'PySide6.QtRemoteObjects', 'PySide6.QtHttpServer',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    ],
    noarchive=False,
    optimize=2,
)


def _qt_plugin_allowed(dest):
    """PySide6 插件只保留最小集；非插件返回 None。"""
    lower = dest.replace("\\", "/").lower()
    marker = 'pyside6/plugins/'
    if marker not in lower:
        return None
    parts = lower.split(marker, 1)[1].split('/')
    if len(parts) < 2:
        return False
    group, filename = parts[0], parts[-1]
    return filename in _PLUGIN_KEEP.get(group, set())


def _drop_binary(dest):
    """剔除用不到的 Qt DLL、Qt 非最小集插件与调试符号相关二进制。"""
    if _qt_plugin_allowed(dest) is False:
        return False
    lower = dest.replace("\\", "/").lower()
    tokens = (
        'opengl32sw.dll', 'd3dcompiler_',
        'qt6quick', 'qt6qml', 'qt6webengine', 'qt6multimedia',
        'qt6pdf', 'qt6charts', 'qt6datavisualization', 'qt6graphs',
        'qt6bluetooth', 'qt6nfc', 'qt6positioning', 'qt6sensors',
        'qt6serialport', 'qt6serialbus', 'qt6sql', 'qt6test',
        'qt6designer', 'qt6help', 'qt6uitools', 'qt6opengl',
        'qt6printsupport', 'qt6svg', 'qt6dbus', 'qt6texttospeech',
        'qt6remoteobjects', 'qt6scxml', 'qt6statemachine', 'qt6webchannel',
        'qt6websockets', 'qt6http', 'qt6spatialaudio', 'qt63d',
    )
    return not any(token in lower for token in tokens)


def _drop_data(dest):
    """剔除 Qt 翻译、QML 以及非最小集的 Qt 插件。"""
    if _qt_plugin_allowed(dest) is False:
        return False
    lower = dest.replace("\\", "/").lower()
    return not any(token in lower for token in ('/translations/', '/qml/'))


a.binaries = [item for item in a.binaries if _drop_binary(item[0])]
a.datas = [item for item in a.datas if _drop_data(item[0])]

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
