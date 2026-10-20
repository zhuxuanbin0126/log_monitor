"""UI 辅助组件（Excel 导出、错误日志、查询展示）测试。"""

import ui.error_log_manager as error_log_module
from ui.error_log_manager import ErrorLogManager
from ui.excel_exporter import ExcelExporter
from ui.query_result_presenter import QueryResultPresenter


def test_operation_result_message_via_presenter():
    logs = []
    presenter = QueryResultPresenter(lambda msg, **kw: logs.append(msg), lambda value: value)
    # formatted_remote_time 已是北京时区墙钟，展示时不再二次 +8
    results = {
        'device_time': {'formatted_remote_time': '2026-10-19 10:00:00', 'time_diff': 200},
        'start_count': '3',
    }
    assert presenter.present('H16-00-0001', results) is True
    joined = "\n".join(logs)
    assert '设备时间: 2026-10-19 10:00:00' in joined
    assert '偏差超过120秒' in joined


def test_presenter_detects_failure():
    assert QueryResultPresenter.is_success({'sum_switch': '设备失败'}) is False
    assert QueryResultPresenter.is_success({'boot_time': {'error': 'x'}}) is False
    assert QueryResultPresenter.is_success({'sum_switch': '正常'}) is True


def test_not_applicable_is_not_a_failure():
    """Linux 设备无播放器概念 → 启动次数「无法获取」不应算查询失败。"""
    results = {
        'start_count': '无法获取',
        'device_time': {'formatted_remote_time': '2026-10-20 12:00:00', 'time_diff': 1},
    }
    assert QueryResultPresenter.is_success(results) is True
    assert QueryResultPresenter.not_applicable_fields(results) == ['start_count']
    assert QueryResultPresenter.not_applicable_fields({'start_count': '3'}) == []


def test_summary_marks_not_applicable_separately():
    logs = []
    presenter = QueryResultPresenter(lambda msg, **kw: logs.append(msg))
    presenter.show_summary('all', 9, ['H16-00-0001'] * 9, [],
                           [('C16L-D24-0F308', ['start_count'])])
    joined = "\n".join(logs)

    assert '查询成功: 9 台' in joined
    assert '查询失败: 0 台' in joined
    assert 'C16L-D24-0F308' in joined
    assert '不适用' in joined


def test_summary_output():
    logs = []
    presenter = QueryResultPresenter(lambda msg, **kw: logs.append(msg))
    presenter.show_summary('all', 3, ['A', 'B'], ['C'])
    joined = "\n".join(logs)
    assert '查询汇总' in joined
    assert '查询成功: 2 台' in joined
    assert '失败设备: C' in joined


def test_excel_exporter_writes_file(monkeypatch, tmp_path):
    import ui.excel_exporter as excel_module

    monkeypatch.setattr(excel_module, 'EXCEL_DIR', str(tmp_path))
    exporter = ExcelExporter()
    path = exporter.export(
        {'H16-00-0001': {'last_card_time': '2026-10-19 10:00:00', 'last_time_diff': 3,
                         'last_boot_time': '2026-10-19T09:00:00', 'last_uptime': '1小时',
                         'last_start_count': 2}},
        'H16',
        [{'id': 'H16-00-0001', 'ip': '192.168.1.10', 'mac_address': 'AA', 'device_name': 'dev'}],
        {'monitor_time': True, 'monitor_boot': True, 'monitor_start_count': True},
        lambda value: value,
    )
    assert path
    assert list(tmp_path.glob('H16_*.xlsx'))


def test_error_log_manager_classification_and_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        error_log_module.FileService, 'write_error_log',
        staticmethod(lambda info: captured.update(info)),
    )
    logs = []
    manager = ErrorLogManager(lambda msg, **kw: logs.append(msg))
    monkeypatch.setattr(manager, 'open_in_notepad', lambda: None)
    manager.handle('设备 H16-00-0001 (192.168.1.10) 连接失败', 'H16-00-0001', '192.168.1.10')
    assert '设备连接失败' in logs[-1]
    assert captured['错误类型'] == '设备离线'
    assert captured['设备ID'] == 'H16-00-0001'


def test_error_message_optimization():
    manager = ErrorLogManager()
    assert manager.optimize_message(
        'Access denied: password was not accepted'
    ) == '设备通信异常: 密码认证失败，请检查设备密码配置'
    assert manager.determine_error_type('通信超时 timeout') == '通信超时'
