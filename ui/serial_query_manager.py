from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy

from .query_thread import QueryThread
from service.tool_service import ToolService
from service.adb_service import ADBService
from service.adb_device_manager import ADBDeviceManager
from service.device_utils import is_android_device
from config import get_device_remote_path


class _DeviceInfoRefresher(QThread):
    """后台线程：ADB 开启成功后异步刷新设备信息，避免阻塞查询线程"""
    info_ready = pyqtSignal(str, dict)  # device_id, info_dict

    def __init__(self, device_id, ip, password):
        super().__init__()
        self.device_id = device_id
        self.ip = ip
        self.password = password

    def run(self):
        try:
            from service.device_utils import ADB_PATH
            info = {}
            success, serial = ADBDeviceManager.ensure_adb_connected(
                self.ip, self.password, self.device_id
            )
            if not success:
                return

            mac_stdout, _, _ = ToolService.run_command(
                f'{ADB_PATH} -s {serial} shell cat /sys/class/net/eth0/address', timeout=5
            )
            name_stdout, _, _ = ToolService.run_command(
                f'{ADB_PATH} -s {serial} shell getprop ro.product.model', timeout=5
            )
            version_stdout, _, _ = ToolService.run_command(
                f'{ADB_PATH} -s {serial} shell getprop ro.build.version', timeout=5
            )

            info['mac_address'] = mac_stdout.strip() if mac_stdout else 'N/A'
            info['device_name'] = name_stdout.strip() if name_stdout else 'N/A'
            info['ota_version'] = version_stdout.strip() if version_stdout else 'N/A'
            info['system_type'] = 'Android'
            info['adb_status'] = '开启'

            dumpsys_out, _, _ = ToolService.run_command(
                f'{ADB_PATH} -s {serial} shell dumpsys package cn.huidu.lcd.player',
                timeout=10
            )
            if dumpsys_out:
                for line in dumpsys_out.strip().split('\n'):
                    if 'versionName' in line:
                        parts = line.split('=', 1)
                        if len(parts) > 1:
                            info['main_version'] = parts[1].strip()
                            break

            self.info_ready.emit(self.device_id, info)
        except Exception as e:
            print(f"[_DeviceInfoRefresher] {self.device_id} 刷新失败: {e}")


