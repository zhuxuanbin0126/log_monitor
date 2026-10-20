"""设备列表刷新控制器：封装找卡线程与设备信息线程池。

**流水线设计（关键）**：找卡层「发现即上报」的 ``(device_id, ip)`` 到达时，
控制器**立即把该台设备提交给信息补全线程池**，不再等 UDP 扫描跑完 6s 收敛窗口。
因此表格是「发现一台、补全一台、显示一台」，而不是「等 6s 再开始取信息」。
扫描结束（``raw_list_signal``）只做**收尾补齐**（提交遗漏项并声明提交完毕）。

信息补全与扫描并行，故新增 ``_submit_done`` 闸门：只有「扫描已结束且补全队列跑空」
才算整体完成，避免扫描途中的瞬时空闲被误判为收尾。
"""

import re

from PyQt5.QtCore import QObject, pyqtSignal

from config import USE_UDP_DISCOVERY, supported_dev_types
from service.logging_service import get_logger
from service.tool_service import TOOLS_DIR
from .reflash_device_threadpool import GetDeviceInfoManager, GetDeviceListThread
from .workers.discovery_worker import DiscoveryThread

INFO_MAX_WORKERS = 8
"""信息补全线程数：协议取数是一个往返的轻量操作，可高于旧的 4"""

INFO_QUEUE_SIZE = 512
"""信息补全任务队列上限：几十台设备也不会丢任务"""


