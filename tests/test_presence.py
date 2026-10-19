"""在线状态跟踪与有界在场探测的离线单测（不触真机）。"""

import service.discovery.udp_finder as uf
from service.discovery.presence import PresenceTracker

_HEADER = bytes([0x00, 0x00, 0x00, 0x01, 0x02, 0x00])


def _id_payload(device_id: str) -> bytes:
    return _HEADER + device_id.encode("ascii") + b"\x00\x00\x00"


class _FakeSocket:
    """实现 UDP socket 子集接口的假 socket，用于离线驱动 probe_presence。"""

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


# ---------------------------------------------------------------- 状态跟踪

def test_tracker_reports_new_devices_immediately():
    tracker = PresenceTracker(offline_grace=2)
    diff = tracker.observe([("A3L-AAAA111", "192.168.1.10")])
    assert diff.added == [("A3L-AAAA111", "192.168.1.10")]
    assert diff.removed == []
    assert diff.changed is True
    assert tracker.known_pairs() == [("A3L-AAAA111", "192.168.1.10")]


def test_tracker_offline_only_after_grace():
    tracker = PresenceTracker(offline_grace=3)
    tracker.observe([("H16-BBBB222", "192.168.1.20")])
    assert tracker.observe([]).changed is False
    assert tracker.observe([]).changed is False
    diff = tracker.observe([])          # 第 3 轮缺失 → 达到宽限 → 下线
    assert diff.removed == [("H16-BBBB222", "192.168.1.20")]
    assert tracker.known_pairs() == []


def test_tracker_miss_then_return_resets_grace():
    tracker = PresenceTracker(offline_grace=2)
    tracker.observe([("A3L-AAAA111", "192.168.1.10")])
    tracker.observe([])                 # 1 次缺失
    assert tracker.observe([("A3L-AAAA111", "192.168.1.10")]).changed is False
    # 计数已重置，再来 1 次缺失仍不应下线
    assert tracker.observe([]).changed is False


def test_tracker_ip_change_emits_both():
    tracker = PresenceTracker(offline_grace=2)
    tracker.observe([("A3L-AAAA111", "192.168.1.10")])
    diff = tracker.observe([("A3L-AAAA111", "192.168.1.99")])
    assert diff.removed == [("A3L-AAAA111", "192.168.1.10")]
    assert diff.added == [("A3L-AAAA111", "192.168.1.99")]


def test_tracker_seed_avoids_false_online():
    tracker = PresenceTracker()
    tracker.seed([("A3L-AAAA111", "192.168.1.10")])
    assert tracker.observe([("A3L-AAAA111", "192.168.1.10")]).changed is False


# ---------------------------------------------------------------- 有界在场探测

def test_probe_presence_collects_and_closes(monkeypatch):
    sock = _FakeSocket("192.168.1.10", [
        (_id_payload("A3L-AAAA111"), ("192.168.1.101", 9527)),
    ])
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock])
    monkeypatch.setattr(
        uf.select, "select",
        lambda rlist, _w, _x, _t: ([s for s in rlist if s.responses], [], []))

    found = uf.probe_presence(duration=0.2, probe_interval=0.01)
    assert found == [("A3L-AAAA111", "192.168.1.101")]
    assert sock.sent and sock.closed


def test_probe_presence_is_bounded_when_nothing_found(monkeypatch):
    sock = _FakeSocket("10.0.0.1")
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock])
    monkeypatch.setattr(uf.select, "select", lambda _r, _w, _x, _t: ([], [], []))

    found = uf.probe_presence(duration=0.1, probe_interval=0.01)
    assert found == []
    assert sock.closed


def test_probe_presence_honours_should_stop(monkeypatch):
    sock = _FakeSocket("10.0.0.1")
    monkeypatch.setattr(uf, "open_probe_sockets", lambda: [sock])
    monkeypatch.setattr(uf.select, "select", lambda _r, _w, _x, _t: ([], [], []))

    found = uf.probe_presence(duration=5, should_stop=lambda: True)
    assert found == []
    assert sock.closed
