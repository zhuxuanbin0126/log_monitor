#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ADB 子进程环境归一（Windows）。

背景（真机复现的根因）：本机 ``%TEMP%`` 存为 **8.3 短名**
``C:\\Users\\ADMINI~1\\AppData\\Local\\Temp``。厂商版 adb 启动时**无条件**把客户端日志
写到 ``%TEMP%\\adb.log``；在该短名路径下打开失败::

    cannot open C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\adb.log: Permission denied
    → could not read ok from ADB Server → failed to start daemon → 5037 无监听

→ 结果是有线/无线 ADB 全部不可用。实测把 ``TEMP``/``TMP`` 指向**长路径可写目录**后，
``adb start-server`` 立即成功、``adb devices`` 正常。

本模块给出统一的**子进程环境**：在继承环境的基础上，只把 ``TEMP``/``TMP`` 归一到
工具可控的长路径目录，其余环境（PATH 等）原样继承，对调用方透明。

可用环境变量 ``LOG_MONITOR_ADB_TMP`` 指定自定义目录。
"""

import os
import sys
from typing import Dict

ENV_OVERRIDE = "LOG_MONITOR_ADB_TMP"
"""覆盖临时目录的环境变量名"""


def _app_root() -> str:
    """程序根目录（打包后为 exe 所在目录，开发态为项目根目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def adb_temp_dir() -> str:
    """adb 使用的临时目录：**长路径、确保存在、工具可控**。"""
    base = os.environ.get(ENV_OVERRIDE)
    if not base:
        base = os.path.join(_app_root(), "output", "tmp")
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except OSError:
        # 兜底：根目录不可写时退到工具目录下的 tmp
        fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def adb_subprocess_env() -> Dict[str, str]:
    """返回 adb 子进程环境变量：``TEMP``/``TMP`` 归一为长路径可写目录。"""
    env = dict(os.environ)
    tmp = adb_temp_dir()
    env["TEMP"] = tmp
    env["TMP"] = tmp
    return env


def is_adb_command(command) -> bool:
    """命令是否涉及 adb（用于自动套用归一化环境）。"""
    return isinstance(command, str) and "adb" in command.lower()
