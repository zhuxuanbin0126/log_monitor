"""config.py 纯函数与常量测试。"""

import os

import config


def test_supported_dev_types_is_immutable_tuple():
    assert isinstance(config.SUPPORTED_DEV_TYPES, tuple)
    assert 'H16' in config.SUPPORTED_DEV_TYPES
    assert 'H20' in config.SUPPORTED_DEV_TYPES


def test_get_device_list_pattern():
    assert config.get_device_list_pattern('A-B-C-D-H') == 'A|B|C|D|H'
    assert config.get_device_list_pattern('H16') == 'H16'


def test_get_base_dir_uses_output_dir():
    base = config.get_base_dir('H16')
    assert base == os.path.join(config.OUTPUT_DIR, 'logs', 'H16_AgingTest')


def test_get_device_remote_path_android():
    assert config.get_device_remote_path('Android') == '/data'
    assert config.get_device_remote_path('安卓 11') == '/data'


def test_get_device_remote_path_linux():
    assert config.get_device_remote_path('Linux') == '/root/Box/project'


def test_get_device_remote_path_fallback():
    assert config.get_device_remote_path('') == config.DEFAULT_REMOTE_PATH
    assert config.get_device_remote_path('unknown-os') == config.DEFAULT_REMOTE_PATH


def test_backward_compatible_aliases():
    assert config.tool_path == config.TOOL_PATH
    assert config.default_dev_type == config.DEFAULT_DEV_TYPE
    assert config.time_diff_threshold == config.BOOT_TIME_DIFF_THRESHOLD_SECONDS
    assert config.supported_dev_types == list(config.SUPPORTED_DEV_TYPES)
