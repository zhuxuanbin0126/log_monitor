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
        对 Android 设备开启网络 ADB 功能：
        1. setprop persist.internet_adb_enable 1
        2. setprop service.adb.tcp.port 5555
        3. 重启 adbd 服务
        4. 使用 adb connect 实际验证连通性（而非仅 getprop）

        返回: (success: bool, message: str)
        """
        plink_exe = get_tool_path('plink.exe')
        base_cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}"'

        try:
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

            # 4. 实际验证：尝试 adb connect，最多等待 10 秒
            _log("INFO", f"正在验证 {device_id} ADB 连通性...")
            for verify_attempt in range(5):
                ADBService.disconnect()
                time.sleep(0.2)
                stdout, stderr, rc = ADBService.connect(ip)
                _log("INFO", f"验证尝试 {verify_attempt + 1} connect {ip}: rc={rc} stdout={stdout!r} stderr={stderr!r}")
                if rc == 0 and "connected" in stdout.lower():
                    serial = ADBService.get_device_serial(ip)
                    if serial and not serial.startswith(f"{ip}:"):
                        cls._put_pooled_connection(ip, serial)
                        cls.set_cached_status(device_id, '开启')
                        _log("INFO", f"{device_id} 网络 ADB 已开启，serial={serial}")
                        return True, f"网络 ADB 已开启，serial={serial}"
                time.sleep(1.5)

            # 5. getprop 仅作为辅助诊断
            prop_enabled, prop_value = cls.check_internet_adb_enabled(ip, password, device_id, timeout=3)
            _log("ERROR", f"{device_id} adb connect 验证失败，persist.internet_adb_enable={prop_value}")
            return False, f"adb connect 验证失败，persist.internet_adb_enable={prop_value}"

        except Exception as e:
            _log("ERROR", f"开启网络 ADB 失败: {e}")
            return False, str(e)

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
            # 2. 直接连接
            ADBService.disconnect()
            time.sleep(0.2)
            stdout, stderr, rc = ADBService.connect(ip)
            _log("INFO", f"attempt {attempt + 1} connect {ip}: rc={rc} stdout={stdout!r} stderr={stderr!r}")
            if rc == 0 and "connected" in stdout.lower():
                serial = ADBService.get_device_serial(ip)
                if serial and not serial.startswith(f"{ip}:"):
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
