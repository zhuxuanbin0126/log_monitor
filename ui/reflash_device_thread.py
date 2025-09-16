from PyQt5.QtCore import QThread, pyqtSignal
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService

class ReflashThread(QThread):
    error_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str)

    def __init__(self,control_panel,update_device_list,log):
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
            
            # 更新设备列表
            self.update_device_list(devices)
            
            # 更新刷新状态标签
            self.control_panel.update_refresh_status(f"当前设备数: {len(devices)}")
            
            self.success_signal.emit(f"设备列表已刷新，共 {len(devices)} 台设备")
        except Exception as e:
            self.error_signal.emit(f"刷新设备列表失败: {str(e)}")
        self.control_panel.refresh_button.setEnabled(True)