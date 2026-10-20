#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""批量任务的**滑动窗口**调度（并发上限固定，完成一台立刻补一台）。

旧实现是「分组」：把设备切成每 8 台一组，**必须等整组跑完**才开始下一组 ——
只要组里有一个慢设备（协议超时后降级 adb，单台 15~17s），后面所有设备都要干等。
实测 12 台截图：前 8 台 ~5s 完成，第 9 台却要等到第 8 台的「最慢者」结束（+8s）。

本模块改为滑动窗口：

* 同时在跑的条目数**恒不超过** ``max_workers``（端口/连接数可控）；
* 任意一台完成，**立刻**补进下一台，不等整批；
* ``should_stop`` 在每个补位点检查，中断后不再派发新条目，已在跑的照常收尾。

无 Qt 依赖，便于离线单测。
"""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable, Iterable, List, Optional, TypeVar

from service.logging_service import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def run_windowed(items: Iterable[T], worker: Callable[[T], R], *,
                 max_workers: int, should_stop: Optional[Callable[[], bool]] = None,
                 on_result: Optional[Callable[[T, R], None]] = None,
                 on_error: Optional[Callable[[T, Exception], None]] = None,
                 on_dispatch: Optional[Callable[[int, int], None]] = None,
                 tick: float = 0.5) -> List[R]:
    """固定并发上限地执行 ``worker(item)``，完成一个补一个。

    Args:
        items: 待处理条目
        worker: 单条目处理函数 ``worker(item) -> R``
        max_workers: **同时**在跑的条目上限（也是峰值并发上限）
        should_stop: 返回 True 时不再派发新条目（已派发的等它跑完）
        on_result / on_error: 成功 / 异常回调
        on_dispatch: 每次派发新条目时回调 ``(已派发数, 总数)``
        tick: 等待轮询粒度（秒）

    Returns:
        成功结果列表（按完成顺序追加）。
    """
    pending_items = list(items)
    total = len(pending_items)
    if not total:
        return []

    workers = max(1, int(max_workers))
    results: List[R] = []
    cursor = 0
    # 进入时已请求中断（例如上一池还没跑完就点了「中断任务」）→ 一台都不派发
    stopped = bool(should_stop is not None and should_stop())

    def _take_next():
        nonlocal cursor
        if stopped or cursor >= total:
            return None
        item = pending_items[cursor]
        cursor += 1
        return item

    executor = ThreadPoolExecutor(max_workers=workers)
    in_flight = {}
    try:
        while len(in_flight) < workers:
            item = _take_next()
            if item is None:
                break
            in_flight[executor.submit(worker, item)] = item
        logger.info("[窗口调度] 共 %s 台，并发上限 %s，首批已派发 %s 台",
                    total, workers, len(in_flight))
        if on_dispatch is not None:
            on_dispatch(len(in_flight), total)

        while in_flight:
            done, _unfinished = wait(list(in_flight), timeout=tick,
                                     return_when=FIRST_COMPLETED)
            if not done:
                # 只是等待超时：借机检查中断标志，避免长时间盲等
                if should_stop is not None and should_stop():
                    stopped = True
                continue

            for future in done:
                item = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("[窗口调度] 条目任务异常(%s): %s", item, exc)
                    if on_error is not None:
                        on_error(item, exc)
                else:
                    results.append(result)
                    if on_result is not None:
                        on_result(item, result)

                if should_stop is not None and should_stop():
                    stopped = True
                next_item = _take_next()
                if next_item is not None:
                    in_flight[executor.submit(worker, next_item)] = next_item
                    if on_dispatch is not None:
                        on_dispatch(cursor, total)
        if stopped:
            logger.info("[窗口调度] 中断：已完成 %s 台，未派发 %s 台",
                        len(results), total - cursor)
    finally:
        executor.shutdown(wait=True)
    return results
