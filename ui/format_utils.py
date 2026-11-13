# -*- coding: utf-8 -*-

"""与 Qt 无关的通用格式化函数。

单独成模块，便于在无图形环境（Linux CI、无显示器的服务器）直接导入测试，
避免为了验证纯字符串逻辑而被迫加载 QtWidgets / libEGL。
"""


def format_duration(seconds):
    """秒数 → 人类可读耗时：``12.3s`` / ``3分05秒`` / ``1时02分03秒``。"""
    if seconds is None:
        return "未知"
    if seconds < 60:
        return f"{seconds:.1f}s"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}时{minutes:02d}分{secs:02d}秒"
    return f"{minutes}分{secs:02d}秒"
