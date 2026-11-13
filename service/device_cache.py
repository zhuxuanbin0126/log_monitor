# -*- coding: utf-8 -*-

"""设备富信息本地缓存（按 device_id 命中）。

目的：设备在老化/测试现场是**同一批常驻设备**，每次刷新的 MAC、设备名、版本、
ADB 状态几乎不变。把上一次真实取到的结果落到本地，刷新时先秒出缓存、再由后台
真实查询校正，避免"表格一排『查询中…』等十几秒"。

安全边界：
- 只缓存**展示字段**，不缓存设备密码（密码由 device_id 确定性计算）；
- 缓存带 TTL，且只在 ``ip`` 一致时命中（换机器/换网段视为不同设备）；
- 命中只是"先显示"，真实查询结果到达后仍会覆盖并回写缓存；
- 任何读写异常都静默降级为"无缓存"，不影响刷新主流程。

时间语义（v2）：
- ``added_at``：该设备**首次**写入缓存的时间（后续更新不变）；
- ``last_seen_at``：最近一次**真实查询成功**的时间（每次成功回写都刷新）。
- 两者均为带时区的 ISO 8601 本地时间（如 ``2026-11-13T20:30:00+08:00``）。
- **读 TTL 与启动清理共用 ``CACHE_TTL_SECONDS``（7 天）且都以 ``last_seen_at`` 为基准**：
  读 TTL 只决定"这次是否命中"，启动清理只删除盘上"7 天未成功查询"的记录，
  两者不重复、不冲突；只有真实查询成功才会推进 ``last_seen_at``，
  所以不会把仍在使用的有效缓存清成「查询中」。
"""

import json
import os
import threading
import time
from datetime import datetime

from .device_utils import app_root
from .logging_service import get_logger

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 3600
"""缓存有效期（秒）：读命中判定与启动清理共用同一阈值（以 last_seen_at 为准）。"""

CACHE_FILE_NAME = os.path.join("output", "device_info_cache.json")

CACHE_VERSION = 2
"""文件结构版本：v2 起每条记录带 added_at / last_seen_at（v1 可读，读取时补时间）。"""

_CACHE_FIELDS = (
    "mac_address", "device_name", "system_type",
    "ota_version", "main_version", "adb_status", "adb_usb_status",
)

_LOCK = threading.RLock()
_ENTRIES = {}
_LOADED = False
_LAST_FLUSH = 0.0
_FLUSH_INTERVAL = 2.0


def _cache_path() -> str:
    return os.path.join(app_root(), CACHE_FILE_NAME)


def _now_iso() -> str:
    """带时区的 ISO 8601 本地时间（秒级），全文件统一格式。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_time(value):
    """把缓存里的时间值解析为 epoch 秒；无法解析返回 ``None``。

    兼容：ISO 8601 字符串（含 ``Z`` 结尾）、旧格式的 ``saved_at`` 数字时间戳。
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:                 # 无时区按本地时间解释
        parsed = parsed.astimezone()
    return parsed.timestamp()


def _entry_last_seen(entry):
    """``last_seen_at`` → epoch；旧格式回退 ``saved_at``；都没有则 ``None``。"""
    epoch = _parse_time(entry.get("last_seen_at"))
    if epoch is None:
        epoch = _parse_time(entry.get("saved_at"))
    return epoch


def _ensure_loaded() -> None:
    """惰性加载缓存文件；旧格式记录就地补齐时间字段（不写盘）。"""
    global _LOADED
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True
        path = _cache_path()
        try:
            file_mtime = os.path.getmtime(path)
        except OSError:
            file_mtime = time.time()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            entries = data.get("devices", data) if isinstance(data, dict) else None
            if not isinstance(entries, dict):
                return
            for raw_key, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                key = str(raw_key).upper()
                normalized = dict(entry)
                # 旧格式（无时间字段）：用文件 mtime 作保守回填。
                # 理由：本模块每次成功回写都会 flush（2s 节流），文件 mtime 即
                # "最近一次成功取数"的下界；既不会把旧记录当成"刚刚上线"而长期保留，
                # 也不会因为升级后首次读取就被全部清空。
                seen = _entry_last_seen(normalized)
                if seen is None:
                    seen = file_mtime
                if _parse_time(normalized.get("added_at")) is None:
                    normalized["added_at"] = datetime.fromtimestamp(
                        seen).astimezone().isoformat(timespec="seconds")
                if _parse_time(normalized.get("last_seen_at")) is None:
                    normalized["last_seen_at"] = datetime.fromtimestamp(
                        seen).astimezone().isoformat(timespec="seconds")
                _ENTRIES[key] = normalized
            logger.info("[缓存] 已加载设备信息缓存 %d 条: %s", len(_ENTRIES), path)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.info("[缓存] 读取缓存失败（已忽略）: %s", exc)


