from PyQt5.QtCore import QThread, pyqtSignal
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService
from data_models import MonitorConfig
import copy


class MonitorThread(QThread):
    """监控线程类，用于后台执行设备监控任务"""
    update_signal = pyqtSignal(str)
    device_list_signal = pyqtSignal(list)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str, str, str)
    monitor_result_signal = pyqtSignal(dict)

    def __init__(self, config: MonitorConfig):
        """使用 MonitorConfig 数据类简化参数"""
        super().__init__()
        self.dev_type = config.dev_type
        self.delay_time = config.delay_time
        self.monitor_time = config.monitor_time
        self.monitor_boot = config.monitor_boot
        self.selected_devices = config.selected_devices
        self.monitor_start_count = config.monitor_start_count
        self.capture_screenshot = config.capture_screenshot
        self.first_time_data = config.first_time_data
        self.screenshot_path = config.screenshot_path
        self.screenshot_failed_devices = config.screenshot_failed_devices
        self.time_failed_devices = config.time_failed_devices
        self.boot_failed_devices = config.boot_failed_devices
        self.start_count_failed_devices = config.start_count_failed_devices
        self.running = False
        self.monitor_service = None

    def run(self):
        try:
            self.running = True
            self.monitor_service = DeviceMonitorService(self.dev_type)

            # 设置第一次获取的数据作为基准数据
            if self.first_time_data:
                for device_id, data in self.first_time_data.items():
                    if device_id not in self.monitor_service.device_data:
                        self.monitor_service.device_data[device_id] = {}
                    self.monitor_service.device_data[device_id].update(data)

            self.status_signal.emit(f"开始监控 {self.dev_type} 类型设备")

            while self.running:
                self._process_monitor_cycle()

                # 保存设备数据
                if self.monitor_service:
                    from service.file_service import FileService
                    FileService.save_device_data(self.monitor_service.device_data)
                    self.monitor_result_signal.emit(copy.deepcopy(self.monitor_service.device_data))

                # 等待下一轮检查
                self._sleep_with_countdown(self.delay_time)
        except Exception as e:
            self.error_signal.emit(f"监控线程错误: {str(e)}", "系统", "N/A")
        finally:
            self.status_signal.emit("监控已停止")

    def _process_monitor_cycle(self):
        """处理一轮设备监控"""
        devices = self.selected_devices
        for idx, device_info in enumerate(devices):
            if not self.running:
                break
            self._process_one_device(device_info, idx, len(devices))

    def _process_one_device(self, device_info, idx, total):
        """处理单个设备的监控检查"""
        # 解析设备信息
        device_id, ip = self._parse_device_info(device_info)
        if not device_id or not ip:
            return

        try:
            password = ToolService.get_password(device_id)
            ToolService.initialize_connection(ip, password)

            # 判断是否首次获取
            is_first_time = self._is_first_time(device_id)

            # 根据失败列表决定启用哪些检测
            current_monitor_time = self.monitor_time and device_id not in self.time_failed_devices
            current_monitor_boot = self.monitor_boot and device_id not in self.boot_failed_devices
            current_monitor_start_count = (self.monitor_start_count and
                                           device_id not in self.start_count_failed_devices)

            errors = self.monitor_service.check_device_status(
                device_id, ip, password,
                monitor_time=current_monitor_time,
                monitor_boot=current_monitor_boot,
                monitor_start_count=current_monitor_start_count,
            )

            # 截图
            if self.capture_screenshot and not errors and device_id not in self.screenshot_failed_devices:
                self._do_screenshot(device_id, ip, password)

            if errors:
                self._report_errors(device_id, ip, errors)
            else:
                self._report_status(device_id, ip, is_first_time)
        except Exception as e:
            self.error_signal.emit(f"处理设备 {device_id} ({ip}) 时出错: {str(e)}", device_id, ip)

        # 设备间延迟
        if self.running and idx < total - 1:
            self.msleep(100)

    def _parse_device_info(self, device_info):
        """解析设备信息为 (device_id, ip)"""
        if isinstance(device_info, tuple) and len(device_info) >= 2:
            return device_info[0], device_info[1]
        if isinstance(device_info, dict):
            return device_info.get('id', ''), device_info.get('ip', '')
        return '', ''

    def _is_first_time(self, device_id):
        """判断是否首次获取某设备数据"""
        return (device_id not in self.monitor_service.device_data or
                ('initial_boot_time' not in self.monitor_service.device_data.get(device_id, {}) and
                 'initial_card_time' not in self.monitor_service.device_data.get(device_id, {}) and
                 'initial_start_count' not in self.monitor_service.device_data.get(device_id, {})))

    def _do_screenshot(self, device_id, ip, password):
        """执行截图操作"""
        try:
            system_type = "Android"
            screenshot_result = self.monitor_service.capture_screenshot(
                device_id, ip, password, system_type, self.screenshot_path
            )
            if screenshot_result.success:
                self.update_signal.emit(
                    f"设备 {device_id} ({ip}) 截图成功，保存路径: {screenshot_result.data}"
                )
            else:
                self.update_signal.emit(
                    f"设备 {device_id} ({ip}) 截图失败: {screenshot_result.error}"
                )
        except Exception as e:
            self.error_signal.emit(f"设备 {device_id} ({ip}) 截图时出错: {str(e)}", device_id, ip)

    def _report_errors(self, device_id, ip, errors):
        """报告设备错误"""
        error_msg = f"设备 {device_id} ({ip}) 发现错误:\n"
        for error in errors:
            error_msg += f"- 类型: {error['type']}\n  过程: {error['process']}\n  差异: {error['difference']}\n"
        self.error_signal.emit(error_msg, device_id, ip)

    def _report_status(self, device_id, ip, is_first_time):
        """报告设备状态"""
        if is_first_time:
            device_data = self.monitor_service.device_data.get(device_id, {})
            msg = f"设备 {device_id} ({ip}) 第一次获取数据:\n"
            if 'initial_boot_time' in device_data:
                msg += f"- 初始启动时间: {device_data['initial_boot_time']}\n"
            if 'last_uptime' in device_data:
                msg += f"- 运行时长: {device_data['last_uptime']}\n"
            if 'initial_card_time' in device_data:
                msg += f"- 设备时间: {device_data['initial_card_time']}\n"
            if 'initial_time_diff' in device_data:
                msg += f"- 与电脑当前的时间差: {device_data['initial_time_diff']}秒\n"
            if device_id.startswith(('C08L', 'C16L', 'D16')):
                msg += "- 启动次数: 无法获取\n"
            elif 'initial_start_count' in device_data:
                msg += f"- 播放器启动次数: {device_data['initial_start_count']}\n"
            self.update_signal.emit(msg)
        else:
            self.update_signal.emit(f"设备 {device_id} ({ip}) 状态正常")

    def _sleep_with_countdown(self, delay_time):
        """带倒计时的睡眠"""
        for i in range(delay_time, 0, -1):
            if not self.running:
                break
            self.status_signal.emit(f"下一轮检查倒计时: {i-1}秒")
            self.msleep(1000)

    def stop(self):
        self.running = False
        self.wait()
