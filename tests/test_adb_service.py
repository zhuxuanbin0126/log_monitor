"""ADBService 设备状态解析测试（不触网、不调用外部程序）。"""

from service import adb_service as adb


def _fake_devices(output, rc=0):
    """构造假的 run_command：只应答 ``adb devices``。"""
    def _run(cmd, *args, **kwargs):
        assert "devices" in cmd
        return output, "", rc
    return _run


def test_list_devices_parses_states(monkeypatch):
    output = (
        "List of devices attached\n"
        "192.168.80.55:5555\tdevice\n"
        "192.168.80.66:5555\toffline\n"
        "0123456789ABCDEF\tunauthorized\n"
    )
    monkeypatch.setattr(adb, "run_command", _fake_devices(output))
    devices = adb.ADBService.list_devices()
    assert devices["192.168.80.55:5555"] == "device"
    assert devices["192.168.80.66:5555"] == "offline"
    assert devices["0123456789ABCDEF"] == "unauthorized"


def test_list_devices_ignores_noise(monkeypatch):
    output = "* daemon not running; starting now at tcp:5037\nList of devices attached\n"
    monkeypatch.setattr(adb, "run_command", _fake_devices(output))
    assert adb.ADBService.list_devices() == {}


def test_get_online_serial_requires_device_state(monkeypatch):
    output = ("List of devices attached\n"
              "192.168.80.55:5555\toffline\n"
              "192.168.80.66:5555\tdevice\n")
    monkeypatch.setattr(adb, "run_command", _fake_devices(output))
    # 网络 ADB 的 serial 恒为 ip:5555 —— 只有状态为 device 才算连通
    assert adb.ADBService.get_online_serial("192.168.80.55") is None
    assert adb.ADBService.get_online_serial("192.168.80.66") == "192.168.80.66:5555"


def test_get_online_serial_missing_device(monkeypatch):
    monkeypatch.setattr(adb, "run_command", _fake_devices("List of devices attached\n"))
    assert adb.ADBService.get_online_serial("10.0.0.9") is None
