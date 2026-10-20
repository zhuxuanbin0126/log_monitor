"""历史数据清理：范围规划、预览、执行（全部在临时目录内，不触碰真实数据）。"""

import os

import service.history_cleaner as hc


def _touch(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _isolate_legacy(monkeypatch, tmp_path):
    """把 ``./screenshot`` / ``./switch_log`` 等相对路径重定向到不存在的临时路径。"""
    monkeypatch.setattr(
        hc, "_abs",
        lambda *parts: str(tmp_path / "legacy" / os.path.join(*parts)))


# ---------------------------------------------------------------- 型号前缀

def test_prefix_pattern_aggregate_and_specific():
    aggregate = hc.prefix_pattern("A-B-C-D-H")
    assert aggregate.match("A3L-00-0001")
    assert aggregate.match("H16-26-A0419")
    assert not aggregate.match("Q910-D26-002B8")

    assert hc.prefix_pattern("H16").match("H16-26-A0419")
    assert not hc.prefix_pattern("H16").match("A3L-00-0001")
    assert hc.prefix_pattern("") is None


# ---------------------------------------------------------------- 各范围规划

def test_plan_excel_only_scans_excel_dir(monkeypatch, tmp_path):
    excel_dir = tmp_path / "output" / "excel"
    excel_dir.mkdir(parents=True)
    _touch(str(excel_dir / "H16_2026.xlsx"))
    _touch(str(excel_dir / "A3L_2026.xlsx"))
    _touch(str(tmp_path / "用户的表格.xlsx"))       # 工作目录下的用户文件
    monkeypatch.setattr(hc, "EXCEL_DIR", str(excel_dir))

    assert [item.label for item in hc.plan_excel("H16")] == ["H16_2026.xlsx"]
    assert len(hc.plan_excel("H16", include_all_types=True)) == 2


def test_plan_excel_ignores_non_xlsx(monkeypatch, tmp_path):
    excel_dir = tmp_path / "excel"
    excel_dir.mkdir()
    _touch(str(excel_dir / "H16_a.txt"))
    _touch(str(excel_dir / "H16_b.xlsx"))
    monkeypatch.setattr(hc, "EXCEL_DIR", str(excel_dir))
    assert [item.label for item in hc.plan_excel("H16")] == ["H16_b.xlsx"]


def test_plan_logs_filters_by_dev_type(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"
    (log_dir / "H16_AgingTest").mkdir(parents=True)
    (log_dir / "C16L_AgingTest").mkdir()
    _touch(str(log_dir / "H16_AgingTest" / "uptime.log"))
    _touch(str(log_dir / "C16L_AgingTest" / "uptime.log"))
    monkeypatch.setattr(hc, "LOG_DIR", str(log_dir))

    assert [item.label for item in hc.plan_logs("H16")] == ["H16_AgingTest/"]
    assert len(hc.plan_logs("H16", include_all_types=True)) == 2


def test_plan_logs_never_includes_app_log(monkeypatch, tmp_path):
    """app.log 被当前进程占用：即使「全部型号」也不得列入清理清单。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _touch(str(log_dir / "app.log"))
    _touch(str(log_dir / "app.log.1"))
    _touch(str(log_dir / "H16_AgingTest_uptime.log"))
    monkeypatch.setattr(hc, "LOG_DIR", str(log_dir))

    # LOG_DIR 下的散落文件（含 app.log）一律不清理
    assert hc.plan_logs("H16", include_all_types=True) == []


def test_plan_logs_includes_matching_type_dirs(monkeypatch, tmp_path):
    """型号日志目录（output/logs/<型号>_AgingTest）参与清理。"""
    log_dir = tmp_path / "logs"
    (log_dir / "H16_AgingTest").mkdir(parents=True)
    _touch(str(log_dir / "H16_AgingTest" / "uptime.log"))
    (log_dir / "Q910_AgingTest").mkdir()
    _touch(str(log_dir / "Q910_AgingTest" / "uptime.log"))
    monkeypatch.setattr(hc, "LOG_DIR", str(log_dir))

    plan = hc.plan_logs("H16")
    assert [item.label for item in plan] == ["H16_AgingTest/"]
    assert plan[0].file_count == 1


def test_plan_monitor_data_lists_existing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(hc, "_abs", lambda *parts: str(tmp_path / os.path.join(*parts)))
    _touch(str(tmp_path / hc.DEVICE_DATA_FILE))
    _touch(str(tmp_path / "monitor_data" / "old.json"))

    labels = sorted(item.label for item in hc.plan_monitor_data())
    assert hc.DEVICE_DATA_FILE in labels
    assert "monitor_data/" in labels
    assert hc.ERROR_LOG_FILE not in labels        # 不存在则不列出


def test_plan_screenshot_matches_device_dirs(monkeypatch, tmp_path):
    _isolate_legacy(monkeypatch, tmp_path)
    shot_dir = tmp_path / "screenshot"
    (shot_dir / "H16-26-A0419").mkdir(parents=True)
    _touch(str(shot_dir / "H16-26-A0419" / "a.jpg"))
    (shot_dir / "Q910-D26-002B8").mkdir()
    _touch(str(shot_dir / "Q910-D26-002B8" / "b.jpg"))
    monkeypatch.setattr(hc, "SCREENSHOT_DIR", str(shot_dir))

    plan = hc.plan_screenshot("H16")
    assert [item.label for item in plan] == ["H16-26-A0419/"]
    assert plan[0].file_count == 1
    assert plan[0].is_dir is True


def test_plan_switch_log_includes_dirs_and_session_csv(monkeypatch, tmp_path):
    _isolate_legacy(monkeypatch, tmp_path)
    switch_dir = tmp_path / "switch_log"
    (switch_dir / "H16-26-A0419").mkdir(parents=True)
    _touch(str(switch_dir / "H16-26-A0419" / "swich_counter.csv"))
    (switch_dir / "Q910-D26-002B8").mkdir()
    _touch(str(switch_dir / "20261019_switch_log.csv"))
    monkeypatch.setattr(hc, "SWITCH_LOG_DIR", str(switch_dir))

    labels = sorted(item.label for item in hc.plan_switch_log("H16"))
    assert labels == ["20261019_switch_log.csv", "H16-26-A0419/"]


# ---------------------------------------------------------------- 汇总与预览

def test_build_plan_is_empty_for_no_scope():
    assert hc.build_plan("H16", []) == []
    assert hc.format_plan_preview([]) == "没有匹配到可清理的历史数据。"


def test_build_plan_follows_all_scopes_order(monkeypatch, tmp_path):
    _isolate_legacy(monkeypatch, tmp_path)
    log_dir = tmp_path / "logs"
    (log_dir / "H16_AgingTest").mkdir(parents=True)
    _touch(str(log_dir / "H16_AgingTest" / "uptime.log"))
    excel_dir = tmp_path / "excel"
    excel_dir.mkdir()
    _touch(str(excel_dir / "H16_a.xlsx"))
    monkeypatch.setattr(hc, "LOG_DIR", str(log_dir))
    monkeypatch.setattr(hc, "EXCEL_DIR", str(excel_dir))

    plan = hc.build_plan("H16", [hc.SCOPE_EXCEL, hc.SCOPE_LOGS])
    assert [item.scope for item in plan] == [hc.SCOPE_LOGS, hc.SCOPE_EXCEL]
    assert hc.plan_summary(plan) == {"items": 2, "files": 2}


def test_format_plan_preview_limits_file_list_and_shows_counts():
    files = [f"/d/{index}.jpg" for index in range(8)]
    item = hc.CleanItem(hc.SCOPE_SCREENSHOT, "H16-1/", "/d/H16-1", True, files)
    text = hc.format_plan_preview([item])

    assert "/d/H16-1" in text
    assert "文件数: 8" in text
    assert "/d/0.jpg" in text and "/d/4.jpg" in text
    assert "/d/5.jpg" not in text
    assert "其余 3 个文件略" in text


# ---------------------------------------------------------------- 执行

def test_execute_plan_removes_files_and_dirs(tmp_path):
    shot_dir = tmp_path / "shot" / "H16-1"
    shot_dir.mkdir(parents=True)
    _touch(str(shot_dir / "a.jpg"))
    log_file = tmp_path / "x.log"
    _touch(str(log_file))

    plan = [
        hc.CleanItem(hc.SCOPE_SCREENSHOT, "H16-1/", str(shot_dir), True,
                     [str(shot_dir / "a.jpg")]),
        hc.CleanItem(hc.SCOPE_LOGS, "x.log", str(log_file), False, [str(log_file)]),
    ]
    seen = []
    results = hc.execute_plan(plan, on_item=seen.append)

    assert [result.removed for result in results] == [1, 1]
    assert not shot_dir.exists()
    assert not log_file.exists()
    assert len(seen) == 2
    assert "删除 2 个文件" in hc.summarize_results(results)


def test_execute_plan_reports_failure(tmp_path, monkeypatch):
    shot_dir = tmp_path / "shot"
    shot_dir.mkdir()

    def _boom(_path):
        raise PermissionError("in use")

    monkeypatch.setattr(hc.shutil, "rmtree", _boom)
    plan = [hc.CleanItem(hc.SCOPE_SCREENSHOT, "shot/", str(shot_dir), True, [])]
    result = hc.execute_plan(plan)[0]

    assert result.ok is False
    assert "in use" in result.error
    assert "失败 1 个条目" in hc.summarize_results([result])
