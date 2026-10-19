#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""应用程序配置文件"""

import os
import sys

VERSION = '1.0.6.0'

# ============================================================
# 路径计算
# ============================================================

def get_project_root():
    """获取项目根目录，支持打包后的环境"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = get_project_root()

# ---- 工具与节目路径 ----
TOOL_PATH = os.path.join(PROJECT_ROOT, "tools")
PROGRAM_PATH = os.path.join(PROJECT_ROOT, "program")
GET_INFO_PATH = os.path.join(PROJECT_ROOT, "tools", "getdeviceinfo.sh")

# ---- 输出目录 ----
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
DATA_DIR = os.path.join(OUTPUT_DIR, "data")
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshot")
SWITCH_LOG_DIR = os.path.join(OUTPUT_DIR, "switch_log")
EXCEL_DIR = os.path.join(OUTPUT_DIR, "excel")

# ============================================================
# 设备类型配置
# ============================================================

SUPPORTED_DEV_TYPES = (
    'A-B-C-D-H', 'A3L', 'A4L', 'A5L', 'A6L', 'B6L', 'B8L',
    'C08L', 'C16H', 'H4K', 'H6', 'H8', 'D16', 'C16L',
    'A7', 'A8', 'H20', 'H16',
)
"""支持的设备类型列表（元组，不可变）"""

DEFAULT_DEV_TYPE = 'A-B-C-D-H'
"""默认设备类型"""

# ============================================================
# 文件路径配置
# ============================================================

DEVICE_DATA_FILE = 'device_monitoring_data.json'
ERROR_LOG_FILE = 'device_error.txt'

# ============================================================
# 监控与时间阈值配置
# ============================================================

DEFAULT_DELAY_SECONDS = 60
"""默认监控间隔（秒）"""

BOOT_TIME_DIFF_THRESHOLD_SECONDS = 120
"""启动时间误差阈值（秒）"""

DAILY_TIME_DIFF_THRESHOLD_SECONDS = 3
"""设备时间日均误差阈值（秒）"""

# ============================================================
# 外部命令超时与重试配置
# ============================================================

ADB_COMMAND_TIMEOUT = 30
"""ADB 命令默认超时（秒）"""

MAX_RETRY_COUNT = 3
"""默认最大重试次数"""

DELAY_INPUT_MIN = 10
"""监控间隔输入下限（秒）"""

DELAY_INPUT_MAX = 86400
"""监控间隔输入上限（秒）"""

PROCESS_SLEEP_MS = 100
"""设备间处理间隔（毫秒）"""

ADB_DISCONNECT_DELAY_MS = 500
"""ADB 断开后等待时间（毫秒）"""

CONNECTION_STABILIZE_SECONDS = 2
"""连接建立后稳定等待时间（秒）"""

DEFAULT_SCREENSHOT_PATH = "./screenshot"
"""默认截图存储路径"""

# ============================================================
# 日志目录配置
# ============================================================

def get_base_dir(dev_type):
    """根据设备类型获取基础日志目录"""
    return os.path.join(OUTPUT_DIR, 'logs', f'{dev_type}_AgingTest')

# ============================================================
# 命令配置
# ============================================================

def get_device_list_pattern(dev_type):
    """获取设备列表的过滤模式"""
    return dev_type.replace('-', '|')


# ============================================================
# 系统类型与远程路径映射
# ============================================================

_SYSTEM_TYPE_PATH_MAP = {
    "android": "/data",
    "linux": "/root/Box/project",
}
DEFAULT_REMOTE_PATH = "/root/Box/project"
"""默认远程路径（用于无法识别的系统类型）"""


def get_device_remote_path(system_type: str) -> str:
    """根据系统类型返回设备端远程数据路径
    
    集中管理 Android/Linux 设备的核心数据目录映射，
    支持中文"安卓"和英文"android"两种系统版本标识。
    """
    if not system_type:
        return DEFAULT_REMOTE_PATH
    sys_type = system_type.lower()
    # 支持中文"安卓"和英文"android"/"安卓"两种标识
    if "android" in sys_type or "安卓" in system_type:
        return _SYSTEM_TYPE_PATH_MAP["android"]
    if "linux" in sys_type:
        return _SYSTEM_TYPE_PATH_MAP["linux"]
    return DEFAULT_REMOTE_PATH


# ============================================================
# 向后兼容别名（过渡期使用，后续版本将移除）
# ============================================================

tool_path = TOOL_PATH
program_path = PROGRAM_PATH
getinfo_path = GET_INFO_PATH
supported_dev_types = list(SUPPORTED_DEV_TYPES)  # 可变副本，兼容旧代码
default_dev_type = DEFAULT_DEV_TYPE
device_data_file = DEVICE_DATA_FILE
error_log_file = ERROR_LOG_FILE
default_delay_time = DEFAULT_DELAY_SECONDS
time_diff_threshold = BOOT_TIME_DIFF_THRESHOLD_SECONDS
daily_time_diff_threshold = DAILY_TIME_DIFF_THRESHOLD_SECONDS
