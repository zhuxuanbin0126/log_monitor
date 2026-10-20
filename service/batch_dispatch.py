#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""批量任务的**分组限流**调度（分组下发 + 组内并发上限）。

动机：几十台设备同时执行时，「一股脑全量并发」会压垮本地资源（adb server 单进程、
网卡带宽、设备端并发连接数）。本模块把目标按 ``group_size`` 切成组，**组内并发受限、
组间串行**，把峰值负载钉在 ``group_size`` 的量级，同时保留并行收益。

典型用法::

    run_grouped(devices, handle_one, group_size=8, max_workers=8,
                should_stop=lambda: not running)

无 Qt 依赖，便于离线单测。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Iterator, List, Optional, TypeVar

from service.logging_service import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def iter_groups(items: Iterable[T], group_size: int) -> Iterator[List[T]]:
    """把序列切成大小不超过 ``group_size`` 的连续分组（保持原顺序）。"""
    size = max(1, int(group_size))
    batch: List[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def run_grouped(items: Iterable[T], worker: Callable[[T], R], *,
                group_size: int, max_workers: Optional[int] = None,
                timeout: float = 180.0,
                should_stop: Optional[Callable[[], bool]] = None,
                on_result: Optional[Callable[[T, R], None]] = None,
                on_error: Optional[Callable[[T, Exception], None]] = None
                ) -> List[R]:
    """分组 + 组内限流地执行 ``worker(item)``，返回成功完成的结果列表。

    Args:
        items: 待处理条目
        worker: 单条目处理函数 ``worker(item) -> R``
        group_size: 每组条目数（同时是**峰值并发上限**）
        max_workers: 组内并发度；缺省取 ``group_size``
        timeout: 单条目等待上限（秒）
        should_stop: 可选回调，返回 True 时不再调度后续分组（已发起的本组等完）
        on_result / on_error: 可选回调（成功结果 / 异常）

    Returns:
        成功结果列表（按分组顺序追加；组内完成顺序不保证）。
    """
    items = list(items)
    if not items:
        return []

    size = max(1, int(group_size))
    workers = max(1, int(max_workers)) if max_workers else size
    workers = min(size, workers)
    results: List[R] = []

    for index, group in enumerate(iter_groups(items, size), start=1):
        if should_stop is not None and should_stop():
            logger.info("[分组调度] 已停止，完成 %s 组", index - 1)
            break
        logger.info("[分组调度] 第 %s 组：%s 台（组内并发 %s）", index, len(group), workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(worker, item): item for item in group}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result(timeout=timeout)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("[分组调度] 条目任务异常(%s): %s", item, exc)
                    if on_error is not None:
                        on_error(item, exc)
                    continue
                results.append(result)
                if on_result is not None:
                    on_result(item, result)
    return results
