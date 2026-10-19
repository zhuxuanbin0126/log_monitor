"""data_models.py 数据模型测试。"""

from data_models import DeviceState, MonitorConfig, OperationResult, QueryType


def test_device_state_roundtrip():
    raw = {
        'initial_boot_time': '2026-10-19 10:00',
        'last_uptime': '1天2时3分',
        'initial_time_diff': 5,
        'last_start_count': 3,
    }
    state = DeviceState.from_dict('H16-00-0001', raw)
    assert state.device_id == 'H16-00-0001'
    assert state.initial_time_diff == 5
    assert state.to_dict() == raw


def test_device_state_ignores_unknown_fields():
    state = DeviceState.from_dict('H16-00-0001', {'unknown': 1, 'last_uptime': '1分'})
    assert state.last_uptime == '1分'
    assert not hasattr(state, 'unknown')


def test_monitor_config_defaults():
    cfg = MonitorConfig(dev_type='H16')
    assert cfg.delay_time == 60
    assert cfg.monitor_time is True
    assert cfg.capture_screenshot is False
    assert cfg.selected_devices == []


def test_query_type_values():
    assert QueryType.ALL.value == 'all'
    assert QueryType.START_COUNT.value == 'start_count'
    assert QueryType.COUNT_INIT.value == 'count_init'


def test_operation_result_truthiness():
    ok = OperationResult(True, data='ok')
    failed = OperationResult(False, error='boom')
    assert bool(ok) is True
    assert bool(failed) is False
