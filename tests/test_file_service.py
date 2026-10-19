"""FileService 文件写入与格式化测试（使用临时目录）。"""

import json

import service.file_service as file_service


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(file_service, 'OUTPUT_DIR', str(tmp_path))
    monkeypatch.setattr(file_service, 'LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setattr(file_service, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(file_service, 'SCREENSHOT_DIR', str(tmp_path / 'screenshot'))
    monkeypatch.setattr(file_service, 'SWITCH_LOG_DIR', str(tmp_path / 'switch_log'))
    monkeypatch.setattr(file_service, 'EXCEL_DIR', str(tmp_path / 'excel'))
    monkeypatch.setattr(file_service, 'DEVICE_DATA_FILE', str(tmp_path / 'device_monitoring_data.json'))
    monkeypatch.setattr(file_service, 'ERROR_LOG_FILE', str(tmp_path / 'device_error.txt'))


def test_init_log_files_creates_all_outputs(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    file_service.FileService.init_log_files(str(tmp_path / 'H16_AgingTest'))

    assert (tmp_path / 'device_monitoring_data.json').exists()
    assert (tmp_path / 'device_error.txt').exists()
    for suffix in ('uptime', 'cardtime', 'startcount', 'comprehensive'):
        assert (tmp_path / 'logs' / f'H16_AgingTest_{suffix}.log').exists()


def test_write_comprehensive_log(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    file_service.FileService.write_comprehensive_log(
        '192.168.1.10', 'pwd', 'H16-00-0001', str(tmp_path / 'H16_AgingTest'),
        '1天2时', '2026-10-19 10:00:00', 5, 3,
    )
    content = (tmp_path / 'logs' / 'H16_AgingTest_comprehensive.log').read_text(encoding='utf-8')
    assert 'H16-00-0001' in content
    assert '192.168.1.10' in content


def test_format_error_details_cleans_duplicate_prefix():
    text = file_service.FileService._format_error_details([
        {
            'type': '设备离线',
            'process': '设备ID: H16-00-0001, IP: 192.168.1.10 ',
            'difference': '设备ID: H16-00-0001, IP: 192.168.1.10 发现错误: 连接失败',
        }
    ])
    assert '- 类型: 设备离线' in text
    assert '设备ID: H16-00-0001, IP: 192.168.1.10 发现错误' not in text
    assert '连接失败' in text


def test_write_error_log_roundtrip(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    file_service.FileService.write_error_log({
        '时间': '2026-10-19 10:00:00',
        '设备ID': 'H16-00-0001',
        'IP地址': '192.168.1.10',
        '错误类型': '设备离线',
        '错误详情': [{'type': '设备离线', 'process': 'P', 'difference': 'D'}],
    })
    content = (tmp_path / 'device_error.txt').read_text(encoding='utf-8')
    assert 'H16-00-0001' in content
    assert '设备离线' in content


def test_save_and_load_device_data(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    data = {'H16-00-0001': {'last_uptime': '1小时'}}
    file_service.FileService.save_device_data(data)
    assert json.loads((tmp_path / 'device_monitoring_data.json').read_text(encoding='utf-8')) == data
    assert file_service.FileService.load_device_data() == data
