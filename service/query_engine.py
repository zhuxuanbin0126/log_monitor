#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""「查询全部信息」执行引擎（协议优先，逐项降级 adb/SSH）。

点一次「查询全部信息」，用**最少的协议往返**取全一台设备下列信息：

============================  ==================================================
信息                          取数通道
============================  ==================================================
设备时间 / 与系统时间差        协议一次 Get（``Time.dateTime``）
运行时长 / 启动时间            同一 Get（``DeviceInfo.uptime``）
播放器启动次数                 加密 Command.exec（批量命令之一）
设备开关机次数                 加密 Command.exec（批量命令之一）
网络开关机次数                 加密 Command.exec（批量命令之一）
============================  ==================================================

设计要点：

1. **阶段一（时间 / 运行时长）**：``Time`` 与 ``DeviceInfo`` 在协议层本就一次 Get
   同时返回（见 :mod:`service.protocol.query_service`），且带短时缓存，故「取设备时间」
   与「取运行时长」**共用一次往返**，不再各发一次。
2. **阶段二（三项计数）**：把 3 条取数命令用**分隔标记**串成**一条** shell 命令，
   经加密 ``exec`` 一次下发，一次往返取回三个值（旧实现为 3 次往返）。
3. **逐项降级**：协议不可用或某项取不到时，**按项**回落既有 adb/SSH 通道
   （``DeviceMonitorService.get_start_count`` / ``sum_switch_count``），
   结果口径与旧实现完全一致。

本模块只做「编排 + 纯函数解析」，不持有设备状态，便于离线单测。
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from config import get_device_remote_path
from service.logging_service import get_logger
from service.protocol.command_query import exec_if_supported, is_protocol_supported

logger = get_logger(__name__)

COUNT_SPLIT_MARKER = "___LM_COUNT_SPLIT___"
"""批量计数命令的分段标记（每段前 ``echo`` 一次，供解析切分）"""

START_COUNT_CMD = "getprop huidu.player.start_count"
"""播放器启动次数的取数命令（与旧 adb/SSH 通道一致）"""

NO_START_COUNT_TYPES = frozenset({"C08L", "C16L", "D16"})
"""不支持取播放器启动次数的型号（与 ``DeviceMonitorService`` 口径一致）"""

_INT_RE = re.compile(r"\d+")


def build_counts_command(start_count_cmd: str, switch_path: str,
                         network_path: str) -> str:
    """把三条取数命令串成一条（用 :data:`COUNT_SPLIT_MARKER` 分段）。

    ``start_count_cmd`` 为空时用 ``true`` 占位（该型号不支持启动次数），
    仍保留空段以维持四段结构，便于统一解析。
    """
    marker = f"echo {COUNT_SPLIT_MARKER}"
    start = start_count_cmd.strip() or "true"
    return (f"{marker}; {start}; {marker}; "
            f"wc -l {switch_path} 2>/dev/null; {marker}; "
            f"wc -l {network_path} 2>/dev/null")


def _first_int(text: str) -> Optional[int]:
    """取文本中首个整数；无则 None。"""
    match = _INT_RE.search(text or "")
    return int(match.group()) if match else None


def _count_from_wc(text: str) -> Optional[int]:
    """``wc -l`` 输出 → 计数（行数 − 1，首行为表头）；取不到返回 None（文件缺失）。"""
    lines = _first_int(text)
    if lines is None:
        return None
    return max(0, lines - 1)


def parse_counts_output(text: str) -> Dict[str, Any]:
    """把批量 exec 输出解析为三个计数值（缺失项为 ``None``）。

    段结构：``["", start_count, switch_wc, network_wc]``（首个标记前为空段）。
    段数不足时三项全部视为缺失，交由调用方逐项降级。
    """
    parts = (text or "").split(COUNT_SPLIT_MARKER)
    if len(parts) < 4:
        return {"start_count": None, "switch_count": None, "network_count": None}
    start_raw = parts[1].strip()
    return {
        "start_count": start_raw or None,
        "switch_count": _count_from_wc(parts[2]),
        "network_count": _count_from_wc(parts[3]),
    }


def query_counts_batched(ip: str, switch_path: str, network_path: str, *,
                         start_count_cmd: str = START_COUNT_CMD,
                         **kwargs) -> Optional[Dict[str, Any]]:
    """一次加密 ``exec`` 批量取「启动次数 + 开关机次数 + 网络开关机次数」。

    Returns:
        解析后的计数 dict（值可能为 ``None``）；协议不可用/无有效回复返回 ``None``
        （调用方据此逐项降级 adb/SSH）。
    """
    if not is_protocol_supported(ip):
        return None
    command = build_counts_command(start_count_cmd, switch_path, network_path)
    result = exec_if_supported(ip, command, **kwargs)
    if result is None:
        logger.debug("设备 %s 批量计数 exec 无回复，逐项降级", ip)
        return None
    return parse_counts_output(result.text())


