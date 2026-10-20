"""离线设备处理：派发前 TCP 探测 + 汇总里的「离线未完成」口径（不触网）。"""

import ui.serial_query_manager as sqm
from ui.query_result_presenter import QueryResultPresenter


class _Conn:
    """最小可用的 socket 替身（支持 with 语句）。"""

    def __init__(self, addr):
        self.addr = addr

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _patch_create(monkeypatch, open_port):
    opened = []

    def fake_create(addr, timeout=None):  # pylint: disable=unused-argument
        opened.append(addr)
        if addr[1] != open_port:
            raise OSError("connection refused")
        return _Conn(addr)

    monkeypatch.setattr(sqm.socket, "create_connection", fake_create)
    return opened


def test_probe_android_accepts_adb_port(monkeypatch):
    """协议端口不通但网络 ADB 5555 通 → 视为在线，不再白等协议超时。"""
    opened = _patch_create(monkeypatch, open_port=5555)

    assert sqm.SerialQueryManager._probe_device("H16-00-0001", "10.0.0.5") is True
    assert [port for _ip, port in opened] == [sqm.PROTOCOL_PORT, 5555]


def test_probe_linux_only_tries_ssh(monkeypatch):
    opened = _patch_create(monkeypatch, open_port=22)

    assert sqm.SerialQueryManager._probe_device("C16L-D24-0F308", "10.0.0.6") is True
    assert [port for _ip, port in opened] == [22]


def test_probe_reports_offline_when_no_port_answers(monkeypatch):
    _patch_create(monkeypatch, open_port=None)      # 所有端口都失败

    assert sqm.SerialQueryManager._probe_device("H8-26-A0657", "10.0.0.7") is False
    assert sqm.SerialQueryManager._probe_device("D16-DB00-A0045", "10.0.0.8") is False


def test_summary_lists_offline_devices_separately():
    logs = []
    presenter = QueryResultPresenter(lambda msg, **kw: logs.append(msg))
    presenter.show_summary(
        'all', 12, ['A'] * 9, ['C'],
        elapsed='9.2s',
        offline=[('H8-26-A0657', '192.168.81.141', 'pwd', 'Android'),
                 ('D16-DB00-A0045', '192.168.80.127', 'pwd', 'Linux')],
    )
    text = "\n".join(logs)

    assert '离线未完成: 2 台' in text
    assert 'H8-26-A0657(192.168.81.141)' in text
    assert '继续执行上一个任务' in text
    assert '查询成功: 9 台' in text and '查询失败: 1 台' in text
