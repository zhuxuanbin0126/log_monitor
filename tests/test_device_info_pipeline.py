"""设备信息补全流水线：缓存即时上表 + 分级重试（离线、不触网、不建窗口）。

覆盖：
1. ``build_cached_payload``：缓存命中即刻产出可直接上表的完整字典（含 id/ip/密码）；
2. 真实查询成功 → emit 结果并回写缓存；
3. 真实查询失败但有缓存 → 保留缓存行，**不** emit None；
4. 真实查询失败且无缓存 → emit None（与旧行为一致）；
5. 重试为「短超时首试 + 长超时兜底」两档，不再是固定 3 次。
"""

import ui.reflash_device_threadpool as rdt
from ui.reflash_device_threadpool import (
    QRunnableWrapper, _split_device_line, build_cached_payload,
)


class _Recorder:
    """记录 emit 的 payload 与任务结束回调次数。"""

    def __init__(self):
        self.payloads = []
        self.finished = 0

    def emit(self, payload):
        self.payloads.append(payload)

    def notify(self):
        self.finished += 1


def _make_runnable(recorder, cache_hit=False):
    return QRunnableWrapper("H16-26-A0419 192.168.81.94", "A-B-C-D-H",
                            recorder.emit, recorder.notify, cache_hit=cache_hit)


def test_split_device_line():
    assert _split_device_line("H16-26-A0419 192.168.81.94") == (
        "H16-26-A0419", "192.168.81.94")
    assert _split_device_line("bad") == ("", "")
    assert _split_device_line("") == ("", "")
    assert _split_device_line(None) == ("", "")


def test_build_cached_payload_hit_and_miss(monkeypatch):
    monkeypatch.setattr(rdt.device_cache, "get_cached",
                        lambda device_id, ip: {"mac_address": "AA:BB", "device_name": "旧名"})
    monkeypatch.setattr(rdt.ToolService, "get_password", lambda device_id: "pw")

    payload = build_cached_payload("H16-26-A0419 192.168.81.94")
    assert payload == {
        "mac_address": "AA:BB", "device_name": "旧名",
        "id": "H16-26-A0419", "ip": "192.168.81.94", "password": "pw",
    }

    monkeypatch.setattr(rdt.device_cache, "get_cached", lambda device_id, ip: None)
    assert build_cached_payload("H16-26-A0419 192.168.81.94") is None
    assert build_cached_payload("bad-line") is None


def test_real_query_succeeds_and_writes_cache(monkeypatch):
    recorder = _Recorder()
    attempts = []
    saved = {}

    monkeypatch.setattr(rdt.device_cache, "put_cached",
                        lambda device_id, ip, info: saved.update(info))

    def fake_get(line, pattern, connect_timeout=None, recv_timeout=None):
        attempts.append((connect_timeout, recv_timeout))
        return {"id": "H16-26-A0419", "ip": "192.168.81.94", "mac_address": "CC:DD"}

    monkeypatch.setattr(rdt.ToolService, "get_device_info", fake_get)

    _make_runnable(recorder).run()

    assert [p["mac_address"] for p in recorder.payloads] == ["CC:DD"]
    # 真实查询成功：只试一次（默认超时），并回写缓存
    assert attempts == [(rdt.PROTOCOL_CONNECT_TIMEOUT, rdt.PROTOCOL_RECV_TIMEOUT)]
    assert saved["mac_address"] == "CC:DD"
    assert recorder.finished == 1


def test_failure_with_cache_keeps_cache_and_grades_timeouts(monkeypatch):
    recorder = _Recorder()
    attempts = []

    monkeypatch.setattr(rdt.device_cache, "put_cached",
                        lambda device_id, ip, info: None)

    def boom(line, pattern, connect_timeout=None, recv_timeout=None):
        attempts.append((connect_timeout, recv_timeout))
        raise OSError("模拟协议不可达")

    monkeypatch.setattr(rdt.ToolService, "get_device_info", boom)

    _make_runnable(recorder, cache_hit=True).run()

    assert recorder.payloads == []          # 缓存行已在提交时上表，这里不再 emit None
    # 首试用默认短超时，兜底加长（+1s）；共 2 次，不再是 3 次
    assert attempts == [
        (rdt.PROTOCOL_CONNECT_TIMEOUT, rdt.PROTOCOL_RECV_TIMEOUT),
        (rdt.PROTOCOL_CONNECT_TIMEOUT + 1.0, rdt.PROTOCOL_RECV_TIMEOUT + 1.0),
    ]
    assert recorder.finished == 1


def test_failure_without_cache_emits_none(monkeypatch):
    recorder = _Recorder()
    attempts = []

    monkeypatch.setattr(rdt.device_cache, "put_cached",
                        lambda device_id, ip, info: None)

    def none_get(line, pattern, connect_timeout=None, recv_timeout=None):
        attempts.append((connect_timeout, recv_timeout))
        return None

    monkeypatch.setattr(rdt.ToolService, "get_device_info", none_get)

    _make_runnable(recorder).run()

    assert recorder.payloads == [None]
    assert len(attempts) == 2
    assert recorder.finished == 1


def test_unexpected_exception_still_notifies_done(monkeypatch):
    """异常路径也必须回报「任务结束」，否则队列补位与收尾判定会卡死。"""
    recorder = _Recorder()

    def boom(line, pattern, connect_timeout=None, recv_timeout=None):
        raise RuntimeError("意外错误")

    monkeypatch.setattr(rdt.ToolService, "get_device_info", boom)

    _make_runnable(recorder).run()

    assert recorder.payloads == [None]
    assert recorder.finished == 1