def get_cached(device_id: str, ip: str, ttl: float = CACHE_TTL_SECONDS):
    """命中则返回展示字段字典，否则 ``None``（TTL 以 ``last_seen_at`` 为基准）。"""
    if not device_id:
        return None
    _ensure_loaded()
    key = device_id.upper()
    entry = _ENTRIES.get(key)
    if not entry:
        return None
    if ip and entry.get("ip") and entry.get("ip") != ip:
        return None
    if ttl:
        last_seen = _entry_last_seen(entry)
        if last_seen is None or time.time() - last_seen > ttl:
            return None
    info = {field: entry.get(field) for field in _CACHE_FIELDS if entry.get(field) is not None}
    return info or None


def put_cached(device_id: str, ip: str, info: dict) -> None:
    """写入/合并一条缓存（只保留展示字段）。

    - 首次写入生成 ``added_at``；
    - 每次写入都推进 ``last_seen_at``（调用方保证只在真实查询成功后调用）。
    """
    global _LAST_FLUSH
    if not device_id or not info:
        return
    payload = {field: info[field] for field in _CACHE_FIELDS if info.get(field) not in (None, "")}
    if not payload:
        return
    now_iso = _now_iso()
    with _LOCK:
        _ensure_loaded()
        key = device_id.upper()
        entry = dict(_ENTRIES.get(key) or {})
        entry.update(payload)
        entry["ip"] = ip or entry.get("ip", "")
        entry.setdefault("added_at", now_iso)
        entry["last_seen_at"] = now_iso
        entry.pop("saved_at", None)           # 旧字段由 last_seen_at 取代
        _ENTRIES[key] = entry
        now = time.time()
        if now - _LAST_FLUSH >= _FLUSH_INTERVAL:
            _LAST_FLUSH = now
            flush()


def flush() -> None:
    """原子写盘（先写临时文件再替换），失败只记日志。"""
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with _LOCK:
            snapshot = {"version": CACHE_VERSION, "devices": dict(_ENTRIES)}
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except (OSError, ValueError) as exc:
        logger.info("[缓存] 写缓存失败（已忽略）: %s", exc)


def clear_cache() -> None:
    """清空内存与磁盘缓存（供「清理历史数据」等场景调用）。"""
    global _LAST_FLUSH
    with _LOCK:
        _ENTRIES.clear()
        _LAST_FLUSH = 0.0
    flush()


def purge_stale(max_age: float = CACHE_TTL_SECONDS) -> int:
    """删除 ``last_seen_at`` 距今超过 ``max_age`` 的记录（启动后台清理用）。

    Returns:
        删除条数；0 表示无记录可清（**不写盘**）。
    """
    _ensure_loaded()
    now = time.time()
    with _LOCK:
        stale = []
        for key, entry in _ENTRIES.items():
            last_seen = _entry_last_seen(entry)
            if last_seen is None or now - last_seen > max_age:
                stale.append(key)
        if not stale:
            return 0
        for key in stale:
            _ENTRIES.pop(key, None)
    flush()
    return len(stale)


def purge_stale_async() -> None:
    """守护线程里跑 :func:`purge_stale`：不阻塞启动、异常静默降级。"""
    def _worker():
        try:
            removed = purge_stale()
            logger.info("[缓存] 启动清理完成：删除过期设备记录 %d 条", removed)
        except Exception as exc:  # pylint: disable=broad-except
            logger.info("[缓存] 启动清理失败（已忽略）: %s", exc)

    threading.Thread(target=_worker, name="cache-purge", daemon=True).start()


def stats() -> dict:
    """缓存规模（测试/日志用）。"""
    with _LOCK:
        _ensure_loaded()
        return {"entries": len(_ENTRIES), "path": _cache_path()}
