"""查询策略分发表测试（使用假业务对象，不触网）。"""

import io
import threading

from business.query_dispatcher import ALL_QUERY_KEYS, build_query_dispatch
from data_models import OperationResult


class FakeMonitorService:
    def get_device_time_info(self, ip, password, device_id):
        return "2026-10-19 10:00:00", 5

    def get_uptime_info(self, ip, password, device_id):
        return {"formatted_uptime": "1天2时"}

    def get_start_count(self, ip, password, device_id):
        return "3"

    def count_init_setting(self, ip, password, device_id, system_type, custom_file_paths=None):
        return OperationResult(True, data=f"{device_id} 初始化成功")

    def sum_switch_count(self, ip, password, device_id, path):
        return 10, 4, True, None

    def clean_switch_log(self, ip, password, device_id, path):
        return True, f"{device_id} 已清除"

    def ntptime_checkout_time(self, ip, password, device_id, system_type):
        return OperationResult(True, data=f"{device_id} 校时成功")

    def upgrade_program(self, ip, password, device_id, system_type, custom_file_paths=None):
        return OperationResult(False, error=f"{device_id} 更新失败")

    def capture_screenshot(self, device_id, ip, password, system_type):
        return OperationResult(True, data=f"/tmp/{device_id}.jpg")

    def switch_log_output(self, ip, password, device_id, system_type, path):
        return True, f"{device_id} 日志已导出"


def _dispatch(results, switch_log_file=None, query_count=None, csv_lock=None):
    return build_query_dispatch(
        FakeMonitorService(), "H16-00-0001", "192.168.1.10", "pwd", "Android", results,
        switch_log_file=switch_log_file,
        query_count=query_count,
        csv_lock=csv_lock,
    )


def test_all_query_keys():
    assert ALL_QUERY_KEYS == ["time", "boot_time", "start_count", "sum_switch"]


def test_time_and_boot_results():
    results = {}
    dispatch = _dispatch(results)
    dispatch["time"]()
    dispatch["boot_time"]()
    assert results["device_time"]["time_diff"] == 5
    assert results["boot_time"]["formatted_uptime"] == "1天2时"


def test_operation_results_use_message():
    results = {}
    dispatch = _dispatch(results)
    dispatch["count_init"]()
    dispatch["check_time"]()
    dispatch["upgrade_program"]()
    dispatch["screenshot"]()
    assert results["count_init"].endswith("初始化成功")
    assert results["check_time"].endswith("校时成功")
    assert results["upgrade_program"].endswith("更新失败")
    assert results["screenshot"].endswith(".jpg")


def test_sum_switch_writes_csv_thread_safely():
    results = {}
    buffer = io.StringIO()
    count = [0]
    lock = threading.Lock()
    dispatch = _dispatch(results, switch_log_file=buffer, query_count=count, csv_lock=lock)
    dispatch["sum_switch"]()
    assert "10" in results["sum_switch"]
    assert buffer.getvalue() == "H16-00-0001,10,4\n"
    assert count[0] == 1


def test_clean_and_output_log():
    results = {}
    dispatch = _dispatch(results)
    dispatch["clean_switch"]()
    dispatch["output_log"]()
    assert "已清除" in results["clean_switch"]
    assert "日志已导出" in results["output_log"]
