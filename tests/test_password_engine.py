"""设备密码引擎与服务单测（含与 HPassword.exe 的逐字节等价性校验）。

参考向量由本机 ``tools/bin/HPassword.exe`` 实测得到，作为确定性基线；
另有 live 用例直接与 ``HPassword.exe`` 输出比对（exe 缺失时自动跳过）。
"""

import os
import subprocess
import sys
import threading

import pytest

from service.device_utils import TOOLS_DIR
from service.password_engine import generate_password
from service.password_service import PasswordService
from service.tool_service import ToolService

# HPassword.exe 实测参考向量（逐字节比对基线）
REFERENCE_VECTORS = [
    ("H16-00-0001", "?:HPeouUag5"),
    ("D16-00-0001", "tjZ2nDI1gZT_"),
    ("A3L-0001", "lysy:nKsbZ6"),
    ("H20-00-A0208", "eqnYC3YeULf."),
    ("A5L-00-1234", "GRqpSY9kQb0%"),
    ("C08L-00-0001", "YFw75HCqZ4_"),
    ("C16L-00-9999", "vPuJ_s4f!g6"),
    ("A7-00-0007", "lNpW44l733."),
    ("A8-00-0008", "94yR^bb8Zx:"),
    ("B8L-0123", "nTUla9_7dPR"),
]

_HPASSWORD_EXE = os.path.join(TOOLS_DIR, "HPassword.exe")


@pytest.mark.parametrize("device_id,expected", REFERENCE_VECTORS)
def test_generate_password_matches_reference(device_id, expected):
    assert generate_password(device_id) == expected


def test_generate_password_empty_device_id_returns_empty():
    assert generate_password("") == ""


def test_generate_password_contains_all_four_character_classes():
    password = generate_password("A3L-0001")
    assert len(password) >= 11
    assert any(ch.isdigit() for ch in password)
    assert any(ch.islower() for ch in password)
    assert any(ch.isupper() for ch in password)
    assert any(not ch.isalnum() for ch in password)


def test_password_service_caches_per_device():
    service = PasswordService()
    first = service.get_password("H16-00-0001")
    assert first == REFERENCE_VECTORS[0][1]
    assert service.cached_device_ids() == ["H16-00-0001"]

    other = service.get_password("D16-00-0001")
    assert other != first  # 换设备不会串味
    assert sorted(service.cached_device_ids()) == ["D16-00-0001", "H16-00-0001"]

    service.clear_cache("H16-00-0001")
    assert service.cached_device_ids() == ["D16-00-0001"]
    service.clear_cache()
    assert service.cached_device_ids() == []


def test_password_service_is_thread_safe_and_consistent():
    service = PasswordService()
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(service.get_password("H16-00-0001")))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert set(results) == {REFERENCE_VECTORS[0][1]}
    assert service.cached_device_ids() == ["H16-00-0001"]


def test_tool_service_get_password_uses_python_engine():
    assert ToolService.get_password("H16-00-0001") == REFERENCE_VECTORS[0][1]
    assert ToolService.get_password("") == ""


@pytest.mark.skipif(
    sys.platform != "win32" or not os.path.exists(_HPASSWORD_EXE),
    reason="HPassword.exe 为 Windows 可执行文件，非 Windows 或无该二进制时跳过",
)
def test_engine_matches_hpassword_exe_live():
    """直接与 HPassword.exe 输出比对（逐字节等价）。"""
    for device_id, _ in REFERENCE_VECTORS:
        try:
            stdout = subprocess.run(
                [_HPASSWORD_EXE, device_id], capture_output=True, text=True,
                timeout=30, check=False,
            ).stdout.strip()
        except OSError as exc:  # 例如非 Windows 环境无法执行 PE
            pytest.skip(f"无法执行 HPassword.exe: {exc}")
        assert generate_password(device_id) == stdout, device_id
