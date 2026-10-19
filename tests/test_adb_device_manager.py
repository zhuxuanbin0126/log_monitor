"""ADBDeviceManager 纯逻辑测试（不触网、不调用外部程序）。"""

from service.adb_device_manager import ADBDeviceManager


def test_classify_device():
    assert ADBDeviceManager.classify_device('H16-00-0001') == 'android'
    assert ADBDeviceManager.classify_device('A3L-00-0001') == 'android'
    assert ADBDeviceManager.classify_device('D16-00-0001') == 'linux'
    assert ADBDeviceManager.classify_device('C08L-00-0001') == 'linux'
    assert ADBDeviceManager.classify_device('UNKNOWN-00-0001') == 'unknown'


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
