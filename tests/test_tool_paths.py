"""工具路径解析：**外部 tools/bin 优先**，缺失才回退 exe 内置副本。

背景（现场问题）：onefile 打包后工具解压在 ``%TEMP%\\_MEIxxxx``；部分电脑临时目录
不可写或被杀软/AppLocker 拦截，导致 adb/plink 等从那里启动失败。发布包在 exe 旁边
带了一份 ``tools/``，因此运行时必须优先用外部真实路径。
"""

import os

import config
import service.device_utils as du


def _reset(monkeypatch, external, bundled=""):
    monkeypatch.setattr(du, "EXTERNAL_TOOLS_DIR", str(external))
    monkeypatch.setattr(du, "BUNDLED_TOOLS_DIR", str(bundled) if bundled else "")
    monkeypatch.setattr(du, "_TOOL_PATH_CACHE", {})


def _touch(path):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


def test_prefers_external_tools_over_bundled(monkeypatch, tmp_path):
    external = tmp_path / "app" / "tools" / "bin"
    bundled = tmp_path / "_MEI123" / "tools" / "bin"
    _touch(external / "adb.exe")
    _touch(bundled / "adb.exe")
    _reset(monkeypatch, external, bundled)

    assert du.get_tool_path("adb.exe") == str(external / "adb.exe")


def test_falls_back_to_bundled_when_external_missing(monkeypatch, tmp_path):
    external = tmp_path / "app" / "tools" / "bin"
    bundled = tmp_path / "_MEI123" / "tools" / "bin"
    _touch(bundled / "plink.exe")
    _reset(monkeypatch, external, bundled)

    assert du.get_tool_path("plink.exe") == str(bundled / "plink.exe")


def test_returns_deterministic_path_when_both_missing(monkeypatch, tmp_path):
    external = tmp_path / "app" / "tools" / "bin"
    _reset(monkeypatch, external, "")

    # 不抛异常：调用方拿到确定路径后再报「文件不存在」
    assert du.get_tool_path("adb.exe") == str(external / "adb.exe")


def test_tool_path_is_cached(monkeypatch, tmp_path):
    external = tmp_path / "tools" / "bin"
    _touch(external / "pscp.exe")
    _reset(monkeypatch, external, "")

    first = du.get_tool_path("pscp.exe")
    os.remove(str(external / "pscp.exe"))       # 缓存后不再重复探测
    assert du.get_tool_path("pscp.exe") == first


def test_tools_status_reports_missing(monkeypatch, tmp_path):
    external = tmp_path / "tools" / "bin"
    _touch(external / "adb.exe")
    _reset(monkeypatch, external, "")

    status = du.tools_status(["adb.exe", "plink.exe"])
    assert status["missing"] == ["plink.exe"]
    assert status["external_exists"] is True
    assert status["resolved"]["adb.exe"].endswith("adb.exe")


def test_tool_path_uses_native_separators(monkeypatch, tmp_path):
    """路径分隔符必须是**当前平台原生**形式（回归：曾写死反斜杠）。

    在 Linux/macOS 上把 ``/`` 替换成 ``\\`` 会得到 ``\\home\\...`` 这种不存在的路径，
    工具「明明在却找不到」；GitHub Actions 的 ubuntu runner 上即由此导致 4 个用例失败。
    """
    external = tmp_path / "tools" / "bin"
    _touch(external / "adb.exe")
    _reset(monkeypatch, external, "")

    path = du.get_tool_path("adb.exe")

    assert path == os.path.normpath(str(external / "adb.exe"))
    assert os.path.isfile(path)                     # 必须能定位到真实文件
    assert os.path.basename(path) == "adb.exe"
    assert os.path.dirname(path) == os.path.normpath(str(external))


def test_tools_search_order_external_first(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path / "ext", tmp_path / "mei")
    paths = du.tool_search_paths("adb.exe")

    assert len(paths) == 2
    assert paths[0].startswith(str(tmp_path / "ext"))
    assert paths[1].startswith(str(tmp_path / "mei"))


def test_config_prefers_external_tools_dir(monkeypatch, tmp_path):
    """config.TOOL_PATH / GET_INFO_PATH 同样外部优先（推送脚本依赖它）。"""
    _touch(tmp_path / "tools" / "getdeviceinfo.sh")
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.delattr(config.sys, "_MEIPASS", raising=False)

    assert config._external_or_bundled("tools") == str(tmp_path / "tools")  # pylint: disable=protected-access
    assert config._external_or_bundled(  # pylint: disable=protected-access
        "tools", "getdeviceinfo.sh") == str(tmp_path / "tools" / "getdeviceinfo.sh")


def test_config_falls_back_to_bundled(monkeypatch, tmp_path):
    external_root = tmp_path / "app"
    mei_root = tmp_path / "_MEI456"
    _touch(mei_root / "tools" / "run.sh")
    monkeypatch.setattr(config, "PROJECT_ROOT", str(external_root))
    monkeypatch.setattr(config.sys, "_MEIPASS", str(mei_root), raising=False)

    # 外部没有 run.sh 时回退到内置副本
    assert config._external_or_bundled("tools", "run.sh") == str(  # pylint: disable=protected-access
        mei_root / "tools" / "run.sh")
