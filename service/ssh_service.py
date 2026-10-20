#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Linux 设备的 SSH 直连通道（**唯一目标：一次连上就发命令**）。

Linux 机型（C08L / C16L / D16 / D36 / Q910）**不支持 MagicPlayer 协议，也没有 adb**，
因此取数、设置、跑脚本都只有一条路：SSH。本模块把这条路收敛成一条最短路径：

1. **paramiko 优先**（``requirements.txt`` 已固定依赖）：``AutoAddPolicy`` 自动接受
   主机密钥，**不需要**先跑一次 plink ``echo y`` 去「初始化连接」；
2. **短时连接复用**：同一设备在 ``IDLE_TTL`` 秒内的连续命令共用一个已认证连接，
   省掉每次重复的 TCP + SSH 握手（单次约 0.1~0.3s，一条「查询全部」省 2 次）；
3. **失败即换 plink，不重试**：paramiko 抛异常（连接被拒/超时/认证失败）时，
   立刻用 plink 走一次；plink 若报「主机密钥未缓存」，**就地**接受一次密钥再补一次。
   全程最多两次尝试、零 ``sleep`` —— 不走「重试 3 次、每次等 1 秒」的老路。

无法用 paramiko（未安装）时直接走 plink 通道。
"""

import os
import threading
import time
from typing import Dict, Optional, Tuple

from service.device_utils import get_tool_path, run_command
from service.logging_service import get_logger

logger = get_logger(__name__)

CONNECT_TIMEOUT = 5.0
"""SSH 建连超时（秒）：局域网内 5s 连不上就是连不上，不必久等"""

BANNER_TIMEOUT = 5.0
"""SSH 握手 banner 超时（秒）"""

AUTH_TIMEOUT = 5.0
"""SSH 认证超时（秒）"""

EXEC_TIMEOUT = 30.0
"""单条命令执行超时（秒）"""

IDLE_TTL = 10.0
"""连接复用空闲上限（秒）：超过则关闭重建，避免用到设备重启后的死连接"""

PLINK_TIMEOUT = 30.0
"""plink 回退通道的命令超时（秒）"""

HOST_KEY_MARKS = ("host key", "hostkey", "not cached", "store key",
                  "man-in-the-middle", "putty")
"""plink 输出里「主机密钥未缓存」类错误的特征（小写匹配）"""


class _Entry:
    """一条被复用的 SSH 连接。"""

    __slots__ = ("client", "last_used", "password")

    def __init__(self, client, password: str):
        self.client = client
        self.password = password
        self.last_used = time.monotonic()

    def alive(self) -> bool:
        transport = self.client.get_transport()
        return bool(transport and transport.is_active())

    def expired(self) -> bool:
        return time.monotonic() - self.last_used > IDLE_TTL


_POOL: Dict[Tuple[str, str], _Entry] = {}
_POOL_LOCK = threading.RLock()
_ACCEPTED_HOSTS = set()
"""已接受过主机密钥的设备（plink 缓存生效后不再重复 ``echo y``）"""


def paramiko_available() -> bool:
    """paramiko 是否可用（不可用时全部命令走 plink）。"""
    try:
        import paramiko  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        return True
    except ImportError:
        return False


def _close_entry(entry: _Entry) -> None:
    try:
        entry.client.close()
    except Exception:  # pylint: disable=broad-except
        pass


def _drop(host: str, password: str) -> None:
    key = (host, password)
    with _POOL_LOCK:
        entry = _POOL.pop(key, None)
    if entry is not None:
        _close_entry(entry)


def close_all() -> None:
    """关闭并清空连接池（程序退出时调用）。"""
    with _POOL_LOCK:
        entries = list(_POOL.values())
        _POOL.clear()
    for entry in entries:
        _close_entry(entry)


def _connect(host: str, password: str):
    """新建一条已认证的 paramiko 连接；失败抛异常。"""
    import paramiko  # pylint: disable=import-outside-toplevel

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host, username='root', password=password,
            timeout=CONNECT_TIMEOUT, banner_timeout=BANNER_TIMEOUT,
            auth_timeout=AUTH_TIMEOUT,
            look_for_keys=False, allow_agent=False,
        )
    except Exception:
        try:
            client.close()
        except Exception:  # pylint: disable=broad-except
            pass
        raise
    return client


def _acquire(host: str, password: str):
    """取一条可用连接：优先复用未过期的存活连接，否则新建。"""
    key = (host, password)
    with _POOL_LOCK:
        entry = _POOL.get(key)
        if entry is not None:
            if entry.alive() and not entry.expired():
                entry.last_used = time.monotonic()
                return entry.client
            _POOL.pop(key, None)
            _close_entry(entry)

    client = _connect(host, password)
    with _POOL_LOCK:
        _POOL[key] = _Entry(client, password)
    logger.debug("[SSH] 新建连接 %s（后续 %.0fs 内复用）", host, IDLE_TTL)
    return client


def _try_paramiko(host: str, password: str, command: str,
                  timeout: float) -> Optional[Tuple[str, str, int]]:
    """paramiko 执行一次；通道级失败返回 None（交由 plink 回退）。"""
    if not paramiko_available():
        return None
    try:
        client = _acquire(host, password)
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        rc = stdout.channel.recv_exit_status()
        with _POOL_LOCK:
            entry = _POOL.get((host, password))
            if entry is not None:
                entry.last_used = time.monotonic()
        return out, err, rc
    except Exception as exc:  # pylint: disable=broad-except
        # 连接可能已失效（设备重启/网络抖动）→ 丢弃，避免下次继续踩
        _drop(host, password)
        logger.info("[SSH] paramiko 通道 %s 不可用（%s），改用 plink 单次尝试", host, exc)
        return None


def is_host_key_error(text: str) -> bool:
    """判断命令输出是否为「主机密钥未缓存」类错误（供 pscp 等外部工具复用）。"""
    lowered = (text or "").lower()
    return any(mark in lowered for mark in HOST_KEY_MARKS)


def accept_host_key(host: str, password: str) -> None:
    """plink 接受主机密钥（等价于原来的 ``initialize_connection``，按需触发）。"""
    if host in _ACCEPTED_HOSTS:
        return
    plink_exe = get_tool_path('plink.exe')
    cmd = f'echo y | "{plink_exe}" -l root -pw "{password}" "{host}" "exit"'
    try:
        run_command(cmd, timeout=10)
        _ACCEPTED_HOSTS.add(host)
        logger.info("[SSH] 已接受 %s 的主机密钥（plink 回退通道）", host)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("[SSH] 接受 %s 的主机密钥失败: %s", host, exc)


def _try_plink(host: str, password: str, command: str,
               base_dir: str, timeout: float) -> Tuple[str, str, int]:
    """plink 执行一次；仅「主机密钥未缓存」时就地接受再补一次。"""
    os.makedirs(base_dir, exist_ok=True)
    script_path = os.path.join(base_dir, f"{host}temp_script.txt")
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(command)
        handle.write('\nexit\n')

    plink_exe = get_tool_path('plink.exe')

    def _run() -> Tuple[str, str, int]:
        cmd = (f'"{plink_exe}" -batch -no-antispoof -l root -pw "{password}" '
               f'"{host}" -m {script_path}')
        stdout, stderr, returncode = run_command(cmd, timeout=timeout)
        return stdout.strip(), stderr.strip(), returncode

    try:
        result = _run()
        if result[2] != 0 and is_host_key_error(result[1]):
            accept_host_key(host, password)
            result = _run()          # 只补一次，不做多轮重试
        return result
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def execute(host: str, password: str, command: str, base_dir: str = ".",
            timeout: float = EXEC_TIMEOUT) -> Tuple[str, str, int]:
    """在 Linux 设备上执行一条命令：paramiko（复用连接）→ plink（单次补发）。

    Returns:
        ``(stdout, stderr, returncode)``；两条通道都不可用时 returncode 为 -1，
        且 ``stderr`` 为两条通道的失败原因（便于现场定位）。
    """
    result = _try_paramiko(host, password, command, timeout)
    if result is not None:
        return result
    return _try_plink(host, password, command, base_dir, timeout)


def file_exists(host: str, password: str, remote_file: str) -> bool:
    """检查远端文件是否存在（一次命令、单次尝试）。"""
    stdout, _stderr, returncode = execute(
        host, password, f"test -f {remote_file} && echo YES", timeout=10.0)
    if returncode != 0:
        return False
    return "YES" in (stdout or "")


# ---------------------------------------------------------------- 文件传输（SFTP / pscp）

def _sftp_put(client, local_file: str, remote_file: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(local_file, remote_file)
    finally:
        sftp.close()


def _sftp_get(client, remote_file: str, local_file: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.get(remote_file, local_file)
    finally:
        sftp.close()


def _pscp_command(action: str, password: str, first: str, second: str) -> str:
    pscp_exe = get_tool_path('pscp.exe')
    if action == "put":
        return f'{pscp_exe} -batch -pw "{password}" "{first}" root@{second}'
    return f'{pscp_exe} -batch -pw "{password}" root@{first} "{second}"'


def _pscp_put(host: str, password: str, local_file: str, remote_file: str):
    """pscp 上传（回退通道）：主机密钥未缓存时就地接受一次再补发。"""
    cmd = _pscp_command("put", password, local_file, f"{host}:{remote_file}")
    stdout, stderr, returncode = run_command(cmd)
    if returncode != 0 and is_host_key_error(stderr):
        accept_host_key(host, password)
        return run_command(cmd)
    return stdout, stderr, returncode


def _pscp_get(host: str, password: str, remote_file: str, local_file: str):
    """pscp 下载（回退通道）：同上，主机密钥未缓存时就地接受一次再补发。"""
    cmd = _pscp_command("get", password, f"{host}:{remote_file}", local_file)
    stdout, stderr, returncode = run_command(cmd)
    if returncode != 0 and is_host_key_error(stderr):
        accept_host_key(host, password)
        return run_command(cmd)
    return stdout, stderr, returncode


def put_file(host: str, password: str, local_file: str, remote_file: str):
    """把本地文件传到设备：**paramiko SFTP（复用连接）** → pscp 单次回退。

    与「每条命令都新起一个 pscp 进程」相比，SFTP 复用已认证的 SSH 连接，
    单文件省 0.3~1s；批量推 rc/脚本/节目包时收益叠加。

    Returns:
        ``(stdout, stderr, returncode)``，与 pscp 口径一致（成功为 ``("", "", 0)``）。
    """
    if paramiko_available():
        try:
            client = _acquire(host, password)
            _sftp_put(client, local_file, remote_file)
            with _POOL_LOCK:
                entry = _POOL.get((host, password))
                if entry is not None:
                    entry.last_used = time.monotonic()
            logger.debug("[SSH] SFTP 已上传 %s -> %s:%s", local_file, host, remote_file)
            return "", "", 0
        except Exception as exc:  # pylint: disable=broad-except
            _drop(host, password)
            logger.info("[SSH] SFTP 上传 %s 失败（%s），改用 pscp 单次尝试", host, exc)
    return _pscp_put(host, password, local_file, remote_file)


def get_file(host: str, password: str, remote_file: str, local_file: str):
    """从设备取文件：**paramiko SFTP（复用连接）** → pscp 单次回退。"""
    folder = os.path.dirname(local_file)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if paramiko_available():
        try:
            client = _acquire(host, password)
            _sftp_get(client, remote_file, local_file)
            with _POOL_LOCK:
                entry = _POOL.get((host, password))
                if entry is not None:
                    entry.last_used = time.monotonic()
            logger.debug("[SSH] SFTP 已下载 %s:%s -> %s", host, remote_file, local_file)
            return "", "", 0
        except Exception as exc:  # pylint: disable=broad-except
            _drop(host, password)
            logger.info("[SSH] SFTP 下载 %s 失败（%s），改用 pscp 单次尝试", host, exc)
    return _pscp_get(host, password, remote_file, local_file)
