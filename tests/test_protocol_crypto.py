"""MagicPlayer 加密通道与 Command.exec 离线单测。

覆盖：AES-128-CBC/PKCS7 与密钥派生、盐值帧布局、exec 报文构造与结果解析，
以及「回环假设备」上的完整加密往返（交换盐值 → 加密请求 → 解密回复）。
"""

import hashlib
import json
import socket
import struct
import threading

import pytest

from service.protocol.command_query import (
    ENCRYPTED_METHODS, ExecResult, build_exec_message, exec_command,
    extract_exec_result, line_count_from_output, message_needs_encryption,
)
from service.protocol.crypto import (
    AES_IV, BLOCK_SIZE, KEY_PREFIX, decrypt_aes, derive_key, encrypt_aes,
    pkcs7_pad, pkcs7_unpad, to_hex,
)
from service.protocol.frame import (
    HEADER_SIZE, SALT_SIZE, TYPE_AES_ANSWER, TYPE_AES_ASK, TYPE_REQUEST,
    TYPE_SWAP_SALT_ANSWER, TYPE_SWAP_SALT_ASK, build_frame, build_swap_salt,
    parse_aes_chunk, parse_swap_salt_answer,
)

_PC_SALT = bytes(range(16))
_DEVICE_SALT = bytes(range(16, 32))


# ---------------------------------------------------------------- 密码学

def test_aes_iv_and_prefix_constants():
    assert AES_IV == b"1234567890000000"
    assert len(AES_IV) == BLOCK_SIZE
    assert KEY_PREFIX == "HUIDUSDK"


def test_derive_key_matches_device_formula():
    expected = hashlib.md5(
        ("HUIDUSDK" + to_hex(_PC_SALT) + to_hex(_DEVICE_SALT)).encode("utf-8")
    ).digest()
    assert derive_key(_PC_SALT, _DEVICE_SALT) == expected
    assert len(derive_key(_PC_SALT, _DEVICE_SALT)) == 16


