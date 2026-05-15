from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from .query_thread import QueryThread
from service.tool_service import ToolService


class SerialQueryManager(QThread):
    """串行查询管理器，确保设备逐个依次执行，避免ADB连接冲突"""
    
    result_signal = pyqtSignal(str, dict)
    error_signal = pyqtSignal(str, str)  # (device_id, error_msg)
    finished_signal = pyqtSignal(int)
    
    def __init__(self, devices_info, query_type, control_panel, switch_log_file):
        super().__init__()
        self.devices_info = devices_info  # 设备信息列表: [(device_id, ip, password, system_type), ...]
        self.query_type = query_type
        self.control_panel = control_panel
        self.switch_log_file = switch_log_file
        self.query_count = [0]
        self.is_running = True
        self.mutex = QMutex()
        
    def run(self):
        """逐个执行设备查询/操作"""
        try:
            total_devices = len(self.devices_info)
            
            for idx, (device_id, ip, password, system_type) in enumerate(self.devices_info):
                if not self.is_running:
                    break
                
                print(f"[串行管理器] 开始处理设备 {idx + 1}/{total_devices}: {device_id} ({ip})")
                
                # 确保之前的ADB连接已断开
                try:
                    ToolService.adb_disconnect()
                except Exception as e:
                    print(f"[串行管理器] 断开ADB连接时出错: {e}")
                
                # 短暂延迟确保连接完全断开
                self.msleep(500)
                
                # 创建并执行单个设备的查询
                try:
                    # 直接调用DeviceMonitorService而不是使用单独的线程
                    from business.device_monitor_service import DeviceMonitorService
                    dev_type = device_id.split('-')[0] if '-' in device_id else 'C16H'
                    monitor_service = DeviceMonitorService(dev_type)
                    
                    ToolService.initialize_connection(ip, password)
                    
                    results = {}
                    
                    # 根据查询类型执行对应的操作
                    if self.query_type == "all" or self.query_type == "time":
                        formatted_remote_time, time_diff = monitor_service.get_device_time_info(ip, password, device_id)
                        results['device_time'] = {
                            'formatted_remote_time': formatted_remote_time,
                            'time_diff': time_diff
                        }
                    
                    if self.query_type == "all" or self.query_type == "boot_time":
                        uptime_info = monitor_service.get_uptime_info(ip, password, device_id)
                        results['boot_time'] = uptime_info
                    
                    if self.query_type == "all" or self.query_type == "start_count":
                        start_count = monitor_service.get_start_count(ip, password, device_id)
                        results['start_count'] = start_count

                    if self.query_type == "count_init":
                        count_init = monitor_service.count_init_setting(ip, password, device_id, system_type)
                        results['count_init'] = count_init
                    
                    if self.query_type == "sum_switch":
                        if "Linux" in system_type:
                            path = "/root/Box/project"
                        elif "Android" in system_type:
                            path = "/data"
                        else:
                            raise ValueError("暂不支持此系统类型")
                        switch_time, network_time, success, error_msg = monitor_service.sum_switch_count(ip, password, device_id, path)
                        if success:
                            if self.switch_log_file != None:
                                self.query_count[0] += 1
                                self.switch_log_file.write(f"{device_id},{switch_time},{network_time}\n")
                            results['sum_switch'] = f"{device_id} 当前开关机次数为：{switch_time} 网络开关机次数为：{network_time}"
                        else:
                            results['sum_switch'] = error_msg

                    if self.query_type == "clean_switch":
                        if "Linux" in system_type:
                            path = "/root/Box/project"
                        elif "Android" in system_type:
                            path = "/data"
                        else:
                            raise ValueError("暂不支持此系统类型")
                        success, error_msg = monitor_service.clean_switch_log(ip, password, device_id, path)
                        if success:
                            results['clean_switch'] = f"{device_id} 开关机记录已清除"
                        else:
                            results['clean_switch'] = error_msg

                    if self.query_type == "check_time":
                        results_log = monitor_service.ntptime_checkout_time(ip, password, device_id, system_type)
                        results['check_time'] = results_log

                    if self.query_type == "upgrade_program":
                        results_upgrade_program = monitor_service.upgrade_program(ip, password, device_id, system_type)
                        results['upgrade_program'] = results_upgrade_program

                    if self.query_type == "screenshot":
                        screenshot_result = monitor_service.capture_screenshot(device_id, ip, password, system_type)
                        results['screenshot'] = screenshot_result
                    
                    if self.query_type == "output_log":
                        if "Linux" in system_type:
                            path = "/root/Box/project"
                        elif "Android" in system_type:
                            path = "/data"
                        else:
                            raise ValueError("暂不支持此系统类型")
                        output_success, output_log = monitor_service.switch_log_output(ip, password, device_id, system_type, path)
                        results['output_log'] = output_log
                    
                    # 发送结果信号
                    self.result_signal.emit(device_id, results)
                    
                except Exception as e:
                    error_msg = f"查询设备 {device_id} ({ip}) 时出错: {str(e)}"
                    self.error_signal.emit(device_id, error_msg)
                
                finally:
                    # 确保当前设备操作完成后断开ADB连接
                    try:
                        ToolService.adb_disconnect()
                    except Exception as e:
                        print(f"[串行管理器] 设备 {device_id} 操作完成后断开ADB连接时出错: {e}")
                
                # 设备间延迟，确保连接完全释放
                if idx < total_devices - 1:
                    self.msleep(800)
            
            # 所有设备处理完成
            self.finished_signal.emit(self.query_count[0])
            
        except Exception as e:
            self.error_signal.emit(f"串行查询管理器出错: {str(e)}")
    
    def stop(self):
        """停止执行"""
        self.is_running = False
