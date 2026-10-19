"""ADB 子进程环境归一（service/adb_env.py）与 run_command 环境解析测试。"""

import os

import service.adb_env as adb_env
import service.device_utils as device_utils


def test_adb_temp_dir_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "adb_tmp"
    monkeypatch.setenv(adb_env.ENV_OVERRIDE, str(target))
    result = adb_env.adb_temp_dir()
    assert result == str(target)
    assert os.path.isdir(result)


def test_adb_subprocess_env_rewrites_temp_and_tmp(monkeypatch, tmp_path):
    target = tmp_path / "long" / "path" / "tmp"
    monkeypatch.setenv(adb_env.ENV_OVERRIDE, str(target))
    monkeypatch.setenv("TEMP", "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp")
    monkeypatch.setenv("TMP", "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp")

    env = adb_env.adb_subprocess_env()

    assert env["TEMP"] == str(target)
    assert env["TMP"] == str(target)
    # 其余环境原样继承
    assert env.get("PATH") == os.environ.get("PATH")


def test_adb_temp_dir_is_long_path_not_short_name(monkeypatch, tmp_path):
    """归一化后目录不应包含 8.3 短名（含 ``~`` 的段）。"""
    target = tmp_path / "adb_tmp"
    monkeypatch.setenv(adb_env.ENV_OVERRIDE, str(target))
    assert "~" not in adb_env.adb_temp_dir()


def test_is_adb_command_detection():
    assert adb_env.is_adb_command(r"C:\tools\bin\adb.exe -s x shell ls") is True
    assert adb_env.is_adb_command("ADB connect 1.2.3.4") is True
    assert adb_env.is_adb_command("plink.exe -batch root@1.2.3.4") is False
    assert adb_env.is_adb_command(None) is False


def test_resolve_command_env_applies_only_for_adb(monkeypatch, tmp_path):
    target = tmp_path / "adb_tmp"
    monkeypatch.setenv(adb_env.ENV_OVERRIDE, str(target))

    adb_env_vars = device_utils._resolve_command_env("adb.exe devices", None)
    assert adb_env_vars is not None
    assert adb_env_vars["TEMP"] == str(target)

    assert device_utils._resolve_command_env("plink.exe -batch ...", None) is None

    explicit = {"TEMP": "explicit"}
    assert device_utils._resolve_command_env("adb.exe devices", explicit) is explicit
