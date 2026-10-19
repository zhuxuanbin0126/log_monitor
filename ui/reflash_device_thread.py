"""
已弃用模块 (DEPRECATED)

该类已被 ui/reflash_device_threadpool.py 中的 GetDeviceListThread 替代。
保留此文件仅为向后兼容，请勿在新代码中使用。将在后续版本中移除。
"""

import warnings
from PyQt5.QtCore import QThread, pyqtSignal
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService


class ReflashThread(QThread):
    """[已弃用] 旧版刷新设备列表线程，请使用 reflash_device_threadpool.GetDeviceListThread"""

    error_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str)

    def __init__(self, control_panel, update_device_list, log):
        warnings.warn(
            "ReflashThread is deprecated. Use GetDeviceListThread from "
            "reflash_device_threadpool instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__()
        self.control_panel = control_panel
        self.update_device_list = update_device_list
        self.log = log

    def run(self):
        """刷新设备列表"""
        from service.tool_service import ToolService
        try:
            # 获取当前设备类型
            dev_type = self.control_panel.dev_type

            # 使用ToolService获取设备列表
            devices = ToolService.get_device_list(dev_type)

            # 通过信号更新（而非直接操作 UI）
            self.update_device_list(devices)
            self.success_signal.emit(f"设备列表已刷新，共 {len(devices)} 台设备")
        except Exception as e:
            self.error_signal.emit(f"刷新设备列表失败: {str(e)}")
