#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer 协议子包（TCP 10001）。

- :mod:`service.protocol.frame`      数据帧（明文 JSON 帧 + 加密/盐值/心跳帧）
- :mod:`service.protocol.crypto`     AES-128-CBC / PKCS7 与密钥派生
- :mod:`service.protocol.envelope`   消息信封（version=5，含 uuid/log）
- :mod:`service.protocol.client`     TCP 握手与收发（明文 / 加密，串行锁）
- :mod:`service.protocol.get_query`  Get 报文构造与多帧重组
- :mod:`service.protocol.command_query`  Command.exec（加密）查询
- :mod:`service.protocol.query_service`  设备状态查询与支持面缓存
"""

from .command_query import (
    ExecResult, exec_command, exec_if_supported, extract_exec_result,
    is_protocol_supported, line_count_from_output, message_needs_encryption,
)
from .envelope import DEFAULT_VERSION, build_envelope, new_uuid
from .frame import build_frame, parse_multi_frame_response
from .get_query import build_get_frame, query_keys, reassemble_get_frames
from .query_service import get_device_status, get_protocol_query_service

__all__ = [
    'DEFAULT_VERSION', 'build_envelope', 'new_uuid',
    'build_frame', 'parse_multi_frame_response',
    'build_get_frame', 'query_keys', 'reassemble_get_frames',
    'get_device_status', 'get_protocol_query_service',
    'ExecResult', 'exec_command', 'exec_if_supported', 'extract_exec_result',
    'is_protocol_supported', 'line_count_from_output', 'message_needs_encryption',
]
