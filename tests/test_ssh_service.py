"""Linux SSH 直连通道：连接复用、失败单次回退、按需接受主机密钥（不触网）。"""

import service.ssh_service as ssh


class _FakeChannel:
    def __init__(self, rc=0):
        self._rc = rc

    def recv_exit_status(self):
        return self._rc


class _FakeStream:
    def __init__(self, data, rc=0):
        self._data = data
        self.channel = _FakeChannel(rc)

    def read(self):
        return self._data


class _FakeClient:
    """伪造 paramiko 客户端：记录 exec 次数，可模拟连接失效。"""

    instances = []

    def __init__(self, fail_connect=False):
        self.commands = []
        self.closed = False
        self.active = True
        self.fail_connect = fail_connect
        _FakeClient.instances.append(self)

    def set_missing_host_key_policy(self, _policy):
        return None

    def connect(self, host, **_kwargs):
        if self.fail_connect:
            raise OSError(f"connect to {host} failed")

    def get_transport(self):
        return self if self.active else None

    def is_active(self):
        return self.active

    def exec_command(self, command, timeout=None):
        # pylint: disable=unused-argument
        self.commands.append(command)
        return None, _FakeStream(b"out"), _FakeStream(b"")

    def close(self):
        self.closed = True


def _patch_paramiko(monkeypatch, client):
    monkeypatch.setattr(ssh, "paramiko_available", lambda: True)
    monkeypatch.setattr(ssh, "_connect", lambda host, password: client)


def _reset():
    ssh.close_all()
    ssh._ACCEPTED_HOSTS.clear()      # pylint: disable=protected-access


def test_execute_reuses_connection_within_ttl(monkeypatch):
    _reset()
    client = _FakeClient()
    _patch_paramiko(monkeypatch, client)

    for _ in range(3):
        assert ssh.execute("10.0.0.1", "pwd", "uptime")[2] == 0

    assert len(_FakeClient.instances) == 1        # 只建连一次
    assert len(client.commands) == 3


def test_execute_reconnects_after_connection_dies(monkeypatch):
    _reset()
    first, second = _FakeClient(), _FakeClient()
    clients = iter([first, second])
    monkeypatch.setattr(ssh, "paramiko_available", lambda: True)
    monkeypatch.setattr(ssh, "_connect", lambda host, password: next(clients))

    ssh.execute("10.0.0.2", "pwd", "date +%s")
    first.active = False                          # 设备重启 → 连接失效
    assert ssh.execute("10.0.0.2", "pwd", "uptime")[2] == 0

    assert len(second.commands) == 1


def test_falls_back_to_plink_once_when_paramiko_unavailable(monkeypatch):
    _reset()
    calls = []

    def _fake_run(cmd, timeout=None):  # pylint: disable=unused-argument
        calls.append(cmd)
        return "plink-out", "", 0

    monkeypatch.setattr(ssh, "paramiko_available", lambda: False)
    monkeypatch.setattr(ssh, "run_command", _fake_run)

    out, err, rc = ssh.execute("10.0.0.3", "pwd", "uptime", base_dir=".")

    assert (out, err, rc) == ("plink-out", "", 0)
    assert len(calls) == 1                        # 一次即止，无重试
    assert "-batch" in calls[0]


def test_plink_accepts_host_key_then_retries_once(monkeypatch):
    """主机密钥未缓存 → 就地接受一次 → 补发一次（而不是重试 3 轮 + sleep）。"""
    _reset()
    results = iter([
        ("", "The server's host key is not cached in the registry", 1),
        ("ok-after-accept", "", 0),
    ])
    accepted = []
    monkeypatch.setattr(ssh, "paramiko_available", lambda: False)
    monkeypatch.setattr(ssh, "run_command", lambda *a, **k: next(results))
    monkeypatch.setattr(ssh, "accept_host_key",
                        lambda host, password: accepted.append(host))

    out, _err, rc = ssh.execute("10.0.0.4", "pwd", "uptime", base_dir=".")

    assert (out, rc) == ("ok-after-accept", 0)
    assert accepted == ["10.0.0.4"]


