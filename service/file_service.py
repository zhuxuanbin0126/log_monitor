#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
from datetime import datetime
from config import (
    DEVICE_DATA_FILE,
    ERROR_LOG_FILE,
    OUTPUT_DIR,
    LOG_DIR,
    DATA_DIR,
    SCREENSHOT_DIR,
    SWITCH_LOG_DIR,
    EXCEL_DIR,
)


class FileService:
    """文件服务类，负责文件读写和日志记录"""

    @staticmethod
    def init_log_files(base_dir: str) -> None:
        """初始化所有日志文件"""
        # 确保所有目录存在
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        os.makedirs(SWITCH_LOG_DIR, exist_ok=True)
        os.makedirs(EXCEL_DIR, exist_ok=True)

        # 初始化设备监控数据文件所在目录
        with open(DEVICE_DATA_FILE, 'w') as f:
            json.dump({}, f)

        # 初始化错误日志文件
        with open(ERROR_LOG_FILE, 'w') as f:
            f.write("")

        # 初始化运行时间日志文件
        with open(f'{LOG_DIR}/{os.path.basename(base_dir)}_uptime.log', 'w', encoding='utf-8') as f:
            f.write("")

        # 初始化设备时间日志文件
        with open(f'{LOG_DIR}/{os.path.basename(base_dir)}_cardtime.log', 'w', encoding='utf-8') as f:
            f.write("")

        # 初始化启动次数日志文件
        with open(f'{LOG_DIR}/{os.path.basename(base_dir)}_startcount.log', 'w', encoding='utf-8') as f:
            f.write("")

        # 初始化综合日志文件
        with open(f'{LOG_DIR}/{os.path.basename(base_dir)}_comprehensive.log', 'w', encoding='utf-8') as f:
            f.write("")

    @staticmethod
    def write_comprehensive_log(ip: str, password: str, device_id: str,
                                 base_dir: str, formatted_uptime: str,
                                 formatted_remote_time: str, time_diff: float,
                                 start_count: int) -> None:
        """输出一份综合的日志"""
        # 确保所有目录存在
        os.makedirs(LOG_DIR, exist_ok=True)

        # 获取当前系统时间
        os_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 构建综合日志条目
        log_entry = (
            f"{os_time},{device_id},{ip},{password},"
            f"{formatted_uptime},{formatted_remote_time},{time_diff}s,{start_count}\n"
        )

        # 写入综合日志文件
        with open(f'{LOG_DIR}/{os.path.basename(base_dir)}_comprehensive.log', 'a', encoding='utf-8') as f:
            f.write(log_entry)

    # ---- 错误详情格式化辅助方法 ----

    @staticmethod
    def _clean_difference_text(difference: str) -> str:
        """清理差异文本中的设备ID/IP冗余前缀"""
        if '发现错误' not in difference:
            return difference
        pattern1 = r'设备ID: [^,]+, IP: [^ ]+ '
        difference = re.sub(pattern1, '', difference)
        pattern2 = r'设备 [^ (]+ \([^)]+\) '
        difference = re.sub(pattern2, '', difference)
        pattern3 = r'设备 [^ ]+ '
        difference = re.sub(pattern3, '', difference)
        return difference

    @staticmethod
    def _format_single_error_dict(error: dict) -> str:
        """格式化单个错误字典条目"""
        lines = []
        err_type = error.get('type', '未知')
        process = error.get('process', '').strip()
        difference = error.get('difference', '').strip()

        lines.append(f"- 类型: {err_type}")
        if process and process != 'N/A' and process != '':
            lines.append(f"  过程: {process}")
        if difference and difference != 'N/A' and difference != '':
            difference = FileService._clean_difference_text(difference)
            lines.append(f"  差异: {difference}")
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _format_error_details(error_details) -> str:
        """根据错误详情类型分发格式化处理"""
        if isinstance(error_details, list):
            lines = []
            for error in error_details:
                if isinstance(error, dict):
                    lines.append(FileService._format_single_error_dict(error))
                else:
                    error_str = str(error).strip()
                    if error_str:
                        lines.append(f"- {error_str}\n")
            return ''.join(lines)
        elif isinstance(error_details, dict):
            return FileService._format_single_error_dict(error_details)
        else:
            error_text = str(error_details)
            if "- 类型:" not in error_text:
                error_text = re.sub(r'\n{2,}', '\n', error_text)
                lines = error_text.split('\n')
                formatted_lines = []
                for line in lines:
                    line = line.strip()
                    if line:
                        if not line.startswith('- '):
                            formatted_lines.append(f"- {line}")
                        else:
                            formatted_lines.append(line)
                error_text = '\n'.join(formatted_lines)
            return error_text + '\n'

    @staticmethod
    def write_error_log(error_info: dict) -> None:
        """写入错误日志，接受结构化错误信息字典"""
        try:
            with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                # 写入分隔线和基本信息
                f.write(f"\n{'='*50}\n")
                f.write(f"时间: {error_info.get('时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}\n")
                f.write(f"设备ID: {error_info.get('设备ID', '未知设备')}\n")
                f.write(f"IP地址: {error_info.get('IP地址', 'N/A')}\n")
                f.write(f"错误类型: {error_info.get('错误类型', '未知错误类型')}\n")
                f.write("错误详情:\n")

                # 处理错误详情
                error_details = error_info.get('错误详情', '')
                if not error_details and '原始错误消息' in error_info:
                    error_details = error_info['原始错误消息']

                f.write(FileService._format_error_details(error_details))
                f.write(f"{'='*50}\n")
        except Exception as e:
            print(f"写入错误日志失败: {str(e)}")
            try:
                with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*50}\n")
                    f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("设备ID: 未知设备\n")
                    f.write("IP地址: N/A\n")
                    f.write("错误类型: 日志记录异常\n")
                    f.write(f"错误详情: 写入日志失败: {str(e)}\n")
                    f.write(f"{'='*50}\n")
            except Exception:
                pass

    @staticmethod
    def load_device_data() -> dict:
        """加载设备历史数据"""
        try:
            with open(DEVICE_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    @staticmethod
    def save_device_data(device_data: dict) -> None:
        """保存设备数据"""
        with open(DEVICE_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(device_data, f, indent=2, ensure_ascii=False, sort_keys=True)