class DeviceRefreshController(QObject):
    """负责“刷新设备列表”全流程，UI 只接收信号。"""

    progress = pyqtSignal(str)
    devices_ready = pyqtSignal(list)
    device_found = pyqtSignal(str, str)
    """找卡过程中「发现即上报」``(device_id, ip)``（仅新 UDP 通道提供）。"""
    device_row_updated = pyqtSignal(dict)
    """单台设备详情补全完成即上报（用于**增量**更新表格行，不必等全部设备）。"""
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._manager = None
        self._devices = []
        self._dev_type = ''
        self._submitted = set()
        self._submit_done = False
        self._incremental = False
        self._stopped = False
        self._logger = get_logger(__name__)

    # ---------------------------------------------------------------- 全量刷新

    def refresh(self, dev_type: str, targets=None) -> None:
        """启动一次设备扫描；重复调用会先停止上一轮。

        Args:
            dev_type: 设备类型前缀（如 ``A3L`` / ``A-B-C-D-H``）。
            targets: 手动找卡目标（单 IP / 区间 / CIDR / 混合）。
                ``None`` 或空表示全网找卡（UDP 广播 / DeviceId.exe）。
        """
        self.stop()
        self._stopped = False
        self._dev_type = dev_type
        self._devices = []
        self._submitted = set()
        self._submit_done = False
        self._incremental = False

        # 信息补全线程池**先建好**：这样扫描过程中「发现一台就能立刻提交一台」
        self._start_manager()

        self._thread = self._create_thread(dev_type, targets)
        self._thread.progress_signal.connect(self.progress)
        self._thread.raw_list_signal.connect(self._on_raw_list)
        found_signal = getattr(self._thread, 'device_found', None)
        if found_signal is not None:
            found_signal.connect(self._on_device_found)
        self._thread.error_signal.connect(self._on_error)
        self._thread.finished_signal.connect(self._on_thread_finished)
        self._thread.start()

    def fetch_device_info(self, pairs) -> None:
        """**增量**补全给定设备的信息（心跳发现新设备时用）。

        只逐台上报 ``device_row_updated``，**不**做全表重建、也**不**重新扫描。
        """
        if self.is_busy():
            self._logger.info("已有找卡/补全任务在跑，跳过本次增量补全")
            return
        pairs = [(device_id, ip) for device_id, ip in pairs if self._accepts_device(device_id)]
        if not pairs:
            return

        self._stopped = False
        self._devices = []
        self._submitted = set()
        self._submit_done = True          # 无扫描阶段，只有补全
        self._incremental = True
        self._start_manager()
        self.progress.emit(f"增量补全 {len(pairs)} 台新设备的信息...")
        for device_id, ip in pairs:
            self._submit_line(f"{device_id} {ip}")

    def _create_thread(self, dev_type: str, targets):
        """按找卡开关选择新（UDP）或旧（DeviceId.exe）通道；手动找卡仅新通道支持。"""
        if USE_UDP_DISCOVERY:
            return DiscoveryThread(dev_type=dev_type, targets=targets or None, timeout=60)

        if targets:
            self._logger.warning(
                "已配置手动找卡目标 %s，但当前使用 DeviceId.exe 通道，目标被忽略", targets)
        return GetDeviceListThread(dev_type=dev_type, tools_dir=TOOLS_DIR, timeout=60)

    def stop(self) -> None:
        """停止扫描与线程池（关窗时调用：必须排空后台任务后才能真正释放）。"""
        self._stopped = True
        self._stop_manager()
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait()
        self._thread = None
        self._submit_done = False

    def is_busy(self) -> bool:
        """当前是否有找卡/补全信息在进行中（用于避免重复触发刷新）。"""
        thread_running = self._thread is not None and self._thread.isRunning()
        return bool(thread_running or self._manager is not None)

    # ---------------------------------------------------------------- 内部

    def _start_manager(self) -> None:
        self._manager = GetDeviceInfoManager(
            self._dev_type.replace('-', '|'),
            max_workers=INFO_MAX_WORKERS, queue_size=INFO_QUEUE_SIZE)
        self._manager.taskCompleted.connect(self._on_device_info)
        self._manager.allTasksCompleted.connect(self._on_all_tasks_completed)

    def _stop_manager(self) -> None:
        manager = self._manager
        if not manager:
            return
        self._manager = None
        # **先排空再断开**：后台任务仍在跑时直接丢弃 manager，
        # 会让它们向已释放的 QObject 发信号 → 关窗瞬间进程崩溃（0xC0000005）
        try:
            manager.stop(5000)
        except Exception:  # pylint: disable=broad-except
            pass
        for signal in (manager.taskCompleted, manager.allTasksCompleted):
            try:
                signal.disconnect()
            except Exception:  # pylint: disable=broad-except
                pass

    def _accepts_device(self, device_id: str) -> bool:
        """与找卡层同口径过滤：型号受支持且匹配当前设备类型。"""
        head = device_id.split('-')[0]
        if head not in supported_dev_types and device_id not in supported_dev_types:
            return False
        return bool(re.match(f"^({self._dev_type.replace('-', '|')})", device_id))

    def _submit_line(self, line: str) -> None:
        """提交单台设备的信息补全（按设备ID去重，避免与扫描结果重复提交）。"""
        parts = line.split()
        if not parts:
            return
        device_id = parts[0]
        if device_id in self._submitted or self._manager is None:
            return
        self._submitted.add(device_id)
        self._manager.submit_task(line)

    def _on_device_found(self, device_id: str, ip: str) -> None:
        """扫描中发现一台设备：**立即提交信息补全**，并转发给 UI 做占位行。"""
        self.device_found.emit(device_id, ip)
        if self._accepts_device(device_id):
            self._submit_line(f"{device_id} {ip}")

    def _on_raw_list(self, raw_lines) -> None:
        """扫描结束：补齐遗漏项并声明「提交完毕」。"""
        raw_lines = raw_lines or []
        self.progress.emit(f"扫描结束，正在补齐 {len(raw_lines)} 台设备的信息...")
        for line in raw_lines:
            self._submit_line(line)
        self._submit_done = True

    def _on_device_info(self, device_info) -> None:
        if self._stopped:
            return
        if device_info:
            self._devices.append(device_info)
            # 增量更新：每台设备详情到位就立即上报，不必等 allTasksCompleted
            self.device_row_updated.emit(device_info)

    def _on_all_tasks_completed(self) -> None:
        # 扫描未结束时的瞬时空闲不算收尾（否则会拿到不完整的设备列表）
        if self._stopped or not self._submit_done:
            return
        self._stop_manager()
        if self._incremental:
            self._incremental = False
            return
        self.devices_ready.emit(list(self._devices))

    def _on_error(self, error_msg) -> None:
        self._logger.error("设备查找失败: %s", error_msg)
        self.failed.emit(error_msg)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self.finished.emit()
