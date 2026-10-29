"""ADBDeviceManager 纯逻辑测试（不触网、不调用外部程序）。"""

import pytest

import service.adb_device_manager as adm
from service.adb_device_manager import ADBDeviceManager


def test_classify_device():
    assert ADBDeviceManager.classify_device('H16-00-0001') == 'android'
    assert ADBDeviceManager.classify_device('A3L-00-0001') == 'android'
    assert ADBDeviceManager.classify_device('D16-00-0001') == 'linux'
    assert ADBDeviceManager.classify_device('C08L-00-0001') == 'linux'
    assert ADBDeviceManager.classify_device('UNKNOWN-00-0001') == 'unknown'


def test_q910_is_a_supported_linux_model():
    """Q910 为定制款 Linux 机型：纳入支持清单，但归类为 linux（不走协议/ADB 提权）。"""
    from config import supported_dev_types
    from service.device_utils import is_android_device

    assert 'Q910' in supported_dev_types
    assert is_android_device('Q910-D26-002B8') is False
    assert ADBDeviceManager.classify_device('Q910-D26-002B8') == 'linux'


def test_status_cache_roundtrip():
    device_id = 'H16-00-CACHE-TEST'
    ADBDeviceManager.set_cached_status(device_id, '开启')
    assert ADBDeviceManager.get_cached_status(device_id) == '开启'
    ADBDeviceManager.set_cached_status(device_id, '未开启')
    assert ADBDeviceManager.get_cached_status(device_id) == '未开启'


def test_should_use_adb_requires_android_and_enabled():
    android_id = 'H16-00-SHOULD-TEST'
    ADBDeviceManager.set_cached_status(android_id, '开启')
    assert ADBDeviceManager.should_use_adb(android_id) is True

    ADBDeviceManager.set_cached_status(android_id, '未开启')
    assert ADBDeviceManager.should_use_adb(android_id) is False

    ADBDeviceManager.set_cached_status('D16-00-SHOULD-TEST', '开启')
    assert ADBDeviceManager.should_use_adb('D16-00-SHOULD-TEST') is False


# ---------------------------------------------------------------- 权限拒绝自动提权

def test_execute_adb_command_roots_and_retries_on_permission_denied(monkeypatch):
    """adb shell 是 uid=shell，/data 下 0600 文件读不了 → 自动 adb root 后重跑一次。"""
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        if len(calls) == 1:
            return "", "wc: /data/swich_counter.csv: Permission denied", 1
        return "2 /data/swich_counter.csv", "", 0

    monkeypatch.setattr(adm, "run_command", fake_run)
    monkeypatch.setattr(
        ADBDeviceManager, "_root_and_reconnect",
        classmethod(lambda cls, ip, serial: "192.168.80.9:5555"))

    stdout, stderr, rc = ADBDeviceManager.execute_adb_command(
        "192.168.80.9", "192.168.80.9:5555", "wc -l /data/swich_counter.csv")

    assert len(calls) == 2                       # 首跑 + 提权后重跑
    assert "192.168.80.9:5555" in calls[0]
    assert "192.168.80.9:5555" in calls[1]       # root 后 serial 不变
    assert (stdout, stderr, rc) == ("2 /data/swich_counter.csv", "", 0)


def test_execute_adb_command_does_not_root_on_other_errors(monkeypatch):
    """非权限类失败不应触发 adb root（避免每条命令都重启 adbd）。"""
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        return "", "error: device offline", 1

    monkeypatch.setattr(adm, "run_command", fake_run)
    monkeypatch.setattr(
        ADBDeviceManager, "_root_and_reconnect",
        classmethod(lambda cls, ip, serial: pytest.fail("不应触发 adb root")))

    stdout, stderr, rc = ADBDeviceManager.execute_adb_command(
        "192.168.80.9", "192.168.80.9:5555", "echo hi")

    assert len(calls) == 1
    assert rc == 1

