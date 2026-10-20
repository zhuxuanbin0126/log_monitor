#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""后台心跳找卡：**监控未运行**时周期性静默探测设备上下线。

设计目标是「前端静默且 UI 稳定」：

- 探测在**独立线程**里循环执行（不占用 UI 事件循环）；
- 每轮为**有界探测**（默认 2s，见 :func:`service.discovery.probe_presence`），
  单轮时长可控，不会因「一台都没发现」而白等；
- 主线程侧用 :class:`service.discovery.presence.PresenceTracker` 做差分，
  **仅当确有设备上线/下线时才发 ``changed`` 信号** —— 无变化不刷新表格、不产生卡顿。
- 设备应答存在节流（可能 4~13s 才回一次），故下线判定带 ``offline_grace`` 宽限，
  避免设备在表格里反复上下线抖动。

无 Qt 依赖的部分（探测、差分）在 ``service.discovery`` 中，便于离线单测。
"""

import time

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from config import (
    BACKGROUND_DISCOVERY_INTERVAL_MS, BACKGROUND_DISCOVERY_OFFLINE_GRACE,
    BACKGROUND_DISCOVERY_PROBE_SECONDS,
)
from service.discovery import probe_presence
from service.discovery.presence import PresenceTracker
from service.logging_service import get_logger

logger = get_logger(__name__)

_STOP_POLL_SECONDS = 0.1
"""停止/间隔睡眠的轮询粒度（秒），保证 stop() 能快速返回"""


class _ProbeWorker(QThread):
    """探测线程：循环「一轮有界探测 → 上报 → 睡眠间隔」，直到 stop()。"""

    probed = pyqtSignal(list)

    def __init__(self, probe_seconds: float, interval_seconds: float, parent=None):
        super().__init__(parent)
        self._probe_seconds = probe_seconds
        self._interval_seconds = interval_seconds
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _should_stop(self) -> bool:
        return self._stop

    def run(self) -> None:
        while not self._stop:
            try:
                found = probe_presence(duration=self._probe_seconds,
                                       should_stop=self._should_stop)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("后台心跳探测异常: %s", exc)
                found = []
            if self._stop:
                break
            self.probed.emit(found)
            deadline = time.monotonic() + self._interval_seconds
            while not self._stop and time.monotonic() < deadline:
                time.sleep(_STOP_POLL_SECONDS)


class BackgroundDiscovery(QObject):
    """后台心跳找卡控制器；仅当设备上下线时才发 ``changed`` 信号。"""

    changed = pyqtSignal(list, list)
    """``(added, removed)``，均为 ``[(device_id, ip), ...]``；无变化则不发。"""

    def __init__(self, parent=None, *, interval_ms=None, probe_seconds=None,
                 offline_grace=None):
        super().__init__(parent)
        interval_ms = (BACKGROUND_DISCOVERY_INTERVAL_MS if interval_ms is None
                       else interval_ms)
        probe_seconds = (BACKGROUND_DISCOVERY_PROBE_SECONDS if probe_seconds is None
                         else probe_seconds)
        offline_grace = (BACKGROUND_DISCOVERY_OFFLINE_GRACE if offline_grace is None
                         else offline_grace)
        self._tracker = PresenceTracker(offline_grace=offline_grace)
        self._worker = _ProbeWorker(probe_seconds, interval_ms / 1000.0, self)
        self._worker.probed.connect(self._on_probed)
        self._accept = None

    def set_filter(self, accept) -> None:
        """设置设备过滤谓词 ``accept(device_id) -> bool``（与找卡/表格同口径）。

        必须过滤：UDP 探测会应答**所有**MagicPlayer 设备（含 Q910 等不在支持型号内的），
        若不过滤，这些设备会被当成「新上线」反复触发刷新。
        """
        self._accept = accept

    def seed(self, pairs) -> None:
        """以当前已知设备集合初始化基线（避免首轮把所有设备误报为「上线」）。"""
        self._tracker.seed(pairs)

    def known_pairs(self):
        """当前在线设备 ``[(device_id, ip), ...]``。"""
        return self._tracker.known_pairs()

    def is_running(self) -> bool:
        return self._worker.isRunning()

    def start(self) -> None:
        if not self._worker.isRunning():
            logger.info("后台心跳找卡已启动（探测 %.1fs/轮，间隔 %sms）",
                        self._worker._probe_seconds,  # pylint: disable=protected-access
                        self._worker._interval_seconds * 1000)  # pylint: disable=protected-access
            self._worker.start()

    def stop(self) -> None:
        if self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
            logger.info("后台心跳找卡已停止")

    def _on_probed(self, found) -> None:
        """主线程侧：按同口径过滤 → 记录一轮结果 → **仅在有变化时**上报。

        无变化时**完全不打印**（心跳每轮必然重新发现全部设备，逐台打印会刷屏）；
        有变化时只打印**变动的那几台**。
        """
        if self._accept is not None:
            found = [pair for pair in found if self._accept(pair[0])]
        diff = self._tracker.observe([tuple(pair) for pair in found])
        if not diff.changed:
            return
        if diff.added:
            logger.info("后台心跳：上线 %s 台 %s", len(diff.added),
                        ", ".join(f"{dev}({ip})" for dev, ip in diff.added))
        if diff.removed:
            logger.info("后台心跳：下线 %s 台 %s", len(diff.removed),
                        ", ".join(f"{dev}({ip})" for dev, ip in diff.removed))
        self.changed.emit(diff.added, diff.removed)
