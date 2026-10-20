#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""历史数据清理：**清理规划**（可预览、可审计）+ **执行**（逐项结果）。

清理范围（scope，可多选）::

    monitor_data  监控基准数据：device_monitoring_data.json / device_error.txt / device_errors.txt / ./monitor_data
    logs          运行日志：LOG_DIR 下与型号匹配的目录（**散落文件永不清理**，含 app.log）
    screenshot    截图：output/screenshot 与 ./screenshot 下匹配型号的设备目录
    switch_log    开关机日志：output/switch_log 与 ./switch_log 下匹配型号的设备目录 + 会话级 CSV
    excel         Excel 报表：output/excel 下 ``{型号}_*.xlsx``

型号匹配：``dev_type`` 为聚合类型（如 ``A-B-C-D-H``）时按 ``^(A|B|C|D|H)`` 前缀匹配；
``include_all_types=True`` 时不做型号过滤（清理全部型号的历史）。

与旧实现的关键差别：**只删 ``EXCEL_DIR`` 内与当前型号匹配的报表**（旧实现会删除
工作目录下所有 ``*.xlsx``）；并且**先出规划再执行**，删除动作可预览、可审计。

无 Qt 依赖，便于离线单测。
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Pattern, Sequence

from config import (
    DEVICE_DATA_FILE, ERROR_LOG_FILE, EXCEL_DIR, LOG_DIR, SCREENSHOT_DIR,
    SWITCH_LOG_DIR,
)
from service.logging_service import get_logger

logger = get_logger(__name__)

SCOPE_MONITOR_DATA = "monitor_data"
SCOPE_LOGS = "logs"
SCOPE_SCREENSHOT = "screenshot"
SCOPE_SWITCH_LOG = "switch_log"
SCOPE_EXCEL = "excel"

SCOPE_LABELS: Dict[str, str] = {
    SCOPE_MONITOR_DATA: "监控基准数据",
    SCOPE_LOGS: "运行日志",
    SCOPE_SCREENSHOT: "截图",
    SCOPE_SWITCH_LOG: "开关机日志",
    SCOPE_EXCEL: "Excel 报表",
}
ALL_SCOPES: Sequence[str] = tuple(SCOPE_LABELS)

DEFAULT_SCOPES: Sequence[str] = (SCOPE_MONITOR_DATA,)
"""默认只勾「监控基准数据」（设备范围默认「仅当前设备类型」）"""

PREVIEW_LIMIT = 5
"""确认框每个条目最多列出 5 个文件，超出显示「… 其余 N 个文件略」"""


