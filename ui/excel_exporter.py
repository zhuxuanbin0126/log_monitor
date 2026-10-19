"""监控结果 Excel 导出。"""

import os
from datetime import datetime

from config import EXCEL_DIR
from service.logging_service import get_logger


class ExcelExporter:
    """把监控结果追加写入单个 Excel 文件。"""

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda *args, **kwargs: None)
        self._logger = get_logger(__name__)
        self.excel_file = None

    def reset(self) -> None:
        """清除当前文件句柄，下次导出重新生成文件名。"""
        self.excel_file = None

    def export(self, device_data, dev_type, devices, options, format_time) -> str:
        """导出一次监控快照，返回 Excel 路径；失败返回空字符串。

        options 需包含 monitor_time / monitor_boot / monitor_start_count 三个布尔值；
        format_time 用于把启动时间格式化为分钟精度。
        """
        try:
            import pandas as pd
        except ImportError:
            self._log("导出Excel失败：未找到pandas模块。请运行 'pip install pandas' 安装依赖", is_error=True)
            return ""

        try:
            os.makedirs(EXCEL_DIR, exist_ok=True)
            if not self.excel_file:
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                self.excel_file = os.path.join(EXCEL_DIR, f'{dev_type}_{timestamp}.xlsx')

            monitor_time = bool(options.get('monitor_time'))
            monitor_boot = bool(options.get('monitor_boot'))
            monitor_start_count = bool(options.get('monitor_start_count'))

            current_system_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            device_index = {d.get('id'): d for d in devices if isinstance(d, dict)}

            rows = []
            for device_id, info in device_data.items():
                device_info = device_index.get(device_id, {})
                row = {
                    '系统时间': current_system_time,
                    '设备ID': device_id,
                    'IP地址': device_info.get('ip', '未知'),
                    'MAC地址': device_info.get('mac_address', '未知'),
                    '设备名称': device_info.get('device_name', '未知'),
                }
                if monitor_time:
                    row['设备时间'] = info.get('last_card_time', info.get('initial_card_time', 'N/A'))
                    time_diff = info.get('last_time_diff', info.get('initial_time_diff', 'N/A'))
                    row['时间差'] = f"{time_diff}秒" if time_diff != 'N/A' else time_diff
                if monitor_boot:
                    row['启动时间'] = format_time(info.get('last_boot_time', 'N/A'))
                    row['运行时长'] = info.get('last_uptime', 'N/A')
                if monitor_start_count:
                    row['播放器启动次数'] = info.get('last_start_count', 'N/A')
                rows.append(row)

            if not rows:
                return self.excel_file

            df = pd.DataFrame(rows)
            self._write_frame(pd, df)
        except Exception as e:
            self._logger.exception("写入Excel文件时出错")
            self._log(f"写入Excel文件时出错: {str(e)}", is_error=True)
            return ""

        excel_path = os.path.abspath(self.excel_file).replace('\\', '/')
        self._log(f"监控结果已成功导出到 {excel_path}")
        return self.excel_file

    def _write_frame(self, pd, df) -> None:
        """写入 DataFrame：已存在文件时追加，并尽量自适应列宽。"""
        try:
            import xlsxwriter  # noqa: F401
            engine = 'xlsxwriter'
        except ImportError:
            engine = None

        file_exists = os.path.exists(self.excel_file)
        if file_exists:
            existing_df = pd.read_excel(self.excel_file)
            merged_df = pd.concat([existing_df, df])
        else:
            merged_df = df

        if engine == 'xlsxwriter':
            with pd.ExcelWriter(self.excel_file, engine=engine) as writer:
                merged_df.to_excel(writer, index=False, sheet_name='设备监控数据')
                worksheet = writer.sheets['设备监控数据']
                for col_num, col_name in enumerate(merged_df.columns):
                    col_values = merged_df[col_name].dropna().astype(str)
                    max_length = max([len(str(x)) for x in col_values] + [len(col_name)]) + 15
                    worksheet.set_column(col_num, col_num, min(max_length, 50))
        else:
            merged_df.to_excel(self.excel_file, index=False, sheet_name='设备监控数据')
