"""找卡层离线单测：UDP 应答解析、去重、收敛、目标解析与单播探测（不触真机）。

用假 socket + monkeypatch ``select.select`` 覆盖广播扫描；用本机回环 UDP
应答器覆盖单播探测，全部离线可跑。
"""

import socket
import threading

import pytest

import service.discovery.manual_finder as mf
import service.discovery.udp_finder as uf

_HEADER = bytes([0x00, 0x00, 0x00, 0x01, 0x02, 0x00])


def _id_payload(device_id: str, pad: bytes = b"\x00\x00\x00") -> bytes:
    """构造 ID 应答包：6 字节协议头 + 设备 ID(ASCII) + 填充。"""
    return _HEADER + device_id.encode("ascii") + pad


class _FakeSocket:
    """实现 UDP socket 子集接口的假 socket，用于离线驱动 scan_devices。"""

    def __init__(self, ip, responses=None):
        self._ip = ip
        self.responses = list(responses or [])
        self.sent = []
        self.closed = False

    def setsockopt(self, *args):
        return None

    def bind(self, addr):
        return None

    def getsockname(self):
        return (self._ip, 0)

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, _size):
        if self.responses:
            return self.responses.pop(0)
        raise OSError("no pending datagram")

    def close(self):
        self.closed = True


# ---------------------------------------------------------------- 应答解析

def test_parse_device_id_from_header_offset():
    assert uf.parse_device_id(_id_payload("A3L-1A2B3C")) == "A3L-1A2B3C"


def test_parse_device_id_scans_whole_packet():
    # 设备 ID 不在偏移 6：全包搜索应能找到
    data = bytes([0x09, 0x00, 0x00, 0x01, 0x04, 0x00, 0x00, 0x00, 0x00]) + b"H16-9Z8Y7X"
    assert uf.parse_device_id(data) == "H16-9Z8Y7X"


def test_parse_device_id_rejects_short_or_bogus():
    assert uf.parse_device_id(b"") is None
    assert uf.parse_device_id(_HEADER) is None
    assert uf.parse_device_id(_HEADER + b"AB") is None


# ---------------------------------------------------------------- 广播扫描

def test_scan_devices_parses_dedups_and_reports(monkeypatch):
    sock_a = _FakeSocket("192.168.1.10", [
        (_id_payload("A3L-1A2B3C"), ("192.168.1.101", 9527)),
        (_id_payload("A3L-1A2B3C"), ("192.168.1.101", 9527)),  # 重复应答
    ])
    sock_b = _FakeSocket("192.168.2.10", [
        (_id_payload("H16-9Z8Y7X"), ("192.168.2.55", 9527)),
    ])
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock_a, sock_b])
    monkeypatch.setattr(
        uf.select, "select",
        lambda rlist, _w, _x, _t: ([s for s in rlist if s.responses], [], []),
    )

    found = uf.scan_devices(timeout=5, min_scan=0.0, quiet_window=0.0,
                            probe_interval=0.01)

    assert sorted(d for d, _ in found) == ["A3L-1A2B3C", "H16-9Z8Y7X"]
    assert ("A3L-1A2B3C", "192.168.1.101") in found
    # 探测包内容与目标广播地址正确
    assert sock_a.sent[0][0] == uf.UDP_PROBE_PACKET
    assert sock_a.sent[0][1][0] == uf.GLOBAL_BROADCAST_ADDR
    assert sock_a.closed and sock_b.closed


def test_scan_devices_on_device_callback_fires_for_new_only(monkeypatch):
    sock = _FakeSocket("192.168.1.10", [
        (_id_payload("A3L-1A2B3C"), ("192.168.1.101", 9527)),
        (_id_payload("A3L-1A2B3C"), ("192.168.1.101", 9527)),
    ])
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock])
    monkeypatch.setattr(
        uf.select, "select",
        lambda rlist, _w, _x, _t: ([s for s in rlist if s.responses], [], []),
    )

    seen = []
    uf.scan_devices(timeout=5, min_scan=0.0, quiet_window=0.0, probe_interval=0.01,
                    on_device=lambda dev_id, ip: seen.append((dev_id, ip)))

    assert seen == [("A3L-1A2B3C", "192.168.1.101")]


def test_scan_devices_honours_should_stop(monkeypatch):
    sock = _FakeSocket("10.0.0.1")
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock])
    monkeypatch.setattr(uf.select, "select", lambda rlist, _w, _x, _t: ([], [], []))

    found = uf.scan_devices(timeout=5, should_stop=lambda: True)

    assert found == []
    assert sock.closed


# ---------------------------------------------------------------- 目标解析

def test_parse_ip_spec_single_mixed_and_dedup():
    assert mf.parse_ip_spec("192.168.1.5") == ["192.168.1.5"]
    assert mf.parse_ip_spec("192.168.1.5,192.168.1.5") == ["192.168.1.5"]
    assert mf.parse_ip_spec(["10.0.0.1", "10.0.0.1;10.0.0.2"]) == ["10.0.0.1", "10.0.0.2"]


def test_parse_ip_spec_range_and_cidr():
    assert mf.parse_ip_spec("192.168.1.1-192.168.1.3") == [
        "192.168.1.1", "192.168.1.2", "192.168.1.3"]
    assert mf.parse_ip_spec("192.168.1.0/30") == ["192.168.1.1", "192.168.1.2"]


