#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer 协议数据帧。

JSON 帧头（12 字节小端）::

    [0:2] 帧总长（含帧头）  [2:4] 类型（0x2103 请求 / 0x2104 回复）
    [4:6] 载荷总长          [6:8] 保留
    [8:10] 分片偏移（0=未分片/首块）  [10:12] 保留

单帧请求：载荷总长 = body 长度，分片偏移 = 0。

加密通道（敏感命令 exec / SetDeviceID 必须走此通道，明文会被设备以
``UNSAFE_MESSAGE`` 拒绝）：

    0x2201 PC→设备 交换盐值请求（4 字节头 + 16 字节盐）
    0x2202 设备→PC 交换盐值应答（4 字节头 + 16 字节盐）
    0x2105 PC→设备 AES 加密请求（12 字节头：u16 帧长 + u16 类型 + u32 总长 + u32 偏移）
    0x2106 设备→PC AES 加密回复（同上）
    0x2000 设备→PC 协议级错误（4 字节头 + u16 错误码）
    0x005F 心跳 / 0x0060 心跳应答（4 字节头，无 body）
"""

import json
import struct
from typing import Dict, List, Optional

HEADER_SIZE = 12
"""JSON 帧头长度（字节）"""

TYPE_REQUEST = 0x2103
"""请求帧类型"""

TYPE_REPLY = 0x2104
"""回复帧类型"""

TYPE_AES_ASK = 0x2105
"""PC → 设备：AES 加密请求"""

TYPE_AES_ANSWER = 0x2106
"""设备 → PC：AES 加密回复"""

TYPE_SWAP_SALT_ASK = 0x2201
"""PC → 设备：交换盐值请求"""

TYPE_SWAP_SALT_ANSWER = 0x2202
"""设备 → PC：交换盐值应答"""

TYPE_ERROR_ANSWER = 0x2000
"""设备 → PC：协议级错误"""

TYPE_HEARTBEAT = 0x005F
"""设备 → PC：心跳（需立即回 0x0060）"""

TYPE_HEARTBEAT_REPLY = 0x0060
"""PC → 设备：心跳应答（同时用作建连握手回应）"""

SALT_SIZE = 16
"""交换盐值长度（字节）"""

SWAP_SALT_FRAME_LEN = 4 + SALT_SIZE
"""交换盐值帧总长（4 字节头 + 16 字节盐）"""

MAX_AES_BODY = 8184
"""AES 加密消息单帧载荷上限（与设备 MAX_TCP_PACKET - 12 字节头一致）"""

MAX_RESPONSE_SIZE = 512 * 1024
"""响应字节流上限（超出视为异常，避免超大包拖垮解析）"""

MAX_FRAME_COUNT = 40
"""单次响应最大帧数"""

# HErrorCode：设备协议级错误帧 0x2000 携带的 u16 错误码
ERROR_CODES: Dict[int, str] = {
    0: "kSuccess", 1: "kWriteFinish", 2: "kProcessError", 3: "kVersionTooLow",
    4: "kDeviceOccupied", 5: "kFileOccupied", 6: "kReadFileExcessive",
    7: "kInvalidPacketLength", 8: "kInvalidMessage", 9: "kSpaceNotEnough",
    10: "kCreateFileFailed", 11: "kWriteFileFailed", 12: "kReadFileFailed",
    13: "kInvalidFileData", 14: "kFileContentError", 15: "kOpenFileFailed",
    16: "kSeekFileFailed", 17: "kRenameFailed", 18: "kFileNotFound",
    19: "kFileNotFinish",
}


def error_name(code: int) -> str:
    """协议错误码 → 可读名称。"""
    return ERROR_CODES.get(code, "kUnknownError")


def build_frame(obj: dict, msg_type: int = TYPE_REQUEST,
                ensure_ascii: bool = False) -> bytes:
    """把 JSON 消息封装为 MagicPlayer socket 数据帧。"""
    body = json.dumps(obj, ensure_ascii=ensure_ascii,
                      separators=(",", ":")).encode("utf-8")
    frame_len = HEADER_SIZE + len(body)
    return struct.pack("<HHHHHH", frame_len, msg_type, len(body), 0, 0, 0) + body


def extract_bodies(raw: bytes, max_response_size: int = MAX_RESPONSE_SIZE,
                   max_frames: int = MAX_FRAME_COUNT) -> List[bytes]:
    """按 12 字节帧头把字节流逐帧切分，返回各帧 body 列表。

    兼容单帧、分片与多帧拼接；遇到长度非法的帧头即停止（保留已解析部分）。
    """
    if len(raw) < HEADER_SIZE or len(raw) > max_response_size:
        return []
    parts: List[bytes] = []
    offset = 0
    frame_count = 0
    total = len(raw)
    while offset + HEADER_SIZE <= total:
        frame_count += 1
        if frame_count > max_frames:
            break
        try:
            frame_len = struct.unpack_from("<H", raw, offset)[0]
        except struct.error:
            break
        if frame_len < HEADER_SIZE or offset + frame_len > total:
            break
        body_start = offset + HEADER_SIZE
        parts.append(raw[body_start:body_start + (frame_len - HEADER_SIZE)])
        offset += frame_len
    return parts


def parse_multi_frame_response(raw: bytes) -> Optional[dict]:
    """解析多帧响应字节流为首个 JSON 对象；失败返回 None。"""
    parts = extract_bodies(raw)
    if not parts:
        return None
    try:
        return json.loads(b"".join(parts).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- 加密通道帧

def build_swap_salt(salt: bytes) -> bytes:
    """交换盐值请求帧（0x2201）：4 字节头（帧长 20 + 类型）+ 16 字节随机盐。

    设备收到后以其本地随机盐应答 0x2202，并据此派生 AES 密钥：
    ``key = MD5("HUIDUSDK" + hex(PC盐) + hex(设备盐))``。
    """
    if len(salt) != SALT_SIZE:
        raise ValueError(f"盐值必须为 {SALT_SIZE} 字节，实际 {len(salt)}")
    return struct.pack("<HH", SWAP_SALT_FRAME_LEN, TYPE_SWAP_SALT_ASK) + salt


def parse_swap_salt_answer(body: bytes) -> Optional[bytes]:
    """解析 0x2202 应答 body（去掉 4 字节头后的 16 字节盐）；非法返回 None。"""
    if len(body) < SALT_SIZE:
        return None
    return body[:SALT_SIZE]


def _aes_frame(chunk: bytes, total: int, offset: int,
               msg_type: int = TYPE_AES_ASK) -> bytes:
    """AES 消息帧：12 字节头 = [u16 本帧长][u16 类型][u32 总长][u32 偏移]。

    与设备 ``sendAESMsgReply`` / ``handleAESMsgAsk`` 的头结构逐字段一致。
    ``total`` / ``offset`` 为 **u32**（大响应超过 65535 字节时不能用 JSON 帧的 u16 头）。
    """
    return struct.pack("<HHII", HEADER_SIZE + len(chunk), msg_type, total, offset) + chunk


def build_aes_frames(ciphertext: bytes, msg_type: int = TYPE_AES_ASK,
                     max_body: int = MAX_AES_BODY) -> List[bytes]:
    """一段 AES 密文 → 1..N 个 0x2105 帧（超过 ``max_body`` 自动分片）。"""
    if len(ciphertext) <= max_body:
        return [_aes_frame(ciphertext, len(ciphertext), 0, msg_type)]
    return [_aes_frame(ciphertext[i:i + max_body], len(ciphertext), i, msg_type)
            for i in range(0, len(ciphertext), max_body)]


def parse_aes_chunk(body: bytes):
    """解析 0x2106 回复 body 头（返回 ``(total, offset, chunk)``）；非法返回 None。"""
    if len(body) < 8:
        return None
    total = struct.unpack_from("<I", body, 0)[0]
    offset = struct.unpack_from("<I", body, 4)[0]
    return total, offset, body[8:]


def build_heartbeat_reply() -> bytes:
    """心跳应答帧（0x0060，4 字节头无 body）。

    收到设备心跳必须回一次，否则设备判定客户端失联并主动断开 TCP。
    """
    return struct.pack("<HH", 4, TYPE_HEARTBEAT_REPLY)


def wrap_plain_reply(body: bytes) -> bytes:
    """把明文 JSON body 重新封装成标准 0x2104 回复帧。

    便于解密后的响应复用 :func:`parse_multi_frame_response`，调用方无需感知加密细节。
    """
    return struct.pack("<HHHHHH", HEADER_SIZE + len(body), TYPE_REPLY,
                       len(body), 0, 0, 0) + body
