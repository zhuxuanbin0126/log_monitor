#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""应用程序配置文件"""

import os
import sys

VERSION = '1.0.6.3'

# ============================================================
# 路径计算
# ============================================================

def get_project_root():
    """获取项目根目录，支持打包后的环境"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


PROJECT_ROOT = get_project_root()


def _external_or_bundled(*parts):
    """**外部（exe 旁边）优先**，缺失才回退到 exe 内解压的副本。

    打包后 onefile 会把 datas 解到 ``%TEMP%\\_MEIxxxx``；部分电脑的临时目录不可写
    （或被杀软拦截），从那里读脚本/推文件都会失败。发布包在 exe 旁带了一份
    ``tools/``，因此这里一律优先用外部真实路径。
    """
    external = os.path.join(PROJECT_ROOT, *parts)
    if os.path.exists(external):
        return external
    bundled_root = getattr(sys, '_MEIPASS', '')
    if bundled_root:
        bundled = os.path.join(bundled_root, *parts)
        if os.path.exists(bundled):
            return bundled
    return external


# ---- 工具与节目路径 ----
TOOL_PATH = _external_or_bundled("tools")
PROGRAM_PATH = _external_or_bundled("program")
GET_INFO_PATH = _external_or_bundled("tools", "getdeviceinfo.sh")

# ---- 输出目录 ----
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
DATA_DIR = os.path.join(OUTPUT_DIR, "data")
SCREENSHOT_DIR = os.path.join(OUTPUT_DIR, "screenshot")
SWITCH_LOG_DIR = os.path.join(OUTPUT_DIR, "switch_log")
EXCEL_DIR = os.path.join(OUTPUT_DIR, "excel")
TASK_CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "task_checkpoint.json")
"""未完成任务检查点：任务被中断/程序关闭后，下次启动据此继续未完成的设备"""

# ============================================================
# 设备类型配置
# ============================================================

SUPPORTED_DEV_TYPES = (
    'A-B-C-D-H', 'A3L', 'A4L', 'A5L', 'A6L', 'B6L', 'B8L',
    'C08L', 'C16H', 'H4K', 'H6', 'H8', 'D16', 'C16L',
    'A7', 'A8', 'H20', 'H16', 'Q910',
)
"""支持的设备类型列表（元组，不可变；``Q910`` 为定制款 Linux 机型）"""

DEFAULT_DEV_TYPE = 'A-B-C-D-H'
"""默认设备类型"""

# ============================================================
# 文件路径配置
# ============================================================

DEVICE_DATA_FILE = 'device_monitoring_data.json'
ERROR_LOG_FILE = 'device_error.txt'

# ============================================================
# 监控与时间阈值配置
# ============================================================

DEFAULT_DELAY_SECONDS = 60
"""默认监控间隔（秒）"""

BOOT_TIME_DIFF_THRESHOLD_SECONDS = 120
"""启动时间误差阈值（秒）"""

DAILY_TIME_DIFF_THRESHOLD_SECONDS = 3
"""设备时间日均误差阈值（秒）"""

# ============================================================
# 外部命令超时与重试配置
# ============================================================

ADB_COMMAND_TIMEOUT = 30
"""ADB 命令默认超时（秒）"""

MAX_RETRY_COUNT = 3
"""默认最大重试次数"""

DELAY_INPUT_MIN = 10
"""监控间隔输入下限（秒）"""

DELAY_INPUT_MAX = 86400
"""监控间隔输入上限（秒）"""

PROCESS_SLEEP_MS = 100
"""设备间处理间隔（毫秒）"""

ADB_DISCONNECT_DELAY_MS = 500
"""ADB 断开后等待时间（毫秒）"""

CONNECTION_STABILIZE_SECONDS = 2
"""连接建立后稳定等待时间（秒）"""

DEFAULT_SCREENSHOT_PATH = "./screenshot"
"""默认截图存储路径"""

QUERY_MAX_WORKERS = 16
"""协议可用设备的最大并发查询数。

每台设备是**独立 TCP 连接**（源端口各自分配），16 个并发连接对本机临时端口
（约 1.6 万）与局域网带宽都毫无压力；12 台规模可一次派完，不再分两批。"""

LEGACY_QUERY_MAX_WORKERS = 4
"""无协议设备（走 adb/SSH）的最大并发数。

