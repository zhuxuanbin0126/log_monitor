#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""协议查询服务：Get 取设备运行状态 + 支持面缓存。

取 ``Time`` 与 ``DeviceInfo`` 两个键（一次往返同时拿到设备时间与运行时长），
并把协议值转换为与 adb/SSH 通道**语义一致**的结果：

- ``Time.dateTime`` 为设备本地（北京时间）墙钟字符串 ``yyyy-MM-dd HH:mm:ss``；
  adb 通道的 ``date +%s`` 为真 epoch，故这里把北京墙钟按下式换回 epoch：
  ``epoch = datetime(y,m,d,H,M,S, tz=+08:00).timestamp()``，
  从而 ``time_diff = epoch - 本机 epoch`` 与 adb 通道完全等价。
- ``DeviceInfo.uptime`` 为运行秒数（long），直接用于计算启动时间。

支持面缓存：成功的短时缓存（避免同轮询重复往返），失败的长负缓存
（避免每轮询都对不支持设备白等建连超时）。
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
    PROTOCOL_STATUS_TTL, PROTOCOL_UNSUPPORTED_TTL,
)
from service.logging_service import get_logger

from .get_query import extract_reply_data, query_keys

logger = get_logger(__name__)

GET_KEYS = ["Time", "DeviceInfo"]
"""一次 Get 同时取设备时间与运行时长"""

BEIJING_TZ = timezone(timedelta(hours=8))
"""设备时间口径：北京时间（与官方上位机 Set.Time.dateTime 使用本机北京时间一致）"""

DEVICE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
"""协议设备时间字符串格式"""


def _to_int(value: Any) -> Optional[int]:
    """把协议返回值（int/float/数字字符串）转为 int；失败返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def parse_device_datetime(text: Any) -> Optional[datetime]:
    """解析设备时间字符串（北京时间）为带时区 datetime；失败返回 None。"""
    if not isinstance(text, str):
        return None
    try:
        naive = datetime.strptime(text.strip(), DEVICE_TIME_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=BEIJING_TZ)


def build_uptime_info(uptime_seconds: int,
                      device_datetime: Optional[datetime] = None,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """由运行秒数构造与 ``DataProcessingService.parse_uptime`` 同形的一段结果。

    Returns:
        dict: 含 ``formatted_uptime`` / ``uptime`` / ``boot_time`` /
        ``current_datetime`` / ``uptime_delta`` 等键（供监控层直接复用）。
    """
    delta = timedelta(seconds=max(0, int(uptime_seconds)))
    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    formatted = ""
    if days > 0:
        formatted += f"{days}天"
    if hours > 0:
        formatted += f"{hours}时"
    formatted += f"{minutes}分"

    current_time = (device_datetime.strftime("%H:%M:%S")
                    if device_datetime is not None else "N/A")
    now = now or datetime.now()
    return {
        'current_time': current_time,
        'uptime': str(delta),
        'user_count': 0,
        'load_1min': 0.0,
        'load_5min': 0.0,
        'load_15min': 0.0,
        'formatted_uptime': formatted,
        'boot_time': (now - delta).isoformat(),
        'current_datetime': now.isoformat(),
        'uptime_delta': str(delta),
    }


def build_device_time_info(device_datetime: datetime,
                           now: Optional[datetime] = None
                           ) -> Tuple[str, int]:
    """由设备时间（北京时间）算出 ``(formatted_remote_time, time_diff)``。

    与 adb/SSH 通道语义一致：``formatted_remote_time`` 为 UTC 墙钟字符串，
    ``time_diff`` = 设备真 epoch − 本机真 epoch（秒）。
    """
    now = now or datetime.now()
    remote_epoch = int(device_datetime.timestamp())
    local_epoch = int(now.timestamp())
    formatted = datetime.fromtimestamp(remote_epoch, tz=timezone.utc).strftime(
        DEVICE_TIME_FORMAT)
    return formatted, remote_epoch - local_epoch


_MISS = object()
"""缓存未命中哨兵（缓存值本身可能是 None —— 负缓存）"""


class ProtocolQueryService:
    """协议查询服务：带支持面缓存的状态获取。"""

    def __init__(self, port: int = PROTOCOL_PORT,
                 connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                 recv_timeout: float = PROTOCOL_RECV_TIMEOUT,
                 status_ttl: float = PROTOCOL_STATUS_TTL,
                 unsupported_ttl: float = PROTOCOL_UNSUPPORTED_TTL):
        self._port = port
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._status_ttl = status_ttl
        self._unsupported_ttl = unsupported_ttl
        self._cache: Dict[str, Tuple[float, Optional[dict]]] = {}
        self._lock = threading.Lock()
        # 按 host 的取数锁：同一设备的并发取数只允许一次真实往返
        self._fetch_locks: Dict[str, threading.Lock] = {}
        self._fetch_locks_guard = threading.Lock()

    def _fetch_lock(self, host: str) -> threading.Lock:
        with self._fetch_locks_guard:
            lock = self._fetch_locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self._fetch_locks[host] = lock
            return lock

    def _read_cache(self, host: str):
        """读缓存；未命中或已过期返回 :data:`_MISS`。"""
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(host)
        if entry is not None and entry[0] > now:
            return entry[1]
        return _MISS

    def get_status(self, host: str) -> Optional[dict]:
        """获取设备运行状态（``{"date_time": str|None, "uptime_seconds": int|None}``）。

        命中缓存直接返回；未命中则发起一次 Get 查询并按结果缓存。
        设备不支持协议或不可达时返回 None（并进入负缓存）。
        """
        if not host:
            return None
        cached = self._read_cache(host)
        if cached is not _MISS:
            return cached

        # 同一设备的并发取数串行化：其余线程等锁后直接复用结果，避免重复往返
        with self._fetch_lock(host):
            cached = self._read_cache(host)
            if cached is not _MISS:
                return cached
            now = time.monotonic()
            data = self._query(host)
            ttl = self._status_ttl if data is not None else self._unsupported_ttl
            with self._lock:
                self._cache[host] = (now + ttl, data)
            return data

    def _query(self, host: str) -> Optional[dict]:
        parsed = query_keys(host, GET_KEYS, port=self._port,
                            connect_timeout=self._connect_timeout,
                            recv_timeout=self._recv_timeout)
        reply_data = extract_reply_data(parsed)
        if reply_data is None:
            return None
        time_cfg = reply_data.get("Time")
        device_cfg = reply_data.get("DeviceInfo")
        return {
            "date_time": time_cfg.get("dateTime") if isinstance(time_cfg, dict) else None,
            "uptime_seconds": (_to_int(device_cfg.get("uptime"))
                               if isinstance(device_cfg, dict) else None),
        }

    def is_supported(self, host: str) -> bool:
        """该设备当前是否可用协议通道（有缓存结论时直接返回）。"""
        return self.get_status(host) is not None

    def invalidate(self, host: Optional[str] = None) -> None:
        """清除缓存：指定 host 只清该设备，为 None 时清空全部。"""
        with self._lock:
            if host is None:
                self._cache.clear()
            else:
                self._cache.pop(host, None)


_default_service = ProtocolQueryService()


def get_protocol_query_service() -> ProtocolQueryService:
    """获取默认协议查询服务单例。"""
    return _default_service


def get_device_status(host: str) -> Optional[dict]:
    """基于默认单例获取设备协议状态。"""
    return _default_service.get_status(host)