def test_pkcs7_pad_unpad_roundtrip():
    for size in (0, 1, 15, 16, 17, 100):
        data = bytes(range(size % 256)) * (1 + size // 256)
        data = data[:size]
        padded = pkcs7_pad(data)
        assert len(padded) % BLOCK_SIZE == 0
        assert pkcs7_unpad(padded) == data
    with pytest.raises(ValueError):
        pkcs7_unpad(b"\x00" * 15)  # 非块对齐


def test_encrypt_decrypt_roundtrip_and_wrong_key():
    key = derive_key(_PC_SALT, _DEVICE_SALT)
    payload = json.dumps({"ask": {"list": ["Time"]}}).encode("utf-8")

    cipher = encrypt_aes(payload, key)
    assert len(cipher) % BLOCK_SIZE == 0
    assert cipher != payload
    assert decrypt_aes(cipher, key) == payload

    other_key = derive_key(_DEVICE_SALT, _PC_SALT)
    assert decrypt_aes(cipher, other_key) is None


def test_decrypt_aes_rejects_misaligned_cipher():
    assert decrypt_aes(b"\x00" * 17, derive_key(_PC_SALT, _DEVICE_SALT)) is None


# ---------------------------------------------------------------- 盐值/AES 帧

def test_build_and_parse_swap_salt():
    frame = build_swap_salt(_PC_SALT)
    assert len(frame) == 4 + SALT_SIZE
    assert struct.unpack_from("<H", frame, 0)[0] == 4 + SALT_SIZE
    assert struct.unpack_from("<H", frame, 2)[0] == TYPE_SWAP_SALT_ASK
    assert frame[4:] == _PC_SALT
    assert parse_swap_salt_answer(frame[4:]) == _PC_SALT
    assert parse_swap_salt_answer(b"\x00" * 4) is None

    with pytest.raises(ValueError):
        build_swap_salt(b"\x00" * 8)


def test_parse_aes_chunk_layout():
    body = struct.pack("<II", 40, 8) + b"cipher-bytes"
    parsed = parse_aes_chunk(body)
    assert parsed == (40, 8, b"cipher-bytes")
    assert parse_aes_chunk(b"\x00" * 4) is None


# ---------------------------------------------------------------- exec 报文与解析

def test_build_exec_message_shape():
    msg = build_exec_message("cat /data/swich_counter.csv | wc -l")
    assert msg["module"] == "Command"
    assert msg["tag"] == "exec"
    assert msg["version"] == 5
    assert msg["ask"]["method"] == "exec"
    params = msg["ask"]["params"]
    assert params["input"] == "cat /data/swich_counter.csv | wc -l"
    assert params["async"] is False
    assert params["start"] == "su"


def test_message_needs_encryption_only_for_command_module():
    assert message_needs_encryption(build_exec_message("ls")) is True
    assert ENCRYPTED_METHODS == frozenset({"exec", "SetDeviceID"})
    # 非 Command 模块即使方法名巧合也不加密
    assert message_needs_encryption(
        {"module": "Get", "ask": {"method": "exec"}}) is False
    assert message_needs_encryption(None) is False


def test_extract_exec_result_parses_output():
    parsed = {"module": "Command", "reply": {
        "method": "exec", "result": "kSuccess",
        "data": {"input": "wc -l x", "exitCode": 0, "output": "12\n", "error": ""}}}
    result = extract_exec_result(parsed)
    assert result == ExecResult(input="wc -l x", exit_code=0, output="12\n", error="")
    assert result.text() == "12"


def test_extract_exec_result_rejects_non_success_and_bad_shape():
    assert extract_exec_result(
        {"module": "Command", "reply": {"result": "kProcessError", "errorMsg": "x"}}) is None
    assert extract_exec_result({"module": "Get", "reply": {"data": {}}}) is None
    assert extract_exec_result(None) is None


def test_line_count_from_output():
    assert line_count_from_output(ExecResult(exit_code=0, output="12\n")) == 12
    assert line_count_from_output(ExecResult(exit_code=0, output="  7")) == 7
    assert line_count_from_output(ExecResult(exit_code=1, output="12\n")) is None
    assert line_count_from_output(ExecResult(exit_code=0, output="")) is None
    assert line_count_from_output(ExecResult(exit_code=0, output="abc")) is None
    assert line_count_from_output(None) is None


# ---------------------------------------------------------------- 回环假设备（加密）

def _recv_exact(conn, size):
    buf = b""
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _read_frame(conn):
    head = _recv_exact(conn, 4)
    if len(head) < 4:
        return None, b""
    frame_len, msg_type = struct.unpack("<HH", head)
    body = _recv_exact(conn, frame_len - 4)
    return msg_type, body


class _MockEncryptedDevice:
    """回环 TCP 假设备（加密会话）：问候 → 握手 → 交换盐值 → 解密请求 → 加密回复。"""

    def __init__(self, reply_obj):
        self._reply_obj = reply_obj
        self.received_handshake = None
        self.received_request = None       # 解密后的请求 JSON
        self.swap_salt_request = None
        self.key = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._sock.settimeout(5.0)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5.0)
            # 1) 设备问候（4 字节心跳帧）+ 期待 0x0060 握手
            conn.sendall(struct.pack("<HH", 4, 0x005F))
            self.received_handshake = _recv_exact(conn, 4)

            # 2) 交换盐值：读 0x2201，回 0x2202
            msg_type, body = _read_frame(conn)
            if msg_type != TYPE_SWAP_SALT_ASK:
                return
            self.swap_salt_request = body[:SALT_SIZE]
            conn.sendall(struct.pack("<HH", 4 + SALT_SIZE, TYPE_SWAP_SALT_ANSWER)
                         + _DEVICE_SALT)
            self.key = derive_key(self.swap_salt_request, _DEVICE_SALT)

            # 3) 读 AES 请求帧并按 total/offset 重组密文
            parts = {}
            total = None
            while True:
                msg_type, body = _read_frame(conn)
                if msg_type != TYPE_AES_ASK:
                    continue
                parsed = parse_aes_chunk(body)
                if parsed is None:
                    return
                total, offset, chunk = parsed
                if chunk:
                    parts[offset] = chunk
                if total and sum(len(v) for v in parts.values()) >= total:
                    break
            cipher = b"".join(parts[k] for k in sorted(parts))[:total]
            plain = decrypt_aes(cipher, self.key)
            if plain is None:
                return
            self.received_request = json.loads(plain.decode("utf-8"))

            # 4) 加密回复（单帧 0x2106）
            reply_cipher = encrypt_aes(
                json.dumps(self._reply_obj, separators=(",", ":")).encode("utf-8"),
                self.key)
            frame = struct.pack("<HHII", HEADER_SIZE + len(reply_cipher),
                                TYPE_AES_ANSWER, len(reply_cipher), 0) + reply_cipher
            conn.sendall(frame)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._thread.join(timeout=6.0)
        self._sock.close()
        return False


