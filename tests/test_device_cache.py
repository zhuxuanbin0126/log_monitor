# -*- coding: utf-8 -*-

"""设备信息缓存：时间字段、旧格式兼容、7 天过期清理的边界回归。"""

import json
import os
import time
from datetime import datetime, timedelta

import pytest

from service import device_cache


def _iso(days_ago: float) -> str:
    return (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat(
        timespec="seconds")


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    """把缓存文件与模块内存状态隔离到临时目录。"""
    path = tmp_path / "output" / "device_info_cache.json"
    monkeypatch.setattr(device_cache, "_cache_path", lambda: str(path))
    monkeypatch.setattr(device_cache, "_ENTRIES", {})
    monkeypatch.setattr(device_cache, "_LOADED", False)
    monkeypatch.setattr(device_cache, "_LAST_FLUSH", 0.0)
    return path


def _write(path, devices, version=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": version, "devices": devices}, handle, ensure_ascii=False)
    return path


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_put_cached_writes_both_timestamps(cache_file):
    device_cache.put_cached("H16-26-A0419", "192.168.81.94",
                            {"mac_address": "AA:BB", "device_name": "屏1"})
    device_cache.flush()
    first = _read(cache_file)["devices"]["H16-26-A0419"]
    assert first["added_at"] and first["last_seen_at"]
    assert "saved_at" not in first
    # ISO 8601 且带时区
    assert datetime.fromisoformat(first["added_at"]).tzinfo is not None
    assert datetime.fromisoformat(first["last_seen_at"]).tzinfo is not None

    time.sleep(0.05)
    device_cache.put_cached("H16-26-A0419", "192.168.81.94", {"device_name": "屏1-新"})
    device_cache.flush()
    second = _read(cache_file)["devices"]["H16-26-A0419"]
    assert second["added_at"] == first["added_at"]        # 首次写入时间不变
    assert second["last_seen_at"] >= first["last_seen_at"]  # 每次成功回写都推进
    assert second["device_name"] == "屏1-新"
    assert _read(cache_file)["version"] == device_cache.CACHE_VERSION


def test_legacy_record_without_timestamps_is_readable(cache_file):
    _write(cache_file, {
        "H16-26-A0001": {"ip": "192.168.1.10", "mac_address": "AA:BB",
                         "saved_at": time.time() - 3600},
        "H16-26-A0002": {"ip": "192.168.1.11", "mac_address": "CC:DD"},
    }, version=1)

    assert device_cache.get_cached("H16-26-A0001", "192.168.1.10")["mac_address"] == "AA:BB"
    # 完全没有时间字段：按文件 mtime 保守回填，不报错、可命中
    assert device_cache.get_cached("H16-26-A0002", "192.168.1.11")["mac_address"] == "CC:DD"


def test_purge_boundary_six_days_kept_eight_days_removed(cache_file):
    _write(cache_file, {
        "A-KEEP": {"ip": "10.0.0.1", "mac_address": "AA", "added_at": _iso(30),
                   "last_seen_at": _iso(6)},
        "A-DROP": {"ip": "10.0.0.2", "mac_address": "BB", "added_at": _iso(30),
                   "last_seen_at": _iso(8)},
    })

    assert device_cache.purge_stale() == 1
    remaining = _read(cache_file)["devices"]
    assert list(remaining) == ["A-KEEP"]
    # 读 TTL 与清理同口径：6 天仍命中，8 天已过期
    assert device_cache.get_cached("A-KEEP", "10.0.0.1") is not None
    assert device_cache.get_cached("A-DROP", "10.0.0.2") is None


def test_purge_all_expired_leaves_valid_empty_file(cache_file):
    _write(cache_file, {
        "A-ONE": {"ip": "10.0.0.1", "mac_address": "AA", "last_seen_at": _iso(8)},
        "A-TWO": {"ip": "10.0.0.2", "mac_address": "BB", "last_seen_at": _iso(400)},
    })

    assert device_cache.purge_stale() == 2
    data = _read(cache_file)                  # 结构仍然合法
    assert data["version"] == device_cache.CACHE_VERSION
    assert data["devices"] == {}


def test_purge_without_stale_does_not_write(cache_file):
    _write(cache_file, {
        "A-FRESH": {"ip": "10.0.0.1", "mac_address": "AA", "last_seen_at": _iso(1)},
    })
    before_bytes = cache_file.read_bytes()
    before_mtime = os.path.getmtime(cache_file)

    assert device_cache.purge_stale() == 0
    assert cache_file.read_bytes() == before_bytes
    assert os.path.getmtime(cache_file) == before_mtime
