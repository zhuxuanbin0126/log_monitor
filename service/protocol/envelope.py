#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer 消息信封统一构造。

所有经 10001 端口下发的协议消息都应携带同一组顶层字段：
``ask`` / ``module`` / ``tag?`` / ``key?`` / ``uuid`` / ``version`` / ``log``。

- ``log``：上位机环境指纹串，设备据此识别操作来源（缺失时操作日志记为
  ``UnknownClient``），故默认附上。
- ``key``：设备锁解锁 key，仅在已解锁时携带。
- ``version``：Socket 通道出站协议版本，**统一为 5**（对齐官方上位机 HDPlayer）。
"""

import platform
import socket
import uuid as _uuid
from typing import Any, Dict, Optional

from config import PROTOCOL_VERSION

DEFAULT_VERSION = PROTOCOL_VERSION
"""Socket 通道出站协议版本（单一真源，禁止在别处再写字面值）"""


def new_uuid() -> str:
    """生成花括号包裹的 UUID（与真实上位机一致）。"""
    return "{" + str(_uuid.uuid4()) + "}"


def build_client_log() -> str:
    """上位机环境指纹串（采集失败回退空串，不让消息构造崩溃）。"""
    try:
        return f"{platform.system()};log_monitor;{socket.gethostname()}"
    except Exception:  # pylint: disable=broad-except
        return ""


def build_envelope(module: str, ask: Dict[str, Any], *,
                   version: int = DEFAULT_VERSION,
                   msg_uuid: Optional[str] = None,
                   tag: Optional[str] = None,
                   key: Optional[str] = None,
                   include_log: bool = True) -> Dict[str, Any]:
    """构造 MagicPlayer 消息信封，字段顺序与真实上位机一致。

    Args:
        module: 模块名（``Get`` / ``Set`` / ``Task`` / ``Command`` …）
        ask: 业务参数（``list`` / ``setting`` …）
        version: 协议版本（默认 5）
        msg_uuid: 指定 uuid（缺省自动生成花括号 UUID）
        tag: 可选业务标签
        key: 可选设备锁解锁 key
        include_log: 是否附带环境指纹 ``log``（默认 True）
    """
    msg: Dict[str, Any] = {"ask": ask, "module": module}
    if tag is not None:
        msg["tag"] = tag
    if key is not None:
        msg["key"] = key
    msg["uuid"] = msg_uuid or new_uuid()
    msg["version"] = version
    if include_log:
        msg["log"] = build_client_log()
    return msg
