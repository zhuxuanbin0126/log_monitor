"""开关机计数取数 / 清除的纯函数测试（不触网）。"""

import business.device_log_service as dls
from business.device_log_service import COUNT_SPLIT_MARKER, DeviceLogService


def _fake_execute(monkeypatch, outputs):
    """按顺序返回预设输出，并记录下发的命令。"""
    calls = []

    def fake(_device_id, _ip, _password, command, _base_dir="."):
        calls.append(command)
        return outputs.pop(0) if outputs else ("", "", 0)

    monkeypatch.setattr(dls.ToolService, "execute_command", fake)
    return calls


def test_count_command_handles_missing_file():
    cmd = DeviceLogService._count_command('/data/a.csv')  # pylint: disable=protected-access
    assert "if [ -f /data/a.csv ]" in cmd
    assert "else echo 0; fi" in cmd


def test_parse_counts_subtracts_header():
    text = (f"{COUNT_SPLIT_MARKER}\n  11 /data/swich_counter.csv\n"
            f"{COUNT_SPLIT_MARKER}\n  5 /data/network_counter.csv\n")
    assert DeviceLogService._parse_counts(text) == (10, 4)  # pylint: disable=protected-access


def test_parse_counts_treats_echo_zero_as_no_record():
    # 文件不存在 → 命令输出 0 → 计数 0（而不是「取不到」）
    text = f"{COUNT_SPLIT_MARKER}\n0\n{COUNT_SPLIT_MARKER}\n0\n"
    assert DeviceLogService._parse_counts(text) == (0, 0)  # pylint: disable=protected-access


def test_parse_counts_rejects_unparsable_output():
    assert DeviceLogService._parse_counts("") is None       # pylint: disable=protected-access
    assert DeviceLogService._parse_counts("sh: syntax error") is None  # pylint: disable=protected-access


# ---------------------------------------------------------------- 清除开关机日志

def test_clean_switch_log_uses_single_round_trip(monkeypatch):
    """删除 + sync + 回读合成一条命令：成功时只发 1 次。"""
    calls = _fake_execute(monkeypatch, [("CLEAN_DONE\n", "", 0)])

    ok, message = DeviceLogService.clean_switch_log(
        "192.168.80.212", "pwd", "C16L-D24-0F308", "/root/Box/data")

    assert ok is True and "已清除" in message
    assert len(calls) == 1
    assert "rm -f /root/Box/data/swich_counter.csv" in calls[0]
    assert "rm -rf /root/Box/data/logcat" in calls[0]
    assert "sync" in calls[0]
    assert "CLEAN_DONE" in calls[0]


def test_clean_switch_log_retries_when_file_left(monkeypatch):
    calls = _fake_execute(monkeypatch, [
        ("SW_EXISTS\nCLEAN_DONE\n", "", 0),      # 第一次残留
        ("CLEAN_DONE\n", "", 0),                 # 重试后干净
    ])

    ok, _ = DeviceLogService.clean_switch_log(
        "192.168.80.212", "pwd", "C16L-D24-0F308", "/root/Box/data")

    assert ok is True
    assert len(calls) == 2


def test_clean_switch_log_reports_failure_when_still_present(monkeypatch):
    _fake_execute(monkeypatch, [
        ("NET_EXISTS\nCLEAN_DONE\n", "", 0),
        ("NET_EXISTS\nCLEAN_DONE\n", "", 0),
    ])

    ok, message = DeviceLogService.clean_switch_log(
        "192.168.80.212", "pwd", "C16L-D24-0F308", "/root/Box/data")

    assert ok is False and "仍存在" in message


def test_clean_switch_log_detects_dead_channel(monkeypatch):
    """通道无输出（没有 CLEAN_DONE）不能当成清理成功。"""
    _fake_execute(monkeypatch, [("", "Connection reset", 255)])

    ok, message = DeviceLogService.clean_switch_log(
        "192.168.80.212", "pwd", "C16L-D24-0F308", "/root/Box/data")

    assert ok is False and "无响应" in message
