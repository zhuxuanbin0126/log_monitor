from PyQt5.QtCore import QThread, pyqtSignal
import socket
import threading

from service.tool_service import ToolService
from service.adb_service import ADBService
from service.adb_device_manager import ADBDeviceManager
from service.batch_dispatch import run_windowed
from service.device_utils import is_android_device
from service.logging_service import get_logger
from service.protocol import get_device_status
from service.task_control import GLOBAL_TASK
from config import (
    DEVICE_PROBE_TIMEOUT, LEGACY_QUERY_MAX_WORKERS, LINUX_SSH_MAX_WORKERS,
    PROTOCOL_PORT, QUERY_MAX_WORKERS, SCREENSHOT_MAX_WORKERS,
)
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
    STATE_OFFLINE = "OFFLINE"
    """派发前 TCP 探测不可达（掉电/掉线）：本轮跳过，结束后补跑一次"""

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
        self.offline_devices = []
        """本轮因 TCP 不可达（离线）被跳过的设备；任务结束后会再试一次，
        仍不可达的会留在未完成清单里（可「继续执行上一个任务」）。"""
        
    def _set_state(self, state, device_id=None):
        """设置当前查询状态并发送信号"""
        if device_id:
            self._current_device = device_id
        self.state_signal.emit(self._current_device, state)
        
    def run(self):
        """按「协议可用性」分池执行：协议池高并发，legacy（adb/SSH）池低并发。"""
        try:
            total_devices = len(self.devices_info)
            # 任务登记由调用方在启动前完成（GLOBAL_TASK.begin），
            # 这样「中断任务」在分池判定阶段就已可用。

            android_devices = [d for d in self.devices_info if is_android_device(d[0])]
            ssh_devices = [d for d in self.devices_info if not is_android_device(d[0])]

            protocol_devices, legacy_devices = self._split_by_protocol(android_devices)
            ssh_limit = min(len(ssh_devices), LINUX_SSH_MAX_WORKERS) or 0
            logger.info(
                "[任务管理器] 任务类型=%s，共 %s 台：协议池 %s 台（并发 %s）、"
                "adb/SSH 池 %s 台（并发 %s）、Linux SSH 池 %s 台（并发 %s）",
                self.query_type, total_devices, len(protocol_devices),
                self._protocol_limit(len(protocol_devices)) or 0,
                len(legacy_devices),
                min(len(legacy_devices), LEGACY_QUERY_MAX_WORKERS) or 0,
                len(ssh_devices), ssh_limit,
            )

            # 协议池：每台设备独立 TCP，可安全高并发
            processed = 0
            if protocol_devices:
                processed += self._process_parallel(
                    protocol_devices, total_devices,
                    self._protocol_limit(len(protocol_devices)), base=processed)

            # legacy 池：走 adb/SSH，adb server 单进程，低并发避免相互干扰
            if legacy_devices:
                processed += self._process_parallel(
                    legacy_devices, total_devices,
                    min(len(legacy_devices), LEGACY_QUERY_MAX_WORKERS),
                    base=processed)

            # Linux 设备：SSH 并发（每台一条独立连接，小并发即够且互不干扰）
            if ssh_devices:
                processed += self._process_parallel(
                    ssh_devices, total_devices, ssh_limit, base=processed)

            # 离线补跑：任务期间掉线（断电/网线松动）又在结束时恢复的设备再试一次
            if self.offline_devices and not self._should_stop():
                retry = list(self.offline_devices)
                self.offline_devices = []
                logger.info("[任务管理器] 对 %s 台离线设备再试一次", len(retry))
                self._process_parallel(
                    retry, total_devices, min(len(retry), QUERY_MAX_WORKERS),
                    base=processed, advance=False)

            if self.offline_devices:
                names = ", ".join(f"{d[0]}({d[1]})" for d in self.offline_devices)
                logger.warning("[任务管理器] 仍有 %s 台设备离线未完成：%s",
                               len(self.offline_devices), names)

            self.finished_signal.emit(total_devices)

        except Exception as e:
            self.error_signal.emit("Unknown", f"串行查询管理器出错: {str(e)}")
        finally:
            GLOBAL_TASK.finish()

    def _protocol_limit(self, count):
        """协议池并发上限：截图单台设备侧要 4~5s，单独放宽（见 config 说明）。"""
        limit = (SCREENSHOT_MAX_WORKERS if self.query_type == "screenshot"
                 else QUERY_MAX_WORKERS)
        return min(count, limit)

    def _split_by_protocol(self, android_devices):
        """按「协议是否可用」把 Android 设备分成协议池与 legacy 池。

        仅当本次任务类型是**协议可取全**的信息类查询（见 ``PROTOCOL_ONLY_TYPES``）时
        才做此拆分；文件推送/日志导出等仍走 adb/SSH，归入 legacy 池。
        """
        if self.query_type not in self.PROTOCOL_ONLY_TYPES:
            return [], list(android_devices)
        protocol_devices, legacy_devices = [], []
        for device in android_devices:
            if self._should_stop():
                # 中断时不再浪费建连超时，未判定的一律按 legacy 交给后续跳过
                legacy_devices.append(device)
                continue
            ip = device[1]
            try:
                supported = get_device_status(ip) is not None
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("[任务管理器] 协议支持面判定失败 %s: %s", ip, exc)
                supported = False
            (protocol_devices if supported else legacy_devices).append(device)
        return protocol_devices, legacy_devices

    def _process_parallel(self, devices, total_devices, workers, base=0, advance=True):
        """**滑动窗口**并发处理一批设备（完成一台立刻补一台）。

        旧实现按 8 台分组、组间串行：组里只要有一台慢设备（协议超时后降级 adb，
        单台 15~17s），后面所有设备都要干等 —— 实测第 9 台要多等 8s。
        现在并发上限仍受控（端口/连接数不放大），但不再有「整组等待」。

        ``base`` 为前序池已处理的台数，用于把进度信号折算成全局 ``x/total``；
        ``advance=False`` 表示这是补跑轮次，不再推进进度。

        每台设备在派发前先做**秒级 TCP 可达性探测**：不可达（离线）就立刻跳过，
        不再让协议/ADB 各自等满超时；跳过的设备记到 :attr:`offline_devices`，
        任务结束后统一再试一次。
        """
        completed = [0]
        started = [0]
        counter_lock = threading.Lock()

        def _bump_progress():
            if not advance:
                return
            self.progress_signal.emit(base + completed[0], total_devices)

        def _handle_device(device_info):
            device_id, ip, password, system_type = device_info
            with counter_lock:
                started[0] += 1
                index = base + started[0]
            logger.info("[任务管理器] 开始处理设备 %s/%s: %s (%s)",
                        index, total_devices, device_id, ip)
            self._set_state(self.STATE_CONNECTING, device_id)
            GLOBAL_TASK.set_current(f"{device_id} ({ip})")

            if not self._probe_device(device_id, ip):
                # 离线：不 mark_done，设备保留在未完成清单里（可续跑）
                with counter_lock:
                    self.offline_devices.append(device_info)
                    completed[0] += 1
                self.state_signal.emit(device_id, self.STATE_OFFLINE)
                logger.info("[任务管理器] %s (%s) 不可达，本轮跳过（结束后会再试一次）",
                            device_id, ip)
                _bump_progress()
                return device_id

            try:
                self._process_single_device(device_id, ip, password, system_type,
                                            needs_adb=is_android_device(device_id))
            finally:
                GLOBAL_TASK.mark_done(device_info)
                with counter_lock:
                    completed[0] += 1
                _bump_progress()
            return device_id

        run_windowed(
            devices, _handle_device,
            max_workers=workers,
            should_stop=self._should_stop,
            on_dispatch=lambda dispatched, total: logger.info(
                "[任务管理器] 已派发 %s/%s 台（并发上限 %s）", dispatched, total, workers),
        )
        with counter_lock:
            return completed[0]

    @staticmethod
    def _probe_device(device_id, ip):
        """秒级判断设备是否可达：任一相关端口能建 TCP 即视为在线。

        - Android：协议 10001 / 网络 ADB 5555 / SSH 22；
        - Linux：只有 SSH 22。

        掉电或网线松动的设备通常直接 ``Connection refused``/超时，
        用 0.8s 超时即可判定，避免后续协议+ADB+SSH 各自等满超时（单台十几秒）。
        """
        ports = (22,) if not is_android_device(device_id) else (PROTOCOL_PORT, 5555, 22)
        for port in ports:
            try:
                with socket.create_connection((ip, port), timeout=DEVICE_PROBE_TIMEOUT):
                    return True
            except OSError:
                continue
        return False

    def _should_stop(self):
        """本地停止（关窗/新任务）或**全局中断**任一成立即停止派发。"""
        return (not self.is_running) or GLOBAL_TASK.should_stop()
    
    def _protocol_ready(self, device_id, ip):
        """该设备本次查询能否**完全**走协议（无需 adb/SSH 前置）。"""
        if self.query_type not in self.PROTOCOL_ONLY_TYPES:
            return False
        if not is_android_device(device_id):
            return False
        try:
            return get_device_status(ip) is not None
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("[任务管理器] 协议支持面判定失败 %s: %s", ip, exc)
            return False

    def _process_single_device(self, device_id, ip, password, system_type, needs_adb=False):
        """处理单个设备的完整查询流程。

        **协议可取全的信息类查询**（``PROTOCOL_ONLY_TYPES``）在协议可用时跳过
        adb connect 与 SSH 初始化 —— 这是「查询全部信息」单机也要等 >5s 的主因。
        """
        protocol_ready = self._protocol_ready(device_id, ip)
        if protocol_ready:
            logger.info("[任务管理器] %s(%s) 协议可用，跳过 adb/SSH 前置", device_id, ip)
        elif is_android_device(device_id):
            try:
                # 只断开**本设备**的 adb 连接：并行处理多台设备时，
                # 全局 `adb disconnect` 会误伤其它正在查询的设备
                ADBService.disconnect_device(ip)
            except Exception as e:
                logger.warning("[任务管理器] 断开设备 %s 的ADB连接时出错: %s", ip, e)
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
                logger.info("[任务管理器] %s 协议不可用，尝试确保网络 ADB 已开启", device_id)
                adb_ok, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                # 通知 UI 更新 ADB 状态
                self.state_signal.emit(device_id, f"ADB:{'开启' if adb_ok else '未开启'}")
                if adb_ok and prev_status != '开启':
                    adb_just_enabled = True

            # 非协议设备不再「先跑一次 plink echo y 初始化」：
            # Linux 走 ssh_service（paramiko 自动接受主机密钥、复用连接），
            # 只有真的回退到 plink/pscp 且报「密钥未缓存」时才就地接受一次。

            self._set_state(self.STATE_QUERYING)
            logger.info("[任务管理器] %s 开始执行查询（类型=%s，通道=%s）",
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

            logger.info("[任务管理器] %s 查询完成，结果键=%s", device_id, sorted(results.keys()))
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
                    logger.warning("[任务管理器] 设备 %s 操作完成后断开ADB连接时出错: %s", device_id, e)

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

    @classmethod
    def stop_refreshers(cls, timeout_ms=3000):
        """等待查询期间拉起的「设备信息刷新」线程收尾（关窗时调用）。

        这些 QThread 没有父对象、只由类级集合持有引用；若窗口先被销毁而线程仍在跑，
        解释器退出时会触发 ``QThread: Destroyed while thread is still running``。
        """
        for refresher in list(cls._active_refreshers):
            try:
                refresher.wait(timeout_ms)
            except Exception:  # pylint: disable=broad-except
                pass