def test_exec_command_encrypted_roundtrip():
    reply = {"module": "Command", "reply": {
        "method": "exec", "result": "kSuccess",
        "data": {"input": "cat /data/swich_counter.csv | wc -l",
                 "exitCode": 0, "output": "13\n", "error": ""}}}

    with _MockEncryptedDevice(reply) as server:
        result = exec_command("127.0.0.1", "cat /data/swich_counter.csv | wc -l",
                              port=server.port, connect_timeout=3.0,
                              recv_timeout=2.0)

    assert result is not None
    assert result.exit_code == 0
    assert result.text() == "13"

    # 握手回包正确
    assert server.received_handshake == struct.pack("<HH", 4, 0x0060)
    # 盐值已交换（PC 盐 16 字节随机，非全零）
    assert server.swap_salt_request is not None and len(server.swap_salt_request) == 16
    # 请求确为加密后解密得到，且字段符合 Command.exec 规格
    sent = server.received_request
    assert sent["module"] == "Command"
    assert sent["tag"] == "exec"
    assert sent["version"] == 5
    assert sent["ask"]["method"] == "exec"
    assert sent["ask"]["params"]["input"] == "cat /data/swich_counter.csv | wc -l"
    assert sent["ask"]["params"]["start"] == "su"
    assert sent["ask"]["params"]["async"] is False


def test_exec_command_returns_none_when_unreachable():
    assert exec_command("127.0.0.1", "ls", port=1,
                        connect_timeout=0.3, recv_timeout=0.3) is None


def test_exec_command_returns_none_on_device_rejecting_swap_salt():
    """设备以 0x2000 拒绝交换盐值 → 加密通道建立失败 → None（触发上层回落）。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5.0)
    port = server.getsockname()[1]

    def serve():
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5.0)
            conn.sendall(struct.pack("<HH", 4, 0x005F))
            _recv_exact(conn, 4)
            _read_frame(conn)                                  # 读掉 0x2201
            # 协议级拒绝（如 kUnsafeMessage 之外的失败）
            conn.sendall(struct.pack("<HH", 6, 0x2000) + struct.pack("<H", 8))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert exec_command("127.0.0.1", "ls", port=port,
                            connect_timeout=3.0, recv_timeout=2.0) is None
    finally:
        thread.join(timeout=6.0)
        server.close()


def test_build_frame_request_type_for_exec():
    """exec 请求帧用 0x2103 明文帧承载，再由客户端剥头加密。"""
    frame = build_frame(build_exec_message("ls"), TYPE_REQUEST)
    assert struct.unpack_from("<H", frame, 2)[0] == TYPE_REQUEST
    assert json.loads(frame[HEADER_SIZE:].decode())["module"] == "Command"