adb server 为单进程，仍要克制；但所有 adb 操作已改为「只断开本设备」，
4 台并发不会互相打断（此前全局 `adb disconnect` 会误伤并行设备）。"""

LINUX_SSH_MAX_WORKERS = 4
"""Linux 机型（C08L/C16L/D16/D36/Q910）的 SSH 并发上限。

这些设备只有 SSH 一条通道，每台是**独立连接**（paramiko 连接池按 host 隔离），
并发 4 台可消除「多台 Linux 设备排队」的成倍等待；现场设备多为低配 ARM，
4 台并发的负载仍很轻。"""

DEVICE_PROBE_TIMEOUT = 0.8
"""派发前 TCP 可达性探测超时（秒）。

设备在任务期间掉线（人为断电/网线松动）时，不再让协议/ADB 各自等满超时
（单台可达十几秒），而是秒级判定「离线」并跳过；任务结束后会再试一次。"""

SCREENSHOT_MAX_WORKERS = 16
"""协议截图的最大并发数。

单张截图在设备侧要先成像（实测 4~5s）再经独立 TCP 回传 5MB 级 PNG，
把并发放宽到 16 台，12 台规模可**一次派完**、总耗时≈单台耗时；
每台设备一个独立出站连接，16 个连接远低于本机临时端口上限（约 1.6 万），
不会耗尽端口，也不影响下位机/上位机的正常通信。
"""

TRANSFER_MAX_ATTEMPTS = 2
"""协议文件通道的传输尝试次数：第 2 次带 offset 续传（断点续传）"""



# ============================================================
# 日志目录配置
# ============================================================

def get_base_dir(dev_type):
    """根据设备类型获取基础日志目录"""
    return os.path.join(OUTPUT_DIR, 'logs', f'{dev_type}_AgingTest')

# ============================================================
# 命令配置
# ============================================================

def get_device_list_pattern(dev_type):
    """获取设备列表的过滤模式"""
    return dev_type.replace('-', '|')


# ============================================================
# 设备发现（找卡）配置
# ============================================================

USE_UDP_DISCOVERY = True
"""找卡方式开关：True 走 UDP 9527 协议找卡；False 回退旧的 DeviceId.exe 扫描"""

UDP_DISCOVERY_PORT = 9527
"""设备找卡 UDP 端口（DeviceId.exe / MagicCatRelay 均使用）"""

UDP_PROBE_PACKET = bytes([0x00, 0x00, 0x00, 0x02, 0x01, 0x00])
"""广播探测包（6 字节，抓包确认）"""

UDP_PROBE_INTERVAL = 1.0
"""探测包重发间隔（秒）：设备应答可能延迟数秒，需周期性重发"""

UDP_QUIET_WINDOW = 3.5
"""收敛静默窗口（秒）：最后一台设备后仍需静默等待的时长"""

UDP_MIN_SCAN_SECONDS = 6.0
"""最短扫描时长（秒）：防止快设备先应答就过早收尾"""

UDP_SCAN_TIMEOUT = 30.0
"""扫描总超时（秒，上限保护）"""

PROBE_MAX_TARGETS = 1024
"""手动找卡目标 IP 数量上限（防止 /16 大区间跑成数分钟）"""

PROBE_CONCURRENCY = 48
"""手动找卡单播探测并发度"""

PROBE_PER_TARGET_TIMEOUT = 2.0
"""手动找卡逐 IP 单播等待响应超时（秒）"""

PROBE_BROADCAST_MOPUP_TIMEOUT = 8.0
"""手动找卡中广播兜底的总超时（秒，短窗口加速收尾）"""

PROBE_BROADCAST_MOPUP_MIN_SCAN = 1.5
"""手动找卡中广播兜底的最短扫描时长（秒）"""

PROBE_BROADCAST_MOPUP_QUIET = 1.5
"""手动找卡中广播兜底的静默收敛窗口（秒）"""

PROBE_BROADCAST_MOPUP_INTERVAL = 0.5
"""手动找卡中广播兜底的探测重发间隔（秒）"""

# ============================================================
# 后台心跳找卡配置
# ============================================================

BACKGROUND_DISCOVERY_ENABLED = True
"""后台心跳找卡开关：**监控未运行**时周期性静默探测设备上下线"""

BACKGROUND_DISCOVERY_INTERVAL_MS = 3000
"""心跳间隔（毫秒）：两轮「在场探测」之间的等待"""

BACKGROUND_DISCOVERY_PROBE_SECONDS = 2.0
"""单轮「在场探测」时长（秒）：期间按 ``UDP_PROBE_INTERVAL`` 周期重发探测包"""

BACKGROUND_DISCOVERY_OFFLINE_GRACE = 4
"""判定设备下线的连续未应答轮数（抗设备应答节流导致的抖动）"""


# ============================================================
# MagicPlayer 协议查询配置
# ============================================================

USE_PROTOCOL_QUERY = True
"""协议查询开关：True 时设备时间/运行时长优先走 MagicPlayer 协议（TCP 10001），失败回落 adb/SSH"""

PROTOCOL_PORT = 10001
"""MagicPlayer 协议端口（设备主动下发 4 字节问候，上位机回 0x0060 握手包）"""

PROTOCOL_VERSION = 5
"""Socket 通道出站协议版本（统一口径，对齐官方上位机 HDPlayer）"""

PROTOCOL_CONNECT_TIMEOUT = 1.5
"""协议 TCP 建连超时（秒）"""

PROTOCOL_RECV_TIMEOUT = 1.5
"""协议响应接收超时（秒）"""

PROTOCOL_STATUS_TTL = 5.0
"""协议查询成功结果的短时缓存（秒）：避免同一轮询内重复往返"""

PROTOCOL_UNSUPPORTED_TTL = 300.0
"""协议不可用（不支持/不可达）的负缓存（秒）：避免每轮询都白等建连超时"""

PROTOCOL_EXEC_START = "su"
"""Command.exec 执行方式：``su``（以 su 执行，默认）/ ``sh``（以 sh 执行）"""

PROTOCOL_FILE_RECV_TIMEOUT = 60.0
"""协议「文件通道」接收总超时（秒）：设备侧截图/打包耗时较长（实测截图 4~5s 才回）"""

PROTOCOL_UPTIME_IN_MS = True
"""``DeviceInfo.uptime`` 单位开关：True = 毫秒（真机实测），False = 秒。

