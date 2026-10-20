"""分组限流调度测试（纯逻辑，不触网）。"""

import threading
import time

from service.batch_dispatch import iter_groups, run_grouped


def test_iter_groups_splits_and_normalizes_group_size():
    assert list(iter_groups([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(iter_groups([], 3)) == []
    assert list(iter_groups([1], 0)) == [[1]]        # group_size<=0 归一到 1


def test_run_grouped_runs_all_and_keeps_peak_bounded():
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

    results = run_grouped(list(range(10)), worker, group_size=3, max_workers=3)

    assert sorted(results) == [index * 2 for index in range(10)]
    assert peak[0] <= 3                              # 峰值并发被钉在组大小内


def test_run_grouped_stops_between_groups():
    seen = []

    def worker(item):
        seen.append(item)
        return item

    run_grouped(list(range(10)), worker, group_size=2, max_workers=2,
                should_stop=lambda: len(seen) >= 2)
    assert len(seen) == 2                            # 第 1 组后即停止，不再调度

def test_run_grouped_reports_errors_without_aborting():
    def worker(item):
        if item == 2:
            raise ValueError("boom")
        return item

    errors = []
    results = run_grouped([1, 2, 3], worker, group_size=3, max_workers=3,
                          on_error=lambda item, exc: errors.append((item, str(exc))))
    assert sorted(results) == [1, 3]
    assert errors == [(2, "boom")]


def test_run_grouped_empty_input():
    assert run_grouped([], lambda item: item, group_size=4) == []
