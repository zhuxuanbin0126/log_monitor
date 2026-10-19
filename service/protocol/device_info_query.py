#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备信息协议查询：一次 Get 取 4 键并解析出设备列表需要的字段。

仅适用于 **Android** 设备（Linux 设备不需要这些信息，只需设备密码）。

一次请求取 4 个键（`ask.list`），一个往返即可拿全，避免逐个键/逐条 adb 命令：

======  ==================  ==========================================================
键      字段路径             用途（对应设备列表列）
======  ==================  ==========================================================
DeviceInfo  ``deviceName``     设备名称（第 7 列）
VersionInfo ``app.player``     主版本 / 播放器版本号（第 3 列）
VersionInfo ``system.buildVersion``  OTA / 固件版本号（第 4 列，缺省回退 ``system.version``）
NetworkInfo ``interfaces`` 中 ``type == "Ethernet"`` 的 ``mac``  MAC 地址（第 5 列）
Development ``adbMode`` / ``adbTimer``  ADB 开启情况（第 9 列）
======  ==================  ==========================================================

``Development`` 语义（设备侧真值源 ``DevelopmentConfig``，Get 可读·设置参数41）：

- ``adbMode``：以逗号分隔的已开启模式，可含 ``usb``（usb 调试）/ ``tcp``（网络 adb），
  最多两项；未设置的模式视为关闭。
- ``adbTimer``：adb 临时开启时长，协议文档标注单位为 **ms**；``> 0`` 为倒计时关闭，
  ``<= 0`` 为**永久开启**。

