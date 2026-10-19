"""MagicPlayer 协议层离线单测：帧构造/重组、信封、状态转换与握手收发。

用回环 TCP 假设备覆盖完整握手 + 请求/应答往返；无真机依赖。
"""

import json
import socket
import struct
import threading
from datetime import datetime, timedelta, timezone

import service.protocol.query_service as qs
from service.protocol.client import HANDSHAKE_REPLY
from service.protocol.envelope import DEFAULT_VERSION, build_envelope, new_uuid
from service.protocol.frame import (
    HEADER_SIZE, TYPE_REPLY, TYPE_REQUEST, build_frame, extract_bodies,
    parse_multi_frame_response,
)
from service.protocol.get_query import (
    build_get_message, extract_reply_data, query_keys, reassemble_get_frames,
)
from service.protocol.query_service import (
    BEIJING_TZ, UTC_TZ, ProtocolQueryService, build_device_time_info,
    build_uptime_info, normalize_uptime, parse_device_datetime,
)


# ---------------------------------------------------------------- 帧与重组

def test_build_frame_layout():
    frame = build_frame({"a": 1})
    assert struct.unpack_from("<H", frame, 0)[0] == len(frame)
    assert struct.unpack_from("<H", frame, 2)[0] == TYPE_REQUEST
    assert struct.unpack_from("<H", frame, 4)[0] == len(frame) - HEADER_SIZE
    assert json.loads(frame[HEADER_SIZE:].decode("utf-8")) == {"a": 1}


def test_extract_bodies_single_and_multi_frame():
    one = build_frame({"k": 1}, TYPE_REPLY)
    assert extract_bodies(one) == [one[HEADER_SIZE:]]

    two = build_frame({"x": 1}, TYPE_REPLY) + build_frame({"y": 2}, TYPE_REPLY)
    bodies = extract_bodies(two)
    assert len(bodies) == 2
    assert json.loads(bodies[0].decode()) == {"x": 1}
    assert json.loads(bodies[1].decode()) == {"y": 2}


def test_extract_bodies_ignores_truncated_tail():
    frame = build_frame({"k": 1}, TYPE_REPLY)
    assert extract_bodies(frame + b"\x10\x00") == [frame[HEADER_SIZE:]]


def test_parse_multi_frame_response_joins_split_json():
    # 一个 JSON 被拆到两帧（参考实现用 body 拼接后再整体解析）
    body = json.dumps({"reply": {"data": {"n": 5}}}).encode()
    mid = len(body) // 2
    first = struct.pack("<HHHHHH", HEADER_SIZE + mid, TYPE_REPLY, mid, 0, 0, 0) + body[:mid]
    rest = body[mid:]
    second = struct.pack("<HHHHHH", HEADER_SIZE + len(rest), TYPE_REPLY, len(rest), 0, 0, 0) + rest
    assert parse_multi_frame_response(first + second) == {"reply": {"data": {"n": 5}}}


def test_parse_multi_frame_response_rejects_garbage():
    assert parse_multi_frame_response(b"") is None
    assert parse_multi_frame_response(b"\x00") is None
    assert parse_multi_frame_response(b"\x04\x00ab") is None


def test_reassemble_get_frames_reasons():
    assert reassemble_get_frames(b"\x00" * 4).reason == "too_short"
    # 长度够 12 字节但帧长非法（0）→ 无有效帧
    assert reassemble_get_frames(struct.pack("<H", 0) + b"\x00" * 10).reason == "no_frames"

    valid = build_frame({"ok": 1}, TYPE_REPLY)
    result = reassemble_get_frames(valid)
    assert result.ok and result.reason == "ok" and result.frame_count == 1

    # 超过 20 帧（每帧 12 字节，21 帧 = 252 字节）→ frame_overflow
    overflow = reassemble_get_frames(b"\x0c\x00" * 126)
    assert overflow.reason == "frame_overflow"

    # payload 超上限（把 max_payload_size 压到很小触发）
    big = build_frame({"pad": "x" * 200}, TYPE_REPLY)
    assert reassemble_get_frames(big, max_payload_size=10).reason == "payload_overflow"


# ---------------------------------------------------------------- 信封与 Get 报文

def test_envelope_fields_and_default_version():
    msg = build_envelope("Get", {"list": ["Time"]}, msg_uuid="{fixed}")
    assert msg["module"] == "Get"
    assert msg["ask"] == {"list": ["Time"]}
    assert msg["uuid"] == "{fixed}"
    assert msg["version"] == DEFAULT_VERSION == 5
    assert "log" in msg
    assert "tag" not in msg and "key" not in msg


