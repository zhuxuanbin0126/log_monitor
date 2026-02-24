from PyQt5.QtCore import QThread, pyqtSignal
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService

class MonitorThread(QThread):
    """监控线程类，用于后台执行设备监控任务"""
    update_signal = pyqtSignal(str)
    device_list_signal = pyqtSignal(list)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str, str, str)  # 修改为包含device_id和ip参数
    monitor_result_signal = pyqtSignal(dict)
    
    def __init__(self, dev_type, delay_time, selected_devices, monitor_time=True, monitor_boot=True, monitor_start_count=True, capture_screenshot=False, first_time_data=None, screenshot_path="./screenshot", screenshot_failed_devices=None, time_failed_devices=None, boot_failed_devices=None, start_count_failed_devices=None):
        super().__init__()
        self.dev_type = dev_type
        self.delay_time = delay_time
        self.monitor_time = monitor_time
        self.monitor_boot = monitor_boot
        self.selected_devices = selected_devices
        self.monitor_start_count = monitor_start_count
        self.capture_screenshot = capture_screenshot
        self.first_time_data = first_time_data or {}
        self.screenshot_path = screenshot_path
        self.screenshot_failed_devices = screenshot_failed_devices or []
        self.time_failed_devices = time_failed_devices or []
        self.boot_failed_devices = boot_failed_devices or []
        self.start_count_failed_devices = start_count_failed_devices or []
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
                    # 更新设备数据，确保包含基准数据
                    self.monitor_service.device_data[device_id].update(data)
            
            self.status_signal.emit(f"开始监控 {self.dev_type} 类型设备")
            
            while self.running:
                # 获取设备列表
                devices = self.selected_devices
                
                has_new_errors = False
                
                # 处理每个设备
                for device_info in devices:
                    try:
                        if isinstance(device_info, tuple):
                            # 支持二元组格式 (device_id, ip) 或多元组
                            if len(device_info) >= 2:
                                device_id, ip = device_info[0], device_info[1]
                            else:
                                continue
                        elif isinstance(device_info, dict):
                            device_id = device_info.get('id', '')
                            ip = device_info.get('ip', '')
                            if not device_id or not ip:
                                continue
                        else:
                            continue
                        
                        password = ToolService.get_password(device_id)
                        ToolService.initialize_connection(ip, password)
                        
                        # 检查是否是第一次获取该设备信息（在调用check_device_status前先判断）
                        is_first_time = device_id not in self.monitor_service.device_data or \
                                      ('initial_boot_time' not in self.monitor_service.device_data.get(device_id, {}) and \
                                       'initial_card_time' not in self.monitor_service.device_data.get(device_id, {}) and \
                                       'initial_start_count' not in self.monitor_service.device_data.get(device_id, {}))
                        
                        # 根据设备是否在失败列表中来决定是否启用对应的检测项
                        current_monitor_time = self.monitor_time and device_id not in self.time_failed_devices
                        current_monitor_boot = self.monitor_boot and device_id not in self.boot_failed_devices
                        current_monitor_start_count = self.monitor_start_count and device_id not in self.start_count_failed_devices
                        
                        # 检查设备状态，传递监控选项
                        errors = self.monitor_service.check_device_status(
                            device_id, ip, password, 
                            monitor_time=current_monitor_time, 
                            monitor_boot=current_monitor_boot, 
                            monitor_start_count=current_monitor_start_count
                        )
                        
                        # 如果需要截图且设备状态正常，执行截图操作
                        if self.capture_screenshot and not errors and device_id not in self.screenshot_failed_devices:
                            try:
                                # 获取设备系统类型
                                # 这里简化处理，假设为Android系统
                                system_type = "Android"
                                
                                # 执行截图
                                screenshot_result = self.monitor_service.capture_screenshot(
                                    device_id, ip, password, system_type, self.screenshot_path
                                )
                                
                                # 发送截图结果信号
                                if screenshot_result and not screenshot_result.startswith("设备"):
                                    self.update_signal.emit(f"设备 {device_id} ({ip}) 截图成功，保存路径: {screenshot_result}")
                                else:
                                    self.update_signal.emit(f"设备 {device_id} ({ip}) 截图失败: {screenshot_result}")
                            except Exception as e:
                                self.error_signal.emit(f"设备 {device_id} ({ip}) 截图时出错: {str(e)}", device_id, ip)
                        
                        if errors:
                            # 以check_device_status的errors = []的拼接结果格式输出
                            error_msg = f"设备 {device_id} ({ip}) 发现错误:\n"
                            for error in errors:
                                error_msg += f"- 类型: {error['type']}\n  过程: {error['process']}\n  差异: {error['difference']}\n"
                            # 发送错误信号时携带device_id和ip
                            self.error_signal.emit(error_msg, device_id, ip)
                        else:
                            if is_first_time:
                                # 第一次获取，显示控制卡的各个指标信息（而不是简单的"状态正常"）
                                device_data = self.monitor_service.device_data.get(device_id, {})
                                first_time_msg = f"设备 {device_id} ({ip}) 第一次获取数据:\n"
                                
                                # 显示初始启动时间（如果有）
                                if 'initial_boot_time' in device_data:
                                    first_time_msg += f"- 初始启动时间: {device_data['initial_boot_time']}\n"
                                if 'last_uptime' in device_data:
                                    first_time_msg += f"- 运行时长: {device_data['last_uptime']}\n"
                                
                                # 显示设备时间信息（如果有）
                                if 'initial_card_time' in device_data:
                                    first_time_msg += f"- 设备时间: {device_data['initial_card_time']}\n"
                                if 'initial_time_diff' in device_data:
                                    first_time_msg += f"- 与电脑当前的时间差: {device_data['initial_time_diff']}秒\n"
                                
                                # 显示启动次数（如果有且不是特殊设备）
                                if device_id.startswith(('C08L', 'C16L', 'D16')):
                                    first_time_msg += f"- 启动次数: 无法获取\n"
                                elif 'initial_start_count' in device_data:
                                    first_time_msg += f"- 播放器启动次数: {device_data['initial_start_count']}\n"
                                
                                self.update_signal.emit(first_time_msg)
                            else:
                                # 非第一次获取且无错误，显示状态正常
                                self.update_signal.emit(f"设备 {device_id} ({ip}) 状态正常")
                    except Exception as e:
                        error_msg = f"处理设备 {device_id} ({ip}) 时出错: {str(e)}"
                        self.error_signal.emit(error_msg, device_id, ip)
                    
                    # 在相邻设备查询之间添加延迟，避免请求过于密集
                    if self.running and device_info != devices[-1]:  # 不是最后一个设备时才添加延迟
                        self.msleep(100)  # 100毫秒延迟)
                
                # 保存设备数据
                if self.monitor_service:
                    from service.file_service import FileService
                    FileService.save_device_data(self.monitor_service.device_data)
                    
                    # 发送监控结果信号
                    self.monitor_result_signal.emit(self.monitor_service.device_data)
                
                # 等待下一轮检查
                for i in range(self.delay_time, 0, -1):
                    if not self.running:
                        break
                    self.status_signal.emit(f"下一轮检查倒计时: {i-1}秒")
                    self.msleep(1000)
        except Exception as e:
            self.error_signal.emit(f"监控线程错误: {str(e)}", "系统", "N/A")
        finally:
            self.status_signal.emit("监控已停止")
    
    def stop(self):
        self.running = False
        self.wait()