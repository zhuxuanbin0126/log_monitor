#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备日志服务 - 负责开关机计数、日志清除和导出"""

import os
import time
from datetime import datetime

from service.tool_service import ToolService
from service.file_service import FileService
from service.adb_service import ADBService


class DeviceLogService:
    """设备日志业务服务类，负责开关机计数读取、日志清除和导出"""

    @staticmethod
    def sum_switch_count(ip, password, device_id, path):
        """设备累计开机次数，优化错误处理和重试"""
        try:
            switch_counter_path = f"{path}/swich_counter.csv"
            network_counter_path = f"{path}/network_counter.csv"

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
            print(f"[clean_switch] adb root: stdout={stdout!r} stderr={stderr!r} rc={rc}")

            # adb root 成功后 adbd 重启，等待并重新连接
            _time.sleep(3)
            _ADB.connect(ip)
            _time.sleep(2)

            # 获取 root 后的新 serial
            serial = _ADB.get_device_serial(ip)
            print(f"[clean_switch] root 后 serial: {serial}")

            # 以 root 身份删除
            for filename in ["swich_counter.csv", "network_counter.csv"]:
                cmd = f"rm -f {delete_path}/{filename}"
                # 直接使用 adb -s {serial} shell 确保用 root 身份执行
                from service.device_utils import ADB_PATH, run_command
                full_cmd = f'{ADB_PATH} -s {serial} shell "{cmd}"'
                stdout, stderr, rc = run_command(full_cmd, timeout=10)
                print(f"[clean_switch] root rm {filename}: rc={rc} stderr={stderr!r}")

                # 验证删除结果
                verify_cmd = f'{ADB_PATH} -s {serial} shell "ls -l {delete_path}/{filename}"'
                v_stdout, v_stderr, v_rc = run_command(verify_cmd, timeout=5)
                if v_rc == 0 and "No such" not in v_stdout:
                    print(f"[clean_switch] ⚠ {filename} 仍然存在! 权限: {v_stdout.strip()}")

            _ADB.disconnect()
            return True
        except Exception as e:
            print(f"[clean_switch] root delete failed: {e}")
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
