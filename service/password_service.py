#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备密码服务：按 ``device_id`` 缓存 + 并发安全地获取 SSH 密码。

替代原先对 ``HPassword.exe`` 外部程序的调用；计算走
:mod:`service.password_engine` 的纯 Python 引擎。

缓存按 ``device_id`` 维度（而非单值），切换设备不会返回上一台设备的密码。
"""

import threading
from typing import Dict, List, Optional

from .logging_service import get_logger
from .password_engine import generate_password

logger = get_logger(__name__)


class PasswordService:
    """密码获取服务（按设备维度缓存 + 并发安全）。"""

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._lock = threading.RLock()

    def get_password(self, device_id: str, use_cache: bool = True) -> str:
        """获取设备 SSH 密码；无法计算时返回空字符串。

        Args:
            device_id: 设备 ID（如 ``H20-00-A0208``）
            use_cache: 是否使用缓存，默认使用
        """
        if not device_id:
            return ""

        if use_cache:
            with self._lock:
                cached = self._cache.get(device_id)
            if cached is not None:
                return cached

        password = generate_password(device_id)
        if not password:
            logger.error("设备 %s 密码计算失败: 结果为空", device_id)
            return ""

        with self._lock:
            self._cache[device_id] = password
        logger.info("设备 %s 密码计算成功", device_id)
        return password

    def clear_cache(self, device_id: Optional[str] = None) -> None:
        """清除缓存：指定 ``device_id`` 时只清该设备，为 None 时清空全部。"""
        with self._lock:
            if device_id is None:
                self._cache.clear()
                return
            self._cache.pop(device_id, None)

    def cached_device_ids(self) -> List[str]:
        """返回当前已缓存密码的设备 ID 列表（便于排查/测试）。"""
        with self._lock:
            return list(self._cache.keys())


# 模块级单例：业务层共用同一份缓存
_default_service = PasswordService()


def get_password(device_id: str, use_cache: bool = True) -> str:
    """基于默认单例获取设备密码。"""
    return _default_service.get_password(device_id, use_cache)


def get_password_service() -> PasswordService:
    """获取默认密码服务单例。"""
    return _default_service
