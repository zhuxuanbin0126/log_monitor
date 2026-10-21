#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备工具共享模块 - 提供 ADB/SSH 操作共享的底层工具方法"""

import subprocess
import os
import sys
import time
import json
import threading
import queue
import hashlib
import re

from .adb_env import adb_subprocess_env, is_adb_command


def app_root():
    """程序根目录：打包后为 **exe 所在目录**（可写、持久），开发态为项目根目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_project_root():
    """打包内部资源根：onefile 下为 ``sys._MEIPASS`` 临时解压目录；开发态同 :func:`app_root`。"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return app_root()


PROJECT_ROOT = get_project_root()

# ---- 工具目录（**外部优先**）----
# 背景：部分电脑上 ``%TEMP%`` 被重定向/不可写，或杀软/AppLocker 禁止执行临时目录里的
# 程序 —— 此时从 ``sys._MEIPASS\tools\bin`` 启动 adb.exe / plink.exe 会失败，
# 表现为「tools 下的工具调不起来，很多功能不可用」。
# 因此**优先使用 exe 旁边的真实目录**（发布包必须带 ``tools/``），
# 仅在外部缺失时才回退到 exe 内解压的副本。
EXTERNAL_TOOLS_DIR = os.path.join(app_root(), 'tools', 'bin')
BUNDLED_TOOLS_DIR = (os.path.join(PROJECT_ROOT, 'tools', 'bin')
                     if getattr(sys, 'frozen', False) else '')

_TOOL_PATH_CACHE = {}


def tool_search_paths(tool_name):
    """工具候选路径（外部在前、内置在后）。"""
    paths = [os.path.join(EXTERNAL_TOOLS_DIR, tool_name)]
    if BUNDLED_TOOLS_DIR:
        paths.append(os.path.join(BUNDLED_TOOLS_DIR, tool_name))
    return paths


def get_tool_path(tool_name):
    """获取工具的完整路径（**当前平台原生分隔符**）：**外部 tools/bin 优先**，缺失才用内置副本。

    结果按工具名缓存，避免 adb 高频调用时反复 ``os.path.isfile``。

    注意：分隔符必须用 :func:`os.path.normpath` 归一，**不能写死反斜杠**——
    在 Linux/macOS 上把 ``/`` 替换成 ``\\`` 会得到 ``\\home\\...`` 这种不存在的路径，
    导致工具「明明在却找不到」（GitHub Actions 的 ubuntu runner 上即由此失败）。
    """
    cached = _TOOL_PATH_CACHE.get(tool_name)
    if cached:
        return cached
    candidates = tool_search_paths(tool_name)
    for path in candidates:
        if os.path.isfile(path):
            resolved = os.path.normpath(path)
            _TOOL_PATH_CACHE[tool_name] = resolved
            return resolved
    # 都不存在：返回首选路径（调用方会拿到「文件不存在」这一确定性错误）
    fallback = os.path.normpath(candidates[0])
    _TOOL_PATH_CACHE[tool_name] = fallback
    return fallback


TOOLS_DIR = os.path.normpath(
    EXTERNAL_TOOLS_DIR if os.path.isdir(EXTERNAL_TOOLS_DIR)
    else (BUNDLED_TOOLS_DIR or EXTERNAL_TOOLS_DIR))
ADB_PATH = get_tool_path('adb.exe')


def tools_status(names=None):
    """工具可用性快照（启动时写入日志，便于现场快速定位环境问题）。"""
    names = names or (
        'adb.exe', 'DeviceId.exe', 'plink.exe', 'pscp.exe',
        'HPassword.exe', 'HSDKCmd.exe', 'bash.exe', 'grep.exe',
    )
    resolved = {name: get_tool_path(name) for name in names}
    return {
        'external_dir': EXTERNAL_TOOLS_DIR,
        'external_exists': os.path.isdir(EXTERNAL_TOOLS_DIR),
        'bundled_dir': BUNDLED_TOOLS_DIR,
        'missing': [name for name, path in resolved.items() if not os.path.isfile(path)],
        'resolved': resolved,
    }


