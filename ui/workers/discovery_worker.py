#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""找卡后台线程：UDP 广播找卡 / 手动定向找卡 → 原始设备行列表。

信号契约与旧的 :class:`ui.reflash_device_threadpool.GetDeviceListThread` 完全一致
（``progress_signal`` / ``raw_list_signal`` / ``error_signal`` / ``finished_signal``），
使 :class:`ui.device_refresh_controller.DeviceRefreshController` 可在新旧通道间透明切换。

输出行格式沿用旧约定（``设备ID IP``，如 ``A3L-1A2B3C 192.168.1.5``），
下游 ``GetDeviceInfoManager`` 无需改动即可继续补全设备详细信息。
"""

import re

from PyQt5.QtCore import QThread, pyqtSignal

from config import UDP_SCAN_TIMEOUT, supported_dev_types
from service.discovery import scan_devices, scan_targets
from service.logging_service import get_logger

logger = get_logger(__name__)


class DiscoveryThread(QThread):
    """异步执行 UDP 找卡的线程，避免阻塞主线程。"""

    progress_signal = pyqtSignal(str)
    raw_list_signal = pyqtSignal(list)
    device_found = pyqtSignal(str, str)
    """发现一台设备即上报 ``(device_id, ip)``，供 UI 即时反馈（详情随后补全）。"""
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, dev_type: str, targets=None, timeout: float = UDP_SCAN_TIMEOUT,
                 parent=None):
        super().__init__(parent)
        self.dev_type = dev_type
        self.targets = targets
        self.timeout = timeout
        self._should_stop = False

    def stop(self) -> None:
        """请求停止扫描（协作式取消，不强制杀线程）。"""
        self._should_stop = True

    def _stop_requested(self) -> bool:
        return self._should_stop

    def _emit_found(self, device_id: str, ip: str) -> None:
        """扫描线程回调：发现即发信号（不阻塞扫描）。"""
        if not self._should_stop:
            self.device_found.emit(device_id, ip)

    def run(self) -> None:
        try:
            if self.targets:
                self.progress_signal.emit(
                    f"正在手动找卡(UDP 定向扫描): {self.targets}")
                pairs = scan_targets(
                    self.targets, on_device=self._emit_found,
                    should_stop=self._stop_requested,
                )
            else:
                self.progress_signal.emit(
                    f"正在扫描设备(UDP 广播找卡, 超时 {self.timeout:.0f} 秒)...")
                pairs = scan_devices(
                    timeout=self.timeout, on_device=self._emit_found,
                    should_stop=self._stop_requested,
                )

            if self._should_stop:
                return

            lines = self._format_lines(pairs)
            self.progress_signal.emit(f"发现 {len(lines)} 台设备")
            self.raw_list_signal.emit(lines)
        except ValueError as exc:
            # 手动找卡的目标 IP 规范非法：给出明确文案，不算致命错误
            error_msg = f"手动找卡目标格式错误: {exc}"
            self.error_signal.emit(error_msg)
            logger.warning("手动找卡目标格式错误: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            error_msg = f"UDP 找卡失败: {exc}"
            self.error_signal.emit(error_msg)
            logger.exception("UDP 找卡失败")
        finally:
            self.finished_signal.emit()

    def _format_lines(self, pairs) -> list:
        """把 ``(device_id, ip)`` 列表按设备类型过滤并格式化为旧约定的行。"""
        pattern = self.dev_type.replace('-', '|')
        regex = re.compile(f'^({pattern})')
        lines = []
        for device_id, ip in pairs:
            head = device_id.split('-')[0]
            if head not in supported_dev_types and device_id not in supported_dev_types:
                continue
            if not regex.match(device_id):
                continue
            lines.append(f"{device_id} {ip}")
        return lines
