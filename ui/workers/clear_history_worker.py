#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""清理历史数据后台线程：执行规划并**逐项回报**结果（可审计）。

删除动作全部在 Worker 线程完成，GUI 线程只接收信号，避免大量文件 I/O 卡住界面。
"""

from PyQt5.QtCore import QThread, pyqtSignal

from service.history_cleaner import execute_plan, summarize_results
from service.logging_service import get_logger

logger = get_logger(__name__)


class ClearHistoryWorker(QThread):
    """执行清理规划，逐条上报结果，最后给一份汇总。"""

    item_done = pyqtSignal(object)
    """单个条目清理完成（:class:`service.history_cleaner.CleanResult`）。"""
    finished_signal = pyqtSignal(int, int, str)
    """``(删除文件数, 失败条目数, 汇总文案)``。"""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self._plan = list(plan)

    def run(self) -> None:
        try:
            results = execute_plan(self._plan, on_item=self.item_done.emit)
            removed = sum(result.removed for result in results)
            failed = sum(1 for result in results if not result.ok)
            summary = summarize_results(results)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("[清理历史] 执行失败")
            removed, failed, summary = 0, len(self._plan), f"清理失败: {exc}"
        self.finished_signal.emit(removed, failed, summary)
