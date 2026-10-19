"""协议 Set Development（开/关 ADB）与 adb 推送后校验的离线单测。

用回环 TCP 假设备按脚本回复，覆盖：报文形态、成功路径、kPermissionDenied →
KeyEvent 解锁 → 用解锁 key 重发成功；以及 verify_remote_file 的三条分支。
"""

import json
import socket
import struct
import threading

import pytest

from service.adb_service import ADBService
from service.protocol.frame import HEADER_SIZE, TYPE_REPLY, build_frame
from service.protocol.set_query import (
    ADB_TIMER_OFF, ADB_TIMER_ON, ADB_MODE_TCP, ADB_MODE_USB, DEVELOPMENT_KEY,
    DEVELOPMENT_SETTING, KEYEVENT_UNLOCK_KEY, build_development_message,
    build_keyevent_unlock_message, enable_all_adb, set_development,
)


def _recv_exact(conn, size):
    buf = b""
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


class _ScriptedDevice:
    """回环 TCP 假设备：每个连接读一条 0x2103 请求，按脚本回一条 0x2104 回复。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.requests = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(5.0)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        while self._replies:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5.0)
                conn.sendall(struct.pack("<HH", 4, 0x005F))   # 问候（心跳）
                _recv_exact(conn, 4)                          # 0x0060 握手
                head = _recv_exact(conn, 4)
                if len(head) < 4:
                    continue
                frame_len, _ = struct.unpack("<HH", head)
                body = _recv_exact(conn, frame_len - 4)
                self.requests.append(json.loads(body[HEADER_SIZE - 4:].decode("utf-8")))
                conn.sendall(build_frame(self._replies.pop(0), TYPE_REPLY))

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._thread.join(timeout=6.0)
        self._sock.close()
        return False


def _ok():
    return {"module": "Set", "reply": {"result": "kSuccess"}}


# ---------------------------------------------------------------- 报文形态

def test_build_development_message_shape():
    msg = build_development_message(ADB_MODE_TCP, ADB_TIMER_ON)
    assert msg["module"] == "Set"
    assert msg["tag"] == DEVELOPMENT_SETTING
    assert msg["key"] == DEVELOPMENT_KEY
    assert msg["version"] == 5
    assert msg["ask"] == {DEVELOPMENT_SETTING: {"adbMode": "tcp", "adbTimer": 0}}
    assert "log" in msg and "uuid" in msg


def test_build_keyevent_unlock_message_shape():
    msg = build_keyevent_unlock_message()
    assert msg["module"] == "KeyEvent"
    assert msg["ask"] == "Test"
    assert msg["key"] == KEYEVENT_UNLOCK_KEY
    assert msg["version"] == 5


# ---------------------------------------------------------------- 协议开 ADB

def test_set_development_success():
    with _ScriptedDevice([_ok()]) as server:
        ok, msg = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_ON,
                                  port=server.port, connect_timeout=3.0,
                                  recv_timeout=2.0)
    assert ok is True
    assert "已通过协议开启 ADB" in msg
    sent = server.requests[0]
    assert sent["ask"] == {DEVELOPMENT_SETTING: {"adbMode": "tcp", "adbTimer": 0}}
    assert sent["key"] == DEVELOPMENT_KEY


def test_set_development_disable_uses_timer_off():
    with _ScriptedDevice([_ok()]) as server:
        ok, _ = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_OFF,
                                port=server.port, connect_timeout=3.0,
                                recv_timeout=2.0)
    assert ok is True
    assert server.requests[0]["ask"] == {
        DEVELOPMENT_SETTING: {"adbMode": "tcp", "adbTimer": 1}}


def test_set_development_permission_denied_triggers_keyevent_retry():
    denied = {"module": "Set", "reply": {"result": "kPermissionDenied"}}
    with _ScriptedDevice([denied, _ok(), _ok()]) as server:
        ok, msg = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_ON,
                                  port=server.port, connect_timeout=3.0,
                                  recv_timeout=2.0)

    assert ok is True
    assert "开启" in msg
    assert len(server.requests) == 3
    # 1) 首次 Set 用开发者 key
    assert server.requests[0]["key"] == DEVELOPMENT_KEY
    # 2) 解锁用 KeyEvent
    assert server.requests[1]["module"] == "KeyEvent"
    assert server.requests[1]["key"] == KEYEVENT_UNLOCK_KEY
    # 3) 重发 Set 改用解锁 key
    assert server.requests[2]["module"] == "Set"
    assert server.requests[2]["key"] == KEYEVENT_UNLOCK_KEY


def test_set_development_permission_denied_and_unlock_fails():
    denied = {"module": "Set", "reply": {"result": "kPermissionDenied"}}
    failed_unlock = {"module": "KeyEvent", "reply": {"result": "kProcessError"}}
    with _ScriptedDevice([denied, failed_unlock]) as server:
        ok, msg = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_ON,
                                  port=server.port, connect_timeout=3.0,
                                  recv_timeout=2.0)
    assert ok is False
    assert "kPermissionDenied" in msg


def test_set_development_non_success_result():
    with _ScriptedDevice([{"module": "Set", "reply": {"result": "kProcessError"}}]) as server:
        ok, msg = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_ON,
                                  port=server.port, connect_timeout=3.0,
                                  recv_timeout=2.0)
    assert ok is False
    assert "kProcessError" in msg


def test_set_development_invalid_mode_raises():
    with pytest.raises(ValueError):
        set_development("127.0.0.1", "serial", ADB_TIMER_ON)


def test_set_development_unreachable_returns_false():
    ok, msg = set_development("127.0.0.1", ADB_MODE_TCP, ADB_TIMER_ON, port=1,
                              connect_timeout=0.3, recv_timeout=0.3)
    assert ok is False
    assert "无响应" in msg


def test_enable_all_adb_uses_both_modes():
    with _ScriptedDevice([_ok()]) as server:
        ok, _ = enable_all_adb("127.0.0.1", port=server.port,
                               connect_timeout=3.0, recv_timeout=2.0)
    assert ok is True
    assert server.requests[0]["ask"] == {
        DEVELOPMENT_SETTING: {"adbMode": "usb,tcp", "adbTimer": 0}}


# ---------------------------------------------------------------- 推送后校验

def test_verify_remote_file_missing(monkeypatch):
    monkeypatch.setattr(ADBService, 'check_file_exists', staticmethod(lambda *a, **k: False))
    ok, msg = ADBService.verify_remote_file("192.168.1.5", "/data/x", "abc")
    assert ok is False
    assert "不存在" in msg


def test_verify_remote_file_md5_matches(monkeypatch):
    monkeypatch.setattr(ADBService, 'check_file_exists', staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(ADBService, 'calc_file_md5', staticmethod(lambda *a, **k: 'abc'))
    ok, msg = ADBService.verify_remote_file("192.168.1.5", "/data/x", "abc")
    assert ok is True
    assert "MD5 一致" in msg


def test_verify_remote_file_md5_mismatch(monkeypatch):
    monkeypatch.setattr(ADBService, 'check_file_exists', staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(ADBService, 'calc_file_md5', staticmethod(lambda *a, **k: 'zzz'))
    ok, msg = ADBService.verify_remote_file("192.168.1.5", "/data/x", "abc")
    assert ok is False
    assert "不一致" in msg


def test_verify_remote_file_degrades_when_md5_unavailable(monkeypatch):
    monkeypatch.setattr(ADBService, 'check_file_exists', staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(ADBService, 'calc_file_md5', staticmethod(lambda *a, **k: None))
    ok, msg = ADBService.verify_remote_file("192.168.1.5", "/data/x", "abc")
    assert ok is True
    assert "降级" in msg
