"""
设备配置加载模块

从 device_info.json 动态加载所有设备型号的配置信息，
支持新增型号时仅修改配置文件，无需修改代码。

对外仍保留原有模块级函数（向后兼容），内部统一由
DeviceConfigRepository 管理缓存与查询。
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional

# 直接计算项目根目录（与 config.py 同级）
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_DIR, "device_info.json")


class DeviceConfigRepository:
    """device_info.json 的加载、缓存与查询封装。

    实例化后可显式 load()/reload()，便于测试与配置热加载；
    默认实例由模块级单例提供，保持旧接口行为不变。
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._configs: Optional[List[Dict[str, Any]]] = None
        self._lookup: Dict[str, Dict[str, Any]] = {}

    @property
    def config_path(self) -> str:
        return self._config_path

    def load(self, force: bool = False) -> None:
        """加载配置文件；force=True 时重新读取磁盘。"""
        with self._lock:
            if self._configs is not None and not force:
                return
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    configs = json.load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f"设备配置文件不存在: {self._config_path}")
            except json.JSONDecodeError as e:
                raise ValueError(f"设备配置文件格式错误: {self._config_path}, 错误: {str(e)}")
            except Exception as e:
                raise RuntimeError(f"加载设备配置文件失败: {self._config_path}, 错误: {str(e)}")

            if not isinstance(configs, list):
                raise ValueError(f"设备配置文件根节点必须为列表: {self._config_path}")

            lookup = {}
            for item in configs:
                if not isinstance(item, dict):
                    continue
                model = item.get("型号", "")
                if model:
                    lookup[model] = item

            self._configs = configs
            self._lookup = lookup

    def reload(self) -> None:
        """强制重新加载配置文件。"""
        self.load(force=True)

    def get_config(self, device_type_prefix: str) -> Optional[Dict[str, Any]]:
        """按型号前缀获取完整配置；找不到返回 None。"""
        if not device_type_prefix:
            return None
        self.load()
        with self._lock:
            return self._lookup.get(device_type_prefix)

    def get_field(self, device_type_prefix: str, field_name: str,
                  default: Any = None) -> Any:
        """按字段名读取配置，统一替代多个同质化 getter。"""
        config = self.get_config(device_type_prefix)
        if not config:
            return default
        return config.get(field_name, default)

    def get_all_models(self) -> List[str]:
        self.load()
        with self._lock:
            return list(self._lookup.keys())

    def get_init_config(self, device_type_prefix: str) -> Optional[Dict[str, Any]]:
        """获取设备开关机初始化配置。"""
        return self.get_field(device_type_prefix, "开关机初始化")

    def get_upgrade_config(self, device_type_prefix: str) -> Optional[Dict[str, Any]]:
        """获取设备发送节目配置。"""
        return self.get_field(device_type_prefix, "发送节目")

    def get_otg_config(self, device_type_prefix: str) -> Optional[str]:
        """获取设备 OTG 配置命令；未配置或为 "nan" 时返回 None。"""
        otg = self.get_field(device_type_prefix, "保存OTG属性", "nan")
        if otg and otg != "nan":
            return otg
        return None

    def get_system_version(self, device_type_prefix: str) -> str:
        return self.get_field(device_type_prefix, "系统版本", "")

    def get_chip_model(self, device_type_prefix: str) -> str:
        return self.get_field(device_type_prefix, "主控型号", "")

    def get_init_grouped_configs(self, selected_device_types: List[str]) -> Dict[str, Dict[str, Any]]:
        """按开关机初始化配置签名分组，返回 {group_key: group_data}。"""
        self.load()
        groups: Dict[str, Dict[str, Any]] = {}

        for dev_type in selected_device_types:
            with self._lock:
                config = self._lookup.get(dev_type)
            if not config:
                groups[f"unknown_{dev_type}"] = {
                    "devices": [dev_type],
                    "config": None,
                    "chip_model": "未知",
                    "system_version": "未知",
                }
                continue

            init_config = config.get("开关机初始化")
            if not init_config:
                groups[f"no_init_{dev_type}"] = {
                    "devices": [dev_type],
                    "config": None,
                    "chip_model": config.get("主控型号", "未知"),
                    "system_version": config.get("系统版本", "未知"),
                }
                continue

            # 使用配置签名作为分组 key（相同配置的设备归入同一组）
            config_signature = json.dumps(init_config, sort_keys=True, ensure_ascii=False)
            if config_signature not in groups:
                groups[config_signature] = {
                    "devices": [],
                    "config": init_config,
                    "chip_model": config.get("主控型号", "未知"),
                    "system_version": config.get("系统版本", "未知"),
                }
            groups[config_signature]["devices"].append(dev_type)

        return groups

    def get_upgrade_grouped_configs(self, selected_device_types: List[str]) -> Dict[str, Dict[str, Any]]:
        """按系统类型 + 发送节目配置签名分组。"""
        self.load()
        groups: Dict[str, Dict[str, Any]] = {}

        def _system_type_label(config: Dict[str, Any]) -> str:
            version = config.get("系统版本", "")
            if "安卓" in version or "android" in version.lower():
                return "安卓系列"
            return "常规系列"

        for dev_type in selected_device_types:
            with self._lock:
                config = self._lookup.get(dev_type)
            if not config:
                groups[f"unknown_{dev_type}"] = {
                    "devices": [dev_type],
                    "config": None,
                    "system_type": "未知",
                }
                continue

            upgrade_config = config.get("发送节目")
            if not upgrade_config:
                groups[f"no_upgrade_{dev_type}"] = {
                    "devices": [dev_type],
                    "config": None,
                    "system_type": _system_type_label(config),
                }
                continue

            sys_type = _system_type_label(config)
            config_signature = json.dumps(upgrade_config, sort_keys=True, ensure_ascii=False)
            group_key = f"{sys_type}_{config_signature}"
            if group_key not in groups:
                groups[group_key] = {
                    "devices": [],
                    "config": upgrade_config,
                    "system_type": sys_type,
                }
            groups[group_key]["devices"].append(dev_type)

        return groups


