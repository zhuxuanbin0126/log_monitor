#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from setuptools import find_packages, setup

from config import VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))

BIN_TOOLS = [
    'DeviceId.exe', 'bash.exe', 'grep.exe', 'plink.exe', 'pscp.exe',
    'adb.exe', 'AdbWinUsbApi.dll', 'AdbWinApi.dll', 'HPassword.exe',
    'HSDKCmd.exe', 'scrcpy.dll',
]
SCRIPT_TOOLS = [
    'getdeviceinfo.sh', 'boot_counter.sh', 'run.sh', 'ntpdate',
    'init.huidu.rc', 'init.rk3399.rc', 'init.rk356x.rc', 'init.rk3588.rc',
]


def _existing(relative_dir, names):
    return [
        os.path.join(relative_dir, name)
        for name in names
        if os.path.exists(os.path.join(ROOT, relative_dir, name))
    ]


setup(
    name="log_monitor",
    version=VERSION,
    description="设备监控和日志记录工具",
    author="xuanbin",
    author_email="xuanbin0126@126.com",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        '': ['*.exe', '*.txt', '*.py', '*.md'],
    },
    data_files=[
        ('tools/bin', _existing('tools/bin', BIN_TOOLS)),
        ('tools', _existing('tools', SCRIPT_TOOLS)),
        ('', [
            path for path in ('config.py', 'device_info.json', 'requirements.txt', 'version_info.txt')
            if os.path.exists(os.path.join(ROOT, path))
        ]),
    ],
    install_requires=[
        'PyQt5==5.15.9',
        'pandas==2.1.0',
        'openpyxl==3.1.2',
        'paramiko==3.5.1',
    ],
    entry_points={
        'console_scripts': [
            'log-monitor=main:main',
        ],
        'gui_scripts': [
            'log-monitor-gui=main:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Operating System :: Microsoft :: Windows',
    ],
    python_requires='>=3.8',
)
