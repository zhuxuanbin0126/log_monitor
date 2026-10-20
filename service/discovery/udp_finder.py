#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""局域网找卡：UDP 9527 限定广播探测（``DeviceId.exe`` 的纯 Python 等价实现）。

通过 UDP 广播探测包查找局域网内的测试设备（MagicPlayer 下位机控制卡）。

协议（抓包确认，UDP 端口 9527）：
  - 广播探测包（6 字节）: ``00 00 00 02 01 00``
      发往 ``255.255.255.255:9527``（以及各网卡的 /24 子网广播，兜底）
  - 设备 ID 应答（UDP 载荷）: ``[6 字节协议头] + 设备ID(ASCII) + [填充]``
      协议头示例: ``00 00 00 01 02 00``（类型 2 = ID 应答）
      详情应答头: ``09 00 00 01 04 00``（类型 4，含网络配置/版本/名称，此处仅取 ID）
  - 设备 ID 字符集: ``[A-Za-z0-9_-]``，后接 NUL 或 0x00 填充

本模块仅需"找卡"能力（设备 ID + IP），因此解析 ID 应答与详情应答中的设备 ID，
IP 取自 UDP 响应包的源地址。

⚠️ 多网卡发包三要点（抓包比对 + 真机矩阵实验定位，务必遵守）：

  1. **必须逐网卡建 socket 并显式绑定该网卡的源 IP**，再向 255.255.255.255
     发限定广播。若只用一个 ``bind(("0.0.0.0", 0))`` 的 socket 发
     255.255.255.255，Windows 只会从**一块**网卡发出，另一网段的设备完全收不到
     探测包 —— 这正是"局域网多台设备只发现少数"的根因。官方上位机抓包显示其
     探测包源 IP 固定为设备所在网段，即逐网卡发送。
  2. **子网定向广播（如 192.168.80.255）对这批设备无效**：实测设备只接受
     255.255.255.255（限定广播）或发往自身 IP 的包；子网广播一律不应答。
     故以限定广播为主通道，子网广播仅作老固件兜底。
  3. **设备应答可能延迟数秒且存在应答节流**（首次 0~16ms，节流时 4~13s）。
     因此扫描期间必须**周期性重发探测包**，且不能一发现设备就立刻收尾 ——
     否则先应答的少数设备会让静默窗口提前结束，晚应答的设备全部丢失。
"""

import select
import socket
import time
from typing import Callable, Dict, List, Optional, Tuple

from config import (
    UDP_DISCOVERY_PORT, UDP_MIN_SCAN_SECONDS, UDP_PROBE_INTERVAL,
    UDP_PROBE_PACKET, UDP_QUIET_WINDOW, UDP_SCAN_TIMEOUT,
)
from service.logging_service import get_logger

logger = get_logger(__name__)

# 限定广播地址（主通道；设备只认这个）
GLOBAL_BROADCAST_ADDR = "255.255.255.255"
# 单包最大长度
MAX_PACKET_SIZE = 4096
# 协议头长度（ID 应答/详情应答的设备 ID 均从偏移 6 开始）
RESPONSE_HEADER_LENGTH = 6
# 设备 ID 合法字符（ASCII 可打印的子集）
_DEVICE_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
# 设备 ID 最短长度（低于此长度视为误报）
_MIN_DEVICE_ID_LENGTH = 8


def _primary_ipv4_address() -> Optional[str]:
    """本机默认出口 IPv4 地址（UDP connect 不真正发包，仅查路由表）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def local_ipv4_addresses() -> List[str]:
    """本机所有非回环 IPv4 地址（逐网卡绑定源 IP 用）。

    以主机名解析枚举网卡地址，并补充默认出口地址兜底（主机名解析失败时仍能
    拿到至少一块网卡的地址）。
    """
    try:
        ips = [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2]
               if not ip.startswith("127.")]
    except OSError:
        ips = []
    primary = _primary_ipv4_address()
    if primary and primary not in ips:
        ips.append(primary)
    return list(dict.fromkeys(ips))


def subnet_broadcast(ip: str) -> str:
    """/24 子网广播地址（仅作老固件兜底，见模块 docstring 要点 2）。"""
    parts = ip.split(".")
    if len(parts) != 4:
        return ""
    return f"{parts[0]}.{parts[1]}.{parts[2]}.255"


