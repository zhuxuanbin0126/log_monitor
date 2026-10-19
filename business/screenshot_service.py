#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备截图服务 - 负责捕获设备屏幕截图

Android 设备**协议优先**：``ReadBack{target:"ScreenShot", fileTransferMode:2}``
经 Socket 文件通道回传整屏图片（免 adb、免 root）；协议不可用时回落原有
adb ``screencap`` 流程。落盘路径与命名规则保持不变。
"""

import os
import time
from datetime import datetime

from config import USE_PROTOCOL_QUERY
from data_models import OperationResult
from service.logging_service import get_logger
from service.tool_service import ToolService

logger = get_logger(__name__)


class ScreenshotService:
    """设备截图业务服务类"""

    @staticmethod
    def _try_protocol_screenshot(ip, target_file) -> bool:
        """协议截图并落盘；成功返回 True（失败返回 False，由调用方回落 adb）。"""
        try:
            from service.protocol import query_screenshot
            image = query_screenshot(ip)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("设备 %s 协议截图异常，回落 adb: %s", ip, exc)
            return False
        if not image:
            return False
        with open(target_file, 'wb') as file_handle:
            file_handle.write(image)
        logger.info("设备 %s 协议截图成功: %s 字节 -> %s", ip, len(image), target_file)
        return True

    @staticmethod
    def capture_screenshot(device_id, ip, password, system_type, screenshot_path="./screenshot") -> OperationResult:
        """捕获设备屏幕截图，返回 OperationResult（成功时 data 为文件路径）。"""
        os.makedirs(screenshot_path, exist_ok=True)

        supported_dev_types = ["H6", "H8", "H4K", "B6L", "B8L", "A3L", "A4L", "A5L", "A6L", "C16H", "H16", "H20"]
        dev_type_prefix = device_id.split('-')[0] if '-' in device_id else device_id

        if dev_type_prefix not in supported_dev_types:
            return OperationResult(False, error=f"设备 {device_id} 不支持通过adb截图")

        if not ToolService.is_android_device(device_id):
            return OperationResult(False, error=f"设备 {device_id} 不支持通过adb截图")

        try:
            screenshot_dir = screenshot_path
            device_dir = f"{screenshot_dir}/{device_id}"
            os.makedirs(device_dir, exist_ok=True)

            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            screenshot_file = f"{device_dir}/{device_id}_{timestamp}.jpg"
            remote_file = "/sdcard/screenshot.png"

            # 协议优先：ReadBack ScreenShot（Socket 文件通道，整屏图片直出、免 adb）
            if USE_PROTOCOL_QUERY and ScreenshotService._try_protocol_screenshot(ip, screenshot_file):
                return OperationResult(True, data=screenshot_file.replace('\\', '/'))
            logger.info("设备 %s 协议截图不可用，回落 adb screencap", device_id)

            stdout, stderr, returncode = ToolService.adb_connect(ip)
            if returncode != 0:
                return OperationResult(False, error=f"连接设备失败: {stderr}")

            stdout, stderr, returncode = ToolService.adb_screencap(ip, remote_file)
            if returncode != 0:
                if "device unauthorized" in stderr:
                    try:
                        ToolService.execute_command(device_id, ip, password, "setprop service.adb.tcp.port 5555", ".")
                        ToolService.execute_command(device_id, ip, password, "stop adbd", ".")
                        ToolService.execute_command(device_id, ip, password, "start adbd", ".")
                        time.sleep(3)
                        ToolService.adb_disconnect()
                        time.sleep(1)
                        stdout, stderr, returncode = ToolService.adb_connect(ip)
                        if returncode != 0:
                            return OperationResult(False, error=f"重新连接设备失败: {stderr}")
                        stdout, stderr, returncode = ToolService.adb_screencap(ip, remote_file)
                        if returncode != 0:
                            return OperationResult(False, error=f"执行截图命令失败: {stderr}")
                    except Exception as e:
                        return OperationResult(False, error=f"处理设备授权失败: {str(e)}")
                else:
                    return OperationResult(False, error=f"执行截图命令失败: {stderr}")

            stdout, stderr, returncode = ToolService.adb_pull_file(ip, remote_file, screenshot_file)
            if returncode != 0:
                return OperationResult(False, error=f"拉取截图文件失败: {stderr}")

            ToolService.adb_rm_file(ip, remote_file)
            ToolService.adb_disconnect()

            screenshot_file = screenshot_file.replace('\\', '/')
            return OperationResult(True, data=screenshot_file)
        except Exception as e:
            return OperationResult(False, error=f"截图失败: {str(e)}")
