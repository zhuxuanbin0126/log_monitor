#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备发现（找卡）子包：UDP 广播扫描与手动定向探测。

- :mod:`service.discovery.udp_finder`  局域网找卡（UDP 9527 限定广播）
- :mod:`service.discovery.manual_finder`  手动找卡（IP / 区间 / CIDR → 单播 + 广播兜底）
"""

from .udp_finder import scan_devices
from .manual_finder import parse_ip_spec, scan_targets

__all__ = ['scan_devices', 'parse_ip_spec', 'scan_targets']