# 模块级默认实例：保持旧函数调用方式不变
_default_repository = DeviceConfigRepository()


# ============================================================
# 向后兼容的模块级函数
# ============================================================

def get_device_config(device_type_prefix):
    """根据设备型号前缀获取完整配置；找不到返回 None。"""
    return _default_repository.get_config(device_type_prefix)


def get_init_config(device_type_prefix):
    """获取设备开关机初始化配置。"""
    return _default_repository.get_init_config(device_type_prefix)


def get_upgrade_config(device_type_prefix):
    """获取设备发送节目配置。"""
    return _default_repository.get_upgrade_config(device_type_prefix)


def get_otg_config(device_type_prefix):
    """获取设备 OTG 配置命令；未配置或为 "nan" 时返回 None。"""
    return _default_repository.get_otg_config(device_type_prefix)


def get_system_version(device_type_prefix):
    """获取设备系统版本。"""
    return _default_repository.get_system_version(device_type_prefix)


def get_chip_model(device_type_prefix):
    """获取设备主控型号。"""
    return _default_repository.get_chip_model(device_type_prefix)


def get_all_models():
    """获取所有已知型号列表。"""
    return _default_repository.get_all_models()


def reload_device_info():
    """重新加载 device_info.json（配置热加载）。"""
    _default_repository.reload()


def get_init_grouped_configs(selected_device_types):
    """按开关机初始化配置分组。"""
    return _default_repository.get_init_grouped_configs(selected_device_types)


def get_upgrade_grouped_configs(selected_device_types):
    """按系统类型 + 发送节目配置分组。"""
    return _default_repository.get_upgrade_grouped_configs(selected_device_types)
