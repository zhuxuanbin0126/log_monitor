#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""应用程序配置文件"""

import os

VERSION = '1.0.1.1'

getinfo_path = "./tools/getdeviceinfo.sh"

# 设备类型配置
supported_dev_types = ['A-B-C-D-H','A3L', 'A4L', 'A5L', 'A6L', 'A7', 'A8', 'B6L', 'B8L', 'C08L', 'C16H', 'H4K', 'H6', 'H8', "D16", "C16L"]
"""支持的设备类型列表"""

tool_path = "./tools" #工具路径

program_path = "./program" #节目保存位置

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