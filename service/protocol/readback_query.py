#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer ``ReadBack`` 回读（当前只实现「屏幕截图」）。

截图走 **Socket 文件通道**（``fileTransferMode=2``），抓包/真机确认的链路::

    ReadBack{target:"ScreenShot", options:{"compress":"false"}, fileTransferMode:2}
      → 设备回 kSuccess{ScreenShot:"<md5>", fileTransferMode:2}（reply 只给 md5 引用）
      → 同一连接用 0x8001/0x8003/0x8005 回传**整屏 PNG**（实测 5.2MB / 4096×3200）

即文件实体不在 reply 里，而在同一 TCP 连接的文件帧里，必须由
:mod:`service.protocol.file_receive` 逐帧应答收齐。
"""

import hashlib
from typing import Any, Dict, Optional

from config import (
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_FILE_RECV_TIMEOUT, PROTOCOL_PORT,
    PROTOCOL_RECV_TIMEOUT, TRANSFER_MAX_ATTEMPTS,
)
from service.logging_service import get_logger

from .command_query import is_protocol_supported
from .envelope import DEFAULT_VERSION, build_envelope
from .file_receive import receive_file, reply_result
from .frame import TYPE_REQUEST, build_frame

logger = get_logger(__name__)

READBACK_TARGET_SCREENSHOT = "ScreenShot"
"""回读对象：屏幕截图"""

FILE_TRANSFER_MODE_SOCKET = 2
"""fileTransferMode：2 = Socket 文件上传（设备把文件推回同一连接）"""

SCREENSHOT_FILE_OPTIONS: Dict[str, Any] = {"compress": "false"}
"""截图文件通道的 options（抓包确认 ``compress=false`` 直接给整屏 PNG）"""


def build_readback_message(target: str, options: Optional[Dict[str, Any]] = None, *,
                           file_transfer_mode: Optional[int] = None,
                           version: int = DEFAULT_VERSION) -> Dict[str, Any]:
    """构造 ``ReadBack`` 请求消息（统一信封，补全 version/log）。"""
    ask: Dict[str, Any] = {"target": target}
    if options:
        ask["options"] = dict(options)
    if file_transfer_mode is not None:
        ask["fileTransferMode"] = int(file_transfer_mode)
    return build_envelope("ReadBack", ask, version=version)


def query_screenshot(host: str, *, port: int = PROTOCOL_PORT,
                     connect_timeout: float = PROTOCOL_CONNECT_TIMEOUT,
                     recv_timeout: float = PROTOCOL_FILE_RECV_TIMEOUT
                     ) -> Optional[bytes]:
    """协议截图：``ReadBack ScreenShot`` + Socket 文件通道，返回整屏图片字节。

    设备侧需先完成截图（实测约 4~5s）再回 JSON + 文件头，故接收超时放宽。

    Returns:
        图片字节（PNG）；失败/无数据/MD5 校验不通过返回 ``None``。
    """
    message = build_readback_message(
        READBACK_TARGET_SCREENSHOT, SCREENSHOT_FILE_OPTIONS,
        file_transfer_mode=FILE_TRANSFER_MODE_SOCKET)
    frame = build_frame(message, TYPE_REQUEST)
    logger.info("设备 %s 尝试协议截图（ReadBack ScreenShot/%s），最多 %s 次（第 2 次可断点续传）",
                host, frame[:4].hex(), TRANSFER_MAX_ATTEMPTS)
    reply, download = receive_file(host, frame, port=port,
                                   connect_timeout=connect_timeout,
                                   recv_timeout=max(recv_timeout,
                                                    PROTOCOL_FILE_RECV_TIMEOUT),
                                   attempts=TRANSFER_MAX_ATTEMPTS)

    if download is None or not download.ok:
        logger.info("设备 %s 协议截图失败: result=%s, 文件数据=%s",
                    host, reply_result(reply),
                    "未收到" if download is None else len(download.data))
        return None

    if download.md5_match is False:
        logger.warning("设备 %s 协议截图 MD5 不一致: 文件头=%s 实际=%s",
                       host, download.md5,
                       hashlib.md5(download.data).hexdigest())
        return None

    logger.info("设备 %s 协议截图成功: %s 字节, 文件名=%s, md5=%s",
                host, len(download.data), download.name, download.md5)
    return download.data


def screenshot_supported(host: str) -> bool:
    """该设备当前是否可用协议截图（复用协议支持面缓存，避免不支持者白等）。"""
    return is_protocol_supported(host)
