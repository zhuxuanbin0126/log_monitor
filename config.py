#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""应用程序配置文件"""

import os
import sys

VERSION = '1.0.3.0'

# 获取项目根目录，支持打包后的环境
def get_project_root():
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        else:
            return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = get_project_root()
getinfo_path = os.path.join(PROJECT_ROOT, "tools", "getdeviceinfo.sh")

# 设备类型配置 (由于A7 A8不支持ssh 所以暂时不支持)
supported_dev_types = ['A-B-C-D-H','A3L', 'A4L', 'A5L', 'A6L', 'B6L', 'B8L', 'C08L', 'C16H', 'H4K', 'H6', 'H8', 'D16', 'C16L', 'A7', 'A8','H20']
"""支持的设备类型列表"""

tool_path = os.path.join(PROJECT_ROOT, "tools") # 工具路径 - 使用绝对路径

program_path = os.path.join(PROJECT_ROOT, "program") # 节目保存位置 - 使用绝对路径

default_dev_type = 'A-B-C-D-H'  # 默认设备类型

# 文件路径配置
device_data_file = 'device_monitoring_data.json'
error_log_file = 'device_error.txt'

# 监控配置
default_delay_time = 60  # 默认监控间隔（秒）

# 日志目录配置
def get_base_dir(dev_type):
    """根据设备类型获取基础日志目录"""
    # 获取当前脚本所在目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 使用绝对路径创建日志目录
    return os.path.join(current_dir, f'{dev_type}_AgingTest')

# 时间误差阈值配置
time_diff_threshold = 120  # 启动时间误差阈值（秒）
daily_time_diff_threshold = 3  # 设备时间日均误差阈值（秒）

# 命令配置
def get_device_list_pattern(dev_type):
    """获取设备列表的过滤模式"""
    return dev_type.replace('-', '|')