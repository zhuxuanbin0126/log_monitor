#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer Set 消息（协议下发设置项）。

当前用于「开启 / 关闭 ADB」：走协议下发 ``Set Development`` 配置项（协议设置参数
``Development``，见设备端 ``Development`` 配置）：

    ask = {"Development": {"adbMode": "usb|tcp|usb,tcp", "adbTimer": 0|1}}
    module = "Set"   tag = "Development"

``adbTimer``：``0`` = 开启（永久）；``1`` = 关闭（设备端「计时=1 即关闭」的技巧）。

消息必须带完整字段（``ask`` / ``key`` / ``log`` / ``module`` / ``tag`` / ``uuid`` /
``version``），缺 ``log`` 或 ``key`` 时设备端对 ``Set Development`` 不生效；
``reply.result == kPermissionDenied`` 时需先发 ``KeyEvent``（``ask="Test"``）解锁，
再用**解锁 key** 重发一次。
"""

import uuid as _uuid
from typing import Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .client import send_request
from .envelope import DEFAULT_VERSION, build_envelope
from .frame import TYPE_REQUEST, build_frame, parse_multi_frame_response

logger = get_logger(__name__)

DEVELOPMENT_SETTING = "Development"
"""ADB 开关所在的协议设置项名"""

DEVELOPMENT_KEY = "5826c641cd23a1119769a442ce716b06"
"""设备开发者授权 key（Set Development 必须携带，否则设备端不生效）"""

KEYEVENT_UNLOCK_KEY = "ab6304930fe27524a3c31527a90e4297"
"""设备锁解锁 key（KeyEvent 解锁用）"""

ADB_MODE_USB = "usb"
ADB_MODE_TCP = "tcp"
ADB_MODE_BOTH = "usb,tcp"

ADB_TIMER_ON = 0
ADB_TIMER_OFF = 1

_PERMISSION_DENIED = "kPermissionDenied"


def build_development_message(adb_mode: str, adb_timer: int = ADB_TIMER_ON,
                              key: str = DEVELOPMENT_KEY) -> dict:
    """构造完整的 ``Set Development`` 消息（含 key / log / tag）。"""
    return build_envelope(
        "Set",
        {DEVELOPMENT_SETTING: {"adbMode": adb_mode, "adbTimer": int(adb_timer)}},
        tag=DEVELOPMENT_SETTING, key=key, version=DEFAULT_VERSION,
    )


def build_keyevent_unlock_message() -> dict:
    """构造 ``KeyEvent`` 解锁消息（``ask="Test"`` + 解锁 key）。"""
    return {
        "module": "KeyEvent",
        "ask": "Test",
        "key": KEYEVENT_UNLOCK_KEY,
        "uuid": str(_uuid.uuid4()),
        "version": DEFAULT_VERSION,
    }


def _send(host: str, message: dict, port: int, connect_timeout: float,
          recv_timeout: float) -> Optional[dict]:
    """发送一条明文 Set 消息并解析回复；失败返回 None。"""
    raw = send_request(host, build_frame(message, TYPE_REQUEST), port=port,
                       connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    if not raw:
        return None
    return parse_multi_frame_response(raw)


def _result_of(response: Optional[dict]) -> str:
    """取回复的 result 码；结构不符返回空串。"""
    if not isinstance(response, dict):
        return ""
    reply = response.get("reply")
    if not isinstance(reply, dict):
        return ""
    return str(reply.get("result", ""))


def set_development(host: str, adb_mode: str,
                    adb_timer: int = ADB_TIMER_ON, *, port: int = PROTOCOL_PORT,
                    connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                    recv_timeout: float = PROTOCOL_RECV_TIMEOUT
                    ) -> Tuple[bool, str]:
    """通过协议下发 ``Set Development`` 开启/关闭 ADB。

    Args:
        host: 设备 IP
        adb_mode: ``usb``（有线）/ ``tcp``（无线）/ ``usb,tcp``（两者都开）
        adb_timer: ``0`` 开启（永久）/ ``1`` 关闭
        port: 协议端口
        connect_timeout / recv_timeout: 收发超时

    Returns:
        ``(是否成功, 结果说明)``

    Raises:
        ValueError: ``adb_mode`` 非法
    """
    if adb_mode not in (ADB_MODE_USB, ADB_MODE_TCP, ADB_MODE_BOTH):
        raise ValueError(f"非法 adbMode: {adb_mode!r}")

    verb = "开启" if int(adb_timer) == ADB_TIMER_ON else "关闭"
    message = build_development_message(adb_mode, adb_timer)
    response = _send(host, message, port, connect_timeout, recv_timeout)
    if response is None:
        return False, "设备无响应（协议未返回或解析失败）"

    result = _result_of(response)
    if result == _PERMISSION_DENIED:
        logger.info("Set Development 返回 kPermissionDenied，尝试 KeyEvent 解锁后重发")
        unlock = _send(host, build_keyevent_unlock_message(), port,
                       connect_timeout, recv_timeout)
        if _result_of(unlock) != "kSuccess":
            return False, "设备拒绝（kPermissionDenied，且 KeyEvent 解锁失败）"

        # 解锁成功后用**解锁 key** 重建消息并重发（与设备端语义一致）
        message = build_development_message(adb_mode, adb_timer,
                                            key=KEYEVENT_UNLOCK_KEY)
        response = _send(host, message, port, connect_timeout, recv_timeout)
        if response is None:
            return False, "解锁后重发失败（设备无响应）"
        result = _result_of(response)

    if result == "kSuccess":
        return True, f"已通过协议{verb} ADB（{adb_mode}）"
    return False, f"协议返回非成功结果: {result or '空'}"


def enable_wireless_adb(host: str, **kwargs) -> Tuple[bool, str]:
    """协议开启无线 ADB（``adbMode="tcp"``，永久）。"""
    return set_development(host, ADB_MODE_TCP, ADB_TIMER_ON, **kwargs)


def disable_wireless_adb(host: str, **kwargs) -> Tuple[bool, str]:
    """协议关闭无线 ADB（``adbMode="tcp"`` + ``adbTimer=1``）。"""
    return set_development(host, ADB_MODE_TCP, ADB_TIMER_OFF, **kwargs)


def enable_wired_adb(host: str, **kwargs) -> Tuple[bool, str]:
    """协议开启有线 ADB（``adbMode="usb"``，永久）。"""
    return set_development(host, ADB_MODE_USB, ADB_TIMER_ON, **kwargs)


def enable_all_adb(host: str, **kwargs) -> Tuple[bool, str]:
    """协议同时开启有线 + 无线 ADB（``adbMode="usb,tcp"``）。"""
    return set_development(host, ADB_MODE_BOTH, ADB_TIMER_ON, **kwargs)
