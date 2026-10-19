"""并行监控下的状态基准读写线程安全冒烟测试（不触网）。"""

import threading

from business.device_monitor_service import DeviceMonitorService


def test_concurrent_state_checks_do_not_break():
    """多个线程同时写基准数据：不应报错、不应丢设备、首次采样只记一次。"""
    service = DeviceMonitorService('H16')
    errors_per_thread = []

    def worker(index):
        local_errors = []
        device_id = f'H16-00-{index:04d}'
        # 同一设备连续两次检查：第一次记基准，第二次不应误报异常
        # pylint: disable=protected-access
        service._check_start_count_deviation(device_id, '1', local_errors)
        service._check_start_count_deviation(device_id, '1', local_errors)
        service._update_device_data(device_id, '1天')
        # pylint: enable=protected-access
        errors_per_thread.append(local_errors)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not errors for errors in errors_per_thread)
    for index in range(20):
        device_id = f'H16-00-{index:04d}'
        assert service.device_data[device_id]['initial_start_count'] == 1
        assert service.device_data[device_id]['last_uptime'] == '1天'
