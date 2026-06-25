"""
设备配置加载模块
从 device_info.json 动态加载所有设备型号的配置信息，
支持新增型号时仅修改配置文件，无需修改代码。
"""

import json
import os

# 直接计算项目根目录（与 config.py 同级）
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# 缓存已加载的配置
_device_info_cache = None
_device_lookup = None  # 型号 -> 配置的快速查找表


def _load_device_info():
    """加载 device_info.json 并建立型号查找表"""
    global _device_info_cache, _device_lookup
    
    if _device_info_cache is not None:
        return
    
    config_path = os.path.join(_PROJECT_DIR, "device_info.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _device_info_cache = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"设备配置文件不存在: {config_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"设备配置文件格式错误: {config_path}, 错误: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"加载设备配置文件失败: {config_path}, 错误: {str(e)}")
    
    _device_lookup = {}
    for item in _device_info_cache:
        model = item.get("型号", "")
        if model:
            _device_lookup[model] = item


def get_device_config(device_type_prefix):
    """
    根据设备型号前缀获取完整配置
    
    参数:
        device_type_prefix: 设备型号前缀，如 "D16", "A7", "H16"
    
    返回:
        dict: 设备配置字典，包含所有字段；如果找不到则返回 None
    """
    _load_device_info()
    return _device_lookup.get(device_type_prefix)


def get_init_config(device_type_prefix):
    """
    获取设备开关机初始化配置
    
    返回:
        dict: {
            "files": [{"local": "xxx", "remote": "/path/xxx", "desc": "描述"}, ...],
            "flag_path": "/flag/path",
            "extra_commands": ["cmd1", "cmd2", ...]
        }
        如果未配置则返回 None
    """
    config = get_device_config(device_type_prefix)
    if config:
        return config.get("开关机初始化")
    return None


def get_upgrade_config(device_type_prefix):
    """
    获取设备发送节目配置
    
    返回:
        dict: {
            "program_name": "{model}_project.tar.gz",
            "remote_dir": "/path/to/program",
            "restart_cmd": "restart command",
            "pre_commands": ["cmd1", ...]
        }
        如果未配置则返回 None
    """
    config = get_device_config(device_type_prefix)
    if config:
        return config.get("发送节目")
    return None


def get_otg_config(device_type_prefix):
    """
    获取设备OTG配置命令
    
    返回:
        str: OTG配置命令，如果未配置或为 "nan" 则返回 None
    """
    config = get_device_config(device_type_prefix)
    if config:
        otg = config.get("保存OTG属性", "nan")
        if otg and otg != "nan":
            return otg
    return None


def get_system_version(device_type_prefix):
    """获取设备系统版本"""
    config = get_device_config(device_type_prefix)
    if config:
        return config.get("系统版本", "")
    return ""


def get_chip_model(device_type_prefix):
    """获取设备主控型号"""
    config = get_device_config(device_type_prefix)
    if config:
        return config.get("主控型号", "")
    return ""


def get_all_models():
    """获取所有已知型号列表"""
    _load_device_info()
    return list(_device_lookup.keys())


def get_init_grouped_configs(selected_device_types):
    """
    根据选中的设备类型列表，按配置分组返回
    
    参数:
        selected_device_types: 设备型号前缀列表，如 ["D16", "A7", "H16"]
    
    返回:
        dict: {
            group_key: {
                "devices": ["D16", "D36", ...],
                "config": {...},  # 开关机初始化配置
                "chip_model": "PX30",
                "system_version": "Liunx"
            }
        }
    """
    _load_device_info()
    groups = {}
    
    for dev_type in selected_device_types:
        config = _device_lookup.get(dev_type)
        if not config:
            # 未知设备类型
            group_key = f"unknown_{dev_type}"
            groups[group_key] = {
                "devices": [dev_type],
                "config": None,
                "chip_model": "未知",
                "system_version": "未知"
            }
            continue
        
        init_config = config.get("开关机初始化")
        if not init_config:
            group_key = f"no_init_{dev_type}"
            groups[group_key] = {
                "devices": [dev_type],
                "config": None,
                "chip_model": config.get("主控型号", "未知"),
                "system_version": config.get("系统版本", "未知")
            }
            continue
        
        # 使用配置的签名作为分组key（相同配置的设备归入同一组）
        config_signature = json.dumps(init_config, sort_keys=True, ensure_ascii=False)
        chip = config.get("主控型号", "未知")
        version = config.get("系统版本", "未知")
        
        if config_signature not in groups:
            groups[config_signature] = {
                "devices": [],
                "config": init_config,
                "chip_model": chip,
                "system_version": version
            }
        groups[config_signature]["devices"].append(dev_type)
    
    return groups


def get_upgrade_grouped_configs(selected_device_types):
    """
    根据选中的设备类型列表，按系统类型分组返回（安卓系列 / 常规系列）
    
    返回:
        dict: {
            group_key: {
                "devices": ["D16", "D36", ...],
                "config": {...},  # 发送节目配置
                "system_type": "安卓系列" | "常规系列"
            }
        }
    """
    _load_device_info()
    groups = {}
    
    def _get_system_type_label(config):
        """根据系统版本判断系统类型"""
        version = config.get("系统版本", "")
        if "安卓" in version or "android" in version.lower():
            return "安卓系列"
        return "常规系列"
    
    for dev_type in selected_device_types:
        config = _device_lookup.get(dev_type)
        if not config:
            group_key = f"unknown_{dev_type}"
            groups[group_key] = {
                "devices": [dev_type],
                "config": None,
                "system_type": "未知"
            }
            continue
        
        upgrade_config = config.get("发送节目")
        if not upgrade_config:
            group_key = f"no_upgrade_{dev_type}"
            groups[group_key] = {
                "devices": [dev_type],
                "config": None,
                "system_type": _get_system_type_label(config)
            }
            continue
        
        sys_type = _get_system_type_label(config)
        config_signature = json.dumps(upgrade_config, sort_keys=True, ensure_ascii=False)
        # 按系统类型 + 配置签名分组
        group_key = f"{sys_type}_{config_signature}"
        
        if group_key not in groups:
            groups[group_key] = {
                "devices": [],
                "config": upgrade_config,
                "system_type": sys_type
            }
        groups[group_key]["devices"].append(dev_type)
    
    return groups