#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：清空 B6L-26-055E3 开关机次数
======================================
1. 查询当前开关机次数（基准）
2. 执行清空操作
3. 再次查询开关机次数（验证）
4. 比对结果，诊断失败原因
"""

import sys
import os
import time

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from config import get_device_remote_path
from service.tool_service import ToolService
from service.adb_service import ADBService
from business.device_log_service import DeviceLogService
from business.device_monitor_service import DeviceMonitorService

DEVICE_ID = "B6L-26-055E3"
DEVICE_IP = "192.168.2.71"
SYSTEM_TYPE = "安卓 11"
DEV_TYPE = "B6L"

# ── 辅助函数 ──────────────────────────────────────────

def get_password(device_id):
    """获取设备密码"""
    pwd = ToolService.get_password(device_id)
    if not pwd:
        print("[WARN] HPassword.exe 返回空密码，尝试使用已知密码")
        # B6L 系列常见默认密码
        for candidate in ["123456", "admin", "admin123", ""]:
            if candidate:
                print(f"  尝试密码: {candidate}")
            return candidate or "123456"
    return pwd

def print_separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── 主流程 ────────────────────────────────────────────

def main():
    print_separator(f"清空开关机次数测试 - {DEVICE_ID} ({DEVICE_IP})")

    # Step 0: 获取密码
    password = get_password(DEVICE_ID)
    print(f"[0] 设备密码: {'***' if password else '(空)'}")

    # 获取远程路径
    remote_path = get_device_remote_path(SYSTEM_TYPE)
    print(f"[0] 远程路径: {remote_path}")
    print(f"[0] Android设备: {ToolService.is_android_device(DEVICE_ID)}")

    # Step 1: 基准查询
    print_separator("Step 1: 查询当前开关机次数（基准）")

    # 先确保 ADB 可达
    print("[1.1] 尝试 ADB 连接...")
    ToolService.adb_disconnect()
    time.sleep(0.5)
    stdout, stderr, rc = ADBService.connect(DEVICE_IP)
    print(f"  adb connect → rc={rc}, stdout={stdout!r}, stderr={stderr!r}")

    # 初始化 SSH（查询操作需要）
    print("[1.2] 初始化 SSH 连接...")
    stdout, stderr, rc = ToolService.initialize_connection(DEVICE_IP, password)
    print(f"  SSH init → rc={rc}")

    # 直接检查文件是否存在（用 ADB）
    print("[1.3] 直接检查文件是否存在（ADB）...")
    swich_path = f"{remote_path}/swich_counter.csv"
    network_path = f"{remote_path}/network_counter.csv"

    for fpath in [swich_path, network_path]:
        exists = ToolService.check_file_exists(DEVICE_ID, DEVICE_IP, password, fpath, max_retries=2)
        print(f"  {fpath}: {'EXISTS' if exists else 'NOT FOUND'}")

    # 读取文件内容
    print("[1.4] 直接读取文件内容...")
    for fpath in [swich_path, network_path]:
        stdout, stderr, rc = ToolService.execute_query_command(
            DEVICE_ID, DEVICE_IP, password, f"cat {fpath}", "."
        )
        content = stdout.strip() if stdout else "(empty/stderr)"
        print(f"  cat {fpath}:")
        print(f"    stdout={content[:200]}")
        if stderr:
            print(f"    stderr={stderr[:200]}")

    # 使用业务接口查询
    print("[1.5] 使用 sum_switch_count 查询...")
    monitor_service = DeviceMonitorService(DEV_TYPE)
    switch_time, network_time, success, error = monitor_service.sum_switch_count(
        DEVICE_IP, password, DEVICE_ID, remote_path
    )
    print(f"  结果: success={success}, switch={switch_time}, network={network_time}, error={error}")

    # Step 2: 清空操作
    print_separator("Step 2: 执行清空操作")

    # 先断开 ADB（避免连接冲突）
    ToolService.adb_disconnect()
    time.sleep(0.5)

    result_success, result_msg = DeviceLogService.clean_switch_log(
        DEVICE_IP, password, DEVICE_ID, remote_path
    )
    print(f"  清空结果: success={result_success}, msg={result_msg}")

    # Step 3: 验证查询
    print_separator("Step 3: 验证清空后状态")

    # 重新初始化连接
    ToolService.adb_disconnect()
    time.sleep(0.5)

    print("[3.1] 重新检查文件是否存在...")
    for fpath in [swich_path, network_path]:
        exists = ToolService.check_file_exists(DEVICE_ID, DEVICE_IP, password, fpath, max_retries=2)
        status = "❌ 仍然存在" if exists else "✅ 已删除"
        print(f"  {fpath}: {status}")

    print("[3.2] 使用 sum_switch_count 查询...")
    monitor_service2 = DeviceMonitorService(DEV_TYPE)
    switch_time2, network_time2, success2, error2 = monitor_service2.sum_switch_count(
        DEVICE_IP, password, DEVICE_ID, remote_path
    )
    print(f"  结果: success={success2}, switch={switch_time2}, network={network_time2}, error={error2}")

    # Step 4: 诊断
    print_separator("Step 4: 诊断")

    if switch_time2 == 0 and network_time2 == 0:
        print("✅ 清空成功！开关机次数已归零。")
    else:
        print("❌ 清空失败！开关机次数未变化。")
        print(f"  清空前: switch={switch_time}, network={network_time}")
        print(f"  清空后: switch={switch_time2}, network={network_time2}")

        # 额外诊断：检查 adb root 是否可用
        print("\n[诊断] 检查 adb root 可用性...")
        ToolService.adb_disconnect()
        time.sleep(0.5)
        ADBService.connect(DEVICE_IP)
        time.sleep(1)
        serial = ADBService.get_device_serial(DEVICE_IP)
        root_stdout, root_stderr, root_rc = ADBService.root_device(serial)
        print(f"  adb root → rc={root_rc}, stdout={root_stdout!r}, stderr={root_stderr!r}")
        ADBService.disconnect()

        # 检查文件权限
        print("\n[诊断] 检查文件权限...")
        ADBService.connect(DEVICE_IP)
        time.sleep(1)
        for fpath in [swich_path, network_path]:
            cmd = f"ls -l {fpath}"
            stdout, stderr, rc = ADBService.shell_command(DEVICE_IP, password, cmd)
            print(f"  {cmd}: {stdout.strip() if stdout else 'NOT FOUND'}")
        ADBService.disconnect()

    # 清理
    ToolService.adb_disconnect()
    print("\nDone.")


if __name__ == "__main__":
    main()