本模块只做「构造请求 + 纯函数解析」，不持有设备状态。
"""

from typing import Any, Dict, List, Optional

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .get_query import extract_reply_data, query_keys

logger = get_logger(__name__)

DEVICE_INFO_KEYS: List[str] = ["DeviceInfo", "VersionInfo", "NetworkInfo", "Development"]
"""一次 Get 取回设备列表所需的全部键"""

NA = "N/A"
"""未知值占位（与旧 adb/SSH 通道口径一致）"""

ADB_STATUS_ON = "开启"
ADB_STATUS_OFF = "未开启"
ADB_STATUS_UNSUPPORTED = "不支持"
ADB_STATUS_UNKNOWN = "未知"

_ETHERNET_TYPE = "Ethernet"
_ETHERNET_KEY = "Ethernet"
"""有线网络设置项（设置参数6）；旧固件 NetworkInfo 不含以太网 mac 时用它兜底取 mac"""


def _as_dict(value: Any) -> Dict[str, Any]:
    """非 dict 一律当空 dict（协议回读字段缺失时为 null）。"""
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str = NA) -> str:
    """取值转字符串；空/None 返回 default。"""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def parse_mac(network_info: Any) -> str:
    """从 ``NetworkInfo.interfaces`` 取 ``type == "Ethernet"`` 那条的 mac。"""
    interfaces = _as_dict(network_info).get("interfaces")
    if not isinstance(interfaces, list):
        return NA
    for item in interfaces:
        entry = _as_dict(item)
        if _text(entry.get("type"), default="").lower() == _ETHERNET_TYPE.lower():
            mac = _text(entry.get("mac"), default="")
            if mac:
                return mac
    return NA


def parse_ethernet_mac(ethernet: Any) -> str:
    """从 ``Ethernet``（有线网络设置项）取 ``mac``。

    旧固件的 ``NetworkInfo.interfaces`` 可能不含以太网条目（实测 A6L/OTA 1.2.8.0），
    此时回退到该设置项回读的 ``reply.data.Ethernet.mac``。
    """
    return _text(_as_dict(ethernet).get("mac"))


def parse_device_name(device_info: Any) -> str:
    """从 ``DeviceInfo.deviceName`` 取设备名。"""
    return _text(_as_dict(device_info).get("deviceName"))


def parse_player_version(version_info: Any) -> str:
    """主版本（播放器版本号）：``VersionInfo.app.player``。"""
    return _text(_as_dict(_as_dict(version_info).get("app")).get("player"))


def parse_ota_version(version_info: Any) -> str:
    """OTA / 固件版本号：优先 ``VersionInfo.system.buildVersion``，缺失回退 ``system.version``。"""
    system = _as_dict(_as_dict(version_info).get("system"))
    build = _text(system.get("buildVersion"), default="")
    if build:
        return build
    return _text(system.get("version"))


def _adb_timer_value(development: Dict[str, Any]) -> Optional[int]:
    """取 ``adbTimer`` 整数；缺失/非法返回 None。"""
    raw = development.get("adbTimer")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def parse_development(development: Any) -> Dict[str, Any]:
    """解析 ``Development``（开发者选项）→ ADB 开启情况。

    Returns:
        dict: ``{'adb_status': 状态, 'adb_detail': 细节, 'adb_mode': 原始模式, 'adb_timer': 原始时长}``

    ``adb_status`` 取值保持设备列表既有口径（``开启``/``未开启``/``未知``），
    细节（是否 usb+tcp、是否永久）放在 ``adb_detail``。
    """
    if not isinstance(development, dict) or not development:
        return {"adb_status": ADB_STATUS_UNKNOWN, "adb_detail": "未读到开发者选项",
                "adb_mode": "", "adb_timer": None}

    mode_raw = _text(development.get("adbMode"), default="")
    modes = {part.strip().lower() for part in mode_raw.split(",") if part.strip()}
    timer = _adb_timer_value(development)

    timer_desc = "永久" if (timer is not None and timer <= 0) else (
        f"adbTimer={timer}" if timer is not None else "adbTimer未知")
    mode_desc = "+".join(sorted(modes)) if modes else "未配置"

    if "tcp" not in modes:
        # 只开了 usb（或没开）：网络 adb 不可用
        detail = (f"仅{'+'.join(sorted(modes))}（无网络adb）" if modes
                  else "未配置adb")
        return {"adb_status": ADB_STATUS_OFF, "adb_detail": detail,
                "adb_mode": mode_raw, "adb_timer": timer}

    status = ADB_STATUS_ON
    if "usb" in modes:
        detail = f"usb+tcp/{timer_desc}"
    else:
        detail = f"tcp/{timer_desc}"
    return {"adb_status": status, "adb_detail": detail,
            "adb_mode": mode_raw, "adb_timer": timer}


def parse_device_info(reply_data: Optional[dict],
                      ethernet: Optional[dict] = None) -> Dict[str, Any]:
    """把 Get 的 ``reply.data`` 解析为设备列表所需字段。

    Args:
        reply_data: 主 Get 的 ``reply.data``（含 DeviceInfo/VersionInfo/NetworkInfo/Development）
        ethernet: 可选的 ``reply.data.Ethernet``；当 ``NetworkInfo`` 里没有以太网 mac 时
            作为 MAC 的回退来源（旧固件实测需要）
    """
    data = _as_dict(reply_data)
    development = parse_development(data.get("Development"))

    mac = parse_mac(data.get("NetworkInfo"))
    if mac == NA and ethernet is not None:
        mac = parse_ethernet_mac(ethernet)

    return {
        "mac_address": mac,
        "device_name": parse_device_name(data.get("DeviceInfo")),
        "system_type": "Android",
        "ota_version": parse_ota_version(data.get("VersionInfo")),
        "main_version": parse_player_version(data.get("VersionInfo")),
        "adb_status": development["adb_status"],
        "adb_detail": development["adb_detail"],
        "adb_mode": development["adb_mode"],
        "adb_timer": development["adb_timer"],
    }


def query_ethernet(host: str, *, port: int = PROTOCOL_PORT,
                   connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                   recv_timeout: float = PROTOCOL_RECV_TIMEOUT) -> Optional[Dict[str, Any]]:
    """按需补查 ``Ethernet`` 设置项，返回 ``reply.data.Ethernet``；失败返回 None。"""
    parsed = query_keys(host, [_ETHERNET_KEY], port=port,
                        connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    data = extract_reply_data(parsed)
    if not isinstance(data, dict):
        return None
    ethernet = data.get(_ETHERNET_KEY)
    return ethernet if isinstance(ethernet, dict) else None


def query_device_info(host: str, *, port: int = PROTOCOL_PORT,
                      connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                      recv_timeout: float = PROTOCOL_RECV_TIMEOUT,
                      keys: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """一次 Get 取回设备信息并解析（MAC 缺失时按需补查 ``Ethernet``）。

    Args:
        host: 设备 IP
        keys: 可覆盖要取的键（默认 :data:`DEVICE_INFO_KEYS`）

    Returns:
        解析后的字段 dict（含 ``mac_address`` / ``device_name`` / ``ota_version`` /
        ``main_version`` / ``adb_status`` 等）；设备不可达或协议不支持返回 None。
    """
    parsed = query_keys(host, keys or DEVICE_INFO_KEYS, port=port,
                        connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    reply_data = extract_reply_data(parsed)
    if reply_data is None:
        logger.debug("设备 %s 协议设备信息查询失败（无有效 reply.data）", host)
        return None

    info = parse_device_info(reply_data)

    # 旧固件（实测 A6L/OTA 1.2.8.0）的 NetworkInfo 可能不含以太网 mac → 补查 Ethernet
    if info["mac_address"] == NA:
        ethernet = query_ethernet(host, port=port, connect_timeout=connect_timeout,
                                  recv_timeout=recv_timeout)
        if ethernet is not None:
            info["mac_address"] = parse_ethernet_mac(ethernet)
            logger.info("设备 %s MAC 回退取 Ethernet.mac: %s", host, info["mac_address"])

    return info
