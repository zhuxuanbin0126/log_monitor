#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer Command 查询（``exec`` 加密通道）。

设备侧真值源（``HCommand.java`` / ``CommandTask``）：``exec`` 与 ``SetDeviceID`` 属
**强制加密**命令，明文 0x2103 会被以 ``UNSAFE_MESSAGE`` 拒绝，必须走
0x2201/0x2202 交换盐值 + 0x2105/0x2106 加密收发（见 :mod:`service.protocol.client`）。

报文形态::

    {"ask": {"method": "exec",
             "params": {"input": "<shell 命令>", "async": false, "start": "su"}},
     "module": "Command", "tag": "exec", ...}

回复形态::

    {"module": "Command",
     "reply": {"method": "exec", "result": "kSuccess",
               "data": {"input": "<命令>", "exitCode": 0, "output": "...", "error": ""}}}

``output`` 即 shell 命令的标准输出，供上层解析取值并反馈到日志/结果面板。
"""

import json
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_EXEC_START, PROTOCOL_PORT,
    PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

from .client import send_request
from .envelope import DEFAULT_VERSION, build_envelope
from .frame import TYPE_REQUEST, build_frame, parse_multi_frame_response
from .query_service import get_device_status

logger = get_logger(__name__)

EXEC_METHOD = "exec"
"""执行 shell 命令的方法名"""

ENCRYPTED_METHODS = frozenset({"exec", "SetDeviceID"})
"""设备强制加密的 Command 方法名（唯一判定点）"""


@dataclass
class ExecResult:
    """Command.exec 的执行结果。"""

    input: Optional[str] = None
    exit_code: int = -1
    output: str = ""
    error: Optional[str] = None

    def text(self) -> str:
        """命令标准输出（去首尾空白）。"""
        return (self.output or "").strip()


def build_command_message(method: str, params: dict, *, tag: Optional[str] = None,
                          version: int = DEFAULT_VERSION) -> dict:
    """构造 Command 模块请求消息（统一信封）。"""
    return build_envelope("Command", {"method": method, "params": params},
                          tag=tag, version=version)


def build_exec_message(command: str, *, start: str = PROTOCOL_EXEC_START,
                       async_run: bool = False, tag: str = EXEC_METHOD,
                       version: int = DEFAULT_VERSION) -> dict:
    """构造 ``Command.exec`` 请求消息。

    Args:
        command: 要执行的 shell 命令
        start: ``su``（以 su 执行，默认）/ ``sh``（以 sh 执行）
        async_run: 是否异步执行（查值场景必须同步，默认 False）
        tag: 业务标签（默认与 method 同名）
    """
    return build_command_message(
        EXEC_METHOD,
        {"input": command, "async": bool(async_run), "start": start},
        tag=tag, version=version,
    )


def message_needs_encryption(message: Any) -> bool:
    """该报文是否必须走加密通道（仅 ``module == "Command"`` 时成立）。"""
    if not isinstance(message, dict):
        return False
    if message.get("module") != "Command":
        return False
    ask = message.get("ask")
    method = ask.get("method") if isinstance(ask, dict) else None
    return method in ENCRYPTED_METHODS


def _to_int(value: Any) -> int:
    """宽松取整（int/float/数字字符串）；失败返回 -1。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return -1
    return -1


def extract_exec_result(parsed: Optional[dict]) -> Optional[ExecResult]:
    """从 Command.exec 回复中提取 ``data``；结构不符或非成功时返回 None。"""
    if not isinstance(parsed, dict) or parsed.get("module") != "Command":
        return None
    reply = parsed.get("reply")
    if not isinstance(reply, dict):
        return None
    if reply.get("result") != "kSuccess":
        logger.debug("Command.exec 非成功应答: result=%s errorMsg=%s",
                     reply.get("result"), reply.get("errorMsg"))
        return None
    data = reply.get("data")
    if not isinstance(data, dict):
        return None
    return ExecResult(
        input=data.get("input"),
        exit_code=_to_int(data.get("exitCode")),
        output=data.get("output") or "",
        error=data.get("error"),
    )


def exec_command(host: str, command: str, *, start: str = PROTOCOL_EXEC_START,
                 async_run: bool = False, port: int = PROTOCOL_PORT,
                 connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                 recv_timeout: float = PROTOCOL_RECV_TIMEOUT,
                 pc_salt: Optional[bytes] = None) -> Optional[ExecResult]:
    """经加密 Command.exec 在设备上执行 shell 命令；失败/不可达返回 None。"""
    message = build_exec_message(command, start=start, async_run=async_run)
    encrypt = message_needs_encryption(message)
    frame = build_frame(message, TYPE_REQUEST)
    raw = send_request(host, frame, port=port, connect_timeout=connect_timeout,
                       recv_timeout=recv_timeout, encrypt=encrypt, pc_salt=pc_salt)
    if not raw:
        return None
    parsed = parse_multi_frame_response(raw)
    if parsed is None:
        logger.debug("Command.exec 响应无法解析（%s 字节）", len(raw))
        return None
    return extract_exec_result(parsed)


def is_protocol_supported(host: str) -> bool:
    """设备当前是否支持 MagicPlayer 协议（复用查询服务的支持面缓存）。"""
    return get_device_status(host) is not None


def exec_if_supported(host: str, command: str, **kwargs) -> Optional[ExecResult]:
    """仅对「已确认支持协议」的设备执行加密命令，避免对不支持设备白等建连超时。"""
    if not is_protocol_supported(host):
        return None
    return exec_command(host, command, **kwargs)


def exec_command_triple(host: str, command: str, *, working_dir: Optional[str] = None,
                        start: str = PROTOCOL_EXEC_START, async_run: bool = False,
                        port: int = PROTOCOL_PORT,
                        connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                        recv_timeout: float = PROTOCOL_RECV_TIMEOUT) -> Optional[Tuple[str, str, int]]:
    """执行命令并返回 ``(stdout, stderr, returncode)``；协议通道不可用返回 None。

    供既有的「三返回值」调用点（``ToolService`` 的命令通道、``service.transports``）
    直接复用，使 Android 的 shell 命令走**加密 Command.exec**，无需拉起 adb/SSH。

    Returns:
        ``(stdout, stderr, returncode)``；``None`` 表示**通道不可用**
        （不可达/不支持加密通道），调用方应回落 adb/SSH。
        注意：命令本身返回非 0 退出码时**不是** None，而是带着真实退出码的三元组，
        调用方不应再改走别的通道重跑（避免副作用命令被重复执行）。
    """
    script = f'cd {working_dir} && {command}' if working_dir else command
    result = exec_command(host, script, start=start, async_run=async_run, port=port,
                          connect_timeout=connect_timeout, recv_timeout=recv_timeout)
    if result is None:
        return None
    if result.exit_code == 0:
        return result.text(), "", 0
    error = (result.error or "").strip() or f"exec 退出码 {result.exit_code}"
    return result.text(), error, result.exit_code


def line_count_from_output(result: Optional[ExecResult]) -> Optional[int]:
    """把 ``wc -l`` 类命令的输出解析为行数（首个整数）；失败返回 None。"""
    if result is None or result.exit_code != 0:
        return None
    text = result.text()
    if not text:
        return None
    first = text.split()[0] if text.split() else ""
    try:
        return int(first)
    except (ValueError, IndexError):
        return None


def parse_json_output(result: Optional[ExecResult]) -> Optional[Any]:
    """把 exec 输出解析为 JSON（设备侧脚本常回 JSON）；失败返回 None。"""
    text = result.text() if result else ""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
