# -*- coding: utf-8 -*-

"""随包 adb 解析的回归测试：命令前缀必须指向本地文件，不依赖系统 PATH。"""

import os
import pathlib

import pytest

from service.device_utils import (
    ADB_CMD, ADB_PATH, adb_resolution_status, has_bundled_adb,
)
from service import path_setup


def test_adb_cmd_is_bundled_absolute_path():
    if not has_bundled_adb():
        pytest.skip("当前环境没有 tools/bin/adb.exe")
    assert ADB_CMD.strip('"') == ADB_PATH
    assert os.path.isabs(ADB_CMD.strip('"'))
    # 不能是裸命令名，否则会被 PATH 中其它 adb 抢占
    assert os.path.basename(ADB_CMD.strip('"')).lower() == "adb.exe"


def test_adb_cmd_quoting_handles_spaces():
    if " " not in ADB_PATH:
        pytest.skip("当前安装路径不含空格，无需断言引号")
    assert ADB_CMD.startswith('"') and ADB_CMD.endswith('"')


def test_resolution_status_reports_bundled():
    status = adb_resolution_status()
    assert set(status) == {"bundled_path", "bundled_ok", "command", "path_adb", "hijacked"}
    assert status["bundled_path"] == ADB_PATH


def test_norm_uses_windows_semantics():
    """path_setup 只服务 Windows：_norm 固定用 ntpath，不随宿主 os.path 漂移。"""
    assert path_setup._norm(r"D:\a\b\\") == r"d:\a\b"
    assert path_setup._norm("d:/a/b") == r"d:\a\b"
    assert path_setup._norm("") == ""


def test_split_handles_windows_path_list():
    assert path_setup._split(r"C:\x; D:\y ;;") == [r"C:\x", r"D:\y"]
    assert path_setup._split("") == []


def test_prepend_process_path_is_idempotent(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\Windows")
    path_setup._prepend_process_path(r"D:\app\tools\bin")
    path_setup._prepend_process_path(r"D:\app\tools\bin")
    value = os.environ["PATH"]
    assert value.lower().count(r"d:\app\tools\bin") == 1
    assert value.lower().startswith(r"d:\app\tools\bin")


def test_ensure_tools_on_path_only_touches_process_env(monkeypatch, tmp_path):
    """注入只改进程内 PATH：不写注册表、不广播环境变更。"""
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("PATH", r"C:\Windows")

    result = path_setup.ensure_tools_on_path(str(tools))

    assert result["action"] == "added"
    assert os.environ["PATH"].startswith(str(tools) + ";")

    # 静态兜底：源码里不得再出现注册表写入 / 广播环境变更的可执行入口
    source = pathlib.Path(path_setup.__file__).read_text(encoding="utf-8")
    assert "import winreg" not in source
    assert "windll" not in source
    assert "SendMessageTimeout" not in source


def test_ensure_tools_on_path_present_is_noop(monkeypatch, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    monkeypatch.setenv("PATH", str(tools) + r";C:\Windows")
    before = os.environ["PATH"]

    result = path_setup.ensure_tools_on_path(str(tools))

    assert result["action"] == "present"
    assert os.environ["PATH"] == before          # 已有则字节级零动作


def test_ensure_tools_on_path_missing_dir_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", r"C:\Windows")
    before = os.environ["PATH"]

    result = path_setup.ensure_tools_on_path(str(tmp_path / "not-exist"))

    assert result["action"] == "skipped-missing"
    assert os.environ["PATH"] == before
