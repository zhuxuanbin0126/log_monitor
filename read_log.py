#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from config import ERROR_LOG_FILE


def main() -> None:
    """读取错误日志文件并打印到控制台"""
    if os.path.exists(ERROR_LOG_FILE):
        print(f"正在读取错误日志文件: {ERROR_LOG_FILE}")
        print("=" * 60)
        with open(ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            print(content)
        print("=" * 60)
        print("文件读取完成")
    else:
        print(f"错误日志文件不存在: {ERROR_LOG_FILE}")


if __name__ == "__main__":
    main()
