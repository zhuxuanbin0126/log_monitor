"""ADBService 设备状态解析与同内容 MD5 备忘测试（不触网、不调用外部程序）。"""

import os

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


# ---------------------------------------------------------------- 同内容 MD5 备忘

def test_local_md5_once_reuses_hash_for_same_content(tmp_path, monkeypatch):
    calls = []

    def _fake_md5(path):
        calls.append(path)
        return "deadbeef"

    monkeypatch.setattr(adb, "calculate_md5", _fake_md5)
    adb._LOCAL_MD5_MEMO.clear()                      # pylint: disable=protected-access

    target = tmp_path / "program.tar.gz"
    target.write_bytes(b"payload")

    assert adb.ADBService.local_md5_once(str(target)) == "deadbeef"
    assert adb.ADBService.local_md5_once(str(target)) == "deadbeef"
    assert len(calls) == 1                           # 同一内容只读盘/哈希一次


def test_local_md5_once_invalidates_after_file_change(tmp_path, monkeypatch):
    calls = []

    def _fake_md5(path):
        calls.append(path)
        return f"hash{len(calls)}"

    monkeypatch.setattr(adb, "calculate_md5", _fake_md5)
    adb._LOCAL_MD5_MEMO.clear()                      # pylint: disable=protected-access

    target = tmp_path / "program.tar.gz"
    target.write_bytes(b"payload")
    adb.ADBService.local_md5_once(str(target))

    stat = target.stat()
    os.utime(str(target), (stat.st_atime + 10, stat.st_mtime + 10))
    adb.ADBService.local_md5_once(str(target))

    assert len(calls) == 2                           # 文件一变即重新计算
