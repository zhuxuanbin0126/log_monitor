from PyQt5.QtCore import QThread, pyqtSignal
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from service.tool_service import ToolService
from service.adb_service import ADBService
from service.adb_device_manager import ADBDeviceManager
from service.device_utils import is_android_device
from service.logging_service import get_logger
from business.query_dispatcher import build_query_dispatch

logger = get_logger(__name__)


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
            logger.warning("[_DeviceInfoRefresher] %s 刷新失败: %s", self.device_id, e)


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
        self._csv_lock = threading.Lock()
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
                logger.info(
                    "[串行管理器] 开始处理设备 %s/%s: %s (%s)",
                    idx + 1 + len(adb_devices), total_devices, device_id, ip,
                )
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
        completed_lock = threading.Lock()
        
        def _handle_adb_device(device_info):
            nonlocal completed
            device_id, ip, password, system_type = device_info
            try:
                self._process_single_device(device_id, ip, password, system_type, needs_adb=True)
            finally:
                with completed_lock:
                    completed += 1
                    current = completed
                self.progress_signal.emit(current, total_devices)
        
        with ThreadPoolExecutor(max_workers=min(adb_count, 4)) as executor:
            futures = [executor.submit(_handle_adb_device, d) for d in adb_devices]
            for f in as_completed(futures):
                if not self.is_running:
                    break
                try:
                    f.result(timeout=120)
                except Exception as e:
                    logger.warning("[并行管理器] 设备任务异常: %s", e)
    
    def _process_single_device(self, device_id, ip, password, system_type, needs_adb=False):
        """处理单个设备的完整查询流程"""
        adb_just_enabled = False
        try:
            # 只断开**本设备**的 adb 连接：并行处理多台设备时，
            # 全局 `adb disconnect` 会误伤其它正在查询的设备
            ADBService.disconnect_device(ip)
        except Exception as e:
            logger.warning("[串行管理器] 断开设备 %s 的ADB连接时出错: %s", ip, e)
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
            dispatch = build_query_dispatch(
                monitor_service, device_id, ip, password, system_type, results,
                switch_log_file=self.switch_log_file,
                custom_file_paths=self.custom_file_paths,
                query_count=self.query_count,
                csv_lock=self._csv_lock,
            )
            # 「查询全部信息」交由执行引擎一次编排；其余类型仍走单项 handler
            if self.query_type == "all":
                dispatch["all"]()
            else:
                dispatch[self.query_type]()
            
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
                # 同上：并行场景下只断开本设备，避免误伤其它设备
                ADBService.disconnect_device(ip)
            except Exception as e:
                logger.warning("[串行管理器] 设备 %s 操作完成后断开ADB连接时出错: %s", device_id, e)

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

