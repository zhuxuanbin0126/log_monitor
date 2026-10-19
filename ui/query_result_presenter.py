"""查询结果与汇总的展示逻辑。"""

from datetime import datetime, timedelta

QUERY_TYPE_TEXT = {
    "all": "全部",
    "time": "设备时间",
    "boot_time": "启动时间",
    "start_count": "播放器启动次数",
    "count_init": "开关机初始化",
    "sum_switch": "开关机次数",
    "clean_switch": "清空开关机次数",
    "check_time": "校时",
    "upgrade_program": "发送节目",
    "screenshot": "截图",
    "output_log": "导出开关机日志",
}

QUERY_OPERATION_TYPES = {"all", "time", "boot_time", "start_count", "sum_switch"}


class QueryResultPresenter:
    """把查询结果字典转换为用户可读日志，并生成汇总。"""

    def __init__(self, log_callback, format_time_callback=None):
        self._log = log_callback
        self._format_time = format_time_callback or (lambda value: value)

    @staticmethod
    def is_query_operation(query_type: str) -> bool:
        return query_type in QUERY_OPERATION_TYPES

    @staticmethod
    def query_type_text(query_type: str) -> str:
        return QUERY_TYPE_TEXT.get(query_type, "未知")

    @staticmethod
    def is_success(results: dict) -> bool:
        """根据结果内容判断本次查询/操作是否成功。"""
        for value in results.values():
            if isinstance(value, dict) and 'error' in value:
                return False
            if isinstance(value, str) and ('失败' in value or '错误' in value or '无法' in value):
                return False
        return True

    def present(self, device_id: str, results: dict) -> bool:
        """输出单设备结果，返回是否成功。"""
        self._log(f"\n设备 {device_id} 操作结果:")

        if 'device_time' in results:
            self._present_device_time(results['device_time'])

        if 'boot_time' in results:
            boot_info = results['boot_time']
            if 'error' not in boot_info:
                self._log(f"运行时长: {boot_info.get('formatted_uptime', 'N/A')}")
                self._log(f"启动时间: {self._format_time(boot_info.get('boot_time', 'N/A'))}")
            else:
                self._log(f"获取启动时间失败: {boot_info['error']}", is_error=True)

        if 'start_count' in results:
            self._present_start_count(results['start_count'])

        for key in ("count_init", "sum_switch", "clean_switch", "check_time",
                    "output_log", "upgrade_program", "screenshot"):
            if key in results:
                self._log(f"设备: {results[key]}")

        return self.is_success(results)

    def _present_device_time(self, time_info: dict) -> None:
        if time_info.get('formatted_remote_time') != 'N/A':
            utc_time = datetime.strptime(time_info['formatted_remote_time'], '%Y-%m-%d %H:%M:%S')
            local_time = utc_time + timedelta(hours=8)
            self._log(f"设备时间: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self._log("设备时间: N/A")

        time_diff = int(time_info['time_diff']) if time_info.get('time_diff') != 'N/A' else 0
        self._log(f"时间差: {time_diff} 秒")
        if time_info.get('time_diff') != 'N/A' and time_diff > 120:
            self._log("警告: 设备时间与系统时间偏差超过120秒", is_warning=True)

    def _present_start_count(self, start_count) -> None:
        self._log(f"播放器启动次数: {start_count}")
        if start_count == '无法获取':
            return
        try:
            count = int(start_count)
        except (ValueError, TypeError):
            return
        if count > 1:
            self._log(f"警告: 播放器启动次数异常，当前值为 {count}", is_warning=True)

    def show_summary(self, current_type, total, successful, failed) -> None:
        """输出查询/操作汇总。"""
        is_query = self.is_query_operation(current_type)
        op_text = self.query_type_text(current_type)
        success_count = len(successful)
        fail_count = len(failed)

        self._log("\n-----------------------------------------------------------------------")
        if is_query:
            self._log("查询汇总:")
            self._log(f"  总设备数: {total}")
            self._log(f"  查询成功: {success_count} 台")
            self._log(f"  查询失败: {fail_count} 台")
            if failed:
                self._log(f"  失败设备: {', '.join(failed)}", is_error=True)
        else:
            self._log(f"已完成 {total} 台设备的{op_text}操作")
            if fail_count > 0:
                self._log(f"  操作失败: {fail_count} 台")
                self._log(f"  失败设备: {', '.join(failed)}", is_error=True)
        self._log("-----------------------------------------------------------------------")
