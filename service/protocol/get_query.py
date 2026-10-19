#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer Get 查询：报文构造与多帧重组。

Get 报文的信封内 ``ask = {"list": [键名...]}``；响应为
``{"module":"Get","reply":{"data":{...},"result":"kSuccess"}}``（大响应会分多帧）。
"""

import json
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .client import send_request
from .envelope import DEFAULT_VERSION, build_envelope
from .frame import HEADER_SIZE, build_frame

logger = get_logger(__name__)

MAX_RESPONSE_SIZE = 256 * 1024
"""响应字节流上限"""
MAX_FRAME_COUNT = 20
"""单次响应最大帧数"""
MAX_PAYLOAD_SIZE = 128 * 1024
"""重组后 payload 上限"""


def build_get_message(keys: List[str], *, tag: Optional[str] = None,
                      key: Optional[str] = None,
                      version: int = DEFAULT_VERSION) -> Dict[str, Any]:
    """构造 MagicPlayer Get 请求消息体（统一信封，补全 version/log）。"""
    return build_envelope("Get", {"list": list(keys)}, version=version, tag=tag, key=key)


def build_get_frame(keys: List[str]) -> bytes:
    """构造并编码 Get 请求帧（12 字节帧头 + JSON body）。"""
    return build_frame(build_get_message(keys))


@dataclass
class Reassembly:
    """多帧重组结果。

    ``reason`` 取值：
      - ``ok``                 成功（parts 非空）
      - ``too_short``          响应不足 12 字节
      - ``too_large``          响应超过 max_response_size
      - ``frame_overflow``     帧数超上限（软错误，保留已收部分帧）
      - ``header_parse_error`` 帧头解析失败（软错误，保留已收部分帧）
      - ``payload_overflow``   payload 超上限（硬错误）
      - ``no_frames``          未解析出任何有效帧
    """

    parts: List[bytes] = field(default_factory=list)
    frame_count: int = 0
    reason: str = "ok"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.parts)

    def payload(self) -> bytes:
        """拼接后的完整 payload。"""
        return b"".join(self.parts)


def reassemble_get_frames(raw_response: bytes, *,
                          max_response_size: int = MAX_RESPONSE_SIZE,
                          max_frames: int = MAX_FRAME_COUNT,
                          max_payload_size: Optional[int] = MAX_PAYLOAD_SIZE
                          ) -> Reassembly:
    """把响应字节流按「帧长 + 12 字节头」逐帧拆出并重组 payload。

    软错误（``frame_overflow`` / ``header_parse_error``）保留已收到的部分帧返回。
    """
    total_len = len(raw_response)
    if total_len < HEADER_SIZE:
        return Reassembly([], 0, "too_short")
    if total_len > max_response_size:
        return Reassembly([], 0, "too_large")

    parts: List[bytes] = []
    offset = 0
    payload_len = 0
    frame_count = 0
    while offset + HEADER_SIZE <= total_len:
        frame_count += 1
        if frame_count > max_frames:
            return Reassembly(parts, frame_count, "frame_overflow",
                              f"帧数超过上限 ({max_frames})")
        try:
            frame_len = struct.unpack_from("<H", raw_response, offset)[0]
        except struct.error as exc:
            return Reassembly(parts, frame_count, "header_parse_error",
                              f"帧头解析失败 ({exc})")
        if frame_len < HEADER_SIZE or offset + frame_len > total_len:
            break
        body_start = offset + HEADER_SIZE
        body = raw_response[body_start:body_start + (frame_len - HEADER_SIZE)]
        parts.append(body)
        payload_len += len(body)
        if max_payload_size is not None and payload_len > max_payload_size:
            return Reassembly(parts, frame_count, "payload_overflow",
                              f"{payload_len} 字节 > {max_payload_size}")
        offset += frame_len

    if not parts:
        return Reassembly([], frame_count, "no_frames")
    return Reassembly(parts, frame_count)


def extract_reply_data(parsed: Optional[dict]) -> Optional[dict]:
    """从 Get 响应中取 ``reply.data``（result 非成功时返回 None）。"""
    if not isinstance(parsed, dict):
        return None
    reply = parsed.get("reply")
    if not isinstance(reply, dict):
        return None
    result = reply.get("result")
    if result is not None and result != "kSuccess":
        logger.debug("协议应答非成功: %s", result)
        return None
    data = reply.get("data")
    return data if isinstance(data, dict) else None


def query_keys(host: str, keys: List[str], *, port: int = PROTOCOL_PORT,
               connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
               recv_timeout: float = PROTOCOL_RECV_TIMEOUT) -> Optional[dict]:
    """对设备发起一次 Get 查询，返回解析后的 JSON 对象；失败返回 None。"""
    frame = build_get_frame(keys)
    raw = send_request(host, frame, port=port,
                       connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    if not raw:
        return None
    reassembly = reassemble_get_frames(raw)
    if not reassembly.ok:
        logger.debug("协议响应重组失败: reason=%s detail=%s",
                     reassembly.reason, reassembly.detail)
        return None
    try:
        return json.loads(reassembly.payload().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.debug("协议响应 JSON 解析失败: %s", exc)
        return None
