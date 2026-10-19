"""设备列表刷新控制器：封装找卡线程与设备信息线程池。"""

from PyQt5.QtCore import QObject, pyqtSignal

from config import USE_UDP_DISCOVERY
from service.logging_service import get_logger
from service.tool_service import TOOLS_DIR
from .reflash_device_threadpool import GetDeviceInfoManager, GetDeviceListThread
from .workers.discovery_worker import DiscoveryThread


class DeviceRefreshController(QObject):
    """负责“刷新设备列表”全流程，UI 只接收信号。"""

    progress = pyqtSignal(str)
    devices_ready = pyqtSignal(list)
    device_found = pyqtSignal(str, str)
    """找卡过程中「发现即上报」``(device_id, ip)``（仅新 UDP 通道提供）。"""
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._manager = None
        self._devices = []
        self._dev_type = ''
        self._logger = get_logger(__name__)

    def refresh(self, dev_type: str, targets=None) -> None:
        """启动一次设备扫描；重复调用会先停止上一轮。

        Args:
            dev_type: 设备类型前缀（如 ``A3L`` / ``A-B-C-D-H``）。
            targets: 手动找卡目标（单 IP / 区间 / CIDR / 混合）。
                ``None`` 或空表示全网找卡（UDP 广播 / DeviceId.exe）。
        """
        self.stop()
        self._dev_type = dev_type
        self._devices = []

        self._thread = self._create_thread(dev_type, targets)
        self._thread.progress_signal.connect(self.progress)
        self._thread.raw_list_signal.connect(self._on_raw_list)
        # 新 UDP 通道支持「发现即上报」，用于 UI 即时反馈（旧 DeviceId.exe 通道没有）
        found_signal = getattr(self._thread, 'device_found', None)
        if found_signal is not None:
            found_signal.connect(self.device_found)
        self._thread.error_signal.connect(self._on_error)
        self._thread.finished_signal.connect(self._on_thread_finished)
        self._thread.start()

    def _create_thread(self, dev_type: str, targets):
        """按找卡开关选择新（UDP）或旧（DeviceId.exe）通道；手动找卡仅新通道支持。"""
        if USE_UDP_DISCOVERY:
            return DiscoveryThread(dev_type=dev_type, targets=targets or None, timeout=60)

        if targets:
            self._logger.warning(
                "已配置手动找卡目标 %s，但当前使用 DeviceId.exe 通道，目标被忽略", targets)
        return GetDeviceListThread(dev_type=dev_type, tools_dir=TOOLS_DIR, timeout=60)

    def stop(self) -> None:
        """停止扫描与线程池。"""
        self._stop_manager()
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait()
        self._thread = None

    def _stop_manager(self) -> None:
        if not self._manager:
            return
        try:
            self._manager.check_timer.stop()
        except Exception:
            pass
        try:
            self._manager.taskCompleted.disconnect()
        except Exception:
            pass
        try:
            self._manager.allTasksCompleted.disconnect()
        except Exception:
            pass
        self._manager = None

    def _on_raw_list(self, raw_lines) -> None:
        if not raw_lines:
            self._devices = []
            self.devices_ready.emit([])
            return

        self.progress.emit(f"开始获取 {len(raw_lines)} 台设备的详细信息...")
        pattern = self._dev_type.replace('-', '|')
        self._manager = GetDeviceInfoManager(
            pattern, max_workers=4, queue_size=len(raw_lines)
        )
        self._manager.taskCompleted.connect(self._on_device_info)
        self._manager.allTasksCompleted.connect(self._on_all_tasks_completed)

        for line in raw_lines:
            self._manager.submit_task(line)

    def _on_device_info(self, device_info) -> None:
        if device_info:
            self._devices.append(device_info)

    def _on_all_tasks_completed(self) -> None:
        self._stop_manager()
        self.devices_ready.emit(list(self._devices))

    def _on_error(self, error_msg) -> None:
        self._logger.error("设备查找失败: %s", error_msg)
        self.failed.emit(error_msg)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self.finished.emit()
