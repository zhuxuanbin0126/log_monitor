"""协议校时（Set Time）离线单测：报文构造 + 回环假设备往返。"""

import json
import socket
import struct
import threading
from datetime import datetime, timedelta, timezone

from service.protocol.frame import TYPE_HEARTBEAT, TYPE_REPLY
from service.protocol.set_time import (
    BEIJING_TIME_ZONE, build_time_message, set_time,
)

BEIJING = timezone(timedelta(hours=8))


def test_build_time_message_fields():
    message = build_time_message("2026-10-19 14:12:38")
    assert message["module"] == "Set"
    assert message["version"] == 5
    body = message["ask"]["Time"]
    assert body["dateTime"] == "2026-10-19 14:12:38"
    assert body["ntp"] == {"ntpHost": ["ntp.huidu.cn"]}
    assert body["sync"] == "auto"
    assert body["syncInterDevice"] == 0
    assert body["timeZone"] == BEIJING_TIME_ZONE


def test_build_time_message_custom_ntp_and_zone():
    message = build_time_message(
        "2026-10-19 14:12:38", ntp_hosts=["pool.ntp.org", "ntp.aliyun.com"],
        sync="ntp", sync_inter_device=1,
        time_zone={"rawOffset": "UTC+09:00", "timeZoneId": "Asia/Tokyo",
                   "timeZoneOffset": "UTC+09:00"})
    body = message["ask"]["Time"]
    assert body["ntp"]["ntpHost"] == ["pool.ntp.org", "ntp.aliyun.com"]
    assert body["sync"] == "ntp"
    assert body["syncInterDevice"] == 1
    assert body["timeZone"]["timeZoneId"] == "Asia/Tokyo"


class _FakeSetDevice:
    """回环假设备：应答一次 kSuccess（记录收到的请求报文）。"""

    def __init__(self, result="kSuccess", with_greeting=True):
        self.result = result
        self.with_greeting = with_greeting
        self.request = None
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
            piece = conn.recv(size - len(buf))
            if not piece:
                break
            buf += piece
        return buf

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
            conn.settimeout(5)
            if self.with_greeting:
                conn.sendall(struct.pack("<HH", 4, TYPE_HEARTBEAT))
                self._recv_exact(conn, 4)               # 握手应答
            head = self._recv_exact(conn, 12)           # JSON 帧头为 12 字节
            frame_len = struct.unpack("<H", head[:2])[0]
            body = self._recv_exact(conn, frame_len - 12)
            self.request = json.loads(body.decode("utf-8"))
            reply = json.dumps({"module": "Set", "reply": {"result": self.result}}).encode()
            conn.sendall(struct.pack("<HHHHHH", 12 + len(reply), TYPE_REPLY,
                                     len(reply), 0, 0, 0) + reply)
            conn.close()
        except OSError:
            pass


def test_set_time_sends_utc_and_reports_success():
    device = _FakeSetDevice()
    device.start()
    # 本机北京时间 21:54:47（UTC+8）→ 下发应为 UTC 13:54:47
    local = datetime(2026, 10, 19, 21, 54, 47, tzinfo=BEIJING)
    ok, message = set_time("127.0.0.1", port=device.port, now=local,
                           connect_timeout=2.0, recv_timeout=2.0)

    assert ok is True
    assert "13:54:47" in message
    assert device.request["ask"]["Time"]["dateTime"] == "2026-10-19 13:54:47"
    assert device.request["ask"]["Time"]["timeZone"]["timeZoneId"] == "Asia/Shanghai"


def test_set_time_naive_now_treated_as_utc():
    device = _FakeSetDevice()
    device.start()
    ok, _ = set_time("127.0.0.1", port=device.port,
                     now=datetime(2026, 10, 19, 14, 12, 38),
                     connect_timeout=2.0, recv_timeout=2.0)
    assert ok is True
    assert device.request["ask"]["Time"]["dateTime"] == "2026-10-19 14:12:38"


def test_set_time_reports_failure_result():
    device = _FakeSetDevice(result="kPermissionDenied")
    device.start()
    ok, message = set_time("127.0.0.1", port=device.port,
                           connect_timeout=2.0, recv_timeout=2.0)
    assert ok is False
    assert "kPermissionDenied" in message


def test_set_time_unreachable_device():
    ok, message = set_time("127.0.0.1", port=1,
                           connect_timeout=0.2, recv_timeout=0.2)
    assert ok is False
    assert "无响应" in message
