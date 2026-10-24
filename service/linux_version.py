#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Linux 机型（C08L / C16L / D16 / D36 / Q910）的版本取数（SSH 通道）。

真机实测结论（C16L-D24-0F308 / C16L-D00-A1100）：

- **不支持 MagicPlayer 协议**：TCP 10001 发 ``Get``（VersionInfo/DeviceInfo/Time…）
  一律回协议级错误帧 ``0x2000``（code=2）；HSDP（UDP 18500）也直接被复位。
  → Linux 机型取版本**只能走 SSH**。
- 版本真值在设备端 ``/root/Box/version/version``（如 ``7.11.34.0``），是 BoxPlayer
  软件的**发行版本号**，与 Android 的「主版本/播放器版本」语义对应。
- 同目录的 ``*.limit``（``version.limit`` / ``version_C16L_V2.limit`` 等）是**硬件型号
  的最低版本门槛**（OTA 升级准入判定用），不是设备自身的版本号。
  ``/root/Box/version/BoxPlayer`` 恒为 ``1.0.0.1``（与 ``libBox*.so.1.0.0`` 同源），
  是组件/库版本，同样不代表设备版本。
- **该类型不存在 OTA 版本**：设备端无 OTA 版本文件，OTA 列固定为 ``N/A``。

本模块只负责「读一个文件 + 解析成版本串」，不做任何设备状态管理。
"""

from typing import Optional

from . import ssh_service
from .logging_service import get_logger

logger = get_logger(__name__)

NA = "N/A"
"""未知值占位（与旧 adb/SSH 通道口径一致）"""

VERSION_FILE = "/root/Box/version/version"
"""设备端 BoxPlayer 发行版本文件"""

VERSION_COMMAND = f"cat {VERSION_FILE} 2>/dev/null"
"""读取版本文件的命令（stderr 丢弃，文件缺失时静默返回空）"""

VERSION_TIMEOUT = 10.0
"""单台取版本的超时（秒）：设备不可达时快速失败，不拖慢设备列表刷新"""


def parse_version(text: Optional[str]) -> str:
    """把版本文件内容解析成版本串；空/非法返回 ``N/A``。

    版本文件内容形如 ``7.11.34.0``（**无换行符**，实测 9 字节），
    这里取首个非空行的首个空白分隔 token，多余内容一律忽略。
    """
    if not text:
        return NA
    for line in text.splitlines():
        token = line.strip().split()
        if token:
            return token[0]
    return NA


def query_version(ip: str, password: str, *,
                  timeout: float = VERSION_TIMEOUT) -> str:
    """经 SSH 读取 Linux 机型的发行版本号；失败返回 ``N/A``。

    Args:
        ip: 设备 IP
        password: 设备 SSH 密码
        timeout: 单条命令超时（秒）

    Returns:
        版本串（如 ``7.11.34.0``）；设备不可达/文件缺失时为 ``N/A``。
    """
    try:
        stdout, stderr, returncode = ssh_service.execute(
            ip, password, VERSION_COMMAND, timeout=timeout)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("取 Linux 设备 %s 版本失败: %s", ip, exc)
        return NA

    if returncode != 0 and not stdout:
        logger.debug("取 Linux 设备 %s 版本失败: rc=%s stderr=%s",
                     ip, returncode, (stderr or "")[:120])
        return NA

    return parse_version(stdout)