@dataclass
class AllQueryOutcome:
    """「查询全部信息」的编排结果。"""

    results: Dict[str, Any] = field(default_factory=dict)
    switch_time: Optional[int] = None
    network_time: Optional[int] = None
    switch_success: bool = False
    protocol_used: bool = False
    """阶段二是否成功走协议批量通道（供日志/断言用）"""


def query_all(monitor_service, device_id: str, ip: str, password: str,
              system_type: str) -> AllQueryOutcome:
    """执行「查询全部信息」并返回结果编排。

    Args:
        monitor_service: :class:`business.device_monitor_service.DeviceMonitorService` 实例
            （提供 ``get_device_time_info`` / ``get_uptime_info`` 等取数与回落方法）
        device_id / ip / password / system_type: 设备标识与连接信息

    Returns:
        :class:`AllQueryOutcome`：``results`` 含 ``device_time`` / ``boot_time`` /
        ``start_count`` / ``sum_switch``（键与旧 dispatcher 完全一致）；
        ``switch_time`` / ``network_time`` 供调用方写开关机 CSV。
    """
    outcome = AllQueryOutcome()
    started = time.monotonic()

    # ---- 阶段一：设备时间 + 运行时长 / 启动时间（协议一次 Get，内部缓存） ----
    logger.info("[查询全部] %s 阶段一：取设备时间与运行时长（协议一次 Get）", device_id)
    phase1 = time.monotonic()
    formatted_remote_time, time_diff = monitor_service.get_device_time_info(
        ip, password, device_id)
    outcome.results["device_time"] = {
        "formatted_remote_time": formatted_remote_time,
        "time_diff": time_diff,
    }
    outcome.results["boot_time"] = monitor_service.get_uptime_info(ip, password, device_id)
    boot_info = outcome.results["boot_time"]
    logger.info(
        "[查询全部] %s 阶段一完成（%.2fs）：设备时间=%s 时间差=%ss 运行时长=%s 启动时间=%s",
        device_id, time.monotonic() - phase1, formatted_remote_time, time_diff,
        boot_info.get("formatted_uptime", "N/A") if isinstance(boot_info, dict) else "N/A",
        boot_info.get("boot_time", "N/A") if isinstance(boot_info, dict) else "N/A",
    )

    # ---- 阶段二：三项计数（协议一次批量 exec，缺失项逐项降级） ----
    path = get_device_remote_path(system_type)
    switch_path = f"{path}/swich_counter.csv"
    network_path = f"{path}/network_counter.csv"

    dev_type_prefix = device_id.split("-")[0] if "-" in device_id else device_id
    want_start_count = dev_type_prefix not in NO_START_COUNT_TYPES
    start_cmd = START_COUNT_CMD if want_start_count else ""

    logger.info("[查询全部] %s 阶段二：批量取 启动次数/开关机次数/网络开关机次数", device_id)
    phase2 = time.monotonic()
    counts = query_counts_batched(
        ip, switch_path, network_path, start_count_cmd=start_cmd)
    if counts is not None:
        outcome.protocol_used = True
    counts = counts or {}

    # 播放器启动次数
    if want_start_count:
        start_count = counts.get("start_count")
        if start_count is None:
            # 该设备不支持启动次数查询，或批量通道没拿到 → 单项降级
            logger.info("[查询全部] %s 启动次数协议未取到，单项降级 adb/SSH", device_id)
            start_count = monitor_service.get_start_count(ip, password, device_id)
        outcome.results["start_count"] = start_count
    else:
        outcome.results["start_count"] = "无法获取"

    # 设备开关机次数 / 网络开关机次数
    switch_time = counts.get("switch_count")
    network_time = counts.get("network_count")
    if switch_time is None and network_time is None:
        logger.info("[查询全部] %s 开关机次数协议未取到，降级 adb/SSH", device_id)
        switch_time, network_time, success, error = monitor_service.sum_switch_count(
            ip, password, device_id, path)
        outcome.switch_time = switch_time
        outcome.network_time = network_time
        outcome.switch_success = success
        if not success:
            outcome.results["sum_switch"] = error
            logger.warning("[查询全部] %s 阶段二失败（%.2fs）：%s",
                           device_id, time.monotonic() - phase2, error)
            return outcome
    else:
        switch_time = switch_time or 0
        network_time = network_time or 0
        outcome.switch_time = switch_time
        outcome.network_time = network_time
        outcome.switch_success = True

    outcome.results["sum_switch"] = (
        f"{device_id} 当前开关机次数为：{outcome.switch_time} "
        f"网络开关机次数为：{outcome.network_time}"
    )
    logger.info(
        "[查询全部] %s 完成（阶段二 %.2fs，合计 %.2fs，批量通道=%s）："
        "启动次数=%s 开关机次数=%s 网络开关机次数=%s",
        device_id, time.monotonic() - phase2, time.monotonic() - started,
        "协议" if outcome.protocol_used else "adb/SSH",
        outcome.results.get("start_count"), outcome.switch_time, outcome.network_time,
    )
    return outcome
