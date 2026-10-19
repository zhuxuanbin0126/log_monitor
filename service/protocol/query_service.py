#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""协议查询服务：Get 取设备运行状态 + 支持面缓存。

取 ``Time`` 与 ``DeviceInfo`` 两个键（一次往返同时拿到设备时间与运行时长），
并把协议值转换为与 adb/SSH 通道**语义一致**的结果：

- ``Time.dateTime`` 为设备**真时区墙钟**字符串 ``yyyy-MM-dd HH:mm:ss``，
  真机实测其取值与本机 UTC 一致（与官方上位机 ``Set.Time`` 下发口径相同），
  故按 **UTC** 挂时区求 epoch：``epoch = datetime(..., tz=utc).timestamp()``，
  于是 ``time_diff = 设备真 epoch − 本机真 epoch`` 与 adb 通道完全等价；
  对外显示的 ``formatted_remote_time`` 一律转成**北京时区**墙钟，UI 直接展示即可。
- ``DeviceInfo.uptime`` 真机实测为**毫秒**（4 天 7 小时上报 ≈3.7e8），
  经 :func:`normalize_uptime` 归一为秒后再算启动时间。

支持面缓存：成功的短时缓存（避免同轮询重复往返），失败的长负缓存
（避免每轮询都对不支持设备白等建连超时）。
"""

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
    PROTOCOL_STATUS_TTL, PROTOCOL_UNSUPPORTED_TTL, PROTOCOL_UPTIME_IN_MS,
)
from service.logging_service import get_logger

from .get_query import extract_reply_data, query_keys

logger = get_logger(__name__)

GET_KEYS = ["Time", "DeviceInfo"]
"""一次 Get 同时取设备时间与运行时长"""

BEIJING_TZ = timezone(timedelta(hours=8))
"""对外显示口径：北京时区（设备墙钟按此渲染给 UI）"""

UTC_TZ = timezone.utc
"""设备 ``Time.dateTime`` 的解析口径：真机实测为 UTC-0"""

DEVICE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
"""协议设备时间字符串格式"""

MAX_UPTIME_SECONDS = 10 * 365 * 24 * 3600
"""运行时长合理性上限（秒，10 年）：换算后仍超出则继续按毫秒降级"""


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


def normalize_uptime(raw: Any,
                     unit_ms: bool = PROTOCOL_UPTIME_IN_MS) -> Optional[int]:
    """把协议上报的运行时长归一为**秒**；非法值返回 None。

    真机实测 ``DeviceInfo.uptime`` 为毫秒（设备开机 4 天 7 小时上报 ≈3.7e8），
    若不换算会得到「4290 天」这种天文数字。单位由 ``config.PROTOCOL_UPTIME_IN_MS``
    决定（默认毫秒）；换算后仍超出合理性上限时继续降级，容忍更大单位。
    """
    value = _to_int(raw)
    if value is None or value < 0:
        return None
    if unit_ms:
        value //= 1000
        while value > MAX_UPTIME_SECONDS:
            value //= 1000
    return max(0, value)


def parse_device_datetime(text: Any) -> Optional[datetime]:
    """解析设备时间字符串为带时区 datetime；失败返回 None。

    真机实测 ``Time.dateTime`` 为 **UTC-0** 墙钟（与官方上位机 ``Set.Time``
    下发的 ``dateTime`` 口径一致），故按 UTC 挂时区；若按北京时间解读会导致
    UI 显示比真实时间少 8 小时。
    """
    if not isinstance(text, str):
        return None
    try:
        naive = datetime.strptime(text.strip(), DEVICE_TIME_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=UTC_TZ)


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

    # 设备时间一律渲染为北京时区（无论协议上报的是 UTC 还是已带时区）
    current_time = (device_datetime.astimezone(BEIJING_TZ).strftime("%H:%M:%S")
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
    """由设备时间算出 ``(formatted_remote_time, time_diff)``。

    与 adb/SSH 通道语义一致：``formatted_remote_time`` 为**北京时区**墙钟字符串
    （UI 直接展示，无需再手动 +8），``time_diff`` = 设备真 epoch − 本机真 epoch（秒）。
    """
    now = now or datetime.now()
    remote_epoch = int(device_datetime.timestamp())
    local_epoch = int(now.timestamp())
    formatted = datetime.fromtimestamp(remote_epoch, tz=BEIJING_TZ).strftime(
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
        raw_uptime = device_cfg.get("uptime") if isinstance(device_cfg, dict) else None
        uptime_seconds = normalize_uptime(raw_uptime)
        logger.debug("设备 %s 协议运行时长: 原始=%r -> %r 秒", host, raw_uptime, uptime_seconds)
        return {
            "date_time": time_cfg.get("dateTime") if isinstance(time_cfg, dict) else None,
            "uptime_seconds": uptime_seconds,
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
