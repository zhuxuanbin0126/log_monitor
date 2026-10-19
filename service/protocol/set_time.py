#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer Set 校时（``Set Time``）。

官方上位机的校时报文（抓包/官方模板）形如::

    {"ask": {"Time": {"dateTime": "2026-10-19 14:12:38",
                      "ntp": {"ntpHost": ["ntp.huidu.cn"]},
                      "sync": "auto",
                      "syncInterDevice": 0,
                      "timeZone": {"rawOffset": "UTC+08:00",
                                   "timeZoneId": "Asia/Shanghai",
                                   "timeZoneOffset": "UTC+08:00"}}},
     "module": "Set"}

⚠️ ``dateTime`` 为 **UTC-0** 墙钟（与设备 Get ``Time.dateTime`` 口径一致），
故本模块把本机时间换算成 UTC 后再下发；时区信息单独由 ``timeZone`` 声明，
使设备显示为北京时间。

协议校时**免推 ntpdate 二进制、免 SSH**，且不会因设备无外网而失败。
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .client import send_request
from .envelope import DEFAULT_VERSION, build_envelope
from .frame import TYPE_REQUEST, build_frame, parse_multi_frame_response

logger = get_logger(__name__)

TIME_SETTING = "Time"
"""校时所在的协议设置项名"""

DEFAULT_NTP_HOSTS: List[str] = ["ntp.huidu.cn"]
"""默认 NTP 服务器（与设备出厂配置一致）"""

BEIJING_TIME_ZONE: Dict[str, str] = {
    "rawOffset": "UTC+08:00",
    "timeZoneId": "Asia/Shanghai",
    "timeZoneOffset": "UTC+08:00",
}
"""北京时间时区声明（rawOffset/timeZoneOffset 均不含夏令时差异）"""

SYNC_AUTO = "auto"
"""自动校时方式：auto（动态选择，与官方模板一致）"""


def build_time_message(date_time_utc: str, *, ntp_hosts: Optional[List[str]] = None,
                       sync: str = SYNC_AUTO, sync_inter_device: int = 0,
                       time_zone: Optional[Dict[str, str]] = None,
                       version: int = DEFAULT_VERSION) -> Dict[str, object]:
    """构造 ``Set Time`` 消息（统一信封，补全 version/log）。

    Args:
        date_time_utc: ``yyyy-MM-dd HH:mm:ss`` 的 **UTC-0** 墙钟字符串
        ntp_hosts: NTP 服务器列表
        sync: 自动校时方式（默认 ``auto``）
        sync_inter_device: 设备间互相校时开关（0=关）
        time_zone: 时区声明；缺省为北京时间
    """
    body = {
        "dateTime": date_time_utc,
        "ntp": {"ntpHost": list(ntp_hosts or DEFAULT_NTP_HOSTS)},
        "sync": sync,
        "syncInterDevice": int(sync_inter_device),
        "timeZone": dict(time_zone or BEIJING_TIME_ZONE),
    }
    return build_envelope("Set", {TIME_SETTING: body},
                          tag=TIME_SETTING, version=version)


def _result_of(response: Optional[dict]) -> str:
    """取回复的 result 码；结构不符返回空串。"""
    if not isinstance(response, dict):
        return ""
    reply = response.get("reply")
    if not isinstance(reply, dict):
        return ""
    return str(reply.get("result", ""))


def set_time(host: str, *, ntp_hosts: Optional[List[str]] = None,
             now: Optional[datetime] = None, port: int = PROTOCOL_PORT,
             connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
             recv_timeout: float = PROTOCOL_RECV_TIMEOUT) -> Tuple[bool, str]:
    """通过协议下发 ``Set Time`` 校时。

    Args:
        host: 设备 IP
        ntp_hosts: NTP 服务器列表（缺省 ``ntp.huidu.cn``）
        now: 本机当前时间；缺省 ``datetime.now(timezone.utc)``（用于测试注入）

    Returns:
        ``(是否成功, 结果说明)``
    """
    utc_now = now or datetime.now(timezone.utc)
    if utc_now.tzinfo is None:
        utc_now = utc_now.replace(tzinfo=timezone.utc)
    date_time_utc = utc_now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    message = build_time_message(date_time_utc, ntp_hosts=ntp_hosts)
    raw = send_request(host, build_frame(message, TYPE_REQUEST), port=port,
                       connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    if not raw:
        return False, "设备无响应（协议未返回或解析失败）"

    result = _result_of(parse_multi_frame_response(raw))
    if result == "kSuccess":
        logger.info("设备 %s 协议校时成功：下发 UTC %s（北京 %s）",
                    host, date_time_utc,
                    utc_now.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        return True, f"已通过协议校时（下发 UTC {date_time_utc}）"
    return False, f"协议返回非成功结果: {result or '空'}"
