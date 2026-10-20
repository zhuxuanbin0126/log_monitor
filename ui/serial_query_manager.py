from PyQt5.QtCore import QThread, pyqtSignal
import threading

from service.tool_service import ToolService
from service.adb_service import ADBService
from service.adb_device_manager import ADBDeviceManager
from service.batch_dispatch import run_grouped
from service.device_utils import is_android_device
from service.logging_service import get_logger
from service.protocol import get_device_status
from config import LEGACY_QUERY_MAX_WORKERS, QUERY_GROUP_SIZE, QUERY_MAX_WORKERS
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

    PROTOCOL_ONLY_TYPES = frozenset({
        "all", "time", "boot_time", "start_count", "sum_switch", "screenshot", "check_time",
    })
    """协议可取全的**信息类查询**：这些类型在协议可用时完全无需 adb/SSH 前置。

    文件推送（``count_init`` / ``upgrade_program``）、日志导出（``output_log``）、
    清理（``clean_switch``）仍依赖 adb/SSH，故不在此列。
    """

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
        """按「协议可用性」分池执行：协议池高并发，legacy（adb/SSH）池低并发。"""
        try:
            total_devices = len(self.devices_info)
            android_devices = [d for d in self.devices_info if is_android_device(d[0])]
            ssh_devices = [d for d in self.devices_info if not is_android_device(d[0])]

            protocol_devices, legacy_devices = self._split_by_protocol(android_devices)
            logger.info(
                "[串行管理器] 查询类型=%s，共 %s 台：协议池 %s 台（并发 %s）、"
                "adb/SSH 池 %s 台（并发 %s）、SSH 串行 %s 台",
                self.query_type, total_devices, len(protocol_devices),
                min(len(protocol_devices), QUERY_MAX_WORKERS) or 0,
                len(legacy_devices),
                min(len(legacy_devices), LEGACY_QUERY_MAX_WORKERS) or 0,
                len(ssh_devices),
            )

            # 协议池：每台设备独立 TCP，可安全高并发
            if protocol_devices:
                self._process_parallel(protocol_devices, total_devices,
                                      min(len(protocol_devices), QUERY_MAX_WORKERS))

            # legacy 池：走 adb/SSH，adb server 单进程，低并发避免相互干扰
            if legacy_devices:
                self._process_parallel(legacy_devices, total_devices,
                                      min(len(legacy_devices), LEGACY_QUERY_MAX_WORKERS))

            # Linux 设备：SSH 串行
            base = len(protocol_devices) + len(legacy_devices)
            for idx, (device_id, ip, password, system_type) in enumerate(ssh_devices):
                if not self.is_running:
                    break
                logger.info(
                    "[串行管理器] 开始处理设备 %s/%s: %s (%s)",
                    idx + 1 + base, total_devices, device_id, ip)
                self._set_state(self.STATE_CONNECTING, device_id)
                self.progress_signal.emit(idx + 1 + base, total_devices)
                self._process_single_device(device_id, ip, password, system_type, needs_adb=False)

            self.finished_signal.emit(total_devices)

        except Exception as e:
            self.error_signal.emit("Unknown", f"串行查询管理器出错: {str(e)}")

    def _split_by_protocol(self, android_devices):
        """按「协议是否可用」把 Android 设备分成协议池与 legacy 池。

        仅当本次查询类型是**协议可取全**的信息类查询（见 ``PROTOCOL_ONLY_TYPES``）时
        才做此拆分；文件推送/日志导出等仍走 adb/SSH，归入 legacy 池。
        """
        if self.query_type not in self.PROTOCOL_ONLY_TYPES:
            return [], list(android_devices)
        protocol_devices, legacy_devices = [], []
        for device in android_devices:
            ip = device[1]
            try:
                supported = get_device_status(ip) is not None
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("[串行管理器] 协议支持面判定失败 %s: %s", ip, exc)
                supported = False
            (protocol_devices if supported else legacy_devices).append(device)
        return protocol_devices, legacy_devices

    def _process_parallel(self, devices, total_devices, workers):
        """分组限流地处理一批设备（每台内部自行决定走协议还是 adb/SSH）。

        组内并发受限、组间串行：把峰值负载钉在 ``QUERY_GROUP_SIZE`` 量级，
        避免几十台设备同时执行时压垮 adb server / 网卡 / 设备端连接数。
        """
        completed = [0]
        completed_lock = threading.Lock()

        def _handle_device(device_info):
            device_id, ip, password, system_type = device_info
            try:
                self._process_single_device(device_id, ip, password, system_type,
                                            needs_adb=is_android_device(device_id))
            finally:
                with completed_lock:
                    completed[0] += 1
                    current = completed[0]
                self.progress_signal.emit(current, total_devices)
            return device_id

        run_grouped(devices, _handle_device,
                    group_size=QUERY_GROUP_SIZE, max_workers=workers,
                    should_stop=lambda: not self.is_running)
    
    def _protocol_ready(self, device_id, ip):
        """该设备本次查询能否**完全**走协议（无需 adb/SSH 前置）。"""
        if self.query_type not in self.PROTOCOL_ONLY_TYPES:
            return False
        if not is_android_device(device_id):
            return False
        try:
            return get_device_status(ip) is not None
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("[串行管理器] 协议支持面判定失败 %s: %s", ip, exc)
            return False

    def _process_single_device(self, device_id, ip, password, system_type, needs_adb=False):
        """处理单个设备的完整查询流程。

        **协议可取全的信息类查询**（``PROTOCOL_ONLY_TYPES``）在协议可用时跳过
        adb connect 与 SSH 初始化 —— 这是「查询全部信息」单机也要等 >5s 的主因。
        """
        protocol_ready = self._protocol_ready(device_id, ip)
        if protocol_ready:
            logger.info("[串行管理器] %s(%s) 协议可用，跳过 adb/SSH 前置", device_id, ip)
        elif is_android_device(device_id):
            try:
                # 只断开**本设备**的 adb 连接：并行处理多台设备时，
                # 全局 `adb disconnect` 会误伤其它正在查询的设备
                ADBService.disconnect_device(ip)
            except Exception as e:
                logger.warning("[串行管理器] 断开设备 %s 的ADB连接时出错: %s", ip, e)
            self.msleep(300)
        # 非 Android（Linux/SSH）设备无需 adb 断开与等待

        adb_just_enabled = False
        try:
            from business.device_monitor_service import DeviceMonitorService
            dev_type = device_id.split('-')[0] if '-' in device_id else 'C16H'
            monitor_service = DeviceMonitorService(dev_type)

            if not protocol_ready and needs_adb:
                # Android 设备：检测/开启网络 ADB（仅协议不可用时才需要）
                self._set_state(self.STATE_CONNECTING, device_id)
                prev_status = ADBDeviceManager.get_cached_status(device_id)
                logger.info("[串行管理器] %s 协议不可用，尝试确保网络 ADB 已开启", device_id)
                adb_ok, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                # 通知 UI 更新 ADB 状态
                self.state_signal.emit(device_id, f"ADB:{'开启' if adb_ok else '未开启'}")
                if adb_ok and prev_status != '开启':
                    adb_just_enabled = True

            # 非协议设备不再「先跑一次 plink echo y 初始化」：
            # Linux 走 ssh_service（paramiko 自动接受主机密钥、复用连接），
            # 只有真的回退到 plink/pscp 且报「密钥未缓存」时才就地接受一次。

            self._set_state(self.STATE_QUERYING)
            logger.info("[串行管理器] %s 开始执行查询（类型=%s，通道=%s）",
                        device_id, self.query_type,
                        "协议" if protocol_ready else "adb/SSH")

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

            logger.info("[串行管理器] %s 查询完成，结果键=%s", device_id, sorted(results.keys()))
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
            if not protocol_ready and is_android_device(device_id):
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

