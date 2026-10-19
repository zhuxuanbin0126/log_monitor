#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""在线状态跟踪：把每轮「在场探测」的结果转成设备上线/下线差分。

后台心跳的可信度取决于**抗抖动**能力：设备对 UDP 探测存在应答节流
（首次 0~16ms，节流时可能 4~13s 才回一次），因此单轮没应答**不等于**设备下线。

本模块提供纯逻辑的 :class:`PresenceTracker`：

- 新出现的设备 → **立即**记上线；
- 连续 ``offline_grace`` 轮未应答 → 才记下线（宽限，避免节流导致抖动）；
- IP 变化 → 记「旧地址下线 + 新地址上线」，保证表格地址正确。

无 Qt 依赖，便于离线单测。
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

Pair = Tuple[str, str]


@dataclass
class PresenceDiff:
    """一轮探测的上下线差分。"""

    added: List[Pair] = field(default_factory=list)
    removed: List[Pair] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """是否有任何上下线变化。"""
        return bool(self.added or self.removed)


class PresenceTracker:
    """维护在线设备集合并给出上下线差分（带抗抖动宽限）。"""

    def __init__(self, offline_grace: int = 4):
        self._offline_grace = max(1, int(offline_grace))
        self._known: Dict[str, str] = {}
        self._misses: Dict[str, int] = {}

    def seed(self, pairs: Iterable[Pair]) -> None:
        """以当前已知集合初始化基线（**不产生**差分，用于首轮前避免误报上线）。"""
        self._known = dict(pairs)
        self._misses = {device_id: 0 for device_id, _ in self._known.items()}

    def observe(self, found: Iterable[Pair]) -> PresenceDiff:
        """记录一轮探测结果并返回差分。"""
        online = dict(found)
        diff = PresenceDiff()

        for device_id, ip in online.items():
            if device_id not in self._known:
                diff.added.append((device_id, ip))
            elif self._known[device_id] != ip:
                # 同设备换了 IP：按「旧地址下线 + 新地址上线」处理
                diff.removed.append((device_id, self._known[device_id]))
                diff.added.append((device_id, ip))
            self._known[device_id] = ip
            self._misses[device_id] = 0

        for device_id in list(self._known):
            if device_id in online:
                continue
            misses = self._misses.get(device_id, 0) + 1
            self._misses[device_id] = misses
            if misses >= self._offline_grace:
                diff.removed.append((device_id, self._known[device_id]))
                self._known.pop(device_id, None)
                self._misses.pop(device_id, None)

        return diff

    def known_pairs(self) -> List[Pair]:
        """当前在线设备 ``[(device_id, ip), ...]``。"""
        return list(self._known.items())

    def reset(self) -> None:
        self._known.clear()
        self._misses.clear()
