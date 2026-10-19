"""传输层选择与回退测试（不触网）。"""

import sys
import types

import service.transports as transports
from service.transports import AndroidTransport, SshTransport, get_transport


def test_get_transport_routing():
    assert isinstance(get_transport('H16-00-0001'), AndroidTransport)
    assert isinstance(get_transport('D16-00-0001'), SshTransport)


def test_android_transport_falls_back_to_ssh_when_adb_disabled(monkeypatch):
    monkeypatch.setattr(transports.ADBDeviceManager, 'should_use_adb', lambda _id: False)
    monkeypatch.setattr(
        transports.SshTransport, 'execute',
        lambda self, ip, password, command, base_dir='.': ('out', '', 0),
    )
    result = AndroidTransport('H16-00-0001').execute('192.168.1.10', 'pwd', 'uptime')
    assert result == ('out', '', 0)


def test_android_transport_uses_adb_when_available(monkeypatch):
    monkeypatch.setattr(transports.ADBDeviceManager, 'should_use_adb', lambda _id: True)
    monkeypatch.setattr(
        transports.ADBDeviceManager, 'ensure_adb_connected',
        lambda ip, password, device_id: (True, 'serial-1'),
    )
    monkeypatch.setattr(
        transports.ADBDeviceManager, 'execute_adb_command',
        lambda ip, serial, command: ('adb-out', '', 0),
    )
    result = AndroidTransport('H16-00-0001').execute('192.168.1.10', 'pwd', 'uptime')
    assert result == ('adb-out', '', 0)


def test_ssh_transport_uses_paramiko_when_available(monkeypatch):
    class FakeChannel:
        @staticmethod
        def recv_exit_status():
            return 0

    class FakeStream:
        def __init__(self, text):
            self._text = text
            self.channel = FakeChannel()

        def read(self):
            return self._text.encode('utf-8')

    class FakeClient:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, *args, **kwargs):
            pass

        def exec_command(self, command, timeout=30):
            return None, FakeStream('ok'), FakeStream('')

        def close(self):
            pass

    fake = types.SimpleNamespace(
        SSHClient=FakeClient,
        AutoAddPolicy=lambda: object(),
    )
    monkeypatch.setitem(sys.modules, 'paramiko', fake)

    out, err, rc = SshTransport().execute('192.168.1.10', 'pwd', 'uptime')
    assert (out, err, rc) == ('ok', '', 0)


def test_ssh_transport_plink_fallback(monkeypatch, tmp_path):
    calls = {}

    def fake_run_command(cmd):
        calls['cmd'] = cmd
        script_path = cmd.split(' -m ')[-1]
        calls['script_exists'] = __import__('os').path.exists(script_path)
        calls['script'] = open(script_path, encoding='utf-8').read()
        return 'plink-out', '', 0

    monkeypatch.setattr(transports, 'run_command', fake_run_command)
    monkeypatch.setattr(transports, 'get_tool_path', lambda name: name)
    monkeypatch.setitem(sys.modules, 'paramiko', None)

    out, err, rc = SshTransport._execute_with_plink(
        '192.168.1.10', 'pwd', 'uptime', str(tmp_path)
    )
    assert (out, err, rc) == ('plink-out', '', 0)
    assert 'uptime' in calls['script']
    assert calls['script_exists'] is True
    assert not (tmp_path / '192.168.1.10temp_script.txt').exists()
