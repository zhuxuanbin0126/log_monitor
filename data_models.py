#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享数据模型模块

提供项目内通用的数据类，用于替代裸字典和超长参数列表。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# ============================================================
# 查询结果模型
# ============================================================

@dataclass
class OperationResult:
    """统一的操作结果模型"""
    success: bool
    data: Any = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    @property
    def message(self) -> str:
        """面向 UI 的单行结果文本：成功取 data，失败取 error。"""
        if self.success:
            return "" if self.data is None else str(self.data)
        return self.error or ""


# ============================================================
# 设备状态模型
# ============================================================

@dataclass
class DeviceState:
    """单台设备的监控状态数据"""
    device_id: str = ""

    # 运行时间相关
    initial_os_time: str = ""
    initial_boot_time: str = ""
    last_boot_time: str = ""
    last_boot_change_time: str = ""
    last_uptime: str = ""

    # 设备时间相关
    initial_card_time: str = ""
    last_card_time: str = ""
    initial_time_diff: Optional[int] = None
    last_time_diff: Optional[int] = None
    last_card_time_change_time: str = ""
    initial_timestamp: Optional[float] = None

    # 启动次数相关
    initial_start_count: Optional[int] = None
    last_start_count: Optional[Union[int, str]] = None
    last_start_count_change_time: str = ""
    os_now_time: str = ""

    @classmethod
    def from_dict(cls, device_id: str, data: Dict[str, Any]) -> "DeviceState":
        """从字典构建 DeviceState，自动过滤已知字段"""
        known_fields = {
            'device_id', 'initial_os_time', 'initial_boot_time', 'last_boot_time',
            'last_boot_change_time', 'last_uptime', 'initial_card_time', 'last_card_time',
            'initial_time_diff', 'last_time_diff', 'last_card_time_change_time',
            'initial_timestamp', 'initial_start_count', 'last_start_count',
            'last_start_count_change_time', 'os_now_time',
        }
        state = cls(device_id=device_id)
        for key, value in data.items():
            if key in known_fields and hasattr(state, key):
                setattr(state, key, value)
        return state

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（用于 JSON 持久化），排除 None 值和 device_id"""
        result = {}
        for field_name in self.__dataclass_fields__:
            if field_name == 'device_id':
                continue
            value = getattr(self, field_name)
            if value is not None and value != "":
                result[field_name] = value
        return result


# ============================================================
# 监控配置模型
# ============================================================

@dataclass
class MonitorConfig:
    """监控线程配置，替代 13 个参数的 __init__"""
    dev_type: str
    delay_time: int = 60
    monitor_time: bool = True
    monitor_boot: bool = True
    monitor_start_count: bool = True
    capture_screenshot: bool = False
    screenshot_path: str = "./screenshot"
    selected_devices: List[Any] = field(default_factory=list)
    first_time_data: Dict[str, Any] = field(default_factory=dict)
    screenshot_failed_devices: List[str] = field(default_factory=list)
    time_failed_devices: List[str] = field(default_factory=list)
    boot_failed_devices: List[str] = field(default_factory=list)
    start_count_failed_devices: List[str] = field(default_factory=list)


# ============================================================
# 查询类型枚举
# ============================================================

from enum import Enum


class QueryType(Enum):
    """查询/操作类型枚举"""
    ALL = "all"
    TIME = "time"
    BOOT_TIME = "boot_time"
    START_COUNT = "start_count"
    SUM_SWITCH = "sum_switch"
    CLEAN_SWITCH = "clean_switch"
    CHECK_TIME = "check_time"
    UPGRADE_PROGRAM = "upgrade_program"
    SCREENSHOT = "screenshot"
    OUTPUT_LOG = "output_log"
    COUNT_INIT = "count_init"