def test_plink_does_not_retry_on_command_failure(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(ssh, "paramiko_available", lambda: False)
    monkeypatch.setattr(
        ssh, "run_command",
        lambda *a, **k: (calls.append(1), ("", "command not found", 127))[1])

    _out, err, rc = ssh.execute("10.0.0.5", "pwd", "bogus", base_dir=".")

    assert rc == 127 and "not found" in err
    assert len(calls) == 1                        # 命令自身失败不换通道重跑


def test_is_host_key_error_recognizes_plink_messages():
    assert ssh.is_host_key_error("The server's host key is not cached") is True
    assert ssh.is_host_key_error("Host key verification failed") is True
    assert ssh.is_host_key_error("Access denied") is False
    assert ssh.is_host_key_error("") is False


def test_file_exists_single_command(monkeypatch):
    _reset()
    seen = []

    def _fake_execute(host, password, command, base_dir=".", timeout=None):
        # pylint: disable=unused-argument
        seen.append(command)
        return "YES", "", 0

    monkeypatch.setattr(ssh, "execute", _fake_execute)

    assert ssh.file_exists("10.0.0.6", "pwd", "/data/a.csv") is True
    assert seen == ["test -f /data/a.csv && echo YES"]


# ---------------------------------------------------------------- SFTP 文件传输

class _FakeSftp:
    def __init__(self):
        self.puts = []
        self.gets = []

    def put(self, local_file, remote_file):
        self.puts.append((local_file, remote_file))

    def get(self, remote_file, local_file):
        self.gets.append((remote_file, local_file))

    def close(self):
        return None


class _SftpClient(_FakeClient):
    def __init__(self, fail_sftp=False):
        super().__init__()
        self.sftp = _FakeSftp()
        self.fail_sftp = fail_sftp

    def open_sftp(self):
        if self.fail_sftp:
            raise OSError("sftp subsystem disabled")
        return self.sftp


def test_put_file_reuses_one_connection(monkeypatch, tmp_path):
    _reset()
    client = _SftpClient()
    created = []
    monkeypatch.setattr(ssh, "paramiko_available", lambda: True)
    monkeypatch.setattr(ssh, "_connect",
                        lambda host, password: (created.append(host), client)[1])
    local = tmp_path / "run.sh"
    local.write_text("#!/bin/sh\n", encoding="utf-8")

    assert ssh.put_file("10.0.0.7", "pwd", str(local), "/root/Box/run.sh")[2] == 0
    assert ssh.put_file("10.0.0.7", "pwd", str(local), "/root/boot_counter.sh")[2] == 0

    assert len(created) == 1                         # 两次上传只建连一次
    assert client.sftp.puts == [
        (str(local), "/root/Box/run.sh"),
        (str(local), "/root/boot_counter.sh"),
    ]


def test_put_file_falls_back_to_pscp(monkeypatch, tmp_path):
    _reset()
    client = _SftpClient(fail_sftp=True)
    _patch_paramiko(monkeypatch, client)
    local = tmp_path / "run.sh"
    local.write_text("#!/bin/sh\n", encoding="utf-8")

    calls = []
    monkeypatch.setattr(ssh, "run_command",
                        lambda cmd, timeout=None: (calls.append(cmd), ("", "", 0))[1])

    assert ssh.put_file("10.0.0.8", "pwd", str(local), "/root/Box/run.sh")[2] == 0
    assert len(calls) == 1 and "pscp" in calls[0]


def test_get_file_creates_local_folder(monkeypatch, tmp_path):
    _reset()
    client = _SftpClient()
    _patch_paramiko(monkeypatch, client)
    target = tmp_path / "switch_log" / "C16L-1" / "swich_counter.csv"

    assert ssh.get_file("10.0.0.9", "pwd", "/root/data/swich_counter.csv",
                        str(target))[2] == 0
    assert target.parent.is_dir()
    assert client.sftp.gets == [("/root/data/swich_counter.csv", str(target))]