# 定义Android设备类型列表
ANDROID_DEV_TYPES = ['A3L', 'A4L', 'A5L', 'A6L', 'A7', 'A8', 'B6L', 'B8L', 'C16H', 'H4K', 'H6', 'H8', 'H16', 'H20']
# 定义Linux设备类型列表
LINUX_DEV_TYPES = ['C08L', 'C16L', 'D16', 'D36', 'Q910']
"""Linux 机型：不支持 MagicPlayer 协议，走 SSH；也无播放器概念（无启动次数）"""

# 加载device_info.json获取OTG配置（**外部优先**：exe 旁边的文件可现场改）
DEVICE_OTG_CONFIG = {}
try:
    _device_info_candidates = [os.path.join(app_root(), 'device_info.json'),
                               os.path.join(PROJECT_ROOT, 'device_info.json')]
    device_info_path = next((p for p in _device_info_candidates if os.path.exists(p)), '')
    if device_info_path:
        with open(device_info_path, 'r', encoding='utf-8') as f:
            device_info_list = json.load(f)
            for device_info in device_info_list:
                model = device_info.get('型号')
                otg_config = device_info.get('保存OTG属性')
                if model and otg_config and otg_config != 'nan':
                    if '>' in otg_config:
                        parts = otg_config.split('>')
                        if len(parts) >= 2:
                            path = parts[1].strip()
                            value = parts[0].strip().split()[-1] if ' ' in parts[0] else 'peripheral'
                            DEVICE_OTG_CONFIG[model] = {'path': path, 'value': value}
except Exception:
    pass


def _resolve_command_env(cmd, env):
    """解析子进程环境：显式传入优先；否则 adb 命令自动套用归一化环境。

    见 :mod:`service.adb_env`：Windows 下 ``%TEMP%`` 若为 8.3 短名，厂商版 adb
    会因写 ``adb.log`` 失败而无法启动 daemon，故 adb 命令必须归一化 TEMP/TMP。
    """
    if env is not None:
        return env
    if is_adb_command(cmd):
        return adb_subprocess_env()
    return None


def run_command(cmd, encoding='utf-8', timeout=30, env=None):
    """执行命令并返回输出，支持超时控制。

    Args:
        cmd: 命令字符串（``shell=True`` 执行）
        encoding: 输出解码
        timeout: 超时秒数
        env: 可选子进程环境；不传时 **adb 相关命令自动套用**归一化环境
    """
    result_queue = queue.Queue()
    child_env = _resolve_command_env(cmd, env)

    def _run_thread():
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding=encoding,
                env=child_env,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            result_queue.put((stdout.strip(), stderr.strip(), proc.returncode))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            result_queue.put(("", f"命令执行超时（{timeout}秒）", -2))
        except Exception as e:
            result_queue.put(("", str(e), -1))

    thread = threading.Thread(target=_run_thread, daemon=True)
    thread.start()
    thread.join(timeout=timeout + 2)

    if thread.is_alive():
        return "", f"命令执行超时（{timeout}秒）", -2

    try:
        return result_queue.get_nowait()
    except queue.Empty:
        return "", "命令执行失败", -1


def calculate_md5(file_path):
    """计算本地文件的MD5值"""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return None


def is_android_device(device_id):
    """判断设备是否是Android类型"""
    if not device_id:
        return False
    if '-' in device_id:
        dev_type = device_id.split('-')[0]
    else:
        dev_type = device_id
    return dev_type in ANDROID_DEV_TYPES


def retry_on_failure(max_attempts=3, delay=1.0, backoff=1.0):
    """重试装饰器：在函数失败时自动重试

    Args:
        max_attempts: 最大尝试次数（含首次）
        delay: 首次重试前等待秒数
        backoff: 退避乘数（实际延迟 = delay * backoff^(attempt-1)）
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff ** attempt)
                        time.sleep(wait)
            raise last_exception
        return wrapper
    return decorator
