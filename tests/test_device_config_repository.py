"""DeviceConfigRepository 显式实例与热加载测试。"""

import json

from device_config import DeviceConfigRepository

CONFIGS = [
    {
        "型号": "D16",
        "主控型号": "PX30",
        "系统版本": "Linux",
        "开关机初始化": {"files": [], "flag_path": "/tmp/flag"},
        "发送节目": {"program_name": "D16_project.tar.gz", "remote_dir": "/root/Box/project"},
        "保存OTG属性": "nan",
    },
    {
        "型号": "A3L",
        "主控型号": "RK3328",
        "系统版本": "安卓 11",
        "开关机初始化": {"files": [{"local": "a.sh", "remote": "/system/bin/a.sh"}]},
        "发送节目": {"program_name": "A3L_project.tar.gz", "remote_dir": "/data"},
        "保存OTG属性": "echo host > /sys/otg",
    },
]


def _write(tmp_path, configs):
    path = tmp_path / "device_info.json"
    path.write_text(json.dumps(configs, ensure_ascii=False), encoding="utf-8")
    return path


def test_repository_loads_and_queries(tmp_path):
    repo = DeviceConfigRepository(str(_write(tmp_path, CONFIGS)))
    assert repo.get_config("D16")["主控型号"] == "PX30"
    assert repo.get_field("D16", "系统版本") == "Linux"
    assert repo.get_field("NOPE", "系统版本", "默认") == "默认"
    assert repo.get_otg_config("D16") is None
    assert repo.get_otg_config("A3L") == "echo host > /sys/otg"
    assert set(repo.get_all_models()) == {"D16", "A3L"}


def test_repository_reload_picks_up_changes(tmp_path):
    path = _write(tmp_path, CONFIGS)
    repo = DeviceConfigRepository(str(path))
    assert repo.get_chip_model("D16") == "PX30"

    updated = json.loads(path.read_text(encoding="utf-8"))
    updated[0]["主控型号"] = "RK3568"
    path.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf-8")

    assert repo.get_chip_model("D16") == "PX30"  # 未 reload 前使用缓存
    repo.reload()
    assert repo.get_chip_model("D16") == "RK3568"


def test_repository_missing_file_raises(tmp_path):
    repo = DeviceConfigRepository(str(tmp_path / "missing.json"))
    try:
        repo.load()
    except FileNotFoundError as e:
        assert "设备配置文件不存在" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_repository_grouping(tmp_path):
    repo = DeviceConfigRepository(str(_write(tmp_path, CONFIGS)))
    init_groups = repo.get_init_grouped_configs(["D16", "A3L", "UNKNOWN"])
    assert sum(len(g["devices"]) for g in init_groups.values()) == 3

    upgrade_groups = repo.get_upgrade_grouped_configs(["D16", "A3L"])
    labels = {g["system_type"] for g in upgrade_groups.values()}
    assert labels == {"常规系列", "安卓系列"}