def open_probe_sockets() -> List[socket.socket]:
    """为每块网卡建立独立探测 socket 并绑定其源 IP（见 docstring 要点 1）。

    绑定源 IP 后，该 socket 发出的限定广播才会从对应网卡出去；
    （``0.0.0.0`` 未绑定源 IP 时，Windows 只挑一块网卡发 → 漏发现其他网段设备）
    """
    sockets: List[socket.socket] = []
    for ip in local_ipv4_addresses():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind((ip, 0))
            sockets.append(sock)
        except OSError as exc:
            logger.warning("网卡 %s 绑定失败，跳过: %s", ip, exc)
            sock.close()
    if not sockets:
        # 兜底：拿不到网卡列表时退回单 socket（只能走系统默认网卡，可能漏设备）
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sockets.append(sock)
        logger.warning("未取到本机网卡 IP，退回默认网卡广播（可能漏发现其他网段设备）")
    return sockets


def send_probe_round(sockets: List[socket.socket], port: int,
                     packet: bytes = UDP_PROBE_PACKET) -> None:
    """一轮探测：每块网卡各发一次限定广播（主）+ 子网广播（兜底）。"""
    for sock in sockets:
        src_ip = sock.getsockname()[0]
        targets = [GLOBAL_BROADCAST_ADDR]
        subnet = subnet_broadcast(src_ip)
        if subnet:
            targets.append(subnet)
        for addr in targets:
            try:
                sock.sendto(packet, (addr, port))
                logger.debug("已发送探测包: %s → %s:%s", src_ip, addr, port)
            except OSError as exc:
                logger.warning("发送探测包到 %s 失败: %s", addr, exc)


def parse_device_id(data: bytes) -> Optional[str]:
    """从设备响应数据包中提取设备 ID。

    优先从协议头（偏移 6）之后读取；若失败则在整个数据包中搜索
    合法的设备 ID 模式（覆盖详情响应/设备主动上报等包型）。

    Args:
        data: UDP 载荷（应用层数据）

    Returns:
        设备 ID 字符串；无法识别时返回 None
    """
    if len(data) < RESPONSE_HEADER_LENGTH + 3:
        return None

    def _read_id_at(start: int) -> Optional[str]:
        end = start
        while end < len(data) and chr(data[end]) in _DEVICE_ID_CHARS:
            end += 1
        if end - start < _MIN_DEVICE_ID_LENGTH:
            return None
        return data[start:end].decode("ascii", "ignore")

    # 方式一：协议头之后
    device_id = _read_id_at(RESPONSE_HEADER_LENGTH)
    if device_id:
        return device_id
    # 方式二：全包搜索（设备 ID 以字母开头，长度 >= 8）
    for i in range(len(data) - (_MIN_DEVICE_ID_LENGTH - 1)):
        if not chr(data[i]).isalpha():
            continue
        device_id = _read_id_at(i)
        if device_id:
            return device_id
    return None


def _drain_socket(sock: socket.socket,
                  discovered: Dict[str, Tuple[str, str]],
                  on_device: Optional[Callable[[str, str], None]],
                  verbose: bool = True
                  ) -> Optional[Tuple[str, str]]:
    """从单个 socket 读取一包并解析；返回新发现的 ``(device_id, ip)`` 或 None。

    ``verbose=False`` 时「发现设备」降到 DEBUG 级：后台心跳每轮都会重新发现全部设备，
    INFO 级会把同一批设备刷屏（只在首次扫描时才有 INFO 价值）。
    """
    try:
        data, addr = sock.recvfrom(MAX_PACKET_SIZE)
    except OSError:
        return None

    device_id = parse_device_id(data)
    if device_id is None:
        logger.debug("忽略无法解析的响应: %s:%s 长度 %s", addr[0], addr[1], len(data))
        return None
    if device_id in discovered:
        return None

    discovered[device_id] = (device_id, addr[0])
    if verbose:
        logger.info("发现设备: %s -> %s", device_id, addr[0])
    else:
        logger.debug("发现设备: %s -> %s", device_id, addr[0])
    if on_device is not None:
        try:
            on_device(device_id, addr[0])
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("设备发现回调异常（不影响扫描）: %s", exc)
    return discovered[device_id]


