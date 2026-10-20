#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""全局任务控制：**中断**、**进度**、**未完成清单（可续跑）**。

设计目标（对应「任务执行中无法准确反馈状态、无法中止」）：

* 一个进程级单例 :data:`GLOBAL_TASK`，所有耗时任务（查询/截图/上传）都向它登记；
* UI 的「中断任务」按钮只做一件事：``GLOBAL_TASK.stop()``。任务在**安全边界**
  （每台设备之间、每批派发之前）检查 :meth:`should_stop`，不再派发新设备，
  已在跑的当台跑完再收尾 —— 不做线程强杀，避免资源泄漏；
* 中断时 :attr:`TaskControl.remaining` 保留**未完成的设备清单**，
  UI 据此提供「继续未完成」按钮实现续跑；
* 清单**落盘**到 ``output/task_checkpoint.json``：即使程序被关闭或意外退出，
  下次启动仍能接着跑未完成的设备；
* :meth:`snapshot` 供 UI 显示「正在执行 截图 3/12（当前：H16-…）」。

无 Qt 依赖，便于离线单测。
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional

from config import TASK_CHECKPOINT_FILE
from service.logging_service import get_logger

logger = get_logger(__name__)


def _as_tuple_list(items: List[Any]) -> List[Any]:
    """JSON 读回来的是 list；设备项是 4 元组，统一还原成 tuple。"""
    return [tuple(item) if isinstance(item, list) else item for item in items]


class TaskControl:
    """进程级任务状态机（线程安全，可选落盘）。"""

    def __init__(self, checkpoint_path: Optional[str] = TASK_CHECKPOINT_FILE):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._active = False
        self.label = ""
        self.total = 0
        self.done = 0
        self.current = ""
        self.remaining: List[Any] = []
        self._checkpoint_path = checkpoint_path
        self._load_checkpoint()

    # ---------------------------------------------------------------- 生命周期

    def begin(self, label: str, total: int, items: Optional[List[Any]] = None) -> None:
        """登记一个任务开始（清掉上一轮的中断标志与剩余清单）。"""
        with self._lock:
            self._stop_event.clear()
            self._active = True
            self.label = label
            self.total = int(total)
            self.done = 0
            self.current = ""
            self.remaining = list(items or [])
            self._save_checkpoint()

    def finish(self) -> None:
        """任务收尾：标记为空闲（保留 ``remaining`` 供「继续未完成」使用）。"""
        with self._lock:
            self._active = False
            self.current = ""
            self._save_checkpoint()

    def stop(self) -> None:
        """请求中断：任务会在下一个安全边界停止派发新设备。"""
        self._stop_event.set()

    def should_stop(self) -> bool:
        """是否已请求中断。"""
        return self._stop_event.is_set()

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    # ---------------------------------------------------------------- 进度

    def set_current(self, text: str) -> None:
        """记录当前正在处理的设备（显示用）。"""
        with self._lock:
            self.current = text or ""

    def mark_done(self, item: Any = None) -> None:
        """标记一条完成：从剩余清单移除并累加进度（顺手落盘，断电可续）。"""
        with self._lock:
            self.done += 1
            if item is not None and item in self.remaining:
                self.remaining.remove(item)
            self._save_checkpoint()

    def set_remaining(self, items: List[Any]) -> None:
        with self._lock:
            self.remaining = list(items)
            self._save_checkpoint()

    def snapshot(self) -> Dict[str, Any]:
        """当前状态快照（UI 直接展示）。"""
        with self._lock:
            return {
                "label": self.label,
                "total": self.total,
                "done": self.done,
                "current": self.current,
                "active": self._active,
                "stopped": self._stop_event.is_set(),
                "remaining": list(self.remaining),
            }

    def reset(self) -> None:
        """彻底清空（新一轮任务开始前，或用户放弃续跑时）。"""
        with self._lock:
            self._stop_event.clear()
            self._active = False
            self.label = ""
            self.total = 0
            self.done = 0
            self.current = ""
            self.remaining = []
            self._save_checkpoint()

    # ---------------------------------------------------------------- 落盘

    def _save_checkpoint(self) -> None:
        """把任务进度写到检查点文件（尽力而为，失败不影响任务本身）。"""
        if not self._checkpoint_path:
            return
        payload = {
            "label": self.label,
            "total": self.total,
            "done": self.done,
            "remaining": self.remaining,
        }
        try:
            folder = os.path.dirname(self._checkpoint_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp_path = f"{self._checkpoint_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp_path, self._checkpoint_path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("任务检查点写入失败（不影响任务）: %s", exc)

    def _load_checkpoint(self) -> None:
        """启动时恢复上次未完成的任务清单（没有或已读失败则保持空闲）。"""
        if not self._checkpoint_path or not os.path.isfile(self._checkpoint_path):
            return
        try:
            with open(self._checkpoint_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("任务检查点读取失败（忽略）: %s", exc)
            return
        if not isinstance(payload, dict):
            return
        remaining = payload.get("remaining")
        if not isinstance(remaining, list) or not remaining:
            return
        self.label = str(payload.get("label") or "")
        self.total = int(payload.get("total") or 0)
        self.done = int(payload.get("done") or 0)
        self.remaining = _as_tuple_list(remaining)
        logger.info("发现未完成任务检查点：%s，剩余 %s 台可续跑",
                    self.label, len(self.remaining))


GLOBAL_TASK = TaskControl()
"""进程级单例：所有耗时任务共用"""
