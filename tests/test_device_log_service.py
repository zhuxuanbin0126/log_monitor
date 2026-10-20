"""开关机计数取数的纯函数测试（不触网）。"""

from business.device_log_service import COUNT_SPLIT_MARKER, DeviceLogService


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
