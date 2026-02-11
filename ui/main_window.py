import time
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer
from datetime import datetime
import os
import shutil
import re

from .base_window import BaseWindow
from .control_panel import ControlPanel
from .device_list_view import DeviceListView
from .reflash_device_threadpool import GetDeviceInfoManager
from .result_display_view import ResultDisplayView
from .monitor_thread import MonitorThread
from .query_thread import QueryThread
from .reflash_device_thread import ReflashThread

from service.tool_service import ToolService
from service.file_service import FileService
from service.data_processing_service import DataProcessingService
from config import get_base_dir, supported_dev_types


class MainWindow(BaseWindow):
    """主窗口类，作为控制器协调各个组件的工作"""
    
    def __init__(self):
        super().__init__()
        
        # 初始化变量
        self.devices = None
        self.monitor_thread = None
        self.query_threads = []
        self.dev_type = ControlPanel().dev_type
        self.notepad_process = None  # 用于跟踪记事本进程
        self.excel_file = None  # 用于存储当前使用的Excel文件名
        self.Manager = None
        
        # 初始化日志文件
        base_dir = get_base_dir(self.dev_type)
        FileService.init_log_files(base_dir)
        
        # 自动刷新设备列表的定时器
        # self.auto_refresh_timer = QTimer(self)
        # self.auto_refresh_timer.setInterval(60000)  # 默认60秒刷新一次
        # self.auto_refresh_timer.timeout.connect(self.refresh_device_list)
        # self.auto_refresh_timer.start()  # 启动自动刷新
        
        # 创建并初始化各个组件
        self.init_components()
        
        # 连接信号和槽
        self.connect_signals_slots()
        
        # 完成布局
        self.finalize_layout()
        
        self.find_dev_Thread = None

        # self.refresh_device_list()

    def init_components(self):
        """初始化各个组件"""
        # 创建控制面板
        self.control_panel = ControlPanel()
        
        # 创建设备列表视图
        self.device_list_view = DeviceListView()
        
        # 创建结果显示视图
        self.result_display_view = ResultDisplayView()
        
        # 添加控制面板到主布局
        self.main_layout.addWidget(self.control_panel)
        
        # 添加设备列表和结果显示到分割器
        self.add_widget_to_splitter(self.device_list_view)
        self.add_widget_to_splitter(self.result_display_view)
        
    def connect_signals_slots(self):
        """连接信号与槽"""
        # 控制面板信号连接
        self.control_panel.refresh_button.clicked.connect(self.refresh_device_list)
        self.control_panel.dev_type_combo.currentTextChanged.connect(self.on_dev_type_changed)
        # 修复：连接到正确的start_monitor_clicked信号，而不是按钮的clicked信号
        self.control_panel.start_monitor_clicked.connect(self.start_monitor)
        self.control_panel.stop_monitor_button.clicked.connect(self.stop_monitor)
        # 添加查询信号连接
        self.control_panel.query_selected_clicked.connect(self.query_selected)
        
        # 设备列表信号连接
        self.device_list_view.device_selected.connect(self.on_device_selected)
        self.device_list_view.device_list_updated.connect(self.on_device_list_updated)
        
        # 结果显示信号连接
        self.result_display_view.clear_log_clicked.connect(self.on_clear_log)

    def handle_error(self, error_msg, device_id, ip):
        """处理监控线程发送的错误信号"""
        # 优化错误消息显示
        optimized_msg = self._optimize_error_message(error_msg)
        self.log(optimized_msg, is_error=True)
        # 调用同名的write_to_error_log方法
        self.write_to_error_log(error_msg, device_id=device_id, ip=ip)
        # 写入错误日志后自动打开记事本
        self.open_error_log_in_notepad()
    
    def write_to_error_log(self, message=None, device_id=None, ip=None, password=None, errors=None):
        """写入错误日志到文件"""
        try:
            # 1. 提取和准备错误信息
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 从错误消息中提取设备信息（如果未直接提供）
            if not device_id or not ip:
                extracted_id, extracted_ip = DataProcessingService.extract_device_info(message)
                device_id = device_id or extracted_id
                ip = ip or extracted_ip

            # 2. 确定错误类型
            error_type = self._determine_error_type(message, errors)

            # 3. 构建错误详情
            error_details = self._build_error_details(message, errors)

            # 4. 创建格式化的错误信息
            error_info = {
                "时间": current_time,
                "设备ID": device_id,
                "IP地址": ip,
                "错误类型": error_type,
                "错误详情": error_details
            }

            # 写入错误日志
            from service.file_service import FileService
            FileService.write_error_log(error_info)

        except Exception as e:
            # 避免递归调用 log 和 write_to_error_log
            print(f"写入错误日志失败: {str(e)}")

    def _determine_error_type(self, message, errors):
        """确定错误类型"""
        if errors and isinstance(errors, list):
            # 从结构化错误中获取类型
            return next((err.get('type', '设备异常') for err in errors if isinstance(err, dict)), '设备异常')
        
        # 从消息文本判断错误类型
        error_patterns = [
            (r'时间[差异]|同步|时钟', '时间同步异常'),
            (r'启动次数|重启', '启动次数异常'),
            (r'离线|断开|连接失败', '设备离线'),
            (r'超时|timeout', '通信超时'),
            (r'认证|密码|登录', '认证失败')
        ]
        
        for pattern, err_type in error_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return err_type
                
        return '设备异常'

    def _optimize_error_message(self, message):
        """优化错误消息显示，使其更友好"""
        # 处理密码认证失败的错误消息
        if "Access denied" in message and "password was not accepted" in message:
            return "设备通信异常: 密码认证失败，请检查设备密码配置"
        
        # 处理其他常见的错误消息
        error_patterns = [
            (r'获取启动时间失败', '设备启动时间获取失败'),
            (r'获取设备时间失败', '设备时间获取失败'),
            (r'获取运行时长失败', '设备运行时长获取失败'),
            (r'获取启动次数失败', '设备启动次数获取失败'),
            (r'超时', '设备通信超时'),
            (r'连接失败', '设备连接失败'),
        ]
        
        for pattern, replacement in error_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        
        # 默认返回原消息
        return message

    def _build_error_details(self, message, errors):
        """构建错误详情"""
        if errors:
            if isinstance(errors, list):
                return errors
            if isinstance(errors, dict):
                return [errors]
                
        # 创建基本错误详情
        return [{
            'type': self._determine_error_type(message, None),
            'process': '错误处理',
            'difference': message
        }]

    def on_dev_type_changed(self, text):
        """设备类型改变时的处理"""
        self.dev_type = text
        # 重新初始化日志文件
        base_dir = get_base_dir(self.dev_type)
        FileService.init_log_files(base_dir)
        # 重新刷新设备列表
        self.refresh_device_list()
    
    def start_monitor(self, delay_time, monitor_time, monitor_boot, monitor_start_count, capture_screenshot=False, clear_history=False, screenshot_path="./screenshot"):
        """开始监控"""
        if len(self.device_list_view.get_devices()) == 0:
            self.log("请先刷新设备列表")
            return

        selected_devices = self.device_list_view.get_selected_devices_info()
        if not selected_devices:
            self.log("请先选择要监控的设备")
            return

        if self.monitor_thread and self.monitor_thread.isRunning():
            self.log("监控已经在运行中")
            return
        
        # 处理清除历史数据
        if clear_history:
            self.log("开始清除历史监控数据...")
            self.clear_history_data()
            self.log("历史监控数据清除完成")
        
        # 第一次获取设备信息，检测设备在线情况和可执行性
        self.log("开始第一次获取设备信息，检测设备在线情况...")
        
        # 创建监控服务实例
        from business.device_monitor_service import DeviceMonitorService
        monitor_service = DeviceMonitorService(self.dev_type)
        
        # 存储第一次获取的设备信息
        first_time_data = {}
        online_count = 0
        offline_count = 0
        error_count = 0
        
        # 存储截图失败的设备
        screenshot_failed_devices = []
        
        # 存储各项检测失败的设备
        time_failed_devices = []
        boot_failed_devices = []
        start_count_failed_devices = []
        
        # 遍历所有选中的设备
        for device_info in selected_devices:
            device_id = device_info['id']
            ip = device_info['ip']
            password = device_info['password']
            
            try:
                # 检查设备状态
                errors = monitor_service.check_device_status(
                    device_id, ip, password, 
                    monitor_time=monitor_time, 
                    monitor_boot=monitor_boot, 
                    monitor_start_count=monitor_start_count
                )
                
                # 保存第一次获取的数据
                if device_id in monitor_service.device_data:
                    first_time_data[device_id] = monitor_service.device_data[device_id].copy()
                    
                    # 检查各项数据是否获取成功
                    device_data = monitor_service.device_data[device_id]
                    
                    # 检查设备时间获取情况
                    if monitor_time and ('initial_card_time' not in device_data or device_data.get('initial_card_time') == 'N/A'):
                        time_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 设备时间获取失败")
                    
                    # 检查启动时间获取情况
                    if monitor_boot and ('initial_boot_time' not in device_data or device_data.get('initial_boot_time') == 'N/A'):
                        boot_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 启动时间获取失败")
                    
                    # 检查启动次数获取情况
                    if monitor_start_count and ('initial_start_count' not in device_data or device_data.get('initial_start_count') == 'N/A'):
                        start_count_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 启动次数获取失败")
                
                # 统计设备状态
                if errors:
                    error_count += 1
                    self.log(f"设备 {device_id} ({ip}) 存在错误: {len(errors)} 个")
                else:
                    online_count += 1
                    # 检查是否有时间异常（时间差大于±3s）
                    time_diff = monitor_service.device_data.get(device_id, {}).get('initial_time_diff', 0)
                    if abs(time_diff) > 3:
                        self.log(f"设备 {device_id} ({ip}) 在线，但存在时间异常，时间差: {time_diff}s")
                    else:
                        self.log(f"设备 {device_id} ({ip}) 在线，状态正常")
                
                # 如果需要截图，尝试执行截图
                if capture_screenshot:
                    try:
                        # 获取设备系统类型
                        system_type = "Android"  # 简化处理，假设为Android系统
                        screenshot_result = monitor_service.capture_screenshot(device_id, ip, password, system_type, screenshot_path)
                        if screenshot_result and (screenshot_result.startswith("设备") or "执行截图命令失败" in screenshot_result):
                            # 截图失败
                            screenshot_failed_devices.append(device_id)
                            self.log(f"设备 {device_id} ({ip}) 截图失败: {screenshot_result}")
                        else:
                            self.log(f"设备 {device_id} ({ip}) 截图成功: {screenshot_result}")
                    except Exception as e:
                        screenshot_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 截图时出错: {str(e)}")
            except Exception as e:
                offline_count += 1
                self.log(f"设备 {device_id} ({ip}) 离线或无法连接: {str(e)}")
        
        # 统计时间异常的设备数量和列表
        time_error_count = 0
        time_error_devices = []
        time_error_details = []
        for device_id, data in first_time_data.items():
            time_diff = data.get('initial_time_diff', 0)
            if abs(time_diff) > 3:
                time_error_count += 1
                time_error_devices.append(device_id)
                time_error_details.append(f"{device_id} ({time_diff}秒)")
        
        # 生成监控摘要
        summary = f"监控摘要:\n"
        summary += f"总设备数: {len(selected_devices)}\n"
        summary += f"在线设备数: {online_count}\n"
        summary += f"离线设备数: {offline_count}\n"
        summary += f"存在错误的设备数: {error_count}\n"
        summary += f"存在时间异常的设备数: {time_error_count}\n"
        summary += f"监控类型: {self.dev_type}\n"
        summary += f"查询间隔: {delay_time}秒\n"
        summary += f"监控项目: {'设备时间' if monitor_time else ''}{'、启动时间' if monitor_boot else ''}{'、启动次数' if monitor_start_count else ''}{'、截图' if capture_screenshot else ''}\n"
        
        # 如果有时间差较大的设备，列举设备名称和偏差值并提示时间异常处理
        if time_error_devices:
            summary += f"时间异常设备: {', '.join(time_error_details)}\n"
            summary += f"时间异常处理: 以当前时间差为基准，后续监控只关注日均偏差是否大于±3s\n"
        
        # 如果有设备时间获取失败的设备，列举设备名称
        if time_failed_devices:
            summary += f"设备时间获取失败设备: {', '.join(time_failed_devices)}\n"
            summary += f"设备时间获取失败处理: 后续监控将不对这些设备进行设备时间检测\n"
        
        # 如果有启动时间获取失败的设备，列举设备名称
        if boot_failed_devices:
            summary += f"启动时间获取失败设备: {', '.join(boot_failed_devices)}\n"
            summary += f"启动时间获取失败处理: 后续监控将不对这些设备进行启动时间检测\n"
        
        # 如果有启动次数获取失败的设备，列举设备名称
        if start_count_failed_devices:
            summary += f"启动次数获取失败设备: {', '.join(start_count_failed_devices)}\n"
            summary += f"启动次数获取失败处理: 后续监控将不对这些设备进行启动次数检测\n"
        
        # 如果有截图失败的设备，列举设备名称
        if screenshot_failed_devices:
            summary += f"截图失败设备: {', '.join(screenshot_failed_devices)}\n"
            summary += f"截图失败处理: 后续监控将不对这些设备进行截图操作\n"
        
        self.log(summary)
        
        # 弹窗确认
        reply = QMessageBox.question(
            self, 
            "监控确认", 
            f"{summary}\n\n是否开始正式监控？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            self.log("监控已取消")
            return
        
        # 开始正式监控
        self.log("开始正式监控任务...")
        
        # 创建监控线程
        self.monitor_thread = MonitorThread(
            self.dev_type, 
            delay_time, 
            selected_devices, 
            monitor_time, 
            monitor_boot, 
            monitor_start_count, 
            capture_screenshot, 
            first_time_data,  # 传递第一次获取的数据作为基准
            screenshot_path,  # 传递截图存储路径
            screenshot_failed_devices,  # 传递截图失败的设备列表
            time_failed_devices,  # 传递设备时间获取失败的设备列表
            boot_failed_devices,  # 传递启动时间获取失败的设备列表
            start_count_failed_devices  # 传递启动次数获取失败的设备列表
        )
        
        # 连接信号
        self.monitor_thread.update_signal.connect(self.log)
        self.monitor_thread.device_list_signal.connect(self.on_device_list_updated)
        self.monitor_thread.status_signal.connect(self.update_status_bar)
        self.monitor_thread.error_signal.connect(self.handle_error)
        self.monitor_thread.monitor_result_signal.connect(self.on_monitor_result)
        
        # 启动线程
        self.monitor_thread.start()
        
        # 更新控制面板状态
        self.control_panel.set_monitor_status(True)
        
        # 暂停自动刷新
        # self.auto_refresh_timer.stop()
        
        # 记录开始监控的日志
        if self.dev_type == 'A-B-C-D-H':
            if capture_screenshot:
                self.log(f"开始监控所有类型的设备，查询间隔为 {delay_time} 秒，同时获取运行画面")
            else:
                self.log(f"开始监控所有类型的设备，查询间隔为 {delay_time} 秒")
        else:
            if capture_screenshot:
                self.log(f"开始监控 {self.dev_type} 类型设备，查询间隔为 {delay_time} 秒，同时获取运行画面")
            else:
                self.log(f"开始监控 {self.dev_type} 类型设备，查询间隔为 {delay_time} 秒")
    
    def stop_monitor(self):
        """停止监控"""
        try:
            if self.monitor_thread:
                if self.monitor_thread.isRunning():
                    self.monitor_thread.stop()
                self.monitor_thread = None
                
                # 更新控制面板状态
                self.control_panel.set_monitor_status(False)
                
                # 恢复自动刷新
                # self.auto_refresh_timer.start()
                
                self.log("监控已停止")
        except Exception as e:
            self.log(f"停止监控时出错: {str(e)}", is_error=True)
            # 无论如何都要确保按钮状态正确
            self.control_panel.set_monitor_status(False)
            self.monitor_thread = None
    
    def on_device_list_updated(self, devices):
        """设备列表更新时的处理"""
        # 检查设备数量是否有变化
        if len(devices) != len(self.device_list_view.get_devices()) and self.monitor_thread and self.monitor_thread.isRunning():
            difference_count = abs(len(devices) - len(self.device_list_view.get_devices()))
            if len(devices) < len(self.device_list_view.get_devices()):
                # 使用警告级别而不是错误级别
                self.log(f"警告: 设备离线，设备数量从 {len(self.device_list_view.get_devices())} 台减少到 {len(devices)} 台", is_warning=True)
                
                # 更新刷新状态标签
                self.control_panel.update_refresh_status(
                    f"当前设备数: {len(devices)} (减少{difference_count}台)",
                    is_error=True
                )
                
                # 写入错误日志
                offline_devices = []
                current_device_ids = {device_info['id'] for device_info in self.device_list_view.get_devices()}
                # 检查devices的格式并相应处理
                if devices and isinstance(devices[0], dict):
                    new_device_ids = {device_info['id'] for device_info in devices}
                else:
                    new_device_ids = {device_id for device_id, _ in devices}
                for device_id in current_device_ids:
                    if device_id not in new_device_ids:
                        offline_devices.append(device_id)
                if offline_devices:
                    # 单独记录每个离线设备的错误日志
                    for device_id in offline_devices:
                        # 查找设备的IP和密码信息
                        device_info = next((d for d in self.device_list_view.get_devices() if d['id'] == device_id), None)
                        ip = device_info.get('ip', 'N/A') if device_info else 'N/A'
                        password = device_info.get('password', 'N/A') if device_info else 'N/A'
                        
                        # 优化错误格式，使其与file_service.py中的格式匹配
                        errors = [{
                            'type': '设备离线',
                            'process': f'设备ID: {device_id}, IP: {ip}',
                            'difference': '设备从监控列表中消失'
                        }]
                        # 构建正确的错误信息字典格式
                        error_info = {
                            "时间": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "设备ID": device_id,
                            "IP地址": ip,
                            "错误类型": "设备离线",
                            "错误详情": errors
                        }
                        FileService.write_error_log(error_info)
            else:
                self.log(f"设备数量增加，从 {len(self.device_list_view.get_devices())} 台增加到 {len(devices)} 台")
                
                # 更新刷新状态标签
                self.control_panel.update_refresh_status(
                    f"当前设备数: {len(devices)} (增加{difference_count}台)"
                )
                
        # 保持已选设备的选择状态
        current_selected = self.device_list_view.get_selected_devices().copy()
        
        # 更新设备列表
        self.device_list_view.update_device_table(devices)
        
        # 恢复选择状态
        try:
            # 尝试新格式（字典列表）
            new_selected = set()
            for device_info in devices:
                if isinstance(device_info, dict) and 'id' in device_info:
                    if device_info['id'] in current_selected:
                        new_selected.add(device_info['id'])
                else:
                    # 尝试旧格式（元组列表）
                    device_id = device_info[0]
                    if device_id in current_selected:
                        new_selected.add(device_id)
            self.device_list_view.set_selected_devices(new_selected)
        except Exception:
            # 出现异常时尝试旧格式处理
            new_selected = set()
            for device_id, _ in devices:
                if device_id in current_selected:
                    new_selected.add(device_id)
            self.device_list_view.set_selected_devices(new_selected)

    def update_device_list(self, devices:list):
        """更新设备列表"""
        # 保持已选设备的选择状态
        current_selected = self.device_list_view.get_selected_devices().copy()
        devices = sorted(devices, key=lambda x: x['id'])
        # 更新设备列表
        self.device_list_view.update_device_table(devices)
        
        # 恢复选择状态
        try:
            # 尝试新格式（字典列表）
            new_selected = set()
            for device_info in devices:
                if isinstance(device_info, dict) and 'id' in device_info:
                    if device_info['id'] in current_selected:
                        new_selected.add(device_info['id'])
                else:
                    # 尝试旧格式（元组列表）
                    device_id = device_info[0]
                    if device_id in current_selected:
                        new_selected.add(device_id)
            self.device_list_view.set_selected_devices(new_selected)
        except Exception:
            # 出现异常时尝试旧格式处理
            new_selected = set()
            for device_id, _ in devices:
                if device_id in current_selected:
                    new_selected.add(device_id)
            self.device_list_view.set_selected_devices(new_selected)
    
    def query_selected(self, query_type):
        """查询选中的设备"""
        selected_devices = self.device_list_view.get_selected_devices()
        if not selected_devices:
            self.log("请先选择要查询的设备")
            return
        
        # 停止所有正在运行的查询线程
        for thread in self.query_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait()
        self.query_threads.clear()
        
        # 开始新的查询 变量作为数组传入线程 数据才会改变
        self.query_count = [0]

        #保存日志结果到CSV文件中
        self.switch_log_file = None
        if query_type == "sum_switch":
            if not os.path.exists("./switch_log"):
                os.mkdir("./switch_log")
            self.switch_log_file = open(f"./switch_log/{time.strftime('%Y%m%d%H%M%S',time.localtime())}_switch_log.csv", "w", encoding="utf-8")
            self.switch_log_file.write("设备ID,累计开机次数,累计网络开机次数\n")

        # 开始查询信息
        for device_info in self.device_list_view.get_devices():
            device_id = device_info['id']
            ip = device_info['ip']
            password = device_info.get('password', '')
            system_type = device_info.get('system_type', '')
            self.getdevice_num = len(selected_devices) # 查询设备的数量
            if device_id in selected_devices:
                # 创建查询线程
                thread = QueryThread(device_id, ip, password, query_type, self.control_panel, system_type, self.switch_log_file, self.query_count)
                thread.result_signal.connect(self.on_query_result)
                thread.error_signal.connect(lambda msg: self.log(msg, is_error=True))
                thread.end_signal.connect(self.close_csv_file)
                self.query_threads.append(thread)
                thread.start()
        
        self.log(f"\n-----------------------------------------------------------------------\n开始查询 {self.getdevice_num} 台设备的{self.get_query_type_text(query_type)}信息")
    
    def get_query_type_text(self, query_type):
        """获取查询类型的文本描述"""
        if query_type == "all":
            return "全部"
        elif query_type == "time":
            return "设备时间"
        elif query_type == "boot_time":
            return "启动时间"
        elif query_type == "start_count":
            return "播放器启动次数"
        elif query_type == "count_init":
            return "开关机初始化"
        elif query_type == "sum_switch":
            return "开关机次数"
        elif query_type == "clean_switch":
            return "清除日志"
        elif query_type == "check_time":
            return "校时"
        elif query_type == "upgrade_program":
            return "更新节目"
        return "未知"
    
    def close_csv_file(self, query_count):
        """关闭csv文件"""
        if query_count == self.getdevice_num:
            self.switch_log_file.close()

    def on_query_result(self, device_id, results):
        """处理查询结果"""
        self.log(f"\n设备 {device_id} 查询结果:")
        
        if 'device_time' in results:
            time_info = results['device_time']
            from datetime import datetime, timedelta
            # 将UTC时间转换为本地时间（UTC+8）
            if time_info['formatted_remote_time'] != 'N/A':
                utc_time = datetime.strptime(time_info['formatted_remote_time'], '%Y-%m-%d %H:%M:%S')
                local_time = utc_time + timedelta(hours=8)
                self.log(f"设备时间: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                self.log("设备时间: N/A")
            time_diff = int(time_info['time_diff']) if time_info['time_diff'] != 'N/A' else 0
            self.log(f"时间差: {time_diff} 秒")
            # 时间差小于120秒属于正常，否则记录警告
            if time_diff != 'N/A' and time_diff > 120:
                self.log(f"警告: 设备时间与系统时间偏差超过120秒", is_warning=True)
        
        if 'boot_time' in results:
            boot_info = results['boot_time']
            if 'error' not in boot_info:
                self.log(f"运行时长: {boot_info.get('formatted_uptime', 'N/A')}")
                self.log(f"启动时间: {self.format_time_to_minute(boot_info.get('boot_time', 'N/A'))}")
            else:
                self.log(f"获取启动时间失败: {boot_info['error']}", is_error=True)

        
        if 'start_count' in results:
            self.log(f"播放器启动次数: {results['start_count']}")
            # 启动次数为1属于正常，否则记录警告
            if results['start_count'] != '无法获取':
                try:
                    start_count = int(results['start_count'])
                    if start_count > 1:
                        self.log(f"警告: 播放器启动次数异常，当前值为 {start_count}", is_warning=True)
                except (ValueError, TypeError):
                    # 如果无法转换为整数，说明是错误信息，不进行异常判断
                    pass
        
        if "count_init" in results:
            self.log(f"设备: {results['count_init']}")

        if "sum_switch" in results:
            self.log(f"设备: {results['sum_switch']}")

        if "clean_switch" in results:
            self.log(f"设备: {results['clean_switch']}")

        if "check_time" in results:
            self.log(f"设备: {results['check_time']}")

        if "output_log" in results:
            self.log(f"设备: {results['output_log']}")

        if "upgrade_program" in results:
            self.log(f"设备: {results['upgrade_program']}")

        if "screenshot" in results:
            self.log(f"设备: {results['screenshot']}")


    def on_monitor_result(self, device_data):
        """处理监控结果并自动导出到Excel"""
        try:
            self.export_monitor_results_to_excel(device_data)
        except Exception as e:
            self.log(f"自动导出Excel失败: {str(e)}", is_error=True)
    
    def export_monitor_results_to_excel(self, device_data):
        """导出监控结果到Excel文件"""
        try:
            import pandas as pd
        except ImportError:
            self.log("导出Excel失败：未找到pandas模块。请运行 'pip install pandas' 安装依赖", is_error=True)
            return
        
        import os
        from datetime import datetime
        
        # 初始化Excel文件名，只在第一次创建时生成
        if not self.excel_file:
            # 确保output/excel目录存在
            excel_dir = './output/excel'
            os.makedirs(excel_dir, exist_ok=True)
            # 生成文件名，格式：[dev_type]_[yy-mm-dd_HH-MM-SS].xlsx
            current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            self.excel_file = f'{excel_dir}/{self.dev_type}_{current_time}.xlsx'
        else:
            # 确保目录存在
            excel_dir = os.path.dirname(self.excel_file)
            if excel_dir:
                os.makedirs(excel_dir, exist_ok=True)
        
        # 创建数据列表
        data = []
        
        # 确定要导出的字段
        fields = {
            '系统时间': 'system_time',
            '设备ID': 'id',
            'IP地址': 'ip',
            'MAC地址': 'mac_address',
            '设备名称': 'device_name'
        }
        
        # 根据监控选项动态添加字段
        if self.control_panel.monitor_time_check.isChecked():
            fields['设备时间'] = 'initial_card_time'
            fields['时间差'] = 'initial_time_diff'
        if self.control_panel.monitor_boot_check.isChecked():
            fields['启动时间'] = 'last_boot_time'
            fields['运行时长'] = 'last_uptime'
        if self.control_panel.monitor_start_count_check.isChecked():
            fields['播放器启动次数'] = 'last_start_count'
        
        # 获取当前系统时间
        current_system_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for device_id, info in device_data.items():
            # 准备一行数据
            row = {}
            
            # 填充固定字段
            row['系统时间'] = current_system_time
            row['设备ID'] = device_id
            
            # 找到对应的设备信息
            device_info = next((d for d in self.device_list_view.get_devices() if d['id'] == device_id), None)
            if device_info:
                row['IP地址'] = device_info.get('ip', '未知')
                row['MAC地址'] = device_info.get('mac_address', '未知')
                row['设备名称'] = device_info.get('device_name', '未知')
            else:
                row['IP地址'] = '未知'
                row['MAC地址'] = '未知'
                row['设备名称'] = '未知'
            
            # 填充动态字段
            if self.control_panel.monitor_time_check.isChecked():
                row['设备时间'] = info.get('last_card_time', info.get('initial_card_time', 'N/A'))
                time_diff = info.get('last_time_diff', info.get('initial_time_diff', 'N/A'))
                row['时间差'] = f"{time_diff}秒" if time_diff != 'N/A' else time_diff
            
            if self.control_panel.monitor_boot_check.isChecked():
                # 格式化启动时间到分钟
                boot_time = info.get('last_boot_time', 'N/A')
                row['启动时间'] = self.format_time_to_minute(boot_time)
                row['运行时长'] = info.get('last_uptime', 'N/A')
            
            if self.control_panel.monitor_start_count_check.isChecked():
                row['播放器启动次数'] = info.get('last_start_count', 'N/A')
            
            data.append(row)
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 写入Excel文件
        try:
            # 检查文件是否存在，决定是否需要写入表头
            file_exists = os.path.exists(self.excel_file)
            
            # 检查是否有xlsxwriter库
            try:
                import xlsxwriter
                # 使用xlsxwriter引擎
                engine = 'xlsxwriter'
            except ImportError:
                # 如果没有xlsxwriter，使用默认引擎
                engine = None
                
            # 写入数据到Excel文件
            if file_exists:
                # 文件已存在，追加数据而不写入表头
                # 读取现有数据
                existing_df = pd.read_excel(self.excel_file)
                # 合并数据
                merged_df = pd.concat([existing_df, df])
                # 使用xlsxwriter引擎保存并调整列宽
                if engine == 'xlsxwriter':
                    with pd.ExcelWriter(self.excel_file, engine=engine) as writer:
                        # 写入合并后的数据
                        merged_df.to_excel(writer, index=False, sheet_name='设备监控数据')
                        # 获取工作表
                        worksheet = writer.sheets['设备监控数据']
                        
                        # 模拟autofit功能：计算每列的最大宽度并设置
                        for col_num, col_name in enumerate(merged_df.columns):
                            # 获取当前列所有非空数据的文本长度
                            col_values = merged_df[col_name].dropna().astype(str)
                            # 找出最大文本长度，包含列名长度
                            max_length = max([len(str(x)) for x in col_values] + [len(col_name)]) + 15  # 加2作为边距
                            # 设置列宽，最大不超过50
                            worksheet.set_column(col_num, col_num, min(max_length, 50))
                else:
                    # 没有xlsxwriter时直接保存
                    merged_df.to_excel(self.excel_file, index=False, sheet_name='设备监控数据')
            else:
                # 文件不存在，创建新文件并写入表头
                with pd.ExcelWriter(self.excel_file, engine=engine) as writer:
                    # 写入数据
                    df.to_excel(writer, index=False, sheet_name='设备监控数据')
                    
                    # 如果使用xlsxwriter引擎，设置列宽
                    if engine == 'xlsxwriter':
                        # 获取工作表
                        worksheet = writer.sheets['设备监控数据']
                        
                        # 模拟autofit功能：计算每列的最大宽度并设置
                        for col_num, col_name in enumerate(df.columns):
                            # 获取当前列所有非空数据的文本长度
                            col_values = df[col_name].dropna().astype(str)
                            # 找出最大文本长度，包含列名长度
                            max_length = max([len(str(x)) for x in col_values] + [len(col_name)]) + 15  # 加2作为边距
                            # 设置列宽，最大不超过50
                            worksheet.set_column(col_num, col_num, min(max_length, 50))
        except Exception as e:
            self.log(f"写入Excel文件时出错: {str(e)}", is_error=True)
            return
        
        # 记录导出日志，统一使用正斜杠
        excel_path = os.path.abspath(self.excel_file).replace('\\', '/')
        self.log(f"监控结果已成功导出到 {excel_path}")
    
    def log(self, message, is_error=False, is_warning=False):
        """记录日志，支持错误(红色)、警告(黄色)和正常(黑色)消息"""
        self.result_display_view.log(message, is_error, is_warning)
        
    def open_error_log_in_notepad(self):
        """打开记事本显示错误日志，并处理进程冲突"""
        import subprocess
        import os
        from config import error_log_file
        
        # 确保错误日志文件存在
        if not os.path.exists(error_log_file):
            with open(error_log_file, 'w') as f:
                f.write("# 错误日志文件\n")
        
        # 如果已经有记事本打开，先关闭它
        if self.notepad_process:
            try:
                self.notepad_process.terminate()
                self.notepad_process.wait(timeout=3)
            except:
                pass  # 如果关闭失败，继续执行下一步
        
        # 打开新的记事本
        self.notepad_process = subprocess.Popen(['notepad.exe', error_log_file])
    
    def format_time_to_minute(self, time_str):
        """将时间字符串格式化为精确到分钟"""
        if time_str == 'N/A' or not time_str:
            return time_str
        try:
            # 尝试不同的时间格式解析
            if 'T' in time_str:  # ISO格式
                dt = datetime.fromisoformat(time_str)
            else:
                # 尝试其他常见格式
                formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S.%f']
                for fmt in formats:
                    try:
                        dt = datetime.strptime(time_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return time_str
            # 返回精确到分钟的格式
            return dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            return time_str
            
    def on_device_selected(self, selected_devices):
        """设备选择变化时的处理"""
        # 这里可以添加设备选择变化时的额外处理逻辑
        pass
        
    def on_clear_log(self):
        """清空日志时的处理"""
        # 这里可以添加清空日志时的额外处理逻辑
        pass
        
    def clear_history_data(self):
        """清除历史监控数据"""
        # 定义要清除的文件和文件夹
        folders_to_clear = [
            "./output",
            "./screenshot",
            "./switch_log",
            "./monitor_data"
        ]
        
        files_to_clear = [
            "device_data.json",
            "device_errors.txt",
            "device_error.txt"
        ]
        
        # 清除文件夹
        for folder in folders_to_clear:
            if os.path.exists(folder):
                try:
                    shutil.rmtree(folder)
                    self.log(f"已清除文件夹: {folder}")
                except Exception as e:
                    self.log(f"清除文件夹 {folder} 时出错: {str(e)}")
        
        # 清除文件
        for file in files_to_clear:
            if os.path.exists(file):
                try:
                    os.remove(file)
                    self.log(f"已清除文件: {file}")
                except Exception as e:
                    self.log(f"清除文件 {file} 时出错: {str(e)}")
        
        # 清除监控类型对应的日志文件夹
        from config import supported_dev_types
        for dev_type in supported_dev_types:
            if os.path.exists(dev_type):
                try:
                    shutil.rmtree(dev_type)
                    self.log(f"已清除监控类型文件夹: {dev_type}")
                except Exception as e:
                    self.log(f"清除监控类型文件夹 {dev_type} 时出错: {str(e)}")
        
        # 清除Excel文件
        for file in os.listdir("."):
            if file.endswith(".xlsx"):
                try:
                    os.remove(file)
                    self.log(f"已清除Excel文件: {file}")
                except Exception as e:
                    self.log(f"清除Excel文件 {file} 时出错: {str(e)}")
    
    def closeEvent(self, event):
        """
        窗口关闭时的处理
        """
        # 检查监控是否正在运行
        if hasattr(self, 'monitor_thread') and self.monitor_thread and self.monitor_thread.isRunning():
            reply = QMessageBox.question(
                self, 
                "关闭确认", 
                "监控正在运行中，确定要关闭应用程序吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                event.ignore()
                return
        
        self.stop_monitor()
        # self.auto_refresh_timer.stop()  # 停止自动刷新定时器
        for thread in self.query_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait()
        event.accept()
    
    def refresh_device_list(self):
        """刷新设备列表"""

        try:
            # 获取当前查询设备类型
            dev_type = self.control_panel.dev_type
            # 禁用刷新按钮
            self.control_panel.refresh_button.setDisabled(True)
            # 调用DeviceId.exe
            from service.tool_service import TOOLS_DIR
            import os
            device_id_exe = os.path.join(TOOLS_DIR, 'DeviceId.exe')
            stdout, stderr, _ = ToolService.run_command(device_id_exe)
            if stderr:
                print(f"DeviceId.exe 错误: {stderr}")
                return []
            # 初始化devices数组
            self.devices = []
            # 配置正则表达式
            pattern = dev_type.replace('-', '|')
            # 创建GetDeviceInfoManager线程池
            # print(f"创建任务列表：",len(stdout.split("\n")))
            self.Manager = GetDeviceInfoManager(pattern, max_workers=4, queue_size=len(stdout.split("\n")))
            self.Manager.taskCompleted.connect(self.refresh_device_flash)
            self.Manager.allTasksCompleted.connect(self.device_info_to_list)
            # 提交任务
            for line in stdout.split("\n"):
                if line.strip().split("-")[0] in supported_dev_types and re.match(f"^({pattern})", line):
                    self.Manager.submit_task(line)
            return None

        except Exception as e:
            self.log(f"刷新设备列表失败: {str(e)}")
            # 恢复刷新按钮
            self.control_panel.refresh_button.setEnabled(True)
            # 释放线程池
            self.Manager.check_timer.stop()
            self.Manager.taskCompleted.disconnect()
            self.Manager.allTasksCompleted.disconnect()
            self.Manager = None
            return None

    def refresh_device_flash(self, device_info):
        """执行完成后执行的操作"""
        if device_info:
            self.devices.append(device_info)
    def device_info_to_list(self):
        # print(f"device_info_to_list {self.devices}")
        self.Manager.check_timer.stop()
        self.Manager.taskCompleted.disconnect()
        self.Manager.allTasksCompleted.disconnect()
        self.Manager = None
        try:
            self.update_device_list(self.devices)

            # 更新刷新状态标签
            self.control_panel.update_refresh_status(f"当前设备数: {len(self.devices)}")

            self.log(f"设备列表已刷新，共 {len(self.devices)} 台设备")

        except Exception as e:
            self.log(f"刷新设备列表失败: {str(e)}")

        self.control_panel.refresh_button.setEnabled(True)

    def monitor_device(self, device):
        """监控单个设备"""
        try:
            # 获取设备时间
            device_time = self.get_device_time(device)
            # 获取当前时间
            current_time = datetime.now()
            # 计算时间差
            time_diff = (current_time - device_time).total_seconds()
            # 写入Excel（确保每次都写最新的时间和时间差）
            self.write_to_excel(device, device_time, time_diff)
        except Exception as e:
            # 写入异常到 device_error.txt
            with open('device_error.txt', 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()} 设备:{device} 获取时间异常: {str(e)}\n")

    def write_to_excel(self, device, device_time, time_diff):
        """写入设备时间和时间差到Excel"""
        # 优化：每次写入最新数据
        import pandas as pd
        import os
        row = {
            '设备': device,
            '设备时间': device_time,
            '与电脑当前的时间差': time_diff,
            '系统时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        file = 'device_time.xlsx'
        df = pd.DataFrame([row])
        if os.path.exists(file):
            old = pd.read_excel(file)
            df = pd.concat([old, df], ignore_index=True)
        df.to_excel(file, index=False)