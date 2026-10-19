"""设备刷新控制器的增量上报逻辑（不触网、不建窗口）。"""

from ui.device_refresh_controller import DeviceRefreshController


def test_device_info_emits_row_update_immediately():
    controller = DeviceRefreshController()
    seen = []
    controller.device_row_updated.connect(lambda info: seen.append(info))

    # pylint: disable=protected-access
    controller._on_device_info({'id': 'H16-00-0001', 'ip': '192.168.1.10'})
    controller._on_device_info({'id': 'A3L-00-0002', 'ip': '192.168.1.11'})
    # pylint: enable=protected-access

    assert seen == [{'id': 'H16-00-0001', 'ip': '192.168.1.10'},
                    {'id': 'A3L-00-0002', 'ip': '192.168.1.11'}]
    assert [d['id'] for d in controller._devices] == [  # pylint: disable=protected-access
        'H16-00-0001', 'A3L-00-0002']


def test_device_info_none_is_ignored():
    controller = DeviceRefreshController()
    seen = []
    controller.device_row_updated.connect(lambda info: seen.append(info))
    controller._on_device_info(None)  # pylint: disable=protected-access
    assert seen == []


def test_is_busy_false_initially():
    assert DeviceRefreshController().is_busy() is False
