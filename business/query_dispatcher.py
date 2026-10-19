"""查询/操作策略分发表（无 Qt 依赖，便于单测）。"""

from config import get_device_remote_path

ALL_QUERY_KEYS = ["time", "boot_time", "start_count", "sum_switch"]


def build_query_dispatch(monitor_service, device_id, ip, password, system_type,
                         results, *, switch_log_file=None, custom_file_paths=None,
                         query_count=None, csv_lock=None):
    """构建 query_type -> handler 的分发表。

    handler 把结果写入 results；sum_switch 在提供文件与锁时追加 CSV。
    """

    def _time():
        formatted_remote_time, time_diff = monitor_service.get_device_time_info(ip, password, device_id)
        results['device_time'] = {
            'formatted_remote_time': formatted_remote_time,
            'time_diff': time_diff,
        }

    def _boot_time():
        results['boot_time'] = monitor_service.get_uptime_info(ip, password, device_id)

    def _start_count():
        results['start_count'] = monitor_service.get_start_count(ip, password, device_id)

    def _count_init():
        results['count_init'] = monitor_service.count_init_setting(
            ip, password, device_id, system_type, custom_file_paths=custom_file_paths
        ).message

    def _sum_switch():
        path = get_device_remote_path(system_type)
        switch_time, network_time, success, error_msg = monitor_service.sum_switch_count(
            ip, password, device_id, path
        )
        if success:
            if switch_log_file is not None:
                if csv_lock is not None:
                    with csv_lock:
                        if query_count is not None:
                            query_count[0] += 1
                        switch_log_file.write(f"{device_id},{switch_time},{network_time}\n")
                else:
                    if query_count is not None:
                        query_count[0] += 1
                    switch_log_file.write(f"{device_id},{switch_time},{network_time}\n")
            results['sum_switch'] = (
                f"{device_id} 当前开关机次数为：{switch_time} "
                f"网络开关机次数为：{network_time}"
            )
        else:
            results['sum_switch'] = error_msg

    def _clean_switch():
        path = get_device_remote_path(system_type)
        success, error_msg = monitor_service.clean_switch_log(ip, password, device_id, path)
        results['clean_switch'] = f"{device_id} 开关机记录已清除" if success else error_msg

    def _check_time():
        results['check_time'] = monitor_service.ntptime_checkout_time(
            ip, password, device_id, system_type
        ).message

    def _upgrade_program():
        results['upgrade_program'] = monitor_service.upgrade_program(
            ip, password, device_id, system_type, custom_file_paths=custom_file_paths
        ).message

    def _screenshot():
        results['screenshot'] = monitor_service.capture_screenshot(
            device_id, ip, password, system_type
        ).message

    def _output_log():
        path = get_device_remote_path(system_type)
        _, output_log = monitor_service.switch_log_output(
            ip, password, device_id, system_type, path
        )
        results['output_log'] = output_log

    def _all():
        pass  # 由 ALL_QUERY_KEYS 控制子处理器调用

    return {
        "all": _all,
        "time": _time,
        "boot_time": _boot_time,
        "start_count": _start_count,
        "count_init": _count_init,
        "sum_switch": _sum_switch,
        "clean_switch": _clean_switch,
        "check_time": _check_time,
        "upgrade_program": _upgrade_program,
        "screenshot": _screenshot,
        "output_log": _output_log,
    }
