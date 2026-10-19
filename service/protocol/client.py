#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer TCP 客户端：握手 + 请求收发（含 AES 加密通道）。

握手流程：设备在 TCP 建连后主动下发 4 字节问候（``04 00 5f 00``，即心跳帧），
上位机须回 4 字节心跳应答 ``04 00 60 00``（帧长 4 + 命令码 ``0x0060``），设备才
开始处理后续请求。若在 ``greet_timeout`` 内未收到问候，仍继续发送请求，兼容不
校验握手的老设备。

加密通道：敏感命令（``exec`` / ``SetDeviceID``）**必须**加密，明文会被设备以
``UNSAFE_MESSAGE`` 拒绝。加密前在同一连接内先经 0x2201/0x2202 交换盐值协商
AES-128 密钥，再用 0x2105 发加密请求、0x2106 收加密回复。

收发串行锁：并发向**同一设备**发协议是已知的不稳定来源，故同一设备同一时刻只允许
一次收发；锁按设备 IP 维度（`host_lock`），**不同设备之间可并行**。
"""

import json
import os
import socket
import struct
import threading
from typing import Dict, Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .crypto import decrypt_aes, derive_key, encrypt_aes
from .frame import (
    ERROR_CODES, HEADER_SIZE, SALT_SIZE, TYPE_AES_ANSWER, TYPE_AES_ASK,
    TYPE_ERROR_ANSWER, TYPE_HEARTBEAT, TYPE_REPLY, TYPE_SWAP_SALT_ANSWER,
    build_aes_frames, build_heartbeat_reply, build_swap_salt, error_name,
    extract_bodies, parse_aes_chunk, parse_swap_salt_answer, wrap_plain_reply,
)

logger = get_logger(__name__)

# 握手帧（与 4 字节心跳应答同形）
HANDSHAKE_REPLY = struct.pack("<HH", 4, 0x0060)

# 设备问候等待窗口（部分设备从不发问候，窗口过大会每条消息固定白等）
GREET_TIMEOUT = 0.15
# 「协议已收完整」后的确认窗口（再探一下有无后续帧，没有即收尾）
DEFAULT_EARLY_EXIT_S = 0.05
# 单次 recv 上限
_RECV_CHUNK = 8192

# 协议收发串行锁（**按设备 IP 维度**）：
# 动机：并发往同一设备发协议是已知的不稳定来源，必须串行；但不同设备之间互不影响。
# 早先的全局锁会把所有设备串成一队，在多台设备查询时白白损失并行度。
# 按 host 取锁后：同设备严格串行，跨设备可并行。
_HOST_LOCKS: Dict[str, threading.RLock] = {}
_HOST_LOCKS_GUARD = threading.Lock()


def host_lock(host: str) -> threading.RLock:
    """取该 host 的协议收发锁（惰性创建，线程安全）。"""
    with _HOST_LOCKS_GUARD:
        lock = _HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.RLock()
            _HOST_LOCKS[host] = lock
        return lock


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    """从 socket 读满 ``size`` 字节（对端提前关闭时返回已读到的部分）。"""
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _has_complete_message(raw: bytes) -> bool:
    """已收字节流中是否已含至少一条完整消息（协议感知，避免按时间猜收尾）。"""
    if not raw:
        return False
    try:
        return bool(extract_bodies(raw))
    except Exception:  # pylint: disable=broad-except
        return False


def _read_frame(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    """读一整帧，返回 ``(帧类型, 去 4 字节头的 body)``；读不满返回 None。"""
    try:
        head = _recv_exact(sock, 4)
    except (socket.timeout, OSError):
        return None
    if len(head) < 4:
        return None
    frame_len, msg_type = struct.unpack("<HH", head)
    if frame_len < 4:
        return None
    try:
        body = _recv_exact(sock, frame_len - 4)
    except (socket.timeout, OSError):
        return None
    if len(body) < frame_len - 4:
        return None
    return msg_type, body


def _plaintext_exchange(sock: socket.socket, data: bytes, recv_timeout: float,
                        early_exit_s: float) -> bytes:
    """明文通道：发送请求帧并按协议自适应收尾读取回复。"""
    sock.sendall(data)
    sock.settimeout(recv_timeout)
    chunks = []
    try:
        while True:
            buf = sock.recv(_RECV_CHUNK)
            if not buf:
                break
            chunks.append(buf)
            if early_exit_s and early_exit_s > 0:
                complete = _has_complete_message(b"".join(chunks))
                sock.settimeout(early_exit_s if complete else recv_timeout)
    except socket.timeout:
        pass
    return b"".join(chunks)


def _error_reply_frame(code: int) -> bytes:
    """把设备 0x2000 协议错误码转成可读的明文回复帧。"""
    body = json.dumps({"result": error_name(code), "errorCode": code},
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return wrap_plain_reply(body)


def _recv_swap_salt_answer(sock: socket.socket, recv_timeout: float) -> Optional[bytes]:
    """读取 0x2202 盐值应答（跳过心跳/未知帧）；失败返回 None。"""
    sock.settimeout(recv_timeout)
    while True:
        frame = _read_frame(sock)
        if frame is None:
            return None
        msg_type, body = frame
        if msg_type == TYPE_SWAP_SALT_ANSWER:
            return parse_swap_salt_answer(body)
        if msg_type == TYPE_ERROR_ANSWER:
            code = struct.unpack("<H", body[:2])[0] if len(body) >= 2 else -1
            logger.debug("交换盐值被拒: %s", ERROR_CODES.get(code, "kUnknownError"))
            return None
        if msg_type == TYPE_HEARTBEAT:
            try:
                sock.sendall(build_heartbeat_reply())
            except OSError:
                return None


def _recv_encrypted_reply(sock: socket.socket, key: bytes,
                          recv_timeout: float) -> bytes:
    """接收 0x2106 加密回复：按 total/offset 重组密文 → 解密 → 包装成 0x2104 帧。"""
    sock.settimeout(recv_timeout)
    parts: Dict[int, bytes] = {}
    while True:
        frame = _read_frame(sock)
        if frame is None:
            break
        msg_type, body = frame
        if msg_type == TYPE_HEARTBEAT:
            try:
                sock.sendall(build_heartbeat_reply())
            except OSError:
                pass
            continue
        if msg_type == TYPE_ERROR_ANSWER:
            code = struct.unpack("<H", body[:2])[0] if len(body) >= 2 else -1
            return _error_reply_frame(code)
        if msg_type == TYPE_REPLY:
            # 明文回复（理论上不应出现在加密会话中）
            return wrap_plain_reply(body)
        if msg_type == TYPE_AES_ANSWER:
            parsed = parse_aes_chunk(body)
            if parsed is None:
                break
            total, offset, chunk = parsed
            if chunk:
                parts[offset] = chunk
            if total and sum(len(v) for v in parts.values()) >= total:
                cipher = b"".join(parts[k] for k in sorted(parts))[:total]
                plain = decrypt_aes(cipher, key)
                if plain is None:
                    logger.debug("加密回复解密失败")
                    return b""
                return wrap_plain_reply(plain)
            continue
        # 其它帧忽略
    return b""


def _encrypted_exchange(sock: socket.socket, data: bytes, recv_timeout: float,
                        pc_salt: Optional[bytes]) -> bytes:
    """在已建连的 socket 内完成 swap-salt 密钥交换 + AES 加密收发。

    返回**明文化**的响应字节流（形如普通 0x2104 帧），可直接喂给
    :func:`parse_multi_frame_response`；任何环节失败返回空字节串。
    """
    salt = pc_salt if pc_salt is not None else os.urandom(SALT_SIZE)
    if len(salt) != SALT_SIZE:
        raise ValueError(f"pc_salt 必须为 {SALT_SIZE} 字节")

    sock.settimeout(recv_timeout)
    sock.sendall(build_swap_salt(salt))
    device_salt = _recv_swap_salt_answer(sock, recv_timeout)
    if device_salt is None:
        return b""

    key = derive_key(salt, device_salt)
    plaintext = data[HEADER_SIZE:] if len(data) >= HEADER_SIZE else data
    ciphertext = encrypt_aes(plaintext, key)
    for frame in build_aes_frames(ciphertext, TYPE_AES_ASK):
        sock.sendall(frame)
    return _recv_encrypted_reply(sock, key, recv_timeout)


def send_request(host: str, data: bytes, port: int = PROTOCOL_PORT,
                 connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                 recv_timeout: float = PROTOCOL_RECV_TIMEOUT,
                 early_exit_s: Optional[float] = DEFAULT_EARLY_EXIT_S,
                 greet_timeout: float = GREET_TIMEOUT,
                 encrypt: bool = False,
                 pc_salt: Optional[bytes] = None) -> bytes:
    """按 MagicPlayer 流程经 TCP 发送请求并接收回复：握手 → 请求帧 → 读回复。

    Args:
        encrypt: 敏感命令（``exec`` / ``SetDeviceID``）必须置 True。开启后在同一
            连接内先做 swap-salt 密钥交换，再以 AES-128-CBC 加密发送并解密接收；
            ``data`` 仍传 :func:`build_frame` 的（12 字节头）明文帧，函数内部自动
            剥头取 JSON body 后加密。
        pc_salt: 可选的 16 字节随机盐（测试/复现用）；缺省随机。

    Returns:
        收到的原始字节流（加密通道为解密后重新封装的明文 0x2104 帧；可能为空）
    """
    with host_lock(host):
        try:
            with socket.create_connection((host, port), timeout=connect_timeout) as sock:
                sock.settimeout(greet_timeout)
                try:
                    greeting = _recv_exact(sock, 4)
                except socket.timeout:
                    greeting = b""
                if len(greeting) == 4:
                    sock.sendall(HANDSHAKE_REPLY)

                if encrypt:
                    return _encrypted_exchange(sock, data, recv_timeout, pc_salt)
                return _plaintext_exchange(sock, data, recv_timeout,
                                           early_exit_s or 0.0)
        except OSError as exc:
            logger.debug("协议请求 %s:%s 失败: %s", host, port, exc)
            return b""
