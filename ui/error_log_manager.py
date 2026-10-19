"""错误日志管理：错误分类、消息优化、落盘与记事本查看。"""

import os
import re
import subprocess
from datetime import datetime

from config import ERROR_LOG_FILE
from service.data_processing_service import DataProcessingService
from service.file_service import FileService
from service.logging_service import get_logger


class ErrorLogManager:
    """集中处理设备错误日志，避免 MainWindow 承担日志细节。"""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda *args, **kwargs: None)
        self._notepad_process = None
        self._logger = get_logger(__name__)

    @staticmethod
    def optimize_message(message: str) -> str:
        """优化错误消息显示，使其更友好。"""
        if "Access denied" in message and "password was not accepted" in message:
            return "设备通信异常: 密码认证失败，请检查设备密码配置"

        error_patterns = [
            (r'获取启动时间失败', '设备启动时间获取失败'),
            (r'获取设备时间失败', '设备时间获取失败'),
            (r'获取运行时长失败', '设备运行时长获取失败'),
            (r'获取启动次数失败', '设备启动次数获取失败'),
            (r'超时', '设备通信超时'),
            (r'连接失败', '设备连接失败'),
        ]

        for pattern, replacement in error_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        return message

    @staticmethod
    def determine_error_type(message: str, errors=None) -> str:
        """确定错误类型。"""
        if errors and isinstance(errors, list):
            return next(
                (err.get('type', '设备异常') for err in errors if isinstance(err, dict)),
                '设备异常',
            )

        error_patterns = [
            (r'时间[差异]|同步|时钟', '时间同步异常'),
            (r'启动次数|重启', '启动次数异常'),
            (r'离线|断开|连接失败', '设备离线'),
            (r'超时|timeout', '通信超时'),
            (r'认证|密码|登录', '认证失败'),
        ]
        for pattern, err_type in error_patterns:
            if re.search(pattern, message or '', re.IGNORECASE):
                return err_type
        return '设备异常'

    def build_error_details(self, message: str, errors=None):
        """构建错误详情结构。"""
        if errors:
            if isinstance(errors, list):
                return errors
            if isinstance(errors, dict):
                return [errors]

        return [{
            'type': self.determine_error_type(message, None),
            'process': '错误处理',
            'difference': message,
        }]

    def write(self, message=None, device_id=None, ip=None, password=None, errors=None) -> None:
        """写入结构化错误日志。"""
        try:
            if not device_id or not ip:
                extracted_id, extracted_ip = DataProcessingService.extract_device_info(message or '')
                device_id = device_id or extracted_id
                ip = ip or extracted_ip

            error_info = {
                "时间": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "设备ID": device_id,
                "IP地址": ip,
                "错误类型": self.determine_error_type(message, errors),
                "错误详情": self.build_error_details(message, errors),
            }
            FileService.write_error_log(error_info)
        except Exception as e:
            # 避免递归调用 UI 日志
            self._logger.exception("写入错误日志失败: %s", e)

    def handle(self, error_msg, device_id, ip) -> None:
        """监控线程错误信号入口：优化显示 + 落盘 + 打开日志。"""
        self._log(self.optimize_message(error_msg), is_error=True)
        self.write(error_msg, device_id=device_id, ip=ip)
        self.open_in_notepad()

    def open_in_notepad(self) -> None:
        """打开记事本显示错误日志，并处理进程冲突。"""
        if not os.path.exists(ERROR_LOG_FILE):
            with open(ERROR_LOG_FILE, 'w', encoding='utf-8') as f:
                f.write("# 错误日志文件\n")

        if self._notepad_process:
            try:
                self._notepad_process.terminate()
                self._notepad_process.wait(timeout=3)
            except Exception:
                pass

        self._notepad_process = subprocess.Popen(['notepad.exe', ERROR_LOG_FILE])