def scan_devices(timeout: float = UDP_SCAN_TIMEOUT, port: int = UDP_DISCOVERY_PORT,
                 on_device: Optional[Callable[[str, str], None]] = None,
                 min_scan: float = UDP_MIN_SCAN_SECONDS,
                 quiet_window: float = UDP_QUIET_WINDOW,
                 probe_interval: float = UDP_PROBE_INTERVAL,
                 should_stop: Optional[Callable[[], bool]] = None,
                 verbose: bool = True,
                 ) -> List[Tuple[str, str]]:
    """扫描局域网内测试设备。

    多网卡场景下**逐网卡绑定源 IP 发送限定广播**（见模块 docstring 三要点），
    扫描期间按 ``probe_interval`` 周期重发探测包，收尾需同时满足：
    「已扫描 ≥ ``min_scan``」且「连续 ``quiet_window`` 无新设备」，
    以覆盖应答延迟数秒的设备。

    Args:
        timeout: 扫描总超时时间（秒），默认 30 秒（上限保护）
        port: 设备 UDP 端口，默认 9527
        on_device: 可选回调 ``f(device_id, ip)``，**每发现一台新设备立即在接收
            逻辑上调用一次**（调用方需自行保证线程安全，典型用法是发 Qt 信号）。
        min_scan: 最短扫描时长（秒）
        quiet_window: 最后一台设备后仍需静默等待的时长（秒）
        probe_interval: 重发探测包的间隔（秒）
        should_stop: 可选回调，返回 True 时提前终止扫描（用于 UI 取消）

    Returns:
        List[Tuple[str, str]]: ``[(device_id, ip_address), ...]``，
        同一设备仅保留一条记录（按设备 ID 去重，保留首次出现 IP）
    """
    sockets = open_probe_sockets()
    discovered: Dict[str, Tuple[str, str]] = {}
    start_time = time.monotonic()
    last_found = start_time

    try:
        local_ips = ", ".join(sock.getsockname()[0] for sock in sockets)
        logger.info("设备发现已启动，网卡: [%s]，目标端口: %s，超时: %ss",
                    local_ips, port, timeout)

        next_probe = start_time  # 立即发第一轮
        while True:
            if should_stop is not None and should_stop():
                logger.info("扫描被取消，结束（共 %s 台）", len(discovered))
                break

            now = time.monotonic()
            elapsed = now - start_time
            if elapsed >= timeout:
                logger.info("扫描达到总超时 %ss，结束（共 %s 台）",
                            timeout, len(discovered))
                break

            # 周期重发探测包（设备应答可能延迟数秒/存在节流，单轮不可靠）
            if now >= next_probe:
                send_probe_round(sockets, port)
                next_probe = now + probe_interval

            # 收尾判定：至少扫描 min_scan，且连续静默 quiet_window
            if (discovered and elapsed >= min_scan
                    and (now - last_found) >= quiet_window):
                logger.info("已连续 %ss 无新设备响应，结束扫描（共 %s 台，用时 %.1fs）",
                            quiet_window, len(discovered), elapsed)
                break

            # 等待任一网卡 socket 可读（超时即进入下一轮重发）
            readable, _, _ = select.select(
                sockets, [], [], min(probe_interval, max(0.05, timeout - elapsed)))
            for sock in readable:
                found = _drain_socket(sock, discovered, on_device, verbose=verbose)
                if found is not None:
                    last_found = time.monotonic()
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass

    return list(discovered.values())


def probe_presence(duration: float = 2.0, port: int = UDP_DISCOVERY_PORT,
                   probe_interval: float = UDP_PROBE_INTERVAL,
                   on_device: Optional[Callable[[str, str], None]] = None,
                   should_stop: Optional[Callable[[], bool]] = None,
                   verbose: bool = False,
                   ) -> List[Tuple[str, str]]:
    """有界的「在场探测」：``duration`` 秒内周期重发探测包并收集应答。

    与 :func:`scan_devices` 的关键区别：本函数**不做发现即收尾**——即使一台设备
    都没应答，也只在 ``duration`` 秒后结束。因此**单轮总时长可控**，适合做后台心跳
    （周期短且稳定，不会因为「一台都没发现」而白等整个扫描超时）。

    ``verbose`` 默认 **False**（心跳每轮都会重新发现全部设备，逐台 INFO 会刷屏）；
    首次扫描请用 :func:`scan_devices`。

    Args:
        duration: 单轮探测时长（秒）
        port: 设备 UDP 端口
        probe_interval: 探测包重发间隔（秒）
        on_device: 可选回调 ``f(device_id, ip)``，每发现一台新设备调用一次
        should_stop: 可选回调，返回 True 时提前终止（用于停止后台心跳）

    Returns:
        ``[(device_id, ip_address), ...]``（按设备 ID 去重）
    """
    sockets = open_probe_sockets()
    discovered: Dict[str, Tuple[str, str]] = {}
    start_time = time.monotonic()
    try:
        next_probe = start_time  # 立即发第一轮
        while True:
            if should_stop is not None and should_stop():
                break
            now = time.monotonic()
            elapsed = now - start_time
            if elapsed >= duration:
                break
            if now >= next_probe:
                send_probe_round(sockets, port)
                next_probe = now + probe_interval
            readable, _, _ = select.select(
                sockets, [], [], min(probe_interval, max(0.05, duration - elapsed)))
            for sock in readable:
                _drain_socket(sock, discovered, on_device, verbose=verbose)
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass
    return list(discovered.values())

