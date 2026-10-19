#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备→PC 的「文件下载」帧通道（ReadBack ``fileTransferMode=2`` 用）。

协议 ``ReadBack`` 以 Socket 方式回传大数据（截图/日志）时，**并不是**把数据
塞进 reply，而是：reply 只给文件 **md5 引用**，实体则在**同一 TCP 连接**上由设备
用文件帧推来，且**需要 PC 逐帧应答**，否则设备发完文件头就静默挂住。

帧序列（下载方向，设备 → PC）与应答（PC → 设备）::

    0x2104 JSON reply（可能 12 字节头分片） → 无需应答
    0x8001 文件头：md5\\0 + u64 size + u16 fileType + name\\0
                                            → 必须回 0x8002(u16 code + u64 offset)
    0x8003 数据块（8192B/帧）                → 无需逐帧应答
    0x8005 本文件结束                        → 回 0x8006
    0x005F 心跳（任意时刻）                  → 立即回 0x0060，否则被断连

本模块把「收帧 → 解析 → 产出应答」做成**纯状态机** :class:`FileDownloadState`，
socket 收发在 :func:`receive_file` 里，便于离线单测（脚本化假设备即可驱动）。
"""

import hashlib
import json
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_PORT, PROTOCOL_RECV_TIMEOUT
from service.logging_service import get_logger

from .client import HANDSHAKE_REPLY, _recv_exact, host_lock  # pylint: disable=protected-access
from .frame import HEADER_SIZE, TYPE_HEARTBEAT, TYPE_REPLY, build_heartbeat_reply

logger = get_logger(__name__)

FT_FILE_HEAD = 0x8001
"""设备 → PC：文件头（md5 / size / fileType / name）"""

FT_FILE_DATA = 0x8003
"""设备 → PC：文件数据块"""

FT_FILE_EOF = 0x8005
"""设备 → PC：本文件发送结束"""

FT_FILE_HEAD_ACK = 0x8002
"""PC → 设备：文件头应答（u16 结果码 + u64 起始偏移），缺它设备不发数据块"""

FT_FILE_DONE = 0x8006
"""PC → 设备：文件完成确认"""

RECV_CHUNK = 65536
"""单次 recv 上限"""

TAIL_SECONDS = 1.0
"""收到 0x8005 后再多等一小段，收尾可能滞后的数据块"""

FILE_HEAD_GRACE_SECONDS = 5.0
"""收到 JSON 回复后，等待文件头的宽限（秒）：超时仍未给文件头即提前收尾。

