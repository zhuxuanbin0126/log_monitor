#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ADB 设备管理器
==============
负责 Android 设备的网络 ADB 状态检测、开启、以及按设备状态路由命令。
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from service.adb_service import ADBService
from service.device_utils import (
    ADB_PATH, run_command, get_tool_path, is_android_device,
)
from service.logging_service import get_logger
from service.protocol.set_query import enable_wireless_adb as protocol_enable_wireless_adb
from config import USE_PROTOCOL_QUERY

logger = get_logger(__name__)


def _log(level, message):
    """统一日志输出（ERROR/WARN/INFO）。"""
    log_method = {'ERROR': logger.error, 'WARN': logger.warning}.get(level, logger.info)
    log_method(message)


class ADBDeviceManager:
    """管理 Android 设备的网络 ADB 开启状态，并提供命令路由"""

    # 全局状态表: device_id -> '开启' | '未开启' | '不支持' | '未知'
    _adb_status_cache = {}
    _cache_lock = threading.Lock()

    # 连接池缓存: ip -> (serial, timestamp_ms)，避免频繁重复 connect/root
    _connection_pool = {}
    _pool_lock = threading.Lock()
    _pool_ttl_ms = 30000  # 连接缓存有效期 30 秒

    @classmethod
    def classify_device(cls, device_id):
        """判断设备分类：'android' 或 'linux' 或 'unknown'"""
        if is_android_device(device_id):
            return "android"
        dev_type = device_id.split('-')[0] if '-' in device_id else device_id
        if dev_type in ['C08L', 'C16L', 'D16', 'D36']:
            return "linux"
        return "unknown"

    @classmethod
    def get_cached_status(cls, device_id):
        """获取缓存的 ADB 状态"""
        with cls._cache_lock:
            return cls._adb_status_cache.get(device_id, '未开启')

    @classmethod
    def set_cached_status(cls, device_id, status):
        """设置缓存的 ADB 状态"""
        with cls._cache_lock:
            cls._adb_status_cache[device_id] = status

    @classmethod
    def check_internet_adb_enabled(cls, ip, password, device_id, timeout=5):
        """
        检测 Android 设备是否已开启网络 ADB (persist.internet_adb_enable=1)
        通过 plink SSH 执行 getprop，避免 ADB 未连接时无法检测。

        返回: (enabled: bool, current_value: str)
        """
        try:
            plink_exe = get_tool_path('plink.exe')
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "getprop persist.internet_adb_enable"'
            stdout, stderr, returncode = run_command(cmd, timeout=timeout)
            value = stdout.strip() if stdout else ""
            _log("INFO", f"getprop persist.internet_adb_enable for {device_id}({ip}): {value!r}")
            return value == "1", value
        except Exception as e:
            _log("ERROR", f"检测 persist.internet_adb_enable 失败: {e}")
            return False, str(e)

    @classmethod
    def enable_internet_adb(cls, ip, password, device_id):
        """
        对 Android 设备开启网络 ADB：
        1. 优先走 MagicPlayer 协议 Set Development（adbMode=tcp, adbTimer=0）
        2. 协议未启用/未生效时回落 plink：setprop 开网络 ADB + 重启 adbd
        3. 统一用 adb connect 实际验证连通性（而非仅 getprop）

        返回: (success: bool, message: str)
        """
        try:
            protocol_ok, protocol_msg = cls._try_protocol_enable_wireless_adb(ip, device_id)
            if not protocol_ok:
                _log("INFO", f"{device_id} 协议通道不可用（{protocol_msg}），走 plink 兜底")
                cls._enable_internet_adb_via_plink(ip, password)

            _log("INFO", f"正在验证 {device_id} ADB 连通性...")
            ok, serial, detail = cls._verify_adb_connect(ip, device_id)
            if ok:
                source = "协议" if protocol_ok else "plink"
                _log("INFO", f"{device_id} 网络 ADB 已开启（{source}），serial={serial}")
                return True, f"网络 ADB 已开启（{source}），serial={serial}"

            # 协议下发成功但端口未通 → 再用 plink 重启 adbd 后重试一次
            if protocol_ok:
                _log("WARN", f"协议开启后 adb connect 未连通（{detail}），回落 plink 重试")
                cls._enable_internet_adb_via_plink(ip, password)
                ok, serial, detail = cls._verify_adb_connect(ip, device_id)
                if ok:
                    _log("INFO", f"{device_id} 网络 ADB 已开启（plink 兜底），serial={serial}")
                    return True, f"网络 ADB 已开启（plink 兜底），serial={serial}"

            # adb devices 状态 + getprop 仅作为辅助诊断（不再作为成败判据）
            state = ADBService.list_devices().get(f"{ip}:5555", "未列出")
            _, prop_value = cls.check_internet_adb_enabled(ip, password, device_id, timeout=3)
            _log("ERROR", f"{device_id} adb connect 验证失败: adb状态={state}, "
                          f"persist.internet_adb_enable={prop_value!r}, {detail}")
            return False, (f"adb connect 验证失败（adb状态={state}, "
                           f"persist.internet_adb_enable={prop_value!r}）")

        except Exception as e:
            _log("ERROR", f"开启网络 ADB 失败: {e}")
            return False, str(e)

    @classmethod
    def _enable_internet_adb_via_plink(cls, ip, password):
        """plink 兜底：setprop 持久化开启网络 ADB + 重启 adbd 服务。"""
        plink_exe = get_tool_path('plink.exe')
        base_cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}"'

        # 1. 设置持久化属性开启网络 ADB
        run_command(f'{base_cmd} "setprop persist.internet_adb_enable 1"', timeout=5)
        time.sleep(0.3)

        # 2. 设置 ADB TCP 端口
        run_command(f'{base_cmd} "setprop service.adb.tcp.port 5555"', timeout=5)
        time.sleep(0.3)

        # 3. 重启 adbd 服务
        run_command(f'{base_cmd} "stop adbd"', timeout=5)
        time.sleep(0.5)
        run_command(f'{base_cmd} "start adbd"', timeout=5)
        time.sleep(2)

    @classmethod
    def _try_protocol_enable_wireless_adb(cls, ip, device_id):
        """协议 Set Development 开启无线 ADB；返回 ``(是否成功, 说明)``。"""
        if not USE_PROTOCOL_QUERY:
            return False, "协议通道未启用"
        try:
            ok, msg = protocol_enable_wireless_adb(ip)
        except Exception as e:
            _log("WARN", f"{device_id} 协议开启无线 ADB 异常: {e}")
            return False, f"协议异常: {e}"
        if ok:
            _log("INFO", f"{device_id} 已通过协议下发开启无线 ADB: {msg}")
        else:
            _log("WARN", f"{device_id} 协议开启无线 ADB 失败: {msg}")
        return ok, msg

    @classmethod
    def _verify_adb_connect(cls, ip, device_id, attempts=5):
        """adb connect 实际验证连通性；返回 ``(是否连通, serial, 末次诊断)``。

        判据：``adb devices`` 中该 serial 的**状态列必须为 ``device``**。
        ``connected to ...`` 只说明 TCP 已连通，设备仍可能处于 ``offline`` /
        ``unauthorized``；而网络 ADB 的 serial 恒为 ``ip:5555``，因此**不能用**
        「serial 是否以 ``ip:`` 开头」来判断可用性（旧实现的判定 bug）。
        """
        detail = ""
        for _ in range(attempts):
            ADBService.disconnect_device(ip)
            time.sleep(0.2)
            stdout, stderr, rc = ADBService.connect(ip)
            detail = f"rc={rc} stdout={stdout!r} stderr={stderr!r}"
            _log("INFO", f"验证 connect {ip}: {detail}")
            if rc == 0 and "connected" in stdout.lower():
                serial = ADBService.get_online_serial(ip)
                if serial:
                    cls._put_pooled_connection(ip, serial)
                    cls.set_cached_status(device_id, '开启')
                    return True, serial, detail
            time.sleep(1.5)
        return False, "", detail

    @classmethod
    def _get_pooled_connection(cls, ip):
        """检查连接池缓存，返回未过期的 serial 或 None"""
        now = int(time.time() * 1000)
        with cls._pool_lock:
            cached = cls._connection_pool.get(ip)
            if cached and (now - cached[1]) < cls._pool_ttl_ms:
                return cached[0]
        return None

    @classmethod
    def _put_pooled_connection(cls, ip, serial):
        """将连接放入缓存"""
        with cls._pool_lock:
            cls._connection_pool[ip] = (serial, int(time.time() * 1000))

    @classmethod
    def _invalidate_pool(cls, ip):
        """失效指定 IP 的连接缓存"""
        with cls._pool_lock:
            cls._connection_pool.pop(ip, None)

    @classmethod
    def ensure_adb_connected(cls, ip, password, device_id, max_attempts=2):
        """
        确保 Android 设备 ADB 已连接。优先使用连接池缓存，减少重复 connect/root。
        流程：
        1. 检查连接池是否已有有效 serial
        2. 直接 adb connect 验证/建立连接
        3. 若失败则通过 plink 开启网络 ADB（enable_internet_adb 内部会验证连通性）

        返回: (success: bool, serial: str)
        """
        # 1. 优先使用缓存
        cached_serial = cls._get_pooled_connection(ip)
        if cached_serial:
            stdout, stderr, rc = run_command(f"{ADB_PATH} -s {cached_serial} shell echo ok", timeout=3)
            if rc == 0:
                cls.set_cached_status(device_id, '开启')
                return True, cached_serial
            cls._invalidate_pool(ip)

        for attempt in range(max_attempts):
            # 2. 直接连接（只断开本设备，避免并行刷新时误伤其它设备）
            ADBService.disconnect_device(ip)
            time.sleep(0.2)
            stdout, stderr, rc = ADBService.connect(ip)
            _log("INFO", f"attempt {attempt + 1} connect {ip}: rc={rc} stdout={stdout!r} stderr={stderr!r}")
            if rc == 0 and "connected" in stdout.lower():
                # 判据同 _verify_adb_connect：状态列必须为 device
                serial = ADBService.get_online_serial(ip)
                if serial:
                    _log("INFO", f"已连接, serial={serial}")
                    cls._put_pooled_connection(ip, serial)
                    cls.set_cached_status(device_id, '开启')
                    return True, serial

            # 3. 直接连接失败，通过 plink 开启网络 ADB（仅最后一次尝试）
            if attempt == max_attempts - 1:
                _log("WARN", f"ADB 直接连接失败，尝试开启网络 ADB: {device_id}")
                ok, msg = cls.enable_internet_adb(ip, password, device_id)
                if ok:
                    # enable_internet_adb 已把成功连接放入连接池
                    cached_serial = cls._get_pooled_connection(ip)
                    if cached_serial:
                        return True, cached_serial
                _log("ERROR", f"开启失败: {msg}")

        cls.set_cached_status(device_id, '未开启')
        return False, ""

    @classmethod
    def should_use_adb(cls, device_id):
        """判断当前设备是否应该优先使用 ADB 执行命令"""
        if cls.classify_device(device_id) != "android":
            return False
        return cls.get_cached_status(device_id) == '开启'

    @classmethod
    def execute_adb_command(cls, ip, serial, command_script, timeout=15):
        """使用 adb -s [serial] shell 执行命令，返回 (stdout, stderr, returncode)"""
        try:
            full_cmd = f'{ADB_PATH} -s {serial} shell "{command_script}"'
            stdout, stderr, rc = run_command(full_cmd, timeout=timeout)
            # 如果命令因连接断开失败，失效该 IP 缓存，下次重连
            if rc != 0 and stderr and (
                "not found" in stderr.lower() or
                "offline" in stderr.lower() or
                "unauthorized" in stderr.lower() or
                "error" in stderr.lower()
            ):
                _log("WARN", f"ADB 命令执行异常，失效 {ip} 连接池: {stderr}")
                cls._invalidate_pool(ip)
            return stdout, stderr, rc
        except Exception as e:
            _log("ERROR", f"execute_adb_command 异常: {e}")
            cls._invalidate_pool(ip)
            return "", str(e), -1

    @classmethod
    def batch_enable_adb(cls, device_infos, max_workers=4, progress_callback=None):
        """
        批量为 Android 设备开启网络 ADB。

        Args:
            device_infos: [(device_id, ip, password), ...]
            max_workers: 并发线程数
            progress_callback: callable(device_id, status, serial_or_msg)

        Returns:
            dict: {device_id: {'success': bool, 'serial': str, 'msg': str}}
        """
        results = {}

        def _task(item):
            device_id, ip, password = item
            try:
                success, serial = cls.ensure_adb_connected(ip, password, device_id)
                result = {
                    'success': success,
                    'serial': serial if success else "",
                    'msg': '开启成功' if success else '开启失败'
                }
                if progress_callback:
                    progress_callback(device_id, '开启' if success else '未开启', serial)
                return device_id, result
            except Exception as e:
                _log("ERROR", f"batch_enable_adb {device_id} 异常: {e}")
                if progress_callback:
                    progress_callback(device_id, '未开启', str(e))
                return device_id, {'success': False, 'serial': '', 'msg': str(e)}

        android_items = [
            (d_id, ip, pwd) for d_id, ip, pwd in device_infos
            if cls.classify_device(d_id) == 'android'
        ]

        if not android_items:
            return results

        with ThreadPoolExecutor(max_workers=min(len(android_items), max_workers)) as executor:
            futures = {executor.submit(_task, item): item[0] for item in android_items}
            for future in as_completed(futures):
                device_id, result = future.result()
                results[device_id] = result

        return results