真机实测（H20 / A6L 等）：设备实际开机 4 天 7 小时（≈3.7e5 秒），上报值 ≈3.7e8，
按秒解读会得到「4290 天」这种天文数字 —— 故默认按毫秒换算。
"""

# ============================================================
# 设备密码计算配置
# ============================================================

USE_PYTHON_PASSWORD = True
"""密码计算开关：True 用纯 Python 引擎（等价 HPassword.exe）；False 回退调用 HPassword.exe"""

# ============================================================
# 系统类型与远程路径映射
# ============================================================

_SYSTEM_TYPE_PATH_MAP = {
    "android": "/data",
    "linux": "/root/Box/project",
}
DEFAULT_REMOTE_PATH = "/root/Box/project"
"""默认远程路径（用于无法识别的系统类型）"""


def get_device_remote_path(system_type: str) -> str:
    """根据系统类型返回设备端远程数据路径
    
    集中管理 Android/Linux 设备的核心数据目录映射，
    支持中文"安卓"和英文"android"两种系统版本标识。
    """
    if not system_type:
        return DEFAULT_REMOTE_PATH
    sys_type = system_type.lower()
    # 支持中文"安卓"和英文"android"/"安卓"两种标识
    if "android" in sys_type or "安卓" in system_type:
        return _SYSTEM_TYPE_PATH_MAP["android"]
    if "linux" in sys_type:
        return _SYSTEM_TYPE_PATH_MAP["linux"]
    return DEFAULT_REMOTE_PATH


# ============================================================
# 向后兼容别名（过渡期使用，后续版本将移除）
# ============================================================

tool_path = TOOL_PATH
program_path = PROGRAM_PATH
getinfo_path = GET_INFO_PATH
supported_dev_types = list(SUPPORTED_DEV_TYPES)  # 可变副本，兼容旧代码
default_dev_type = DEFAULT_DEV_TYPE
device_data_file = DEVICE_DATA_FILE
error_log_file = ERROR_LOG_FILE
default_delay_time = DEFAULT_DELAY_SECONDS
time_diff_threshold = BOOT_TIME_DIFF_THRESHOLD_SECONDS
daily_time_diff_threshold = DAILY_TIME_DIFF_THRESHOLD_SECONDS
