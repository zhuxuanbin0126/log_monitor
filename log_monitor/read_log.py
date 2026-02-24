#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from config import error_log_file

if __name__ == "__main__":
    # 检查文件是否存在
    if os.path.exists(error_log_file):
        print(f"正在读取错误日志文件: {error_log_file}")
        print("="*60)
        # 使用UTF-8编码读取文件内容
        with open(error_log_file, 'r', encoding='utf-8') as f:
            content = f.read()
            print(content)
        print("="*60)
        print("文件读取完成")
    else:
        print(f"错误日志文件不存在: {error_log_file}")