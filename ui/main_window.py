import time
from PyQt5.QtWidgets import (QApplication, QMessageBox, QDialog, QWidget,
                              QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                              QPushButton, QGroupBox, QGridLayout, QFileDialog, 
                              QScrollArea)
from datetime import datetime
import os
import re

from .base_window import BaseWindow
from .control_panel import ControlPanel
from .device_list_view import DeviceListView
from .device_refresh_controller import DeviceRefreshController
from .error_log_manager import ErrorLogManager
from .excel_exporter import ExcelExporter
from .query_result_presenter import QueryResultPresenter
from .result_display_view import ResultDisplayView
from .monitor_thread import MonitorThread
from .serial_query_manager import SerialQueryManager
from .workers.adb_enable_worker import EnableAdbWorker
from .workers.background_discovery_worker import BackgroundDiscovery
from .workers.clear_history_worker import ClearHistoryWorker

from service.tool_service import ToolService
from service.file_service import FileService
from service.logging_service import get_logger
from config import (
    get_base_dir, supported_dev_types, tool_path, program_path,
    BACKGROUND_DISCOVERY_ENABLED,
)
from .dialogs import ClearHistoryDialog, CountInitConfirmDialog, UpgradeConfirmDialog

logger = get_logger(__name__)


class MainWindow(BaseWindow):
    """主窗口类，作为控制器协调各个组件的工作"""
    
    def __init__(self):
        super().__init__()
        
        # 初始化变量
        self.devices = None
        self.monitor_thread = None
        self.serial_manager = None
        self.switch_log_file = None
        self.query_count = [0]
        self.dev_type = ControlPanel().dev_type
        self.error_log_manager = ErrorLogManager(self.log)
        self.excel_exporter = ExcelExporter(self.log)
        self.query_presenter = QueryResultPresenter(self.log, self.format_time_to_minute)
        self.refresh_controller = DeviceRefreshController(self)
        self.enable_adb_worker = None
        self.background_discovery = BackgroundDiscovery(self)
        self.clear_history_worker = None
        
        # 启动时最大化窗口
        self.showMaximized()
        
        # 查询相关的变量
        self.successful_devices = []
        self.failed_devices = []
        self.not_applicable_devices = []
        self.current_query_type = None
        self.getdevice_num = 0
        self._discovered_count = 0
        
        # 初始化日志文件
        base_dir = get_base_dir(self.dev_type)
        FileService.init_log_files(base_dir)
        
        # 创建并初始化各个组件
        self.init_components()
        
        # 连接信号和槽
        self.connect_signals_slots()
        
        # 完成布局
        self.finalize_layout()
        
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
        self.control_panel.manual_find_clicked.connect(self.manual_find_device_list)
        self.control_panel.enable_adb_clicked.connect(self.enable_adb_for_selected)
        self.control_panel.clear_history_clicked.connect(self.clear_history_data)
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

        # 设备刷新控制器信号连接
        self.refresh_controller.progress.connect(self.control_panel.update_refresh_status)
        self.refresh_controller.devices_ready.connect(self.on_devices_ready)
        self.refresh_controller.device_found.connect(self.on_device_found)
        self.refresh_controller.device_row_updated.connect(self.on_device_row_updated)
        self.refresh_controller.failed.connect(self.on_refresh_failed)
        self.refresh_controller.finished.connect(self.on_refresh_finished)

        # 后台心跳找卡：仅在设备上下线时通知（监控未运行时才跑）
        self.background_discovery.changed.connect(self.on_background_devices_changed)

    def refresh_android_device_info_after_adb(self, device_id, ip, password):
        """
        Android 设备 ADB 开启后，重新获取并刷新设备列表中的 MAC、设备名、系统类型、版本等信息。
        使用 ADB 方式获取，避免再次走 SSH 造成延迟。
        """
        try:
            from service.adb_device_manager import ADBDeviceManager
            from service.adb_service import ADBService
            from service.tool_service import ToolService
            from service.device_utils import ADB_PATH

            if not ADBDeviceManager.should_use_adb(device_id):
                return

            success, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
            if not success:
                return

            # 使用 adb -s serial shell 批量获取信息
            mac_cmd = f'{ADB_PATH} -s {serial} shell cat /sys/class/net/eth0/address'
            name_cmd = f'{ADB_PATH} -s {serial} shell getprop ro.product.model'
            version_cmd = f'{ADB_PATH} -s {serial} shell getprop ro.build.version'

            mac_stdout, _, _ = ToolService.run_command(mac_cmd, timeout=5)
            name_stdout, _, _ = ToolService.run_command(name_cmd, timeout=5)
            version_stdout, _, _ = ToolService.run_command(version_cmd, timeout=5)

            mac_address = mac_stdout.strip() if mac_stdout else 'N/A'
            device_name = name_stdout.strip() if name_stdout else 'N/A'
            ota_version = version_stdout.strip() if version_stdout else 'N/A'
            system_type = 'Android'

            # 主版本通过 dumpsys package 获取（播放器版本）
            main_version = 'N/A'
            dumpsys_cmd = f'{ADB_PATH} -s {serial} shell dumpsys package cn.huidu.lcd.player'
            dumpsys_out, _, _ = ToolService.run_command(dumpsys_cmd, timeout=10)
            if dumpsys_out:
                for line in dumpsys_out.strip().split('\n'):
                    if 'versionName' in line:
                        parts = line.split('=', 1)
                        if len(parts) > 1:
                            main_version = parts[1].strip()
                            break

            # 刷新 UI 表格
            self.device_list_view.update_device_info_field(device_id, 'mac_address', mac_address)
            self.device_list_view.update_device_info_field(device_id, 'device_name', device_name)
            self.device_list_view.update_device_info_field(device_id, 'system_type', system_type)
            self.device_list_view.update_device_info_field(device_id, 'ota_version', ota_version)
            self.device_list_view.update_device_info_field(device_id, 'main_version', main_version)
            self.device_list_view.update_device_info_field(device_id, 'adb_status', '开启')

            # 同步刷新 self.devices 中的数据
            for info in self.devices:
                if info.get('id') == device_id:
                    info['mac_address'] = mac_address
                    info['device_name'] = device_name
                    info['system_type'] = system_type
                    info['ota_version'] = ota_version
                    info['main_version'] = main_version
                    info['adb_status'] = '开启'
                    break
        except Exception as e:
            logger.warning("[MainWindow] ADB 开启后刷新设备信息失败 %s: %s", device_id, e)

    def handle_error(self, error_msg, device_id, ip):
        """处理监控线程发送的错误信号"""
        self.error_log_manager.handle(error_msg, device_id, ip)

    def on_dev_type_changed(self, text):
        """设备类型改变时的处理"""
        self.dev_type = text
        # 重新初始化日志文件
        base_dir = get_base_dir(self.dev_type)
        FileService.init_log_files(base_dir)
        # 重新刷新设备列表
        self.refresh_device_list()
    
    def _check_devices_first_time(self, selected_devices, monitor_service,
                                   monitor_time, monitor_boot, monitor_start_count,
                                   capture_screenshot, screenshot_path):
        """首次检查选中设备：逐台检测在线状态、截图，收集失败列表"""
        first_time_data = {}
        online_count = 0
        offline_count = 0
        error_count = 0
        screenshot_failed_devices = []
        time_failed_devices = []
        boot_failed_devices = []
        start_count_failed_devices = []

        for device_info in selected_devices:
            device_id = device_info['id']
            ip = device_info['ip']
            password = device_info['password']

            try:
                errors = monitor_service.check_device_status(
                    device_id, ip, password,
                    monitor_time=monitor_time,
                    monitor_boot=monitor_boot,
                    monitor_start_count=monitor_start_count
                )

                if device_id in monitor_service.device_data:
                    first_time_data[device_id] = monitor_service.device_data[device_id].copy()
                    device_data = monitor_service.device_data[device_id]

                    if monitor_time and ('initial_card_time' not in device_data or device_data.get('initial_card_time') == 'N/A'):
                        time_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 设备时间获取失败")

                    if monitor_boot and ('initial_boot_time' not in device_data or device_data.get('initial_boot_time') == 'N/A'):
                        boot_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 启动时间获取失败")

                    if monitor_start_count and ('initial_start_count' not in device_data or device_data.get('initial_start_count') == 'N/A'):
                        start_count_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 启动次数获取失败")

                if errors:
                    error_count += 1
                    self.log(f"设备 {device_id} ({ip}) 存在错误: {len(errors)} 个")
                else:
                    online_count += 1
                    time_diff = monitor_service.device_data.get(device_id, {}).get('initial_time_diff', 0)
                    if abs(time_diff) > 3:
                        self.log(f"设备 {device_id} ({ip}) 在线，但存在时间异常，时间差: {time_diff}s")
                    else:
                        self.log(f"设备 {device_id} ({ip}) 在线，状态正常")

                if capture_screenshot:
                    try:
                        screenshot_result = monitor_service.capture_screenshot(
                            device_id, ip, password, "Android", screenshot_path
                        )
                        if screenshot_result.success:
                            self.log(f"设备 {device_id} ({ip}) 截图成功: {screenshot_result.data}")
                        else:
                            screenshot_failed_devices.append(device_id)
                            self.log(f"设备 {device_id} ({ip}) 截图失败: {screenshot_result.error}")
                    except Exception as e:
                        screenshot_failed_devices.append(device_id)
                        self.log(f"设备 {device_id} ({ip}) 截图时出错: {str(e)}")
            except Exception as e:
                offline_count += 1
                self.log(f"设备 {device_id} ({ip}) 离线或无法连接: {str(e)}")

        return (first_time_data, online_count, offline_count, error_count,
                time_failed_devices, boot_failed_devices,
                start_count_failed_devices, screenshot_failed_devices)

    @staticmethod
    def _build_monitor_summary(selected_devices, online_count, offline_count,
                                error_count, first_time_data, dev_type,
                                delay_time, monitor_time, monitor_boot,
                                monitor_start_count, capture_screenshot,
                                time_failed_devices, boot_failed_devices,
                                start_count_failed_devices, screenshot_failed_devices):
        """构建首次检测的监控摘要文本"""
        time_error_count = 0
        time_error_devices = []
        time_error_details = []
        for device_id, data in first_time_data.items():
            time_diff = data.get('initial_time_diff', 0)
            if abs(time_diff) > 3:
                time_error_count += 1
                time_error_devices.append(device_id)
                time_error_details.append(f"{device_id} ({time_diff}秒)")

        items = []
        if monitor_time:
            items.append('设备时间')
        if monitor_boot:
            items.append('启动时间')
        if monitor_start_count:
            items.append('启动次数')
        if capture_screenshot:
            items.append('截图')

        summary = "监控摘要:\n"
        summary += f"总设备数: {len(selected_devices)}\n"
        summary += f"在线设备数: {online_count}\n"
        summary += f"离线设备数: {offline_count}\n"
        summary += f"存在错误的设备数: {error_count}\n"
        summary += f"存在时间异常的设备数: {time_error_count}\n"
        summary += f"监控类型: {dev_type}\n"
        summary += f"查询间隔: {delay_time}秒\n"
        summary += f"监控项目: {'、'.join(items)}\n"

        if time_error_devices:
            summary += f"时间异常设备: {', '.join(time_error_details)}\n"
            summary += "时间异常处理: 以当前时间差为基准，后续监控只关注日均偏差是否大于±3s\n"

        if time_failed_devices:
            summary += f"设备时间获取失败设备: {', '.join(time_failed_devices)}\n"
            summary += "设备时间获取失败处理: 后续监控将不对这些设备进行设备时间检测\n"

        if boot_failed_devices:
            summary += f"启动时间获取失败设备: {', '.join(boot_failed_devices)}\n"
            summary += "启动时间获取失败处理: 后续监控将不对这些设备进行启动时间检测\n"

        if start_count_failed_devices:
            summary += f"启动次数获取失败设备: {', '.join(start_count_failed_devices)}\n"
            summary += "启动次数获取失败处理: 后续监控将不对这些设备进行启动次数检测\n"

        if screenshot_failed_devices:
            summary += f"截图失败设备: {', '.join(screenshot_failed_devices)}\n"
            summary += "截图失败处理: 后续监控将不对这些设备进行截图操作\n"

        return summary

    def start_monitor(self, delay_time, monitor_time, monitor_boot, monitor_start_count,
                       capture_screenshot=False, screenshot_path="./screenshot"):
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

        # 第一次获取设备信息，检测设备在线情况和可执行性
        self.log("开始第一次获取设备信息，检测设备在线情况...")

        from business.device_monitor_service import DeviceMonitorService
        monitor_service = DeviceMonitorService(self.dev_type)

        (first_time_data, online_count, offline_count, error_count,
         time_failed_devices, boot_failed_devices,
         start_count_failed_devices, screenshot_failed_devices
         ) = self._check_devices_first_time(
            selected_devices, monitor_service,
            monitor_time, monitor_boot, monitor_start_count,
            capture_screenshot, screenshot_path
        )

        # 生成监控摘要
        summary = self._build_monitor_summary(
            selected_devices, online_count, offline_count, error_count,
            first_time_data, self.dev_type, delay_time,
            monitor_time, monitor_boot, monitor_start_count,
            capture_screenshot,
            time_failed_devices, boot_failed_devices,
            start_count_failed_devices, screenshot_failed_devices
        )
        self.log(summary)

        # 弹窗确认
        reply = QMessageBox.question(
            self, "监控确认",
            f"{summary}\n\n是否开始正式监控？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            self.log("监控已取消")
            return

        # 开始正式监控
        self.log("开始正式监控任务...")
        # 监控运行期间不需要后台心跳（避免与监控取数竞争）
        self.background_discovery.stop()
        self._launch_monitor(delay_time, monitor_time, monitor_boot,
                              monitor_start_count, capture_screenshot,
                              screenshot_path, selected_devices,
                              first_time_data, screenshot_failed_devices,
                              time_failed_devices, boot_failed_devices,
                              start_count_failed_devices)

    def _launch_monitor(self, delay_time, monitor_time, monitor_boot,
                         monitor_start_count, capture_screenshot,
                         screenshot_path, selected_devices,
                         first_time_data, screenshot_failed_devices,
                         time_failed_devices, boot_failed_devices,
                         start_count_failed_devices):
        """创建 MonitorConfig 并启动监控线程"""
        from data_models import MonitorConfig
        monitor_config = MonitorConfig(
            dev_type=self.dev_type,
            delay_time=delay_time,
            monitor_time=monitor_time,
            monitor_boot=monitor_boot,
            monitor_start_count=monitor_start_count,
            capture_screenshot=capture_screenshot,
            screenshot_path=screenshot_path,
            selected_devices=selected_devices,
            first_time_data=first_time_data,
            screenshot_failed_devices=screenshot_failed_devices,
            time_failed_devices=time_failed_devices,
            boot_failed_devices=boot_failed_devices,
            start_count_failed_devices=start_count_failed_devices,
        )
        self.monitor_thread = MonitorThread(monitor_config)

        self.monitor_thread.update_signal.connect(self.log)
        self.monitor_thread.device_list_signal.connect(self.on_device_list_updated)
        self.monitor_thread.status_signal.connect(self.update_status_bar)
        self.monitor_thread.error_signal.connect(self.handle_error)
        self.monitor_thread.monitor_result_signal.connect(self.on_monitor_result)

        self.monitor_thread.start()
        self.control_panel.set_monitor_status(True)

        suffix = "，同时获取运行画面" if capture_screenshot else ""
        type_name = "所有类型的设备" if self.dev_type == 'A-B-C-D-H' else f"{self.dev_type} 类型设备"
        self.log(f"开始监控{type_name}，查询间隔为 {delay_time} 秒{suffix}")
    
    def stop_monitor(self):
        """停止监控"""
        try:
            if self.monitor_thread:
                if self.monitor_thread.isRunning():
                    self.monitor_thread.stop()
                # 断开信号连接，防止重复连接
                try:
                    self.monitor_thread.update_signal.disconnect(self.log)
                except TypeError:
                    pass
                try:
                    self.monitor_thread.device_list_signal.disconnect(self.on_device_list_updated)
                except TypeError:
                    pass
                try:
                    self.monitor_thread.status_signal.disconnect(self.update_status_bar)
                except TypeError:
                    pass
                try:
                    self.monitor_thread.error_signal.disconnect(self.handle_error)
                except TypeError:
                    pass
                try:
                    self.monitor_thread.monitor_result_signal.disconnect(self.on_monitor_result)
                except TypeError:
                    pass
                self.monitor_thread = None
                
                # 更新控制面板状态
                self.control_panel.set_monitor_status(False)
                
                self.log("监控已停止")
        except Exception as e:
            self.log(f"停止监控时出错: {str(e)}", is_error=True)
            # 无论如何都要确保按钮状态正确
            self.control_panel.set_monitor_status(False)
            self.monitor_thread = None

        # 监控停止后恢复后台心跳找卡（监控未运行期间保持设备上下线感知）
        self._sync_background_discovery()
    
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
        
        # 如果存在串行管理器，停止它
        if self.serial_manager and self.serial_manager.isRunning():
            self.serial_manager.stop()
            self.serial_manager.wait()
        
        # 初始化成功和失败设备列表
        self.successful_devices = []
        self.failed_devices = []
        self.not_applicable_devices = []
        
        # 开始新的查询 变量作为数组传入线程 数据才会改变
        self.query_count = [0]

        #保存日志结果到CSV文件中
        self.switch_log_file = None
        if query_type == "sum_switch":
            if not os.path.exists("./switch_log"):
                os.mkdir("./switch_log")
            self.switch_log_file = open(f"./switch_log/{time.strftime('%Y%m%d%H%M%S',time.localtime())}_switch_log.csv", "w", encoding="utf-8")
            self.switch_log_file.write("设备ID,累计开机次数,累计网络开机次数\n")
        
        # 保存查询类型用于汇总
        self.current_query_type = query_type
        
        # 收集要处理的设备信息
        devices_to_process = []
        for device_info in self.device_list_view.get_devices():
            device_id = device_info['id']
            if device_id in selected_devices:
                ip = device_info['ip']
                password = device_info.get('password', '')
                system_type = device_info.get('system_type', '')
                devices_to_process.append((device_id, ip, password, system_type))
        
        self.getdevice_num = len(devices_to_process)
        
        # 开关机初始化操作前，弹出确认对话框，让用户确认设备分组和文件路径
        custom_file_paths = None
        if query_type == "count_init":
            # 获取选中的设备完整信息
            selected_devices_info = self.device_list_view.get_selected_devices_info()
            
            # 弹出确认对话框
            dialog = CountInitConfirmDialog(selected_devices_info, tool_path, parent=self)
            if dialog.exec_() != QDialog.Accepted:
                self.log("开关机初始化操作已取消")
                return
            
            # 获取用户自定义的文件路径
            custom_file_paths = dialog.get_file_paths()
            self.log(f"开关机初始化确认完成，使用自定义文件路径: {custom_file_paths}")
        
        if query_type == "upgrade_program":
            selected_devices_info = self.device_list_view.get_selected_devices_info()
            dialog = UpgradeConfirmDialog(selected_devices_info, program_path, parent=self)
            if dialog.exec_() != QDialog.Accepted:
                self.log("发送节目操作已取消")
                return
            custom_file_paths = dialog.get_file_paths()
            self.log(f"发送节目确认完成，使用自定义文件路径: {custom_file_paths}")
        
        # 使用串行管理器执行
        self.serial_manager = SerialQueryManager(
            devices_to_process, 
            query_type, 
            self.control_panel, 
            self.switch_log_file,
            custom_file_paths  # 传递自定义文件路径
        )
        self.serial_manager.result_signal.connect(self.on_query_result)
        self.serial_manager.error_signal.connect(self.on_query_error)
        self.serial_manager.finished_signal.connect(self.close_csv_file)
        self.serial_manager.state_signal.connect(self.on_query_state)
        self.serial_manager.start()
        
        # 判断是查询还是操作
        op_text = self.query_presenter.query_type_text(query_type)
        if QueryResultPresenter.is_query_operation(query_type):
            self.log(f"\n-----------------------------------------------------------------------\n开始查询 {self.getdevice_num} 台设备的{op_text}信息")
        else:
            self.log(f"\n-----------------------------------------------------------------------\n开始执行 {self.getdevice_num} 台设备的{op_text}操作")
    
    def on_query_state(self, device_id, state):
        """接收 SerialQueryManager 的状态信号，更新 ADB 列或刷新设备信息"""
        if not device_id:
            return
        if state.startswith("ADB:"):
            status = state.split(":", 1)[1]
            self.device_list_view.update_device_info_field(device_id, 'adb_status', status)
            for info in self.devices:
                if info.get('id') == device_id:
                    info['adb_status'] = status
                    break
        elif state.startswith("INFO_REFRESH:"):
            try:
                import ast
                info_str = state.split(":", 1)[1]
                info = ast.literal_eval(info_str)
                if isinstance(info, dict):
                    for field, value in info.items():
                        self.device_list_view.update_device_info_field(device_id, field, value)
                    for info_item in self.devices:
                        if info_item.get('id') == device_id:
                            info_item.update(info)
                            break
            except Exception as e:
                logger.warning("[MainWindow] 解析 INFO_REFRESH 失败: %s", e)

    def close_csv_file(self, query_count):
        """关闭csv文件并显示汇总"""
        if query_count == self.getdevice_num:
            if self.switch_log_file:
                self.switch_log_file.close()
            # 显示汇总信息（监控任务的查询和截图不显示汇总）
            if not (self.monitor_thread and self.monitor_thread.isRunning()):
                self.query_presenter.show_summary(
                    self.current_query_type,
                    self.getdevice_num,
                    self.successful_devices,
                    self.failed_devices,
                    self.not_applicable_devices,
                )
            # 更新状态栏提示
            op_text = self.query_presenter.query_type_text(self.current_query_type)
            self.update_status_bar(f"已完成 {self.getdevice_num} 台设备 {op_text}")

    def on_query_result(self, device_id, results):
        """处理查询结果"""
        success = self.query_presenter.present(device_id, results)
        if success:
            self.successful_devices.append(device_id)
        else:
            self.failed_devices.append(device_id)
        # 「不适用」（如 Linux 设备无播放器概念 → 启动次数无法获取）单独记录，不计入失败
        fields = QueryResultPresenter.not_applicable_fields(results)
        if fields:
            self.not_applicable_devices.append((device_id, fields))
    
    def on_query_error(self, device_id, error_msg):
        """处理查询错误"""
        self.failed_devices.append(device_id)
        self.log(error_msg, is_error=True)


    def on_monitor_result(self, device_data):
        """处理监控结果并自动导出到Excel"""
        options = {
            'monitor_time': self.control_panel.monitor_time_check.isChecked(),
            'monitor_boot': self.control_panel.monitor_boot_check.isChecked(),
            'monitor_start_count': self.control_panel.monitor_start_count_check.isChecked(),
        }
        try:
            self.excel_exporter.export(
                device_data,
                self.dev_type,
                self.device_list_view.get_devices(),
                options,
                self.format_time_to_minute,
            )
        except Exception as e:
            self.log(f"自动导出Excel失败: {str(e)}", is_error=True)

    def log(self, message, is_error=False, is_warning=False):
        """记录日志，支持错误(红色)、警告(黄色)和正常(黑色)消息"""
        self.result_display_view.log(message, is_error, is_warning)
        
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
        """清理历史数据（控制类操作）：选范围 → 预览确切路径与文件数 → 后台执行并逐项回报。"""
        if self.clear_history_worker and self.clear_history_worker.isRunning():
            self.log("清理历史数据任务正在进行中，请稍候")
            return

        dialog = ClearHistoryDialog(self.dev_type, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            self.log("清理历史数据已取消")
            return

        plan = dialog.plan()
        if not plan:
            self.log("当前选择没有匹配到可清理的历史数据")
            return

        from service.history_cleaner import plan_summary
        summary = plan_summary(plan)
        self.log(f"开始清理历史数据：{summary['items']} 个条目、{summary['files']} 个文件")
        for item in plan:
            self.log(f"  待清理: {item.label}（{item.file_count} 个文件）-> {item.path}")

        self.control_panel.clear_history_button.setEnabled(False)
        self.clear_history_worker = ClearHistoryWorker(plan, self)
        self.clear_history_worker.item_done.connect(self.on_clear_history_item)
        self.clear_history_worker.finished_signal.connect(self.on_clear_history_finished)
        self.clear_history_worker.start()

    def on_clear_history_item(self, result):
        """单条目清理完成：逐项回报（可审计）。"""
        scope_text = {"monitor_data": "监控基准数据", "logs": "运行日志",
                      "screenshot": "截图", "switch_log": "开关机日志",
                      "excel": "Excel 报表"}.get(result.scope, result.scope)
        if result.ok:
            self.log(f"[清理] {scope_text}·{result.label} 已删除 {result.removed} 个文件（{result.path}）")
        else:
            self.log(f"[清理] {scope_text}·{result.label} 删除失败（{result.path}）: "
                     f"{result.error or '部分文件失败'}", is_error=True)

    def on_clear_history_finished(self, removed, failed, summary):
        """清理结束：汇总 + 恢复按钮 + 重置 Excel 句柄。"""
        self.log(summary, is_error=failed > 0)
        self.excel_exporter.reset()
        # 基准数据可能已被删除 → 重新加载内存中的历史数据
        try:
            from service.file_service import FileService
            if self.monitor_thread and self.monitor_thread.monitor_service:
                self.monitor_thread.monitor_service.device_data = FileService.load_device_data()
        except Exception as e:
            logger.debug("[清理] 重新加载监控数据失败: %s", e)
        self.control_panel.clear_history_button.setEnabled(True)

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
        self.refresh_controller.stop()
        self.background_discovery.stop()
        if self.enable_adb_worker and self.enable_adb_worker.isRunning():
            self.enable_adb_worker.stop()
            self.enable_adb_worker.wait()
        if self.clear_history_worker and self.clear_history_worker.isRunning():
            self.clear_history_worker.wait(5000)
        try:
            from service import ssh_service
            ssh_service.close_all()
        except Exception:  # pylint: disable=broad-except
            pass
        event.accept()
    
    def refresh_device_list(self):
        """刷新设备列表 - 通过控制器异步执行，避免阻塞主线程"""
        try:
            self.control_panel.refresh_button.setDisabled(True)
            # 暂停后台心跳：避免与本次扫描的探测包相互干扰
            self.background_discovery.stop()
            self.devices = []
            self._discovered_count = 0
            self.refresh_controller.refresh(self.control_panel.dev_type)
        except Exception as e:
            self.log(f"刷新设备列表失败: {str(e)}", is_error=True)
            self.control_panel.refresh_button.setEnabled(True)

    def manual_find_device_list(self, targets):
        """手动找卡 - 按输入的 IP/区间/CIDR 定向扫描（广播兜底），异步执行。"""
        try:
            self.control_panel.refresh_button.setDisabled(True)
            # 暂停后台心跳：避免与本次扫描的探测包相互干扰
            self.background_discovery.stop()
            self.devices = []
            self._discovered_count = 0
            self.refresh_controller.refresh(self.control_panel.dev_type, targets)
        except Exception as e:
            self.log(f"手动找卡失败: {str(e)}", is_error=True)
            self.control_panel.refresh_button.setEnabled(True)

    def enable_adb_for_selected(self):
        """对勾选的 Android 设备下发协议 Set Development 开启 ADB（usb+tcp/永久）。"""
        if self.enable_adb_worker and self.enable_adb_worker.isRunning():
            self.log("开启 ADB 任务正在进行中，请稍候")
            return

        from service.device_utils import is_android_device

        devices = list(getattr(self.device_list_view, 'selected_devices_info', []) or [])
        targets = [(d['id'], d['ip']) for d in devices if is_android_device(d['id'])]
        if not targets:
            self.log("请先勾选 Android 类型的设备（Linux 设备无需开启 ADB）", is_error=True)
            return

        self.control_panel.enable_adb_button.setEnabled(False)
        self.log(f"开始为 {len(targets)} 台 Android 设备开启 ADB（协议 Set Development）...")

        self.enable_adb_worker = EnableAdbWorker(targets, self)
        self.enable_adb_worker.progress_signal.connect(self.log)
        self.enable_adb_worker.device_done.connect(self.on_enable_adb_device_done)
        self.enable_adb_worker.finished_signal.connect(self.on_enable_adb_finished)
        self.enable_adb_worker.start()

    def on_enable_adb_device_done(self, device_id, ok, message):
        """单台设备开启 ADB 完成：刷新表格与内存数据。"""
        if ok:
            self.device_list_view.update_device_info_field(device_id, 'adb_status', '开启')
            for info in (self.devices or []):
                if info.get('id') == device_id:
                    info['adb_status'] = '开启'
                    break
            self.log(f"{device_id} 开启 ADB 成功 - {message}")
        else:
            self.log(f"{device_id} 开启 ADB 失败 - {message}", is_error=True)

    def on_enable_adb_finished(self, ok_count, total):
        """开启 ADB 任务结束：恢复按钮并汇总结果。"""
        self.control_panel.enable_adb_button.setEnabled(True)
        self.log(f"开启 ADB 完成：成功 {ok_count}/{total}")
        self.enable_adb_worker = None

    def on_device_found(self, device_id, ip):
        """找卡「发现即上报」：**立即**插入占位行（先显示设备ID/IP），详情随后补全。

        这样扫描到设备的那一刻表格就有内容，不必等全部设备信息收集完（原先要等
        十几秒才看到任何一行）。
        """
        self._discovered_count += 1
        self.control_panel.update_refresh_status(
            f"已发现 {self._discovered_count} 台设备（正在补全信息...）")
        logger.debug("发现设备 %s (%s)", device_id, ip)
        if not self._is_supported_device(device_id):
            return
        if self.devices is None:
            self.devices = []
        info = self._placeholder_device(device_id, ip)
        self.devices.append(info)
        self.device_list_view.add_or_update_device(info)

    def _is_supported_device(self, device_id):
        """该设备ID是否既在支持型号内、又匹配当前设备类型筛选（与找卡层同口径）。"""
        head = device_id.split('-')[0]
        if head not in supported_dev_types and device_id not in supported_dev_types:
            return False
        pattern = self.dev_type.replace('-', '|')
        return bool(re.match(f'^({pattern})', device_id))

    @staticmethod
    def _placeholder_device(device_id, ip):
        """扫描刚发现设备时的占位信息：先给出可确定的 ID/IP/密码，其余标注「查询中」。"""
        return {
            'id': device_id,
            'ip': ip,
            'password': ToolService.get_password(device_id),
            'mac_address': '查询中…',
            'device_name': '查询中…',
            'system_type': '查询中…',
            'ota_version': '查询中…',
            'main_version': '查询中…',
            'adb_status': '未知',
        }

    def on_device_row_updated(self, device_info):
        """单台设备详情补全：**增量**更新表格对应行（无需等全部设备完成）。"""
        if not device_info or not device_info.get('id'):
            return
        self.device_list_view.add_or_update_device(device_info)
        if self.devices is None:
            self.devices = []
        for existing in self.devices:
            if existing.get('id') == device_info['id']:
                existing.update(device_info)
                return
        self.devices.append(dict(device_info))

    def on_devices_ready(self, devices):
        """设备信息收集完成：更新表格与状态栏。"""
        self.devices = devices
        self.update_device_list(devices)
        self.control_panel.update_refresh_status(f"当前设备数: {len(devices)}")
        self.log(f"设备列表已刷新，共 {len(devices)} 台设备")
        # 以最新设备集合为基线，避免后台心跳把全部设备误报为「上线」
        self.background_discovery.seed([(d['id'], d['ip']) for d in devices])
        self._sync_background_discovery()

    def _sync_background_discovery(self):
        """按「监控是否运行」决定后台心跳的启停（监控运行时不跑）。"""
        monitoring = bool(self.monitor_thread and self.monitor_thread.isRunning())
        if BACKGROUND_DISCOVERY_ENABLED and not monitoring and self.devices:
            self.background_discovery.set_filter(self._is_supported_device)
            self.background_discovery.start()
        else:
            self.background_discovery.stop()

    def on_background_devices_changed(self, added, removed):
        """后台心跳发现设备上线/下线：**只做增量变更**，不做整表刷新。

        - 新增：逐台后台补全信息，到位后**插入一行**（不重扫、不重建整表）；
        - 下线：**只移除该行**；
        - 无变化时心跳根本不发信号，因此不会有任何多余的表格刷新。

        （旧实现是触发 `refresh_device_list()` 全量重扫 → 11 台重新取一遍，约 8s。）
        """
        parts = []
        if added:
            parts.append("上线 " + ", ".join(f"{dev}({ip})" for dev, ip in added))
        if removed:
            parts.append("下线 " + ", ".join(f"{dev}({ip})" for dev, ip in removed))
        self.log("- " + "；".join(parts))

        for device_id, _ip in removed:
            if self.device_list_view.remove_device(device_id):
                self.devices = [d for d in (self.devices or []) if d.get('id') != device_id]
                logger.info("设备: %s 下线", device_id)

        if added:
            # 仅对新增设备补全信息（并行、逐台回报 → 插入/更新该行）
            self.refresh_controller.fetch_device_info(added)

        count = len(self.devices or [])
        self.control_panel.update_refresh_status(f"当前设备数: {count}")

    def on_refresh_failed(self, error_msg):
        """设备查找失败回调。"""
        self.log(error_msg, is_error=True)
        self.control_panel.update_refresh_status(error_msg, is_error=True)
        self.control_panel.refresh_button.setEnabled(True)

    def on_refresh_finished(self):
        """设备查找线程结束：恢复刷新按钮。"""
        self.control_panel.refresh_button.setEnabled(True)
