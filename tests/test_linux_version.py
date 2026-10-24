"""Linux 机型版本取数单测（纯离线，SSH 打桩）。

真机实测：C16L 的发行版本在 ``/root/Box/version/version``（如 ``7.11.34.0``，
**无换行符**）；该类型无 OTA 版本，OTA 列固定 ``N/A``。
"""

import pytest

import service.linux_version as lv
from service.linux_version import NA, parse_version, query_version


# ---------------------------------------------------------------- 纯解析

def test_parse_version_plain():
    """真机实测：版本文件内容 9 字节、无换行符。"""
    assert parse_version('7.11.34.0') == '7.11.34.0'


def test_parse_version_with_newline_and_spaces():
    assert parse_version('7.10.62.3\n') == '7.10.62.3'
    assert parse_version('  7.9.73.0  ') == '7.9.73.0'
    assert parse_version('\n7.11.34.0\n') == '7.11.34.0'


def test_parse_version_empty_returns_na():
    assert parse_version('') == NA
    assert parse_version(None) == NA
    assert parse_version('\n\n') == NA
    assert parse_version('   ') == NA


def test_parse_version_takes_first_token():
    """多余内容只取首个 token（避免把噪声带进表格）。"""
    assert parse_version('7.11.34.0 extra') == '7.11.34.0'


# ---------------------------------------------------------------- SSH 取数

def test_query_version_reads_version_file(monkeypatch):
    """成功取到版本：返回版本串，且命令指向设备端版本文件。"""
    seen = {}

    def fake_execute(ip, password, command, base_dir=".", timeout=None):
        seen.update(ip=ip, password=password, command=command, timeout=timeout)
        return '7.11.34.0', '', 0

    monkeypatch.setattr(lv.ssh_service, 'execute', fake_execute)

    assert query_version('192.168.81.127', 'pwd') == '7.11.34.0'
    assert seen['ip'] == '192.168.81.127'
    assert lv.VERSION_FILE in seen['command']
    assert '2>/dev/null' in seen['command']   # 文件缺失时静默


def test_query_version_file_missing_returns_na(monkeypatch):
    """文件不存在（命令空输出）→ N/A，不抛异常。"""
    monkeypatch.setattr(lv.ssh_service, 'execute',
                        lambda *a, **k: ('', '', 1))
    assert query_version('192.168.81.127', 'pwd') == NA


def test_query_version_unreachable_returns_na(monkeypatch):
    """设备不可达（SSH 抛异常）→ N/A。"""
    def boom(*_a, **_k):
        raise OSError('connection refused')

    monkeypatch.setattr(lv.ssh_service, 'execute', boom)
    assert query_version('192.168.81.127', 'pwd') == NA


def test_query_version_nonzero_rc_with_output(monkeypatch):
    """命令返回非 0 但有输出时仍按输出解析（不误判为失败）。"""
    monkeypatch.setattr(lv.ssh_service, 'execute',
                        lambda *a, **k: ('7.10.62.3', 'warn', 1))
    assert query_version('192.168.81.127', 'pwd') == '7.10.62.3'


def test_query_version_timeout_is_bounded(monkeypatch):
    """超时上限受控（设备不可达时不拖慢设备列表刷新）。"""
    seen = {}
    monkeypatch.setattr(
        lv.ssh_service, 'execute',
        lambda ip, pw, cmd, base_dir=".", timeout=None: seen.update(timeout=timeout) or ('', '', 1))

    query_version('192.168.81.127', 'pwd')
    assert seen['timeout'] == lv.VERSION_TIMEOUT
    assert lv.VERSION_TIMEOUT <= 10.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