def test_envelope_tag_key_and_log_toggle():
    msg = build_envelope("Set", {"Time": {}}, tag="Time", key="k1", include_log=False)
    assert msg["tag"] == "Time" and msg["key"] == "k1"
    assert "log" not in msg


def test_new_uuid_is_braced():
    value = new_uuid()
    assert value.startswith("{") and value.endswith("}")


def test_build_get_message_uses_list_ask():
    msg = build_get_message(["Time", "DeviceInfo"])
    assert msg["module"] == "Get"
    assert msg["ask"] == {"list": ["Time", "DeviceInfo"]}
    assert msg["version"] == 5


def test_extract_reply_data_rules():
    good = {"reply": {"result": "kSuccess", "data": {"Time": {"dateTime": "x"}}}}
    assert extract_reply_data(good) == {"Time": {"dateTime": "x"}}
    assert extract_reply_data({"reply": {"result": "kProcessError", "data": {}}}) is None
    assert extract_reply_data({"reply": {"data": 3}}) is None
    assert extract_reply_data(None) is None


# ---------------------------------------------------------------- 状态转换

def test_parse_device_datetime_is_utc():
    # 真机实测 Time.dateTime 为 UTC-0 墙钟（与官方上位机 Set.Time 下发口径一致）
    parsed = parse_device_datetime("2026-10-19 18:30:05")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(0)
    assert (parsed.year, parsed.hour, parsed.minute) == (2026, 18, 30)
    assert parse_device_datetime("not-a-date") is None
    assert parse_device_datetime(None) is None
    assert parse_device_datetime(12345) is None


def test_build_uptime_info_matches_adb_format():
    now = datetime(2026, 10, 19, 12, 0, 0)
    device_dt = datetime(2026, 10, 19, 19, 59, 1, tzinfo=BEIJING_TZ)
    info = build_uptime_info(90061, device_dt, now=now)

    assert info["formatted_uptime"] == "1天1时1分"
    assert info["uptime"] == "1 day, 1:01:01"
    assert info["current_time"] == "19:59:01"
    assert info["boot_time"] == (now - timedelta(seconds=90061)).isoformat()
    assert info["current_datetime"] == now.isoformat()


def test_build_uptime_info_without_device_time():
    info = build_uptime_info(0, None, now=datetime(2026, 10, 19, 12, 0, 0))
    assert info["formatted_uptime"] == "0分"
    assert info["current_time"] == "N/A"


def test_build_device_time_info_semantics():
    now = datetime(2026, 10, 19, 18, 0, 0, tzinfo=BEIJING_TZ)
    device_dt = datetime(2026, 10, 19, 19, 0, 0, tzinfo=BEIJING_TZ)
    formatted, diff = build_device_time_info(device_dt, now=now)
    assert diff == 3600                      # 设备快 1 小时
    assert formatted == "2026-10-19 19:00:00"  # 北京时区墙钟（UI 直接展示）


def test_build_device_time_info_converts_utc_to_beijing():
    # 设备上报 2026-10-19 13:54:47（UTC）→ 北京时区应为 21:54:47
    device_dt = datetime(2026, 10, 19, 13, 54, 47, tzinfo=UTC_TZ)
    formatted, diff = build_device_time_info(
        device_dt, now=datetime(2026, 10, 19, 13, 54, 47, tzinfo=UTC_TZ))
    assert formatted == "2026-10-19 21:54:47"
    assert diff == 0


def test_normalize_uptime_handles_milliseconds():
    # 真机实测：开机 4 天 7 小时上报 ≈3.7e8（毫秒），按秒解读会得到 4290 天
    assert normalize_uptime(370709940) == 370709
    assert normalize_uptime("3600000") == 3600
    # 单位开关可切换：按秒上报的设备需显式关闭
    assert normalize_uptime(370709, unit_ms=False) == 370709
    assert normalize_uptime(None) is None
    assert normalize_uptime(-1) is None


# ---------------------------------------------------------------- 回环假设备

def _recv_exact(conn, size):
    buf = b""
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


class _MockDeviceServer:
    """回环 TCP 假设备：发 4 字节问候 → 期待 0x0060 握手 → 收一帧请求 → 回一帧 JSON。"""

    def __init__(self, reply_obj, greeting=b"\x04\x00\x5f\x00"):
        self._reply = build_frame(reply_obj, TYPE_REPLY)
        self._greeting = greeting
        self.received_handshake = None
        self.received_request = None
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
            if self._greeting:
                conn.sendall(self._greeting)
                self.received_handshake = _recv_exact(conn, 4)
            header = _recv_exact(conn, HEADER_SIZE)
            if len(header) < HEADER_SIZE:
                return
            frame_len = struct.unpack_from("<H", header, 0)[0]
            body = _recv_exact(conn, frame_len - HEADER_SIZE)
            self.received_request = header + body
            conn.sendall(self._reply)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._thread.join(timeout=6.0)
        self._sock.close()
        return False


