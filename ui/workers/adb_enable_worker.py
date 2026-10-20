#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""开启 ADB 后台线程：对选中的 Android 设备下发协议 ``Set Development``。

发送的报文与官方消息模板一致：

    {"ask": {"Development": {"adbMode": "usb,tcp", "adbTimer": 0,
                             "omsEnable": false, "omsTimer": 0}},
     "module": "Set", "tag": "Development", ...}

``adbTimer`` 为 0 表示**永久开启**；``kPermissionDenied`` 时由
:func:`service.protocol.set_query.set_development` 自动走 KeyEvent 解锁后重发。
"""

from PyQt5.QtCore import QThread, pyqtSignal

from service.logging_service import get_logger
from service.protocol.set_query import ADB_MODE_BOTH, ADB_TIMER_ON, set_development

logger = get_logger(__name__)


class EnableAdbWorker(QThread):
    """逐台下发 ``Set Development`` 开启 Android 设备的 usb+tcp ADB（永久）。"""

    progress_signal = pyqtSignal(str)
    device_done = pyqtSignal(str, bool, str)   # device_id, 是否成功, 说明
    finished_signal = pyqtSignal(int, int)     # 成功数, 总数

    def __init__(self, devices, parent=None):
        """
        Args:
            devices: ``[(device_id, ip), ...]``（调用方需自行筛出 Android 设备）
        """
        super().__init__(parent)
        self._devices = list(devices)
        self._should_stop = False

    def stop(self) -> None:
        """请求停止（协作式，当前设备处理完即退出）。"""
        self._should_stop = True

    @property
    def was_stopped(self) -> bool:
        """是否因「中断任务」提前退出（供 UI 汇总说明，区分于真正的失败）。"""
        return self._should_stop

    def run(self) -> None:
        ok_count = 0
        total = len(self._devices)
        for device_id, ip in self._devices:
            if self._should_stop:
                break
            self.progress_signal.emit(f"正在开启 {device_id} ({ip}) 的 ADB ...")
            try:
                ok, message = set_development(ip, ADB_MODE_BOTH, ADB_TIMER_ON)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("设备 %s 协议开启 ADB 异常: %s", device_id, exc)
                ok, message = False, f"协议异常: {exc}"
            if ok:
                ok_count += 1
            self.device_done.emit(device_id, ok, message)
        self.finished_signal.emit(ok_count, total)
