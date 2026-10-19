"""协议截图文件通道（file_receive / readback_query）离线单测。

- 纯状态机用**合成帧**驱动（不触网）；
- 端到端用本机回环「脚本化假设备」按下载方向协议逐帧回传（真实 socket，离线可跑）。
"""

import hashlib
import json
import socket
import struct
import threading

from service.protocol import file_receive as fr
from service.protocol.frame import TYPE_HEARTBEAT, TYPE_REQUEST, TYPE_REPLY, build_frame
from service.protocol.readback_query import build_readback_message

FT_HEARTBEAT_REPLY = 0x0060


# ---------------------------------------------------------------- 帧构造辅助

def _json_frame(obj, fragmented=False):
    body = json.dumps(obj).encode()
    if not fragmented:
        return (struct.pack("<HHHHHH", 12 + len(body), TYPE_REPLY, len(body), 0, 0, 0)
                + body)
    half = len(body) // 2
    return (struct.pack("<HHHHHH", 12 + half, TYPE_REPLY, len(body), 0, 0, 0) + body[:half]
            + struct.pack("<HHHHHH", 12 + len(body) - half, TYPE_REPLY, len(body), 0, half, 0)
            + body[half:])


def _head_frame(md5_hex, size, name, file_type=2):
    body = (md5_hex.encode() + b"\x00" + struct.pack("<Q", size)
            + struct.pack("<H", file_type) + name.encode() + b"\x00")
    return struct.pack("<HH", 4 + len(body), fr.FT_FILE_HEAD) + body


def _data_frame(chunk):
    return struct.pack("<HH", 4 + len(chunk), fr.FT_FILE_DATA) + chunk


def _eof_frame():
    return struct.pack("<HH", 4, fr.FT_FILE_EOF)


def _mtype(frame):
    return struct.unpack_from("<H", frame, 2)[0]


# ---------------------------------------------------------------- 纯状态机

def test_state_acknowledges_file_head():
    state = fr.FileDownloadState()
    replies = state.feed(_head_frame("a" * 32, 10, "shot.png"))
    assert len(replies) == 1
    assert _mtype(replies[0]) == fr.FT_FILE_HEAD_ACK
    assert state.head["name"] == "shot.png"
    assert state.head["size"] == 10


def test_state_collects_data_and_eof_and_reassembles_json():
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    md5 = hashlib.md5(payload).hexdigest()
    state = fr.FileDownloadState()
    state.feed(_json_frame(
        {"module": "ReadBack",
         "reply": {"data": {"ScreenShot": md5}, "result": "kSuccess"}},
        fragmented=True))
    state.feed(_head_frame(md5, len(payload), "shot.png"))
    assert state.feed(_data_frame(payload[:100])) == []
    assert state.feed(_data_frame(payload[100:])) == []

    eof_replies = state.feed(_eof_frame())
    assert _mtype(eof_replies[0]) == fr.FT_FILE_DONE
    assert state.reply["result"] == "kSuccess"

    download = state.download()
    assert download.data == payload
    assert download.md5_match is True
    assert download.name == "shot.png"


def test_state_answers_heartbeat():
    state = fr.FileDownloadState()
    replies = state.feed(struct.pack("<HH", 4, TYPE_HEARTBEAT))
    assert replies == [struct.pack("<HH", 4, FT_HEARTBEAT_REPLY)]


def test_state_buffers_partial_frames():
    state = fr.FileDownloadState()
    head = _head_frame("b" * 32, 4, "x.png")
    assert state.feed(head[:5]) == []          # 不足一帧，先缓存
    assert len(state.feed(head[5:])) == 1


def test_build_readback_message_fields():
    message = build_readback_message(
        "ScreenShot", {"compress": "false"}, file_transfer_mode=2)
    assert message["module"] == "ReadBack"
    assert message["ask"] == {
        "target": "ScreenShot", "options": {"compress": "false"}, "fileTransferMode": 2}
    assert message["version"] == 5


# ---------------------------------------------------------------- 端到端（回环假设备）

class _LoopbackDevice:
    """脚本化假设备：按「文件下载」对称协议逐帧回传，记录收到的应答帧。"""

    def __init__(self, payload, name="screen.png", with_greeting=True):
        self.payload = payload
        self.name = name
        self.md5 = hashlib.md5(payload).hexdigest()
        self.acks = []
        self._with_greeting = with_greeting
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()

    @staticmethod
    def _recv_exact(conn, size):
        buf = b""
        while len(buf) < size:
            chunk = conn.recv(size - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf

    def _read_frame_head(self, conn):
        head = self._recv_exact(conn, 4)
        frame_len = struct.unpack("<H", head[:2])[0]
        body = self._recv_exact(conn, frame_len - 4) if frame_len > 4 else b""
        return struct.unpack("<H", head[2:4])[0], body

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
            conn.settimeout(5)
            if self._with_greeting:
                conn.sendall(struct.pack("<HH", 4, TYPE_HEARTBEAT))
                self._recv_exact(conn, 4)               # 握手应答
            self._read_frame_head(conn)                 # 请求帧

            reply = {"module": "ReadBack",
                     "reply": {"data": {"ScreenShot": self.md5}, "result": "kSuccess"}}
            conn.sendall(_json_frame(reply))
            conn.sendall(_head_frame(self.md5, len(self.payload), self.name))

            self.acks.append(self._read_frame_head(conn))   # 期待 0x8002

            for index in range(0, len(self.payload), 8192):
                conn.sendall(_data_frame(self.payload[index:index + 8192]))
            conn.sendall(_eof_frame())

            self.acks.append(self._read_frame_head(conn))   # 期待 0x8006
            conn.close()
        except OSError:
            pass


def test_receive_file_round_trip_over_loopback():
    payload = b"\x89PNG\r\n\x1a\n" + b"0123456789" * 1000
    device = _LoopbackDevice(payload)
    device.start()

    frame = build_frame(build_readback_message(
        "ScreenShot", {"compress": "false"}, file_transfer_mode=2), TYPE_REQUEST)
    reply, download = fr.receive_file(
        "127.0.0.1", frame, port=device.port, connect_timeout=2.0,
        recv_timeout=5.0, tail_seconds=0.3)

    assert reply["result"] == "kSuccess"
    assert download is not None
    assert download.data == payload
    assert download.md5_match is True
    assert (fr.FT_FILE_HEAD_ACK, struct.pack("<HQ", 0, 0)) == device.acks[0]
    assert device.acks[-1][0] == fr.FT_FILE_DONE


def test_receive_file_without_greeting_still_works():
    payload = b"\x89PNG\r\n\x1a\n" + b"hello"
    device = _LoopbackDevice(payload, with_greeting=False)
    device.start()

    frame = build_frame(build_readback_message(
        "ScreenShot", file_transfer_mode=2), TYPE_REQUEST)
    _, download = fr.receive_file(
        "127.0.0.1", frame, port=device.port, connect_timeout=2.0,
        recv_timeout=5.0, tail_seconds=0.3)

    assert download is not None and download.data == payload


def test_receive_file_head_without_data_is_reported():
    """只收到文件头、无数据块：download.ok 为假，由上层如实报错。"""
    device = _LoopbackDevice(b"", name="empty.png")
    device.start()

    frame = build_frame(build_readback_message(
        "ScreenShot", file_transfer_mode=2), TYPE_REQUEST)
    _, download = fr.receive_file(
        "127.0.0.1", frame, port=device.port, connect_timeout=2.0,
        recv_timeout=3.0, tail_seconds=0.3)

    assert download is not None
    assert download.ok is False
    assert download.name == "empty.png"
