"""设备刷新控制器：增量上报 + 发现即补全流水线（不触网、不建窗口）。"""

from ui.device_refresh_controller import DeviceRefreshController


class _FakeSignal:
    def connect(self, *_args):
        return None

    def disconnect(self, *_args):
        return None


class _FakeTimer:
    def stop(self):
        return None


class _FakeManager:
    """记录提交内容的假信息池。"""

    def __init__(self):
        self.calls = []
        self.taskCompleted = _FakeSignal()
        self.allTasksCompleted = _FakeSignal()
        self.check_timer = _FakeTimer()

    def submit_task(self, line):
        self.calls.append(line)


# ---------------------------------------------------------------- 增量上报

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


# ---------------------------------------------------------------- 发现即补全

def test_accepts_device_filters_by_support_and_dev_type():
    controller = DeviceRefreshController()
    controller._dev_type = "A-B-C-D-H"            # pylint: disable=protected-access
    # pylint: disable=protected-access
    assert controller._accepts_device("H16-26-A0419") is True
    assert controller._accepts_device("A3L-00-A7729") is True
    assert controller._accepts_device("Q910-D26-002B8") is False   # 不支持型号
    # pylint: enable=protected-access


def test_device_found_submits_info_fetch_immediately():
    """关键：发现一台就立刻提交补全，不等扫描收敛结束。"""
    controller = DeviceRefreshController()
    controller._dev_type = "H16"                  # pylint: disable=protected-access
    controller._manager = _FakeManager()          # pylint: disable=protected-access
    found = []
    controller.device_found.connect(lambda dev, ip: found.append((dev, ip)))

    controller._on_device_found("H16-26-A0419", "192.168.81.94")  # pylint: disable=protected-access

    assert found == [("H16-26-A0419", "192.168.81.94")]
    assert controller._manager.calls == ["H16-26-A0419 192.168.81.94"]  # pylint: disable=protected-access

    # 不支持的型号：仅转发信号（供 UI 判断），不提交补全
    controller._on_device_found("Q910-D26-002B8", "192.168.1.230")   # pylint: disable=protected-access
    assert controller._manager.calls == ["H16-26-A0419 192.168.81.94"]  # pylint: disable=protected-access


def test_found_submission_is_deduped_against_raw_list():
    controller = DeviceRefreshController()
    controller._dev_type = "H16"                  # pylint: disable=protected-access
    controller._manager = _FakeManager()          # pylint: disable=protected-access
    # pylint: disable=protected-access
    controller._on_device_found("H16-26-A0419", "192.168.81.94")
    controller._on_raw_list(["H16-26-A0419 192.168.81.94", "H16-26-A000F 192.168.80.55"])
    # pylint: enable=protected-access

    assert controller._manager.calls == [          # pylint: disable=protected-access
        "H16-26-A0419 192.168.81.94", "H16-26-A000F 192.168.80.55"]
    assert controller._submit_done is True         # pylint: disable=protected-access


# ---------------------------------------------------------------- 收尾闸门

def test_devices_ready_waits_until_submit_done():
    controller = DeviceRefreshController()
    ready = []
    controller.devices_ready.connect(ready.append)

    controller._manager = _FakeManager()           # pylint: disable=protected-access
    controller._submit_done = False                # pylint: disable=protected-access
    controller._on_all_tasks_completed()           # pylint: disable=protected-access
    assert ready == []                             # 扫描未结束 → 不算收尾
    assert controller._manager is not None         # pylint: disable=protected-access

    controller._submit_done = True                 # pylint: disable=protected-access
    controller._on_all_tasks_completed()           # pylint: disable=protected-access
    assert ready == [[]]                           # 空列表也照发（无设备场景）


def test_incremental_fetch_does_not_rebuild_table():
    """增量补全只发 device_row_updated，不发 devices_ready（不做全表重建）。"""
    controller = DeviceRefreshController()
    ready = []
    controller.devices_ready.connect(ready.append)

    controller._manager = _FakeManager()           # pylint: disable=protected-access
    controller._incremental = True                 # pylint: disable=protected-access
    controller._submit_done = True                 # pylint: disable=protected-access
    controller._on_all_tasks_completed()           # pylint: disable=protected-access

    assert ready == []
    assert controller._incremental is False        # pylint: disable=protected-access


def test_background_discovery_filters_devices(monkeypatch):
    """心跳必须按同口径过滤：不支持的型号不得被当成「新上线」。"""
    from ui.workers.background_discovery_worker import BackgroundDiscovery

    discovery = BackgroundDiscovery()
    discovery.set_filter(lambda device_id: device_id.startswith("H16"))
    seen = []
    discovery.changed.connect(lambda added, removed: seen.append((added, removed)))

    discovery._on_probed([  # pylint: disable=protected-access
        ("H16-26-A0419", "192.168.81.94"),
        ("Q910-D26-002B8", "192.168.1.230"),      # 不支持型号 → 必须被过滤掉
    ])

    assert seen == [([("H16-26-A0419", "192.168.81.94")], [])]