@dataclass
class CleanItem:
    """一个待清理条目（目录或单个文件）。"""

    scope: str
    label: str
    path: str
    is_dir: bool
    files: List[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        """该条目包含的文件数（目录为其下全部文件；文件项为 1）。"""
        return len(self.files)


@dataclass
class CleanResult:
    """单个条目的清理结果（供 UI 逐项回报）。"""

    scope: str
    label: str
    path: str
    removed: int = 0
    failed: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.failed


def prefix_pattern(dev_type: str) -> Optional[Pattern[str]]:
    """按设备类型生成型号前缀正则；``dev_type`` 为空返回 None（不过滤）。"""
    parts = [part for part in str(dev_type or "").split("-") if part]
    if not parts:
        return None
    return re.compile("^(" + "|".join(re.escape(part) for part in parts) + ")")


def _abs(*parts: str) -> str:
    return os.path.abspath(os.path.join(*parts))


def _list_files(path: str) -> List[str]:
    """目录 → 其下全部文件的绝对路径（递归）；单个文件 → ``[path]``；不存在 → ``[]``。"""
    if not path or not os.path.exists(path):
        return []
    if os.path.isfile(path):
        return [path]
    collected: List[str] = []
    for root, _dirs, names in os.walk(path):
        collected.extend(os.path.join(root, name) for name in names)
    return collected


def _matches(regex: Optional[Pattern[str]], name: str) -> bool:
    return regex is None or bool(regex.match(name))


# ---------------------------------------------------------------- 各范围规划

def plan_monitor_data(_dev_type: str = "", _all_types: bool = False) -> List[CleanItem]:
    """监控基准数据：数据文件与错误日志（与型号无关，均为“当前工程的历史”）。"""
    items: List[CleanItem] = []
    for name in (DEVICE_DATA_FILE, ERROR_LOG_FILE, "device_errors.txt"):
        path = _abs(name)
        if os.path.isfile(path):
            items.append(CleanItem(SCOPE_MONITOR_DATA, f"{name}", path, False, [path]))
    for folder in ("monitor_data",):
        path = _abs(folder)
        if os.path.isdir(path):
            items.append(CleanItem(SCOPE_MONITOR_DATA, f"{folder}/", path, True,
                                   _list_files(path)))
    return items


APP_LOG_PREFIX = "app.log"
"""程序自身运行日志（轮转文件）。

它被当前进程**持续占用**：删不掉（Windows 会报「文件正在被使用」），
而且清理它等于抹掉本次排查线索 —— 因此「运行日志」范围**永不包含**它。
"""


def plan_logs(dev_type: str, include_all_types: bool = False) -> List[CleanItem]:
    """运行日志：``LOG_DIR`` 下与型号匹配的**日志目录**。

    **只清目录、不碰 ``LOG_DIR`` 下的散落文件**：
    ``app.log`` 及其轮转副本被当前进程持续占用（Windows 报「文件正在被使用」），
    删不掉也不该删；该目录下其它散落文件同样一律不列入、不清理。
    型号日志目录（如 ``output/logs/H16_AgingTest/``）照常参与清理。
    """
    regex = None if include_all_types else prefix_pattern(dev_type)
    if not os.path.isdir(LOG_DIR):
        return []
    items: List[CleanItem] = []
    for name in sorted(os.listdir(LOG_DIR)):
        full = os.path.join(LOG_DIR, name)
        if name.lower().startswith(APP_LOG_PREFIX):
            continue                      # 程序自身运行日志：永不清理
        if not os.path.isdir(full):
            continue                      # 该目录下的散落文件：不执行、不清理
        if not _matches(regex, name):
            continue
        items.append(CleanItem(SCOPE_LOGS, f"{name}/", full, True, _list_files(full)))
    return items


def plan_screenshot(dev_type: str, include_all_types: bool = False) -> List[CleanItem]:
    """截图：``SCREENSHOT_DIR`` 与 ``./screenshot`` 下匹配型号的设备目录。"""
    regex = None if include_all_types else prefix_pattern(dev_type)
    items: List[CleanItem] = []
    for base in dict.fromkeys([SCREENSHOT_DIR, _abs("screenshot")]):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if not os.path.isdir(full) or not _matches(regex, name):
                continue
            items.append(CleanItem(SCOPE_SCREENSHOT, f"{name}/", full, True,
                                   _list_files(full)))
    return items


def plan_switch_log(dev_type: str, include_all_types: bool = False) -> List[CleanItem]:
    """开关机日志：型号匹配的设备目录 + 会话级 CSV（文件名是时间戳，无法按型号过滤）。"""
    regex = None if include_all_types else prefix_pattern(dev_type)
    items: List[CleanItem] = []
    for base in dict.fromkeys([SWITCH_LOG_DIR, _abs("switch_log")]):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                if not _matches(regex, name):
                    continue
                items.append(CleanItem(SCOPE_SWITCH_LOG, f"{name}/", full, True,
                                       _list_files(full)))
            elif os.path.isfile(full) and name.lower().endswith(".csv"):
                items.append(CleanItem(SCOPE_SWITCH_LOG, name, full, False, [full]))
    return items


def plan_excel(dev_type: str, include_all_types: bool = False) -> List[CleanItem]:
    """Excel 报表：**只扫 ``EXCEL_DIR``**，且仅匹配 ``{型号}_*.xlsx``。

    （旧实现会删除工作目录下所有 ``*.xlsx`` —— 会误删用户自己的表格文件。）
    """
    if not os.path.isdir(EXCEL_DIR):
        return []
    prefix = None if include_all_types else f"{dev_type}_"
    items: List[CleanItem] = []
    for name in sorted(os.listdir(EXCEL_DIR)):
        full = os.path.join(EXCEL_DIR, name)
        if not os.path.isfile(full) or not name.lower().endswith(".xlsx"):
            continue
        if prefix is not None and not name.startswith(prefix):
            continue
        items.append(CleanItem(SCOPE_EXCEL, name, full, False, [full]))
    return items


_PLANNERS: Dict[str, Callable[[str, bool], List[CleanItem]]] = {
    SCOPE_MONITOR_DATA: plan_monitor_data,
    SCOPE_LOGS: plan_logs,
    SCOPE_SCREENSHOT: plan_screenshot,
    SCOPE_SWITCH_LOG: plan_switch_log,
    SCOPE_EXCEL: plan_excel,
}


def build_plan(dev_type: str, scopes: Sequence[str],
               include_all_types: bool = False) -> List[CleanItem]:
    """按选中范围生成清理规划（顺序与 :data:`ALL_SCOPES` 一致，便于稳定预览）。"""
    ordered = [scope for scope in ALL_SCOPES if scope in set(scopes)]
    plan: List[CleanItem] = []
    for scope in ordered:
        planner = _PLANNERS.get(scope)
        if planner is None:
            logger.warning("未知清理范围，已跳过: %s", scope)
            continue
        plan.extend(planner(dev_type, include_all_types))
    return plan


def plan_summary(plan: Sequence[CleanItem]) -> Dict[str, int]:
    """规划汇总：``{'items': 条目数, 'files': 文件总数}``。"""
    return {"items": len(plan), "files": sum(item.file_count for item in plan)}


def format_plan_preview(plan: Sequence[CleanItem],
                        limit: int = PREVIEW_LIMIT) -> str:
    """生成确认框预览文本：确切路径 + 文件数 + 文件清单（超过 limit 只列前 limit 个）。"""
    if not plan:
        return "没有匹配到可清理的历史数据。"
    summary = plan_summary(plan)
    lines = [f"共 {summary['items']} 个条目、{summary['files']} 个文件待清理："]
    for item in plan:
        lines.append("")
        lines.append(f"● {SCOPE_LABELS.get(item.scope, item.scope)} · {item.label}")
        lines.append(f"  路径: {item.path}")
        lines.append(f"  文件数: {item.file_count}")
        if item.is_dir:
            for name in item.files[:limit]:
                lines.append(f"    - {name}")
            if item.file_count > limit:
                lines.append(f"    … 其余 {item.file_count - limit} 个文件略")
    return "\n".join(lines)


# ---------------------------------------------------------------- 执行

def _remove_item(item: CleanItem) -> CleanResult:
    """删除单个条目并返回可审计结果。"""
    result = CleanResult(item.scope, item.label, item.path)
    try:
        if item.is_dir:
            if os.path.isdir(item.path):
                shutil.rmtree(item.path)
            result.removed = item.file_count
        elif os.path.isfile(item.path):
            os.remove(item.path)
            result.removed = 1
        logger.info("[清理历史] %s → 删除 %s 个文件（%s）",
                    item.label, result.removed, item.path)
    except Exception as exc:  # pylint: disable=broad-except
        result.error = str(exc)
        result.failed = [item.path]
        logger.warning("[清理历史] %s 删除失败（%s）: %s", item.label, item.path, exc)
    return result


def execute_plan(plan: Sequence[CleanItem],
                 on_item: Optional[Callable[[CleanResult], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None
                 ) -> List[CleanResult]:
    """执行清理规划；每个条目完成后回调 ``on_item``（供 UI 逐项回报）。

    ``should_stop`` 为真时在**条目边界**停止（已删除的条目照常回报，
    未执行的条目留在规划里，汇总时可据此说明「已中断」）。
    """
    results: List[CleanResult] = []
    for item in plan:
        if should_stop is not None and should_stop():
            logger.info("[清理历史] 已请求中断：剩余 %s 个条目未执行",
                        len(plan) - len(results))
            break
        result = _remove_item(item)
        results.append(result)
        if on_item is not None:
            try:
                on_item(result)
            except Exception:  # pylint: disable=broad-except
                logger.exception("[清理历史] 逐项回调失败（不影响清理）")
    return results


def summarize_results(results: Sequence[CleanResult]) -> str:
    """执行结果汇总文案（可审计）。"""
    removed = sum(result.removed for result in results)
    failed = [result for result in results if not result.ok]
    text = f"清理完成：删除 {removed} 个文件（{len(results)} 个条目）"
    if failed:
        text += f"，失败 {len(failed)} 个条目："
        text += "; ".join(f"{item.label}({item.error or '部分文件失败'})"
                          for item in failed)
    return text
