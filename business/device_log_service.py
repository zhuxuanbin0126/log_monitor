#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备日志服务 - 负责开关机计数、日志清除和导出"""

import os
import re
import time
from datetime import datetime

from service.tool_service import ToolService
from service.file_service import FileService
from service.adb_service import ADBService
from service.logging_service import get_logger

logger = get_logger(__name__)

COUNT_SPLIT_MARKER = "___LM_SWITCH_SPLIT___"
"""一次往返取两个计数时的分段标记"""


class DeviceLogService:
    """设备日志业务服务类，负责开关机计数读取、日志清除和导出"""

    @staticmethod
    def _count_command(file_path):
        """文件计数命令：文件不存在时显式输出 ``0``（=无记录）。

        原先用 ``wc -l path``，文件不存在时输出空串 → 被误判为「取不到」→
        回落 adb/SSH（`disconnect` + `sleep` + 连接重试），单台白花 10~20s。
        """
        return f"if [ -f {file_path} ]; then wc -l {file_path}; else echo 0; fi"

    @staticmethod
    def _parse_counts(text):
        """解析 ``标记 + 计数 + 标记 + 计数`` 形式的输出；无法解析返回 None。

        计数 = ``wc -l`` 行数 − 1（首行为表头）。
        """
        parts = (text or "").split(COUNT_SPLIT_MARKER)
        if len(parts) < 3:
            return None

        def _one(raw):
            match = re.search(r"\d+", raw or "")
            return max(0, int(match.group()) - 1) if match else None

        switch_count = _one(parts[1])
        network_count = _one(parts[2])
        if switch_count is None and network_count is None:
            return None
        return switch_count or 0, network_count or 0

    @staticmethod
    def _query_counts_once(ip, password, device_id, switch_path, network_path):
        """**一次往返**取「开关机次数 + 网络开关机次数」。

        Android 走协议加密 ``Command.exec``，Linux 走 SSH；无论哪种都只一个
        往返，替代原先「逐个文件 check_file_exists + 3 次重试」的多次往返。
        """
        marker = COUNT_SPLIT_MARKER
        command = (f"echo {marker}; {DeviceLogService._count_command(switch_path)}; "
                   f"echo {marker}; {DeviceLogService._count_command(network_path)}")
        stdout, stderr, _ = ToolService.execute_query_command(
            device_id, ip, password, command, ".")
        if stderr and not stdout:
            logger.debug("设备 %s 一次往返取计数失败: %s", device_id, stderr)
        return DeviceLogService._parse_counts(stdout)

    @staticmethod
    def sum_switch_count(ip, password, device_id, path):
        """设备累计开机次数（一次往返优先，失败才逐文件降级）。"""
        try:
            switch_counter_path = f"{path}/swich_counter.csv"
            network_counter_path = f"{path}/network_counter.csv"

            # 一次往返：Android 走协议加密 exec（ms 级）、Linux 走 SSH（单次）
            counts = DeviceLogService._query_counts_once(
                ip, password, device_id, switch_counter_path, network_counter_path)
            if counts is not None:
                logger.info("[开关机计数] %s 一次往返取数成功: 开关机=%s 网络开关机=%s",
                            device_id, counts[0], counts[1])
                return counts[0], counts[1], True, None

            logger.info("[开关机计数] %s 一次往返未取到，逐文件降级", device_id)
            switch_time = 0
            network_time = 0

            switch_exists = ToolService.check_file_exists(device_id, ip, password, switch_counter_path, max_retries=2)
            if switch_exists:
                for attempt in range(3):
                    try:
                        cmd = f"wc -l {switch_counter_path}"
                        stdout, stderr, returncode = ToolService.execute_query_command(device_id, ip, password, cmd, ".")
                        if not stderr and returncode == 0 and stdout:
                            stdout = stdout.strip()
                            try:
                                switch_time = max(0, int(stdout.split()[0]) - 1)
                                break
                            except (ValueError, IndexError):
                                pass

                        if switch_time == 0:
                            cmd = f"grep -c '^' {switch_counter_path}"
                            stdout, stderr, returncode = ToolService.execute_query_command(device_id, ip, password, cmd, ".")
                            if not stderr and returncode == 0 and stdout:
                                try:
                                    switch_time = max(0, int(stdout.strip()) - 1)
                                    break
                                except (ValueError, IndexError):
                                    pass

                        if attempt < 2:
                            time.sleep(0.5)
                    except Exception:
                        if attempt < 2:
                            time.sleep(0.5)

            network_exists = ToolService.check_file_exists(device_id, ip, password, network_counter_path, max_retries=2)
            if network_exists:
                for attempt in range(3):
                    try:
                        cmd = f"wc -l {network_counter_path}"
                        stdout, stderr, returncode = ToolService.execute_query_command(device_id, ip, password, cmd, ".")
                        if not stderr and returncode == 0 and stdout:
                            stdout = stdout.strip()
                            try:
                                network_time = max(0, int(stdout.split()[0]) - 1)
                                break
                            except (ValueError, IndexError):
                                pass

                        if network_time == 0:
                            cmd = f"grep -c '^' {network_counter_path}"
                            stdout, stderr, returncode = ToolService.execute_query_command(device_id, ip, password, cmd, ".")
                            if not stderr and returncode == 0 and stdout:
                                try:
                                    network_time = max(0, int(stdout.strip()) - 1)
                                    break
                                except (ValueError, IndexError):
                                    pass

                        if attempt < 2:
                            time.sleep(0.5)
                    except Exception:
                        if attempt < 2:
                            time.sleep(0.5)

            return switch_time, network_time, True, None
        except Exception:
            return 0, 0, True, None

    @staticmethod
    def clean_switch_log(ip, password, device_id, path):
        """清除开关机日志，使用传入的 path 参数（由 get_device_remote_path 统一决定）

        对于 Android 设备，shell 用户可能无权删除 /data/ 下 root/system 拥有的文件。
        策略：先尝试普通 rm，文件残留时尝试 adb root + 重试删除。
        """
        try:
            delete_path = path
            is_android = ToolService.is_android_device(device_id)

            cmd = f"rm -f {delete_path}/swich_counter.csv"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            cmd = f"rm -f {delete_path}/network_counter.csv"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            cmd = f"rm -rf {delete_path}/logcat"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            cmd = f"rm -rf {delete_path}/ping"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            cmd = "sync"
            ToolService.execute_command(device_id, ip, password, cmd, ".")

            time.sleep(1)

            switch_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/swich_counter.csv", max_retries=1)
            network_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/network_counter.csv", max_retries=1)

            # 文件残留 → Android 设备尝试 adb root 提权后重新删除
            if (switch_exists or network_exists) and is_android:
                root_ok = DeviceLogService._try_root_delete(ip, password, device_id, delete_path)
                if not root_ok:
                    return False, f"{device_id} 清除失败: 文件受权限保护(shell用户无权删除)，adb root 不可用"
                # root 删除后重新检查
                time.sleep(1)
                switch_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/swich_counter.csv", max_retries=1)
                network_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/network_counter.csv", max_retries=1)
            elif switch_exists or network_exists:
                # Linux 设备：重试一次普通删除
                if switch_exists:
                    cmd = f"rm -f {delete_path}/swich_counter.csv"
                    ToolService.execute_command(device_id, ip, password, cmd, ".")
                if network_exists:
                    cmd = f"rm -f {delete_path}/network_counter.csv"
                    ToolService.execute_command(device_id, ip, password, cmd, ".")
                cmd = "sync"
                ToolService.execute_command(device_id, ip, password, cmd, ".")
                time.sleep(1)

            return True, f"{device_id} 开关机记录已清除"
        except Exception as e:
            return False, f"{device_id} 清除累计开机次数失败 - {str(e)}"

    @staticmethod
    def _try_root_delete(ip, password, device_id, delete_path):
        """Android 设备：尝试 adb root 后删除 /data/ 下文件，返回是否成功"""
        import time as _time
        from service.adb_service import ADBService as _ADB
        try:
            # 先确保 ADB 已连接（之前可能被 disconnect）
            _ADB.connect(ip)
            _time.sleep(1)

            # 执行 adb root
            serial = _ADB.get_device_serial(ip)
            stdout, stderr, rc = _ADB.root_device(serial)
            logger.debug("[clean_switch] adb root: stdout=%r stderr=%r rc=%s", stdout, stderr, rc)

            # adb root 成功后 adbd 重启，等待并重新连接
            _time.sleep(3)
            _ADB.connect(ip)
            _time.sleep(2)

            # 获取 root 后的新 serial
            serial = _ADB.get_device_serial(ip)
            logger.debug("[clean_switch] root 后 serial: %s", serial)

            # 以 root 身份删除
            for filename in ["swich_counter.csv", "network_counter.csv"]:
                cmd = f"rm -f {delete_path}/{filename}"
                # 直接使用 adb -s {serial} shell 确保用 root 身份执行
                from service.device_utils import ADB_PATH, run_command
                full_cmd = f'{ADB_PATH} -s {serial} shell "{cmd}"'
                stdout, stderr, rc = run_command(full_cmd, timeout=10)
                logger.debug("[clean_switch] root rm %s: rc=%s stderr=%r", filename, rc, stderr)

                # 验证删除结果
                verify_cmd = f'{ADB_PATH} -s {serial} shell "ls -l {delete_path}/{filename}"'
                v_stdout, v_stderr, v_rc = run_command(verify_cmd, timeout=5)
                if v_rc == 0 and "No such" not in v_stdout:
                    logger.warning("[clean_switch] %s 仍然存在! 权限: %s", filename, v_stdout.strip())

            _ADB.disconnect()
            return True
        except Exception as e:
            logger.warning("[clean_switch] root delete failed: %s", e)
            try:
                _ADB.disconnect()
            except Exception:
                pass
            return False

    @staticmethod
    def switch_log_output(ip, password, device_id, system_type, path):
        """导出开关机日志"""
        try:
            output_dir = f"./switch_log/{device_id}"
            if not os.path.exists("./switch_log"):
                os.mkdir("./switch_log")
            if not os.path.exists(output_dir):
                os.mkdir(output_dir)

            success_count = 0
            messages = []

            stdout, stderr, returncode = ToolService.pull_file(
                device_id, ip, password, f"{path}/network_counter.csv", f"{output_dir}/network_counter.csv"
            )
            if not stderr and returncode == 0:
                success_count += 1
            else:
                messages.append(f"network_counter.csv 拉取失败: {stderr}")

            stdout, stderr, returncode = ToolService.pull_file(
                device_id, ip, password, f"{path}/swich_counter.csv", f"{output_dir}/swich_counter.csv"
            )
            if not stderr and returncode == 0:
                success_count += 1
            else:
                messages.append(f"swich_counter.csv 拉取失败: {stderr}")

            if success_count > 0:
                msg = f"{device_id} 日志已保存至：{output_dir}"
                if messages:
                    msg += f" (部分文件: {'; '.join(messages)})"
                return True, msg
            else:
                return False, f"{device_id} 所有日志文件拉取失败: {'; '.join(messages)}"
        except Exception as e:
            return False, f"{device_id} 获取日志失败 - {str(e)}"
