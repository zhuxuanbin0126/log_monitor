from PyQt5.QtCore import QThread, pyqtSignal
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService

class QueryThread(QThread):
    """查询线程类，用于执行单个设备的查询任务"""
    result_signal = pyqtSignal(str, dict)
    error_signal = pyqtSignal(str)
    end_signal = pyqtSignal(int)
    
    def __init__(self, device_id, ip, password, query_type, control_panel, system_type, switch_log_file, query_count, custom_file_paths=None):
        super().__init__()
        self.device_id = device_id
        self.ip = ip
        self.password = password
        self.query_type = query_type
        self.dev_type = device_id.split('-')[0] if '-' in device_id else 'C16H'
        self.control_panel = control_panel
        self.system_type = system_type
        self.switch_log_file = switch_log_file
        self.query_count = query_count
        self.custom_file_paths = custom_file_paths  # 自定义文件路径 {文件名: 本地路径}

    def run(self):
        try:
            monitor_service = DeviceMonitorService(self.dev_type)
            ToolService.initialize_connection(self.ip, self.password)
            
            results = {}
            
            if self.query_type == "all" or self.query_type == "time":
                formatted_remote_time, time_diff = monitor_service.get_device_time_info(self.ip, self.password, self.device_id)
                results['device_time'] = {
                    'formatted_remote_time': formatted_remote_time,
                    'time_diff': time_diff
                }
            
            if self.query_type == "all" or self.query_type == "boot_time":
                uptime_info = monitor_service.get_uptime_info(self.ip, self.password, self.device_id)
                results['boot_time'] = uptime_info
            
            if self.query_type == "all" or self.query_type == "start_count":
                start_count = monitor_service.get_start_count(self.ip, self.password, self.device_id)
                results['start_count'] = start_count

            if  self.query_type == "count_init":
                count_init = monitor_service.count_init_setting(
                    self.ip, self.password, self.device_id, self.system_type,
                    custom_file_paths=self.custom_file_paths
                )
                results['count_init'] = count_init
            
            if self.query_type == "sum_switch":
                sys_type = self.system_type.lower() if self.system_type else ""
                if "linux" in sys_type:
                    path = "/root/Box/project"
                elif "android" in sys_type:
                    path = "/data"
                else:
                    path = "/root/Box/project"
                switch_time, network_time, success, error_msg = monitor_service.sum_switch_count(self.ip, self.password, self.device_id, path)
                if success:
                    if self.switch_log_file != None:
                        self.query_count[0] += 1
                        self.switch_log_file.write(f"{self.device_id},{switch_time},{network_time}\n")
                    results['sum_switch'] = f"{self.device_id} 当前开关机次数为：{switch_time} 网络开关机次数为：{network_time}"
                else:
                    results['sum_switch'] = error_msg

            if self.query_type == "clean_switch":
                sys_type = self.system_type.lower() if self.system_type else ""
                if "linux" in sys_type:
                    path = "/root/Box/project"
                elif "android" in sys_type:
                    path = "/data"
                else:
                    path = "/root/Box/project"
                success, error_msg = monitor_service.clean_switch_log(self.ip, self.password, self.device_id, path)
                if success:
                    results['clean_switch'] = f"{self.device_id} 开关机记录已清除"
                else:
                    results['clean_switch'] = error_msg

            if self.query_type == "check_time":
                results_log = monitor_service.ntptime_checkout_time(self.ip, self.password, self.device_id, self.system_type)
                results['check_time'] = results_log

            if self.query_type == "upgrade_program":
                results_upgrade_program = monitor_service.upgrade_program(
                    self.ip, self.password, self.device_id, self.system_type,
                    custom_file_paths=self.custom_file_paths
                )
                results['upgrade_program'] = results_upgrade_program

            if self.query_type == "screenshot":
                screenshot_result = monitor_service.capture_screenshot(self.device_id, self.ip, self.password, self.system_type)
                results['screenshot'] = screenshot_result
            
            if self.query_type == "output_log":
                sys_type = self.system_type.lower() if self.system_type else ""
                if "linux" in sys_type:
                    path = "/root/Box/project"
                elif "android" in sys_type:
                    path = "/data"
                else:
                    path = "/root/Box/project"
                output_success, output_log = monitor_service.switch_log_output(self.ip, self.password, self.device_id, self.system_type, path)
                results['output_log'] = output_log

            self.result_signal.emit(self.device_id, results)
            self.end_signal.emit(self.query_count[0])
        except Exception as e:
            self.error_signal.emit(f"查询设备 {self.device_id} ({self.ip}) 时出错: {str(e)}")