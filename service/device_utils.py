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


def get_project_root():
    """获取项目根目录，支持打包后的环境"""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        else:
            return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROJECT_ROOT = get_project_root()

# 工具目录
if getattr(sys, 'frozen', False):
    TOOLS_DIR = os.path.join(PROJECT_ROOT, 'tools', 'bin')
else:
    TOOLS_DIR = os.path.join(PROJECT_ROOT, 'tools', 'bin')

ADB_PATH = os.path.join(TOOLS_DIR, 'adb.exe').replace('/', '\\')
TOOLS_DIR = TOOLS_DIR.replace('/', '\\')

# 定义Android设备类型列表
ANDROID_DEV_TYPES = ['A3L', 'A4L', 'A5L', 'A6L', 'A7', 'A8', 'B6L', 'B8L', 'C16H', 'H4K', 'H6', 'H8', 'H16', 'H20']
# 定义Linux设备类型列表
LINUX_DEV_TYPES = ['C08L', 'C16L', 'D16', 'D36', 'Q910']
"""Linux 机型：不支持 MagicPlayer 协议，走 SSH；也无播放器概念（无启动次数）"""

# 加载device_info.json获取OTG配置
DEVICE_OTG_CONFIG = {}
try:
    device_info_path = os.path.join(PROJECT_ROOT, 'device_info.json')
    if os.path.exists(device_info_path):
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


def get_tool_path(tool_name):
    """获取工具的完整路径，确保使用反斜杠格式（Windows）"""
    path = os.path.join(TOOLS_DIR, tool_name)
    return path.replace('/', '\\')


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