class SerialQueryManager(QThread):
    """串行查询管理器，确保设备逐个依次执行，避免ADB连接冲突"""
    
    result_signal = pyqtSignal(str, dict)
    error_signal = pyqtSignal(str, str)  # (device_id, error_msg)
    finished_signal = pyqtSignal(int)
    state_signal = pyqtSignal(str, str)  # (device_id, state) 状态追踪信号
    progress_signal = pyqtSignal(int, int)  # (current, total) 进度信号
    
    # 查询状态枚举
    STATE_IDLE = "IDLE"
    STATE_CONNECTING = "CONNECTING"
    STATE_QUERYING = "QUERYING"
    STATE_DONE = "DONE"
    STATE_ERROR = "ERROR"
    
    # "查询全部信息" 仅包含以下 4 项查询（明确排除：校时、截图、发送节目、初始化、导出日志、清空次数）
    ALL_QUERY_KEYS = ["time", "boot_time", "start_count", "sum_switch"]
    
    # 保存活跃的设备信息刷新线程引用，防止被 GC 销毁导致 QThread 崩溃
    _active_refreshers = set()
    
    def __init__(self, devices_info, query_type, control_panel, switch_log_file, custom_file_paths=None):
        super().__init__()
        self.devices_info = devices_info
        self.query_type = query_type
        self.control_panel = control_panel
        self.switch_log_file = switch_log_file
        self.custom_file_paths = custom_file_paths
        self.query_count = [0]
        self.is_running = True
        self.mutex = QMutex()
        self._current_device = ""
        
    def _set_state(self, state, device_id=None):
        """设置当前查询状态并发送信号"""
        if device_id:
            self._current_device = device_id
        self.state_signal.emit(self._current_device, state)
        
    def run(self):
        """逐个执行设备查询/操作，支持并行模式"""
        try:
            total_devices = len(self.devices_info)
            # 分离 ADB 设备和 SSH 设备
            adb_devices = [d for d in self.devices_info if is_android_device(d[0])]
            ssh_devices = [d for d in self.devices_info if not is_android_device(d[0])]
            
            # 先并行处理 ADB 设备
            if adb_devices:
                self._process_adb_parallel(adb_devices, total_devices)
            
            # 再串行处理 SSH/Linux 设备
            for idx, (device_id, ip, password, system_type) in enumerate(ssh_devices):
                if not self.is_running:
                    break
                print(f"[串行管理器] 开始处理设备 {idx + 1 + len(adb_devices)}/{total_devices}: {device_id} ({ip})")
                self._set_state(self.STATE_CONNECTING, device_id)
                self.progress_signal.emit(idx + 1 + len(adb_devices), total_devices)
                self._process_single_device(device_id, ip, password, system_type, needs_adb=False)
            
            self.finished_signal.emit(total_devices)
            
        except Exception as e:
            self.error_signal.emit("Unknown", f"串行查询管理器出错: {str(e)}")
    
    def _process_adb_parallel(self, adb_devices, total_devices):
        """并行处理 ADB 设备（每个设备独立 ADB 连接）"""
        adb_count = len(adb_devices)
        completed = 0
        
        def _handle_adb_device(device_info):
            device_id, ip, password, system_type = device_info
            try:
                self._process_single_device(device_id, ip, password, system_type, needs_adb=True)
            finally:
                nonlocal completed
                completed += 1
                self.progress_signal.emit(completed, total_devices)
        
        with ThreadPoolExecutor(max_workers=min(adb_count, 4)) as executor:
            futures = [executor.submit(_handle_adb_device, d) for d in adb_devices]
            for f in as_completed(futures):
                if not self.is_running:
                    break
                try:
                    f.result(timeout=120)
                except Exception as e:
                    print(f"[并行管理器] 设备任务异常: {e}")
    
    def _process_single_device(self, device_id, ip, password, system_type, needs_adb=False):
        """处理单个设备的完整查询流程"""
        adb_just_enabled = False
        try:
            ToolService.adb_disconnect()
        except Exception as e:
            print(f"[串行管理器] 断开ADB连接时出错: {e}")
        self.msleep(300)
        
        try:
            from business.device_monitor_service import DeviceMonitorService
            dev_type = device_id.split('-')[0] if '-' in device_id else 'C16H'
            monitor_service = DeviceMonitorService(dev_type)
            
            # Android 设备：使用 ADBDeviceManager 检测/开启网络 ADB
            if needs_adb:
                self._set_state(self.STATE_CONNECTING, device_id)
                prev_status = ADBDeviceManager.get_cached_status(device_id)
                adb_ok, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                # 通知 UI 更新 ADB 状态
                self.state_signal.emit(device_id, f"ADB:{'开启' if adb_ok else '未开启'}")
                if adb_ok and prev_status != '开启':
                    adb_just_enabled = True
            
            # 始终初始化 SSH 连接（作为 fallback，部分旧逻辑仍依赖 SSH）
            ToolService.initialize_connection(ip, password)
            
            self._set_state(self.STATE_QUERYING)

            results = {}
            dispatch = self._build_query_dispatch(
                monitor_service, device_id, ip, password, system_type, results
            )
            dispatch[self.query_type]()
            if self.query_type == "all":
                for key in self.ALL_QUERY_KEYS:
                    dispatch[key]()
            
            self._set_state(self.STATE_DONE)
            self.result_signal.emit(device_id, results)

            # ADB 刚刚由未开启转为开启 → 后台异步刷新设备信息
            if adb_just_enabled:
                self._start_info_refresher(device_id, ip, password)
            
        except Exception as e:
            self._set_state(self.STATE_ERROR)
            error_msg = f"查询设备 {device_id} ({ip}) 时出错: {str(e)}"
            self.error_signal.emit(device_id, error_msg)
        
        finally:
            try:
                ToolService.adb_disconnect()
            except Exception as e:
                print(f"[串行管理器] 设备 {device_id} 操作完成后断开ADB连接时出错: {e}")

    def _start_info_refresher(self, device_id, ip, password):
        """启动后台线程刷新设备信息，并通过信号通知 UI"""
        refresher = _DeviceInfoRefresher(device_id, ip, password)
        refresher.info_ready.connect(self._on_refreshed_info)
        refresher.finished.connect(lambda: self._release_refresher(refresher))
        refresher.finished.connect(refresher.deleteLater)
        SerialQueryManager._active_refreshers.add(refresher)
        refresher.start()

    def _release_refresher(self, refresher):
        """刷新线程结束时从集合中移除引用，允许 GC"""
        SerialQueryManager._active_refreshers.discard(refresher)

    def _on_refreshed_info(self, device_id, info):
        """设备信息刷新完成后转发给 UI"""
        # 复用 state_signal 携带完整信息，主窗口槽函数中识别并刷新表格
        self.state_signal.emit(device_id, f"INFO_REFRESH:{info}")
    
    def stop(self):
        """停止执行"""
        self.is_running = False

    def _build_query_dispatch(self, monitor_service, device_id, ip, password,
                               system_type, results):
        """构建查询策略分发表，将查询类型映射到处理函数"""
        custom_paths = self.custom_file_paths
        switch_log_file = self.switch_log_file
        query_count = self.query_count

        def _time():
            formatted_remote_time, time_diff = monitor_service.get_device_time_info(ip, password, device_id)
            results['device_time'] = {
                'formatted_remote_time': formatted_remote_time,
                'time_diff': time_diff,
            }

        def _boot_time():
            results['boot_time'] = monitor_service.get_uptime_info(ip, password, device_id)

        def _start_count():
            results['start_count'] = monitor_service.get_start_count(ip, password, device_id)

        def _count_init():
            results['count_init'] = monitor_service.count_init_setting(
                ip, password, device_id, system_type, custom_file_paths=custom_paths
            )

        def _sum_switch():
            path = get_device_remote_path(system_type)
            switch_time, network_time, success, error_msg = monitor_service.sum_switch_count(ip, password, device_id, path)
            if success:
                if switch_log_file is not None:
                    query_count[0] += 1
                    switch_log_file.write(f"{device_id},{switch_time},{network_time}\n")
                results['sum_switch'] = f"{device_id} 当前开关机次数为：{switch_time} 网络开关机次数为：{network_time}"
            else:
                results['sum_switch'] = error_msg

        def _clean_switch():
            path = get_device_remote_path(system_type)
            success, error_msg = monitor_service.clean_switch_log(ip, password, device_id, path)
            results['clean_switch'] = f"{device_id} 开关机记录已清除" if success else error_msg

        def _check_time():
            results['check_time'] = monitor_service.ntptime_checkout_time(ip, password, device_id, system_type)

        def _upgrade_program():
            results['upgrade_program'] = monitor_service.upgrade_program(
                ip, password, device_id, system_type, custom_file_paths=custom_paths
            )

        def _screenshot():
            results['screenshot'] = monitor_service.capture_screenshot(device_id, ip, password, system_type)

        def _output_log():
            path = get_device_remote_path(system_type)
            _, output_log = monitor_service.switch_log_output(ip, password, device_id, system_type, path)
            results['output_log'] = output_log

        def _all():
            pass  # 由 ALL_QUERY_KEYS 控制子处理器调用

        return {
            "all": _all,
            "time": _time,
            "boot_time": _boot_time,
            "start_count": _start_count,
            "count_init": _count_init,
            "sum_switch": _sum_switch,
            "clean_switch": _clean_switch,
            "check_time": _check_time,
            "upgrade_program": _upgrade_program,
            "screenshot": _screenshot,
            "output_log": _output_log,
        }
