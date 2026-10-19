#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""手动找卡：把「目标 IP 规范」解析为 IP 列表，做单播探测 + 广播兜底。

设计原则（与参考实现一致，解决"定向扫描遗漏既有局域网设备"与"效率低"）：

1. **广播发现始终执行**（O(1) 轮次，覆盖本机所有可达网段），因此既有局域网
   设备**必然保留**，定向扫描只是"加法"而非"替换" —— 设备列表 =
   广播发现的全集 ∪ 手动 IP 命中的设备。
2. **只对「跨子网」的目标 IP 做单播探测**：同网段的目标 IP 已被广播覆盖，
   无需逐 IP 单播（否则区间 511 个 IP 就是 511 次探测，正是慢的根因）。
   跨子网 IP（广播到不了）才必须单播，并发 + 短超时把代价压到最低。
3. **广播与单播并发执行**，总耗时 ≈ max(广播耗时, 单播耗时) ≈ 广播耗时。
"""

import ipaddress
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from config import (
    PROBE_BROADCAST_MOPUP_INTERVAL, PROBE_BROADCAST_MOPUP_MIN_SCAN,
    PROBE_BROADCAST_MOPUP_QUIET, PROBE_BROADCAST_MOPUP_TIMEOUT,
    PROBE_CONCURRENCY, PROBE_MAX_TARGETS, PROBE_PER_TARGET_TIMEOUT,
    UDP_DISCOVERY_PORT, UDP_PROBE_PACKET,
)
from service.logging_service import get_logger

from .udp_finder import (
    MAX_PACKET_SIZE, local_ipv4_addresses, parse_device_id, scan_devices,
)

logger = get_logger(__name__)


def parse_ip_spec(spec, max_targets: Optional[int] = PROBE_MAX_TARGETS) -> List[str]:
    """把「目标规范」解析为 IPv4 字符串列表（去重、保序）。

    支持单 IP / 区间 / CIDR / 逗号-空格混合：
      - ``"192.168.80.6"``
      - ``"192.168.80.1-192.168.81.255"``   （区间，按整数递增展开）
      - ``"192.168.80.0/24"``               （CIDR，取 hosts）
      - ``"192.168.80.1,192.168.80.5-192.168.80.10,192.168.81.7"``  （混合）

    Args:
        spec: 字符串或 IP 字符串列表。
        max_targets: 目标 IP 上限；超出抛 ValueError（防止 /16 等大区间把扫描
            跑成数分钟）。

    Returns:
        List[str]: 去重后的 IP 字符串列表。

    Raises:
        ValueError: 规范非法或超出上限。
    """
    tokens: List[str] = []
    if isinstance(spec, (list, tuple, set)):
        for item in spec:
            tokens.extend(str(item).replace(";", ",").split(","))
    else:
        tokens.extend(str(spec).replace(";", ",").split(","))

    ips: List[str] = []
    seen = set()
    for raw in tokens:
        tok = raw.strip()
        if not tok:
            continue
        try:
            if "-" in tok and tok.count("-") == 1:
                start_s, end_s = tok.split("-")
                start = ipaddress.ip_address(start_s.strip())
                end = ipaddress.ip_address(end_s.strip())
                if start.version != 4 or end.version != 4:
                    raise ValueError(f"仅支持 IPv4: {tok}")
                if int(end) < int(start):
                    raise ValueError(f"区间起点大于终点: {tok}")
                count = int(end) - int(start) + 1
                if max_targets is not None and len(ips) + count > max_targets:
                    raise ValueError(
                        f"目标 IP 数量 {len(ips) + count} 超出上限 {max_targets}（请缩小区间）")
                for i in range(count):
                    ip = str(ipaddress.ip_address(int(start) + i))
                    if ip not in seen:
                        seen.add(ip)
                        ips.append(ip)
            elif "/" in tok:
                net = ipaddress.ip_network(tok, strict=False)
                if net.version != 4:
                    raise ValueError(f"仅支持 IPv4: {tok}")
                hosts = list(net.hosts())
                if max_targets is not None and len(ips) + len(hosts) > max_targets:
                    raise ValueError(
                        f"目标 IP 数量 {len(ips) + len(hosts)} 超出上限 {max_targets}（请缩小区间）")
                for host in hosts:
                    ip = str(host)
                    if ip not in seen:
                        seen.add(ip)
                        ips.append(ip)
            else:
                ip = str(ipaddress.ip_address(tok))
                if ip not in seen:
                    seen.add(ip)
                    ips.append(ip)
        except ValueError as exc:
            # 容量超限（"超出上限"）直接透传；其余视为规范非法
            if "超出上限" in str(exc):
                raise
            raise ValueError(f"非法目标 IP 规范 '{tok}': {exc}") from exc
    return ips


def local_subnets() -> List[ipaddress.IPv4Network]:
    """本机所有非回环 IPv4 子网，用于判断目标 IP 是否与本机同网段。

    同网段的目标 IP 由广播发现覆盖（O(1) 轮次，一次探测包直达网段内所有设备），
    无需逐 IP 单播 —— 这正是"手动找卡"高效的关键。

    以本机网卡地址按 /24 估算掩码（生产环境常见配置，且不引入额外依赖）。
    """
    nets: List[ipaddress.IPv4Network] = []
    for ip in local_ipv4_addresses():
        try:
            nets.append(ipaddress.ip_network(f"{ip}/24", strict=False))
        except ValueError:
            pass
    return nets


def split_local_remote(ips: List[str]) -> Tuple[List[str], List[str]]:
    """把目标 IP 分为「同网段（广播可覆盖）」与「跨子网（必须单播）」两组。

    Returns:
        ``(local_ips, remote_ips)``
    """
    nets = local_subnets()
    local: List[str] = []
    remote: List[str] = []
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            remote.append(ip)
            continue
        (local if any(addr in net for net in nets) else remote).append(ip)
    return local, remote


def probe_one(ip: str, port: int = UDP_DISCOVERY_PORT,
              timeout: float = PROBE_PER_TARGET_TIMEOUT,
              packet: bytes = UDP_PROBE_PACKET) -> Optional[Tuple[str, str]]:
    """向单台目标 IP 单播探测，等待设备 ID 应答（最多重试一次）。

    设备仅应答 255.255.255.255 或**发往自身 IP** 的包（见 udp_finder 模块
    docstring 要点 2），故单播 ``(ip, port)`` 在协议层可行；解析复用
    :func:`parse_device_id`，与广播发现语义一致。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.settimeout(timeout)
        sock.bind(("0.0.0.0", 0))
        try:
            sock.sendto(packet, (ip, port))
            try:
                data, addr = sock.recvfrom(MAX_PACKET_SIZE)
            except socket.timeout:
                # 设备应答可能节流/延迟，补发一次再等一轮
                sock.sendto(packet, (ip, port))
                data, addr = sock.recvfrom(MAX_PACKET_SIZE)
        except (OSError, socket.timeout):
            return None
        device_id = parse_device_id(data)
        if device_id:
            return (device_id, addr[0])
        return None
    except (OSError, socket.timeout):
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def probe_targets(targets: List[str], port: int = UDP_DISCOVERY_PORT,
                  per_target_timeout: float = PROBE_PER_TARGET_TIMEOUT,
                  concurrency: int = PROBE_CONCURRENCY,
                  on_device: Optional[Callable[[str, str], None]] = None,
                  should_stop: Optional[Callable[[], bool]] = None,
                  ) -> List[Tuple[str, str]]:
    """对一组目标 IP 做单播 UDP 探测，返回命中的 ``(device_id, ip)``。

    逐 IP 并发探测；按 ``device_id`` 去重（保留首次出现 IP）。
    复用 PROBE_PACKET 与 :func:`parse_device_id`，与广播发现语义一致。
    """
    results: dict = {}
    try:
        workers = max(1, min(concurrency, len(targets) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(probe_one, ip, port, per_target_timeout): ip
                       for ip in targets}
            for future in as_completed(futures):
                if should_stop is not None and should_stop():
                    break
                try:
                    result = future.result()
                except Exception:  # pylint: disable=broad-except
                    result = None
                if result and result[0] not in results:
                    results[result[0]] = result
                    if on_device is not None:
                        try:
                            on_device(result[0], result[1])
                        except Exception as exc:  # pylint: disable=broad-except
                            logger.warning("定向扫描回调异常（不影响结果）: %s", exc)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("定向扫描线程池异常: %s", exc)
    return list(results.values())


def scan_targets(targets, per_target_timeout: Optional[float] = None,
                 concurrency: Optional[int] = None,
                 on_device: Optional[Callable[[str, str], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None,
                 port: int = UDP_DISCOVERY_PORT,
                 ) -> List[Tuple[str, str]]:
    """定向探测指定 IP / 区间 / CIDR（"手动找卡"），广播兜底并行执行。

    Args:
        targets: 单 IP 字符串 / 区间 ``"a-b"`` / CIDR ``"x/y"`` / 逗号-空格混合，
            或上述组成的列表；交由 :func:`parse_ip_spec` 统一解析。
        per_target_timeout: 逐 IP 单播等待响应超时（秒）。
        concurrency: 单播并发度。
        on_device: 可选回调 ``(device_id, ip)``，发现即调用（调用方需保证线程安全）。
        should_stop: 可选回调，返回 True 时提前终止。
        port: 设备 UDP 端口。

    Returns:
        List[Tuple[str, str]]: 命中设备（广播全集 ∪ 手动 IP 命中，去重合并）

    Raises:
        ValueError: 目标 IP 规范非法或超出上限
    """
    ips = parse_ip_spec(targets, max_targets=PROBE_MAX_TARGETS)
    if not ips:
        logger.warning("定向扫描：未解析到任何目标 IP")
        return []

    local_ips, remote_ips = split_local_remote(ips)
    logger.info("定向扫描：目标 %s 个 IP（同网段 %s 由广播覆盖，跨子网单播 %s）",
                len(ips), len(local_ips), len(remote_ips))

    found: dict = {}
    lock = threading.Lock()

    def _on(device_id: str, ip: str) -> None:
        with lock:
            is_new = device_id not in found
            if is_new:
                found[device_id] = (device_id, ip)
        if is_new and on_device is not None:
            try:
                on_device(device_id, ip)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("定向扫描回调异常（不影响结果）: %s", exc)

    def _broadcast() -> None:
        # 广播发现覆盖同网段全部设备（含既有局域网设备）。定向扫描里这只是
        # "加法兜底" (mop-up)：主结果由快的单播给出，故用短窗口，避免把完整
        # 节流容忍窗口强加在定向扫描上。
        try:
            scan_devices(
                timeout=PROBE_BROADCAST_MOPUP_TIMEOUT, port=port, on_device=_on,
                min_scan=PROBE_BROADCAST_MOPUP_MIN_SCAN,
                quiet_window=PROBE_BROADCAST_MOPUP_QUIET,
                probe_interval=PROBE_BROADCAST_MOPUP_INTERVAL,
                should_stop=should_stop,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("广播发现失败（不影响单播结果）: %s", exc)

    def _unicast() -> None:
        if not remote_ips:
            return
        try:
            probe_targets(
                remote_ips, port=port,
                per_target_timeout=per_target_timeout or PROBE_PER_TARGET_TIMEOUT,
                concurrency=concurrency or PROBE_CONCURRENCY,
                on_device=_on, should_stop=should_stop,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("跨子网单播探测失败（不影响广播结果）: %s", exc)

    if remote_ips:
        # 广播 + 单播并发：总耗时约等于广播耗时
        thread_b = threading.Thread(target=_broadcast, daemon=True)
        thread_u = threading.Thread(target=_unicast, daemon=True)
        thread_b.start()
        thread_u.start()
        thread_b.join()
        thread_u.join()
    else:
        # 目标全在同网段：纯广播即可（与未添加手动 IP 的耗时几乎一致）
        _broadcast()

    logger.info("定向扫描完成，命中 %s 个设备", len(found))
    return list(found.values())
