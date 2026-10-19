"""查询执行引擎测试（纯函数 + 假 monitor_service，不触网）。"""

from service import query_engine as qe
from service.protocol.command_query import ExecResult


def test_build_counts_command_has_three_markers():
    cmd = qe.build_counts_command("getprop x", "/data/a.csv", "/data/b.csv")
    assert cmd.count(qe.COUNT_SPLIT_MARKER) == 3
    assert "getprop x" in cmd
    assert "/data/a.csv" in cmd
    assert "/data/b.csv" in cmd


def test_build_counts_command_empty_start_uses_true():
    cmd = qe.build_counts_command("", "/data/a.csv", "/data/b.csv")
    assert "true" in cmd


def test_parse_counts_output_partial():
    text = (f"{qe.COUNT_SPLIT_MARKER}\n120\n{qe.COUNT_SPLIT_MARKER}\n"
            f"  11 /data/a.csv\n{qe.COUNT_SPLIT_MARKER}\n")
    parsed = qe.parse_counts_output(text)
    assert parsed["start_count"] == "120"
    assert parsed["switch_count"] == 10
    assert parsed["network_count"] is None


def test_parse_counts_output_too_few_segments():
    parsed = qe.parse_counts_output("garbage")
    assert parsed == {"start_count": None, "switch_count": None, "network_count": None}


class FakeMonitorService:
    """记录调用并返回固定值的假业务对象。"""

    def __init__(self):
        self.calls = []

    def get_device_time_info(self, ip, password, device_id):
        self.calls.append("time")
        return "2026-10-19 02:00:00", 5

    def get_uptime_info(self, ip, password, device_id):
        self.calls.append("uptime")
        return {"formatted_uptime": "1天2时"}

    def get_start_count(self, ip, password, device_id):
        self.calls.append("start_count")
        return "fallback-start"

    def sum_switch_count(self, ip, password, device_id, path):
        self.calls.append("sum_switch")
        return 7, 3, True, None


def _batch_text(start, switch_lines, network_lines):
    return (f"{qe.COUNT_SPLIT_MARKER}\n{start}\n{qe.COUNT_SPLIT_MARKER}\n"
            f"{switch_lines}\n{qe.COUNT_SPLIT_MARKER}\n{network_lines}\n")


def test_query_all_protocol_batch(monkeypatch):
    monkeypatch.setattr(qe, "is_protocol_supported", lambda ip: True)
    text = _batch_text(42, "  8 /data/swich_counter.csv", "  4 /data/network_counter.csv")
    monkeypatch.setattr(
        qe, "exec_if_supported",
        lambda ip, cmd, **kw: ExecResult(output=text, exit_code=0))

    service = FakeMonitorService()
    outcome = qe.query_all(service, "H16-00-0001", "1.2.3.4", "pwd", "Android")

    assert outcome.results["device_time"]["time_diff"] == 5
    assert outcome.results["boot_time"]["formatted_uptime"] == "1天2时"
    assert outcome.results["start_count"] == "42"
    assert outcome.switch_time == 7
    assert outcome.network_time == 3
    assert outcome.switch_success is True
    assert outcome.protocol_used is True
    # 协议批量通道取到值 → 不再逐项降级
    assert "start_count" not in service.calls
    assert "sum_switch" not in service.calls


def test_query_all_falls_back_per_item(monkeypatch):
    monkeypatch.setattr(qe, "is_protocol_supported", lambda ip: False)

    service = FakeMonitorService()
    outcome = qe.query_all(service, "H16-00-0001", "1.2.3.4", "pwd", "Android")

    assert outcome.protocol_used is False
    assert outcome.results["start_count"] == "fallback-start"
    assert outcome.switch_time == 7
    assert outcome.network_time == 3
    assert "sum_switch" in service.calls
    assert "start_count" in service.calls


def test_query_all_skips_start_count_for_linux_types(monkeypatch):
    monkeypatch.setattr(qe, "is_protocol_supported", lambda ip: False)

    service = FakeMonitorService()
    outcome = qe.query_all(service, "C08L-0001", "1.2.3.4", "pwd", "Linux")

    assert outcome.results["start_count"] == "无法获取"
    assert "start_count" not in service.calls
