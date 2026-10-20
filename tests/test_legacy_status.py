"""Linux/SSH 通道的「一次往返」优化测试（合并取数、批量文件校验，不触网）。"""

from datetime import datetime

import business.device_monitor_service as dms
from service.protocol.query_service import BEIJING_TZ

_UPTIME_TEXT = ("10:20:30 up 2 days, 3:04, 1 user, "
                "load average: 0.10, 0.20, 0.30")
_EPOCH = 1700000000


def _fake_execute(recorder):
    def _run(device_id, ip, password, command, base_dir="."):
        recorder.append((device_id, ip, command))
        payload = f"{_EPOCH}\n{dms.TIME_UPTIME_SPLIT}\n{_UPTIME_TEXT}"
        return payload, "", 0
    return _run


def test_legacy_status_one_round_trip_shared_by_time_and_uptime(monkeypatch, tmp_path):
    """同一轮询内「设备时间」与「运行时长」共用一个 SSH 往返。"""
    calls = []
    monkeypatch.setattr(dms.ToolService, "execute_command",
                        staticmethod(_fake_execute(calls)))
    monkeypatch.setattr(dms, "get_base_dir", lambda _dev_type: str(tmp_path))
    monkeypatch.setattr(dms, "USE_PROTOCOL_QUERY", False)   # 强制走 legacy 通道
    dms.clear_legacy_status_cache()

    service = dms.DeviceMonitorService("H16")
    formatted, diff = service.get_device_time_info("10.9.9.1", "pwd", "H16-00-0001")
    info = service.get_uptime_info("10.9.9.1", "pwd", "H16-00-0001")

    assert len(calls) == 1                                  # 关键：只一次往返
    assert "date +%s" in calls[0][2] and "uptime" in calls[0][2]
    expected = datetime.fromtimestamp(_EPOCH, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    assert formatted == expected
    assert isinstance(diff, int)
    assert info["formatted_uptime"] == "2天3时4分"
    assert info["boot_time"]


def test_legacy_status_cache_expires_between_rounds(monkeypatch, tmp_path):
    """缓存按 TTL 过期：下一轮取数会重新往返。"""
    calls = []
    monkeypatch.setattr(dms.ToolService, "execute_command",
                        staticmethod(_fake_execute(calls)))
    monkeypatch.setattr(dms, "get_base_dir", lambda _dev_type: str(tmp_path))
    monkeypatch.setattr(dms, "USE_PROTOCOL_QUERY", False)
    monkeypatch.setattr(dms, "LEGACY_STATUS_TTL_SECONDS", 0.0)
    dms.clear_legacy_status_cache()

    service = dms.DeviceMonitorService("H16")
    service.get_device_time_info("10.9.9.2", "pwd", "H16-00-0002")
    service.get_device_time_info("10.9.9.2", "pwd", "H16-00-0002")

    assert len(calls) == 2


def test_legacy_status_reports_error_when_output_unparsable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        dms.ToolService, "execute_command",
        staticmethod(lambda *_a, **_kw: ("garbage without marker", "", 0)))
    monkeypatch.setattr(dms, "get_base_dir", lambda _dev_type: str(tmp_path))
    monkeypatch.setattr(dms, "USE_PROTOCOL_QUERY", False)
    dms.clear_legacy_status_cache()

    service = dms.DeviceMonitorService("H16")
    info = service.get_uptime_info("10.9.9.3", "pwd", "H16-00-0003")
    assert info["formatted_uptime"] == "N/A"
    assert "error" in info


# ---------------------------------------------------------------- 批量文件校验（一次往返）

def test_missing_remote_files_single_round_trip(monkeypatch):
    calls = []

    def _fake(device_id, ip, password, command, base_dir="."):
        calls.append(command)
        return "OK 0\nMISS 1\nOK 2\n", "", 0

    monkeypatch.setattr(dms.ToolService, "execute_command", staticmethod(_fake))

    paths = ["/root/a.sh", "/root/b.sh", "/root/Box/project/flag"]
    missing = dms.DeviceMonitorService._missing_remote_files(
        "D16-DB00-A0045", "10.0.0.9", "pwd", paths)

    assert missing == ["/root/b.sh"]
    assert len(calls) == 1                      # 3 个文件只查一次
    assert "test" not in calls[0] and "[ -e" in calls[0]


def test_missing_remote_files_reports_all_when_channel_silent(monkeypatch):
    """通道无任何回显 → 视为全部未验证，不能误判成功。"""
    monkeypatch.setattr(dms.ToolService, "execute_command",
                        staticmethod(lambda *_a, **_kw: ("", "timeout", 255)))

    paths = ["/root/a.sh", "/root/b.sh"]
    assert dms.DeviceMonitorService._missing_remote_files(
        "D16-DB00-A0045", "10.0.0.9", "pwd", paths) == paths
