"""device_info.json 动态配置读取测试。"""

from device_config import (
    get_all_models,
    get_chip_model,
    get_device_config,
    get_init_grouped_configs,
    get_system_version,
    get_upgrade_grouped_configs,
)


def test_get_all_models_contains_known_models():
    models = get_all_models()
    assert 'D16' in models
    assert 'H16' in models
    assert 'H20' in models


def test_get_device_config_fields():
    cfg = get_device_config('D16')
    assert cfg is not None
    assert cfg['型号'] == 'D16'
    assert get_chip_model('D16') == 'PX30'
    assert get_system_version('D16') == 'Linux'


def test_unknown_model_returns_none():
    assert get_device_config('NOT-EXIST') is None
    assert get_chip_model('NOT-EXIST') == ''


def test_init_grouped_configs_cover_all_devices():
    devices = ['D16', 'C08L', 'A3L']
    groups = get_init_grouped_configs(devices)
    grouped_devices = []
    for group in groups.values():
        grouped_devices.extend(group['devices'])
    assert sorted(grouped_devices) == sorted(devices)


def test_upgrade_grouped_configs_have_system_type():
    groups = get_upgrade_grouped_configs(['D16', 'A3L'])
    labels = {group['system_type'] for group in groups.values()}
    assert '常规系列' in labels
    assert '安卓系列' in labels
