"""ADBDeviceManager 纯逻辑测试（不触网、不调用外部程序）。"""

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
