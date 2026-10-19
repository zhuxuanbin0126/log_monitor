#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ADB 设备服务 - 负责所有与 Android 设备通过 ADB 的交互操作"""

import os
import time

from .device_utils import (
    ADB_PATH, get_tool_path, run_command, calculate_md5, TOOLS_DIR,
    DEVICE_OTG_CONFIG, is_android_device,
)


class ADBService:
    """ADB 设备操作服务类，封装所有 ADB 命令交互"""

    @staticmethod
    def root_device(serial):
        """执行 adb root 获取 root 权限，返回 (stdout, stderr, returncode)"""
        cmd = f"{ADB_PATH} -s {serial} root"
        return run_command(cmd, timeout=10)

    @staticmethod
    def shell_command(ip, password, command_script=None):
        """通过adb shell执行命令 (仅用于Android设备)"""
        run_command(f"{ADB_PATH} connect {ip}:5555")
        time.sleep(0.5)
        serial = ADBService.get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell {command_script}"
        stdout, stderr, returncode = run_command(cmd)
        run_command(f"{ADB_PATH} disconnect {ip}:5555")
        return stdout.strip(), stderr.strip(), returncode

    @staticmethod
    def push_file(ip, password, local_file, remote_file, device_id=None):
        """完整的adb推送文件方法"""
        try:
            need_remount = remote_file.startswith("/system/") or "/system/" in remote_file

            stdout, stderr, returncode = ADBService.prepare_connection(
                ip, need_remount=need_remount, device_id=device_id, password=password
            )
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                try:
                    print(f"[push] 连接失败，尝试通过SSH重启ADB服务")
                    plink_exe = get_tool_path('plink.exe')
                    run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"setprop service.adb.tcp.port 5555\"", timeout=5)
                    run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"stop adbd\"", timeout=5)
                    run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"start adbd\"", timeout=5)
                    time.sleep(3)
                    stdout, stderr, returncode = ADBService.prepare_connection(
                        ip, need_remount=need_remount, device_id=device_id, password=password
                    )
                    if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                        return "", stderr, returncode
                except Exception as e:
                    return "", str(e), -1

            serial = ADBService.get_device_serial(ip)
            print(f"[push] 开始推送文件: {local_file} -> {remote_file}")
            cmd = f"{ADB_PATH} -s {serial} push \"{local_file}\" \"{remote_file}\""
            stdout, stderr, returncode = run_command(cmd, timeout=60)
            print(f"[push] 推送结果: stdout={stdout}, stderr={stderr}, code={returncode}")

            ADBService.disconnect()
            return stdout.strip(), stderr.strip(), returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def pull_file(ip, remote_file, local_file, device_id=None, password=None):
        """完整的adb拉取文件方法"""
        try:
            stdout, stderr, returncode = ADBService.prepare_connection(
                ip, need_remount=False, device_id=device_id, password=password
            )
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                return "", stderr, returncode

            serial = ADBService.get_device_serial(ip)
            cmd = f"{ADB_PATH} -s {serial} root"
            run_command(cmd, timeout=10)
            time.sleep(2)

            cmd = f"{ADB_PATH} connect {ip}:5555"
            run_command(cmd)
            time.sleep(2)

            cmd = f"{ADB_PATH} -s {serial} pull \"{remote_file}\" \"{local_file}\""
            stdout, stderr, returncode = run_command(cmd, timeout=60)

            ADBService.disconnect()
            return stdout.strip(), stderr.strip(), returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def screencap(ip, remote_file):
        """使用adb执行屏幕截图命令"""
        serial = ADBService.get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell screencap -p {remote_file}"
        return run_command(cmd)

    @staticmethod
    def prepare_connection(ip, need_remount=False, device_id=None, password=None):
        """准备ADB连接（严格顺序）：
        1. adb disconnect 清理已有连接
        2. adb devices 确认无残留连接
        3. adb connect 连接目标设备
        4. (仅 need_remount=True) adb root 获取管理员权限
        5. (仅 need_remount=True) adb remount 赋予文件传输权限
        """
        try:
            # 步骤1: 断开所有已有连接
            cmd = f"{ADB_PATH} disconnect"
            run_command(cmd)
            time.sleep(1)

            # 步骤2: 确认当前无设备连接
            cmd = f"{ADB_PATH} devices"
            devices_output, _, _ = run_command(cmd, timeout=10)
            print(f"[ADB] devices 输出: {devices_output}")

            # 步骤3: 连接目标设备
            cmd = f"{ADB_PATH} connect {ip}:5555"
            stdout, stderr, returncode = run_command(cmd)
            time.sleep(2)

            # 判断连接是否成功
            connection_failed = (stderr and (
                "unable" in stderr.lower() or
                "cannot" in stderr.lower() or
                "refused" in stderr.lower() or
                "积极拒绝" in stderr)) or returncode != 0

            if connection_failed and device_id and password:
                ADBService._fallback_enable_adb(ip, password, device_id)
                time.sleep(3)
                cmd = f"{ADB_PATH} connect {ip}:5555"
                stdout, stderr, returncode = run_command(cmd)
                time.sleep(2)

            # 步骤4-5: 仅在需要 remount 时执行 root + remount
            if need_remount:
                serial = ADBService.get_device_serial(ip)
                cmd = f"{ADB_PATH} -s {serial} root"
                root_stdout, root_stderr, root_rc = run_command(cmd, timeout=10)
                print(f"[ADB] root 结果: {root_stdout} {root_stderr}")
                time.sleep(3)
                ADBService.remount_system(ip)

            return stdout, stderr, returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def _fallback_enable_adb(ip, password, device_id):
        """ADB 连接失败时的 fallback：通过 SSH 开启 OTG 模式和重启 ADB"""
        from .device_utils import DEVICE_OTG_CONFIG as otg_cfg
        dev_type_prefix = device_id.split('-')[0]
        otg_config = otg_cfg.get(dev_type_prefix)

        if otg_config:
            plink_exe = get_tool_path('plink.exe')
            # 执行 OTG 命令切换到 peripheral 模式
            otg_value = otg_config["value"]
            otg_path = otg_config["path"]
            otg_cmd = (
                f'echo y | "{plink_exe}" -batch -l root -pw "{password}" '
                f'"{ip}" "echo {otg_value} > {otg_path}"'
            )
            run_command(otg_cmd, timeout=10)
            time.sleep(2)

        plink_exe = get_tool_path('plink.exe')
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" '
            f'"{ip}" "setprop service.adb.tcp.port 5555"', timeout=5
        )
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" '
            f'"{ip}" "stop adbd"', timeout=5
        )
        time.sleep(1)
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" '
            f'"{ip}" "start adbd"', timeout=5
        )
        time.sleep(3)

    @staticmethod
    def connect(ip):
        """使用adb连接设备"""
        cmd = f"{ADB_PATH} connect {ip}:5555"
        return run_command(cmd)

    @staticmethod
    def get_device_serial(ip):
        """从adb devices输出中获取设备序列号"""
        try:
            cmd = f"{ADB_PATH} devices"
            stdout, stderr, returncode = run_command(cmd, timeout=10)
            if returncode == 0 and stdout:
                for line in stdout.strip().split('\n'):
                    line = line.strip()
                    if line and '\t' in line and 'device' in line and not line.startswith('*'):
                        parts = line.split('\t')
                        serial = parts[0].strip()
                        if serial and serial != 'List of devices attached':
                            if serial.startswith(f"{ip}:"):
                                return serial
        except Exception:
            pass
        return f"{ip}:5555"

    @staticmethod
    def disconnect():
        """使用adb断开所有连接"""
        cmd = f"{ADB_PATH} disconnect"
        return run_command(cmd)

    @staticmethod
    def rm_file(ip, remote_file):
        """使用adb删除设备上的文件（自动确保 ADB 连接）"""
        ADBService.connect(ip)
        time.sleep(0.5)
        serial = ADBService.get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell rm {remote_file}"
        return run_command(cmd)

    @staticmethod
    def calc_file_md5(ip, remote_file, device_id=None, password=None):
        """使用adb计算远程文件的MD5值"""
        try:
            stdout, stderr, returncode = ADBService.prepare_connection(
                ip, need_remount=False, device_id=device_id, password=password
            )
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                return None

            serial = ADBService.get_device_serial(ip)
            cmd = f"{ADB_PATH} -s {serial} shell md5sum {remote_file}"
            stdout, stderr, returncode = run_command(cmd)
            if not stderr and stdout:
                md5_value = stdout.strip().split()[0]
                ADBService.disconnect()
                return md5_value

            local_temp = f"temp_md5_{ip.replace('.', '_')}_{int(time.time())}"
            stdout, stderr, returncode = ADBService.pull_file(ip, remote_file, local_temp, device_id=device_id, password=password)
            if not stderr and os.path.exists(local_temp):
                md5_value = calculate_md5(local_temp)
                try:
                    os.remove(local_temp)
                except Exception:
                    pass
                ADBService.disconnect()
                return md5_value

            ADBService.disconnect()
            return None
        except Exception:
            return None

    @staticmethod
    def ensure_directory(ip, remote_dir):
        """确保远程目录存在（自动确保 ADB 连接）"""
        try:
            ADBService.connect(ip)
            time.sleep(0.3)
            serial = ADBService.get_device_serial(ip)
            cmd = f"{ADB_PATH} -s {serial} shell mkdir -p {remote_dir}"
            stdout, stderr, returncode = run_command(cmd)
            return returncode == 0 or (stderr and "File exists" in stderr)
        except Exception:
            return False

    @staticmethod
    def push_file_reliable(ip, password, local_file, remote_file, max_retries=3, device_id=None):
        """可靠的adb推送文件方法，带有重试和MD5校验"""
        if not os.path.exists(local_file):
            return "", f"本地文件不存在: {local_file}", -1

        local_md5 = calculate_md5(local_file)
        if not local_md5:
            return "", "无法计算本地文件MD5", -2

        remote_dir = os.path.dirname(remote_file)
        need_remount = remote_file.startswith("/system/") or "/system/" in remote_file or remote_dir.startswith("/system/")

        serial = ADBService.get_device_serial(ip)
        for attempt in range(max_retries):
            try:
                stdout, stderr, returncode = ADBService.prepare_connection(
                    ip, need_remount=need_remount, device_id=device_id, password=password
                )

                if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                    try:
                        plink_exe = get_tool_path('plink.exe')
                        run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"setprop service.adb.tcp.port 5555\"", timeout=5)
                        run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"stop adbd\"", timeout=5)
                        run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"start adbd\"", timeout=5)
                        time.sleep(3)
                        stdout, stderr, returncode = ADBService.prepare_connection(
                            ip, need_remount=need_remount, device_id=device_id, password=password
                        )
                        if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                            if attempt < max_retries - 1:
                                time.sleep(2)
                                continue
                            return "", stderr, returncode
                    except Exception as e:
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        return "", str(e), -1

                if remote_dir and remote_dir != "/":
                    ADBService.ensure_directory(ip, remote_dir)

                cmd = f"{ADB_PATH} -s {serial} push \"{local_file}\" \"{remote_file}\""
                stdout, stderr, returncode = run_command(cmd, timeout=60)

                if (stderr and ("Read-only file system" in stderr or "couldn't create file" in stderr)) or \
                   (stdout and ("Read-only file system" in stdout or "couldn't create file" in stdout)):
                    remount_stdout, remount_stderr, remount_code = ADBService.remount_system(ip)
                    if remount_code == 0 or not remount_stderr:
                        stdout, stderr, returncode = run_command(cmd, timeout=60)

                if stderr or returncode != 0:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    ADBService.disconnect()
                    return stdout, stderr, returncode

                remote_md5 = ADBService.calc_file_md5(ip, remote_file, device_id=device_id, password=password)
                if remote_md5 and remote_md5 == local_md5:
                    ADBService.disconnect()
                    return f"推送成功，MD5: {local_md5}", "", 0
                else:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    ADBService.disconnect()
                    return "", f"MD5校验失败: 本地={local_md5}, 远程={remote_md5}", -3

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return "", str(e), -1

        ADBService.disconnect()
        return "", f"已达到最大重试次数 ({max_retries})", -4

    @staticmethod
    def remount_system(ip):
        """重新挂载/system分区为可读写模式"""
        try:
            cmd = f"{ADB_PATH} disconnect"
            run_command(cmd)
            time.sleep(1)

            cmd = f"{ADB_PATH} connect {ip}:5555"
            stdout, stderr, returncode = run_command(cmd)
            time.sleep(2)

            serial = ADBService.get_device_serial(ip)
            cmd = f"{ADB_PATH} -s {serial} root"
            stdout, stderr, returncode = run_command(cmd, timeout=10)
            time.sleep(3)

            cmd = f"{ADB_PATH} connect {ip}:5555"
            run_command(cmd)
            time.sleep(2)

            cmd = f"{ADB_PATH} -s {serial} remount"
            stdout, stderr, returncode = run_command(cmd, timeout=10)

            if returncode != 0 or stderr:
                cmd = f"{ADB_PATH} -s {serial} shell \"mount -o remount,rw /system\""
                stdout, stderr, returncode = run_command(cmd, timeout=10)

            return stdout, stderr, returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def set_permissions(ip, remote_file, permissions="777"):
        """设置远程文件的权限（自动确保 ADB 连接）"""
        # 确保设备已连接
        ADBService.connect(ip)
        time.sleep(0.5)
        serial = ADBService.get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell chmod {permissions} {remote_file}"
        return run_command(cmd)

    @staticmethod
    def set_executable(ip, remote_file):
        """设置远程文件为可执行"""
        return ADBService.set_permissions(ip, remote_file, "0755")

    @staticmethod
    def check_file_exists(ip, remote_file, max_retries=3, device_id=None, password=None):
        """使用ADB检查远程文件是否存在，带重试机制"""
        is_fast_check = max_retries == 1

        serial = ADBService.get_device_serial(ip)
        for attempt in range(max_retries):
            try:
                if is_fast_check:
                    cmd = f"{ADB_PATH} disconnect"
                    run_command(cmd)
                    cmd = f"{ADB_PATH} connect {ip}:5555"
                    stdout, stderr, returncode = run_command(cmd)
                    time.sleep(0.5)
                else:
                    stdout, stderr, returncode = ADBService.prepare_connection(
                        ip, need_remount=False, device_id=device_id, password=password
                    )

                if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                    if attempt < max_retries - 1 and not is_fast_check:
                        time.sleep(1)
                        continue
                    return False

                cmd = f"{ADB_PATH} -s {serial} shell ls -l {remote_file}"
                stdout, stderr, returncode = run_command(cmd, timeout=5 if is_fast_check else 10)

                if returncode == 0 and not stderr and "No such" not in stdout:
                    ADBService.disconnect()
                    return True

                if attempt < max_retries - 1 and not is_fast_check:
                    time.sleep(1)
            except Exception:
                if attempt < max_retries - 1 and not is_fast_check:
                    time.sleep(1)

        ADBService.disconnect()
        return False

    @staticmethod
    def set_otg_mode(ip, password, device_id):
        """通过SSH设置设备的OTG模式为peripheral模式"""
        try:
            try:
                dev_type_prefix = device_id.split('-')[0]
                otg_config = DEVICE_OTG_CONFIG.get(dev_type_prefix)
            except Exception:
                otg_config = None

            if not otg_config:
                return True, "无OTG配置"

            plink_exe = get_tool_path('plink.exe')
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "echo {otg_config["value"]} > {otg_config["path"]}"'
            run_command(cmd, timeout=10)
            time.sleep(2)

            return True, "OTG模式设置成功"
        except Exception as e:
            return False, f"设置OTG模式异常: {str(e)}"

    @staticmethod
    def restart_service(ip, password, device_id=None):
        """通过SSH重启设备的ADB服务"""
        try:
            plink_exe = get_tool_path('plink.exe')
            run_command(f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "setprop service.adb.tcp.port 5555"', timeout=5)
            run_command(f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "stop adbd"', timeout=5)
            time.sleep(1)
            run_command(f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "start adbd"', timeout=5)
            time.sleep(3)
            return True, "ADB服务重启成功"
        except Exception as e:
            return False, f"重启ADB服务异常: {str(e)}"