def test_parse_ip_spec_accepts_mixed_combo_with_spaces():
    """提示里给的组合写法（逗号/空格混用）必须真的能解析。"""
    spec = "192.168.1.9 192.168.1.10-192.168.1.11, 192.168.1.0/30"
    assert mf.parse_ip_spec(spec) == [
        "192.168.1.9", "192.168.1.10", "192.168.1.11", "192.168.1.1", "192.168.1.2"]

    # 换行/制表符分隔同样可用（从表格里复制粘贴常见）
    assert mf.parse_ip_spec("10.0.0.1\n10.0.0.2\t10.0.0.3") == [
        "10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_target_spec_hint_lists_three_formats_and_combo():
    hint = mf.format_target_spec_hint()
    for sample in ("192.168.80.6", "192.168.80.1-192.168.80.50", "192.168.80.0/24"):
        assert sample in hint
    assert "多种组合" in hint and "192.168.81.0/24" in hint
    assert str(mf.PROBE_MAX_TARGETS) in hint


def test_parse_ip_spec_rejects_invalid():
    with pytest.raises(ValueError):
        mf.parse_ip_spec("not-an-ip")
    with pytest.raises(ValueError):
        mf.parse_ip_spec("192.168.1.9-192.168.1.1")  # 起点大于终点


def test_parse_ip_spec_reports_specific_reason():
    """错误提示要能直接给用户看（中文、指明是哪一段写法不对）。"""
    with pytest.raises(ValueError) as reversed_range:
        mf.parse_ip_spec("192.168.1.9-192.168.1.1")
    assert "区间起点大于终点" in str(reversed_range.value)

    with pytest.raises(ValueError) as bad_token:
        mf.parse_ip_spec("192.168.80.999")
    assert "无法识别的目标" in str(bad_token.value)

    with pytest.raises(ValueError) as too_many:
        mf.parse_ip_spec("192.168.0.0/16", max_targets=100)
    assert "超出上限" in str(too_many.value)


def test_parse_ip_spec_enforces_target_limit():
    with pytest.raises(ValueError):
        mf.parse_ip_spec("192.168.0.0/16", max_targets=100)


def test_split_local_remote_partitions(monkeypatch):
    import ipaddress
    monkeypatch.setattr(mf, "local_subnets",
                        lambda: [ipaddress.ip_network("192.168.1.0/24")])
    local, remote = mf.split_local_remote(["192.168.1.10", "10.0.0.5"])
    assert local == ["192.168.1.10"]
    assert remote == ["10.0.0.5"]


def test_scan_targets_merges_broadcast_and_unicast(monkeypatch):
    import ipaddress
    monkeypatch.setattr(mf, "local_subnets",
                        lambda: [ipaddress.ip_network("192.168.1.0/24")])

    def fake_broadcast(**kwargs):
        kwargs["on_device"]("A3L-AAAA111", "192.168.1.20")
        return [("A3L-AAAA111", "192.168.1.20")]

    def fake_unicast(targets, **kwargs):
        kwargs["on_device"]("H16-BBBB222", "10.0.0.9")
        return [("H16-BBBB222", "10.0.0.9")]

    monkeypatch.setattr(mf, "scan_devices", fake_broadcast)
    monkeypatch.setattr(mf, "probe_targets", fake_unicast)

    found = mf.scan_targets("192.168.1.10,10.0.0.9")
    assert sorted(d for d, _ in found) == ["A3L-AAAA111", "H16-BBBB222"]


# ---------------------------------------------------------------- 单播探测

class _LoopbackResponder:
    """本机回环 UDP 应答器：对每个探测包回一个 ID 应答，用于离线单播单测。"""

    def __init__(self, device_id):
        self._payload = _id_payload(device_id)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        while not self._stop.is_set():
            try:
                _data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._sock.sendto(self._payload, addr)
            except OSError:
                break

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._sock.close()
        return False


def test_probe_one_hits_loopback_responder():
    with _LoopbackResponder("D16-ABC1234") as responder:
        result = mf.probe_one("127.0.0.1", port=responder.port, timeout=1.0)
    assert result == ("D16-ABC1234", "127.0.0.1")


def test_probe_one_returns_none_on_timeout():
    # 未监听端口：连接被拒或超时，均应返回 None 而非抛异常
    assert mf.probe_one("127.0.0.1", port=1, timeout=0.2) is None


def test_probe_targets_loopback_responder():
    with _LoopbackResponder("H16-XYZ9876") as responder:
        result = mf.probe_targets(["127.0.0.1"], port=responder.port,
                                  per_target_timeout=1.0, concurrency=4)
    assert result == [("H16-XYZ9876", "127.0.0.1")]


# ---------------------------------------------------------------- 找卡 worker

def test_discovery_thread_formats_lines_by_dev_type():
    from ui.workers.discovery_worker import DiscoveryThread

    thread = DiscoveryThread("A3L")
    lines = thread._format_lines([  # pylint: disable=protected-access
        ("A3L-1A2B3C", "192.168.1.5"),
        ("H16-9Z8Y7X", "192.168.1.6"),
        ("A3L-ZZZ", "192.168.1.7"),
        ("XX-NA", "192.168.1.8"),
    ])
    assert lines == ["A3L-1A2B3C 192.168.1.5", "A3L-ZZZ 192.168.1.7"]


def test_discovery_thread_reports_found_immediately():
    """发现即上报：供 UI 即时反馈；停止后不再上报。"""
    from ui.workers.discovery_worker import DiscoveryThread

    thread = DiscoveryThread("A3L")
    seen = []
    thread.device_found.connect(lambda dev, ip: seen.append((dev, ip)))

    thread._emit_found("A3L-1A2B3C", "192.168.1.5")  # pylint: disable=protected-access
    assert seen == [("A3L-1A2B3C", "192.168.1.5")]

    thread.stop()
    thread._emit_found("A3L-ZZZ", "192.168.1.7")     # pylint: disable=protected-access
    assert seen == [("A3L-1A2B3C", "192.168.1.5")]
