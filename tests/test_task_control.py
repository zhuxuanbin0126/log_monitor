"""全局任务控制（中断 / 进度 / 检查点续跑）测试。"""

from service.task_control import TaskControl


def _devices(*ids):
    return [(device_id, "192.168.80.1", "pwd", "Android") for device_id in ids]


def test_begin_mark_done_and_snapshot():
    task = TaskControl(checkpoint_path=None)
    task.begin("screenshot", 2, _devices("A", "B"))
    task.set_current("A (192.168.80.1)")

    snapshot = task.snapshot()
    assert snapshot["active"] is True
    assert snapshot["total"] == 2
    assert snapshot["done"] == 0
    assert snapshot["label"] == "screenshot"

    task.mark_done(_devices("A")[0])
    snapshot = task.snapshot()
    assert snapshot["done"] == 1
    assert [item[0] for item in snapshot["remaining"]] == ["B"]

    task.finish()
    assert task.is_active is False
    assert task.snapshot()["remaining"]          # 收尾后仍保留未完成清单


def test_stop_flag_is_cleared_by_begin():
    task = TaskControl(checkpoint_path=None)
    task.begin("all", 1, _devices("A"))
    task.stop()
    assert task.should_stop() is True
    task.begin("all", 1, _devices("B"))
    assert task.should_stop() is False


def test_checkpoint_survives_new_instance(tmp_path):
    """中断后新建实例（≈程序重启）仍能读到未完成清单，实现断电续跑。"""
    path = str(tmp_path / "task_checkpoint.json")
    devices = _devices("A", "B")

    task = TaskControl(checkpoint_path=path)
    task.begin("screenshot", 2, devices)
    task.mark_done(devices[0])
    task.finish()

    restored = TaskControl(checkpoint_path=path)
    snapshot = restored.snapshot()
    assert snapshot["label"] == "screenshot"
    assert snapshot["total"] == 2
    assert snapshot["done"] == 1
    assert snapshot["remaining"] == [devices[1]]      # list 已还原成 tuple


def test_reset_clears_checkpoint(tmp_path):
    path = str(tmp_path / "task_checkpoint.json")
    task = TaskControl(checkpoint_path=path)
    task.begin("all", 1, _devices("A"))
    task.reset()

    assert TaskControl(checkpoint_path=path).snapshot()["remaining"] == []