def test_query_keys_roundtrip_with_handshake():
    reply = {"module": "Get", "reply": {"result": "kSuccess",
                                        "data": {"Time": {"dateTime": "2026-10-19 18:30:05"},
                                                 "DeviceInfo": {"uptime": 12345}}}}
    with _MockDeviceServer(reply) as server:
        parsed = query_keys("127.0.0.1", ["Time", "DeviceInfo"], port=server.port,
                            connect_timeout=3.0, recv_timeout=2.0)

    assert parsed == reply
    assert server.received_handshake == HANDSHAKE_REPLY
    sent = json.loads(server.received_request[HEADER_SIZE:].decode("utf-8"))
    assert sent["module"] == "Get"
    assert sent["ask"] == {"list": ["Time", "DeviceInfo"]}
    assert sent["version"] == 5


def test_query_keys_without_greeting_still_works():
    reply = {"module": "Get", "reply": {"result": "kSuccess", "data": {"DeviceInfo": {"uptime": 1}}}}
    with _MockDeviceServer(reply, greeting=b"") as server:
        parsed = query_keys("127.0.0.1", ["DeviceInfo"], port=server.port,
                            connect_timeout=3.0, recv_timeout=2.0)
    assert parsed == reply
    assert server.received_handshake is None


def test_query_keys_returns_none_when_unreachable():
    # 未监听端口：建连失败 → None（不抛异常）
    assert query_keys("127.0.0.1", ["Time"], port=1,
                      connect_timeout=0.3, recv_timeout=0.3) is None


# ---------------------------------------------------------------- 查询服务缓存

def test_protocol_query_service_success_cache(monkeypatch):
    calls = []

    def fake_query(host, keys, **kwargs):
        calls.append(host)
        return {"module": "Get", "reply": {"result": "kSuccess", "data": {
            "Time": {"dateTime": "2026-10-19 18:30:05"},
            "DeviceInfo": {"uptime": 3600000}}}}

    monkeypatch.setattr(qs, "query_keys", fake_query)
    service = ProtocolQueryService()

    first = service.get_status("192.168.1.5")
    second = service.get_status("192.168.1.5")

    assert first == {"date_time": "2026-10-19 18:30:05", "uptime_seconds": 3600}
    assert second == first
    assert calls == ["192.168.1.5"]          # 第二次命中缓存，不再往返
    assert service.is_supported("192.168.1.5") is True


def test_protocol_query_service_negative_cache_and_invalidate(monkeypatch):
    calls = []

    def fake_query(host, keys, **kwargs):
        calls.append(host)
        return None

    monkeypatch.setattr(qs, "query_keys", fake_query)
    service = ProtocolQueryService()

    assert service.get_status("10.0.0.9") is None
    assert service.get_status("10.0.0.9") is None   # 负缓存命中
    assert len(calls) == 1
    assert service.is_supported("10.0.0.9") is False

    service.invalidate("10.0.0.9")
    assert service.get_status("10.0.0.9") is None
    assert len(calls) == 2


# ---------------------------------------------------------------- P5 并发收敛

def test_host_lock_is_per_host():
    """协议锁按设备维度：同 host 同一把锁，不同 host 不同锁（跨设备可并行）。"""
    from service.protocol.client import host_lock

    assert host_lock("10.0.0.1") is host_lock("10.0.0.1")
    assert host_lock("10.0.0.1") is not host_lock("10.0.0.2")


def test_protocol_query_service_dedups_concurrent_same_host(monkeypatch):
    """同一设备的并发取数只发生一次真实往返（其余线程复用结果）。"""
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def fake_query(host, keys, **kwargs):
        calls.append(host)
        entered.set()
        release.wait(timeout=3.0)
        return {"module": "Get", "reply": {"result": "kSuccess", "data": {
            "Time": {"dateTime": "2026-10-19 18:30:05"},
            "DeviceInfo": {"uptime": 60000}}}}

    monkeypatch.setattr(qs, "query_keys", fake_query)
    service = ProtocolQueryService()
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(service.get_status("192.168.1.7")))
        for _ in range(3)
    ]

    threads[0].start()
    assert entered.wait(timeout=3.0)      # 首个线程已进入真实取数
    for thread in threads[1:]:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(timeout=5.0)

    assert calls == ["192.168.1.7"]        # 只一次往返
    assert len(results) == 3
    assert all(result == results[0] for result in results)
    assert results[0] == {"date_time": "2026-10-19 18:30:05", "uptime_seconds": 60}
