#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages
import os
from config import VERSION

# 获取当前目录下的所有文件
def get_data_files():
    data_files = []
    
    # 添加可执行文件
    exe_files = ['DeviceId.exe', 'bash.exe', 'grep.exe', 'plink.exe','adb.exe', 'pscp.exe', 'AdbWinUsbApi.dll', 'AdbWinApi.dll']
    for exe_file in exe_files:
        if os.path.exists(exe_file):
            data_files.append(exe_file)
    
    # 添加配置文件
    config_files = ['config.py', 'requirements.txt']
    for config_file in config_files:
        if os.path.exists(config_file):
            data_files.append(config_file)
    
    # 添加日志目录结构（空目录）
    aging_test_dirs = [
        'A-B-C-D-H_AgingTest', 'A4L_AgingTest', 'A5L_AgingTest', 'A6L_AgingTest',
        'C08L_AgingTest', 'C16H_AgingTest', 'C16L_AgingTest', 'C16_AgingTest',
        'D16_AgingTest', 'H6_AgingTest', 'H8_AgingTest'
    ]
    
    return data_files

setup(
    name="log_monitor",
    version=VERSION,
    description="设备监控和日志记录工具",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        '': ['*.exe', '*.txt', '*.py', '*.md'],
    },
    data_files=[
        ('', get_data_files()),
    ],
    install_requires=[
        'PyQt5==5.15.9',
        'pandas==2.1.0',
        'openpyxl==3.1.2',
    ],
    entry_points={
        'console_scripts': [
            'log-monitor=main:main',
        ],
        'gui_scripts': [
            'log-monitor-gui=main:main',
        ]
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: Microsoft :: Windows',
    ],
    python_requires='>=3.8',
)