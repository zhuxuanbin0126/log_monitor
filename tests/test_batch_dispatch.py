"""滑动窗口调度测试（纯逻辑，不触网）。"""

import threading
import time

from service.batch_dispatch import run_windowed


def test_runs_all_and_keeps_peak_bounded():
    peak = [0]
    active = [0]
    lock = threading.Lock()

    def worker(item):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.01)
        with lock:
            active[0] -= 1
        return item * 2

    results = run_windowed(list(range(10)), worker, max_workers=3)

    assert sorted(results) == [index * 2 for index in range(10)]
    assert peak[0] <= 3                              # 峰值并发被钉在窗口内


def test_slow_item_does_not_block_followers():
    """关键回归：慢设备不再拖住整组 —— 后续条目在它完成前就开始跑。"""
    started = []
    lock = threading.Lock()

    def worker(item):
        with lock:
            started.append(item)
        if item == 0:
            time.sleep(0.4)                          # 模拟「协议超时 → 降级 adb」的慢设备
        else:
            time.sleep(0.01)
        return item

    run_windowed(list(range(6)), worker, max_workers=2)

    # items 1 在 0 完成前就已派发（旧的分组实现会等整组结束）
    assert started.index(1) < 6
    assert set(started) == set(range(6))


def test_stops_dispatching_after_interrupt():
    seen = []
    lock = threading.Lock()

    def worker(item):
        with lock:
            seen.append(item)
        time.sleep(0.05)
        return item

    run_windowed(list(range(20)), worker, max_workers=2,
                 should_stop=lambda: len(seen) >= 2)
    assert len(seen) <= 4                             # 已派发的照常收尾，不再补位


def test_already_stopped_dispatches_nothing():
    """进入前就已中断（上一池还没跑完点了「中断任务」）→ 一台都不派发。"""
    seen = []
    results = run_windowed([1, 2, 3], lambda item: seen.append(item),
                           max_workers=3, should_stop=lambda: True)
    assert results == []
    assert seen == []


def test_reports_errors_without_aborting():
    def worker(item):
        if item == 2:
            raise ValueError("boom")
        return item

    errors = []
    results = run_windowed([1, 2, 3], worker, max_workers=3,
                           on_error=lambda item, exc: errors.append((item, str(exc))))
    assert sorted(results) == [1, 3]
    assert errors == [(2, "boom")]


def test_empty_input_returns_empty():
    assert run_windowed([], lambda item: item, max_workers=4) == []


def test_dispatch_callback_tracks_cursor():
    progress = []
    run_windowed([1, 2, 3, 4], lambda item: item, max_workers=2,
                 on_dispatch=lambda dispatched, total: progress.append((dispatched, total)))
    assert progress[0] == (2, 4)
    assert progress[-1][0] == 4