设备侧完成截图（实测 4~5s）后会**立即**回 JSON + 文件头，故该宽限足够；
设置它是为了避免设备只回 JSON（如 ``kNotImplemented``）时白等满接收超时。
"""


def build_bin_frame(mtype: int, body: bytes = b"") -> bytes:
    """4 字节通用帧（文件传输应答 / 心跳应答）。"""
    return struct.pack("<HH", 4 + len(body), mtype) + body


def reply_result(reply: Optional[dict]) -> str:
    """取 reply 的 result 码；结构不符返回空串。"""
    if not isinstance(reply, dict):
        return ""
    return str(reply.get("result", ""))


def parse_file_head(body: bytes) -> Dict[str, Any]:
    """解析 0x8001 文件头载荷：``md5\\0 + u64 size + u16 fileType + name\\0``。

    结构不符时返回全空字段（**不猜测**）。
    """
    try:
        md5b, rest = body.split(b"\x00", 1)
        return {
            "md5": md5b.decode("ascii", "replace"),
            "size": struct.unpack_from("<Q", rest, 0)[0],
            "file_type": struct.unpack_from("<H", rest, 8)[0],
            "name": rest[10:].split(b"\x00", 1)[0].decode("utf-8", "replace"),
        }
    except (ValueError, struct.error):
        return {"md5": "", "size": 0, "file_type": 0, "name": ""}


@dataclass
class FileDownload:
    """一次文件下载的结果。"""

    name: Optional[str] = None
    md5: Optional[str] = None
    size: Optional[int] = None
    file_type: Optional[int] = None
    data: bytes = b""
    md5_match: Optional[bool] = None

    @property
    def ok(self) -> bool:
        """是否真的收到了文件数据。"""
        return bool(self.data)


class FileDownloadState:
    """「设备 → PC 文件下载」纯状态机（不碰 socket，便于离线单测）。

    用法：把收到的字节喂给 :meth:`feed`，把返回的帧立刻回给设备；
    结束后用 :meth:`download` 取结果。
    """

    def __init__(self):
        self.buffer = bytearray()
        self.reply: Optional[dict] = None
        """解析出的 reply 对象（0x2104 JSON，可能分片重组）"""
        self.head: Optional[Dict[str, Any]] = None
        self.data = bytearray()
        self.eof = False
        self._json_parts: Dict[int, bytes] = {}
        self._json_total = 0

    def feed(self, chunk: bytes) -> List[bytes]:
        """追加字节流并处理其中的完整帧；返回需要回给设备的应答帧。"""
        replies: List[bytes] = []
        self.buffer += chunk
        while len(self.buffer) >= 4:
            frame_len = self.buffer[0] | (self.buffer[1] << 8)
            mtype = self.buffer[2] | (self.buffer[3] << 8)
            if frame_len < 4 or frame_len > len(self.buffer):
                break  # 残帧，等后续 TCP 段
            frame = bytes(self.buffer[:frame_len])
            del self.buffer[:frame_len]
            replies.extend(self._handle_frame(mtype, frame))
        return replies

    def _handle_frame(self, mtype: int, frame: bytes) -> List[bytes]:
        body4 = frame[4:]
        if mtype == TYPE_REPLY:
            self._collect_json(frame)
            return []
        if mtype == FT_FILE_HEAD:
            self.head = parse_file_head(body4)
            # code=0 接受文件、offset=0 从头发送（断点续传可给非 0 偏移）
            return [build_bin_frame(FT_FILE_HEAD_ACK, struct.pack("<HQ", 0, 0))]
        if mtype == FT_FILE_DATA:
            self.data += body4
            return []
        if mtype == FT_FILE_EOF:
            self.eof = True
            return [build_bin_frame(FT_FILE_DONE)]
        if mtype == TYPE_HEARTBEAT:
            return [build_heartbeat_reply()]
        return []

    def _collect_json(self, frame: bytes) -> None:
        """重组 0x2104 JSON 回复（12 字节头：u16 总长 @4、u16 分片偏移 @8）。"""
        if len(frame) < HEADER_SIZE:
            return
        self._json_total = frame[4] | (frame[5] << 8)
        offset = frame[8] | (frame[9] << 8)
        self._json_parts[offset] = frame[HEADER_SIZE:]
        ordered = b"".join(self._json_parts[k] for k in sorted(self._json_parts))
        if self._json_total and len(ordered) >= self._json_total:
            self._json_parts.clear()
            try:
                parsed = json.loads(ordered[:self._json_total].decode(
                    "utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            if isinstance(parsed, dict) and isinstance(parsed.get("reply"), dict):
                self.reply = parsed["reply"]

    def download(self) -> Optional[FileDownload]:
        """取下载结果；未收到文件头返回 None。"""
        if self.head is None:
            return None
        blob = bytes(self.data)
        md5 = self.head.get("md5") or ""
        match = (hashlib.md5(blob).hexdigest() == md5) if (blob and md5) else None
        return FileDownload(
            name=self.head.get("name"), md5=md5, size=self.head.get("size"),
            file_type=self.head.get("file_type"), data=blob, md5_match=match,
        )


def receive_file(host: str, frame: bytes, *, port: int = PROTOCOL_PORT,
                 connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                 recv_timeout: float = PROTOCOL_RECV_TIMEOUT,
                 tail_seconds: float = TAIL_SECONDS
                 ) -> Tuple[Optional[dict], Optional[FileDownload]]:
    """发出一条请求帧，并按「文件下载」通道交互式收完整文件。

    与 :func:`service.protocol.client.send_request` 的「发→收→关」不同：设备推文件
    需要**边收边应答**（0x8002 / 0x8006 / 0x0060），否则会静默挂住。

    Args:
        host: 设备 IP
        frame: 已构造好的请求帧（12 字节头 + JSON body，明文）
        port / connect_timeout / recv_timeout: 连接与总接收超时
        tail_seconds: 收到 0x8005 后再多等的小窗口（秒）

    Returns:
        ``(reply, download)``；reply 为 0x2104 JSON 的 ``reply`` 对象（无则 None），
        download 为文件下载结果（无则 None）。
    """
    state = FileDownloadState()
    with host_lock(host):
        try:
            with socket.create_connection((host, port), timeout=connect_timeout) as sock:
                _handshake(sock)
                sock.sendall(frame)
                _pump(sock, state, recv_timeout, tail_seconds)
        except OSError as exc:
            logger.debug("文件下载通道 %s:%s 失败: %s", host, port, exc)
    return state.reply, state.download()


def _handshake(sock: socket.socket, greet_timeout: float = 0.15) -> None:
    """MagicPlayer 建连握手：读设备问候（若有）并回 0x0060。"""
    sock.settimeout(greet_timeout)
    try:
        greeting = _recv_exact(sock, 4)
    except socket.timeout:
        greeting = b""
    if len(greeting) == 4:
        sock.sendall(HANDSHAKE_REPLY)


def _pump(sock: socket.socket, state: FileDownloadState, recv_timeout: float,
          tail_seconds: float) -> None:
    """接收循环：读字节 → 喂状态机 → 立即回设备所需应答（含提前收尾）。"""
    deadline = time.monotonic() + recv_timeout
    tail_until = 0.0
    reply_seen_at = 0.0
    while True:
        now = time.monotonic()
        wait = (tail_until - now) if state.eof else (deadline - now)
        if wait <= 0:
            break
        # 每次 recv 最多阻塞 1s：保证下面的「提前收尾」判定能周期性执行
        sock.settimeout(max(0.5, min(wait, 1.0)))
        try:
            chunk = sock.recv(RECV_CHUNK)
        except socket.timeout:
            if state.eof:
                break
            continue
        if not chunk:
            break  # 对端关闭
        for reply_frame in state.feed(chunk):
            try:
                sock.sendall(reply_frame)
            except OSError:
                return
        if state.eof and not tail_until:
            tail_until = time.monotonic() + tail_seconds
        if state.reply is not None and not reply_seen_at:
            reply_seen_at = time.monotonic()

        # 提前收尾①：回复为非成功（如 kNotImplemented）→ 设备不会再推文件
        if state.head is None and reply_seen_at and reply_result(state.reply) != "kSuccess":
            logger.debug("文件通道回复非成功(%s)，提前收尾", reply_result(state.reply))
            break
        # 提前收尾②：成功回复后迟迟不给文件头（超出宽限）→ 不再白等。
        # 注：**不**按「已收字节数 == 文件头 size」提前收尾 —— 0x8005 与 0x8006
        # 应答是设备判定本次传输完成的依据，跳过会留下未收尾的传输状态。
        if (state.head is None and reply_seen_at
                and time.monotonic() - reply_seen_at >= FILE_HEAD_GRACE_SECONDS):
            logger.debug("收到成功回复但 %.1fs 未收到文件头，提前收尾",
                         FILE_HEAD_GRACE_SECONDS)
            break
