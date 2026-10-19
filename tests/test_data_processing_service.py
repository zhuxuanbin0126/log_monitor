"""DataProcessingService 纯逻辑测试。"""

import pytest

from service.data_processing_service import DataProcessingService


def test_parse_uptime_with_days_and_user():
    info = DataProcessingService.parse_uptime(
        "10:20:30 up 2 days, 3:04, 1 user, load average: 0.10, 0.20, 0.30"
    )
    assert info['current_time'] == '10:20:30'
    assert info['formatted_uptime'] == '2天3时4分'
    assert info['user_count'] == 1
    assert info['load_1min'] == pytest.approx(0.10)
    assert info['load_15min'] == pytest.approx(0.30)


def test_parse_uptime_minutes_only():
    info = DataProcessingService.parse_uptime(
        "10:20:30 up 45 min, load average: 0.00, 0.01, 0.05"
    )
    assert info['formatted_uptime'] == '45分'
    assert info['user_count'] == 0


def test_parse_uptime_invalid_raises():
    with pytest.raises(ValueError):
        DataProcessingService.parse_uptime("not an uptime output")


def test_process_time_difference_returns_error_when_over_threshold():
    error = DataProcessingService.process_time_difference(10, 20, threshold=3, days_passed=1)
    assert error is not None
    assert error['type'] == '时间同步异常'
    assert '10.00' in error['difference']


def test_process_time_difference_returns_none_when_normal():
    assert DataProcessingService.process_time_difference(1, 2, threshold=3, days_passed=1) is None


def test_process_time_difference_never_divides_by_zero():
    error = DataProcessingService.process_time_difference(0, 10, threshold=3, days_passed=0)
    assert error is not None


def test_process_boot_count_detects_jump_and_decrease():
    assert DataProcessingService.process_boot_count(1, 10, threshold=5) is not None
    assert DataProcessingService.process_boot_count(10, 1, threshold=5) is not None
    assert DataProcessingService.process_boot_count(1, 2, threshold=5) is None


def test_extract_device_info():
    assert DataProcessingService.extract_device_info(
        "设备 A5L-00-A7959 (192.168.1.43) 离线"
    ) == ('A5L-00-A7959', '192.168.1.43')
    assert DataProcessingService.extract_device_info("无设备信息") == ('未知设备', '未知IP')


def test_format_error_message_contains_device_and_type():
    message = DataProcessingService.format_error_message(
        'H16-00-0001', '192.168.1.10', '设备离线',
        [{'type': '设备离线', 'process': '设备ID: H16-00-0001, IP: 192.168.1.10',
          'difference': '设备从监控列表中消失'}],
    )
    assert 'H16-00-0001' in message
    assert '设备离线' in message
    assert '设备从监控列表中消失' in message
