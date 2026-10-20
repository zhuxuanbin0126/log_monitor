#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ADB 设备服务 - 负责所有与 Android 设备通过 ADB 的交互操作"""

import os
import threading
import time
from typing import Dict, Optional, Tuple

from .device_utils import (
    ADB_PATH, get_tool_path, run_command, calculate_md5, TOOLS_DIR,
    DEVICE_OTG_CONFIG, is_android_device,
)
from .logging_service import get_logger
from .protocol.command_query import exec_command_triple
from .protocol.set_query import ADB_MODE_BOTH, ADB_TIMER_ON, set_development

logger = get_logger(__name__)

_LOCAL_MD5_MEMO: Dict[Tuple[str, int, int], str] = {}
"""本地文件 MD5 备忘：``(绝对路径, 大小, mtime) -> md5``。

「同一内容发给多台设备」时只需读一次文件、算一次 MD5（批量发送节目场景收益明显）。
键含大小与 mtime，文件一变即自动失效。
"""
_LOCAL_MD5_MEMO_LIMIT = 64
_LOCAL_MD5_LOCK = threading.Lock()



class ADBService:
    """ADB 设备操作服务类，封装所有 ADB 命令交互"""

    @staticmethod
    def local_md5_once(local_file: str) -> Optional[str]:
        """本地文件 MD5，**同内容只算一次**（路径+大小+mtime 命中即复用）。

        批量把同一个节目/脚本推给几十台设备时，避免对同一文件重复读盘与哈希；
        文件被修改后（大小或 mtime 变化）自动重新计算。
        """
        try:
            stat = os.stat(local_file)
            key = (os.path.abspath(local_file), stat.st_size, int(stat.st_mtime))
        except OSError:
            return calculate_md5(local_file)

        with _LOCAL_MD5_LOCK:
            cached = _LOCAL_MD5_MEMO.get(key)
        if cached:
            logger.debug("[同内容优化] 复用已计算的本地 MD5: %s", local_file)
            return cached

        digest = calculate_md5(local_file)
        if digest:
            with _LOCAL_MD5_LOCK:
                if len(_LOCAL_MD5_MEMO) >= _LOCAL_MD5_MEMO_LIMIT:
                    _LOCAL_MD5_MEMO.clear()
                _LOCAL_MD5_MEMO[key] = digest
        return digest

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
                    logger.warning("[push] 连接失败，尝试重启设备 ADB 服务（协议优先）")
                    ADBService._restart_adbd(ip, password)
                    stdout, stderr, returncode = ADBService.prepare_connection(
                        ip, need_remount=need_remount, device_id=device_id, password=password
                    )
                    if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                        return "", stderr, returncode
                except Exception as e:
                    return "", str(e), -1

            serial = ADBService.get_device_serial(ip)
            logger.info("[push] 开始推送文件: %s -> %s", local_file, remote_file)
            cmd = f"{ADB_PATH} -s {serial} push \"{local_file}\" \"{remote_file}\""
            stdout, stderr, returncode = run_command(cmd, timeout=60)
            logger.debug("[push] 推送结果: stdout=%s, stderr=%s, code=%s", stdout, stderr, returncode)

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
            logger.debug("[ADB] devices 输出: %s", devices_output)

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
                logger.debug("[ADB] root 结果: %s %s", root_stdout, root_stderr)
                time.sleep(3)
                ADBService.remount_system(ip)

            return stdout, stderr, returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def _restart_adbd(ip, password):
        """重启/开启设备网络 ADB：**协议 Set Development 优先**，plink 兜底。

        Returns:
            bool: 是否由**协议**成功下发（False 表示走了 plink 兜底）。
        """
        try:
            ok, msg = set_development(ip, ADB_MODE_BOTH, ADB_TIMER_ON)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("协议 Set Development 异常，回落 plink: %s", exc)
            ok, msg = False, str(exc)
        if ok:
            logger.info("已通过协议开启 usb+tcp ADB: %s", msg)
            time.sleep(2)
            return True

        logger.info("协议不可用（%s），回落 plink 重启 adbd", msg)
        plink_exe = get_tool_path('plink.exe')
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" '
            f'"setprop service.adb.tcp.port 5555"', timeout=5)
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" '
            f'"stop adbd"', timeout=5)
        time.sleep(1)
        run_command(
            f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" '
            f'"start adbd"', timeout=5)
        time.sleep(3)
        return False

    @staticmethod
    def _fallback_enable_adb(ip, password, device_id):
        """ADB 连接失败时的 fallback：切换 OTG 模式 + 重启设备 ADB（协议优先）。"""
        from .device_utils import DEVICE_OTG_CONFIG as otg_cfg
        dev_type_prefix = device_id.split('-')[0]
        otg_config = otg_cfg.get(dev_type_prefix)

        if otg_config:
            # 切换 OTG 到 peripheral 模式：协议 exec 优先，plink 兜底
            otg_value = otg_config["value"]
            otg_path = otg_config["path"]
            triple = exec_command_triple(ip, f'echo {otg_value} > {otg_path}')
            if triple is None:
                plink_exe = get_tool_path('plink.exe')
                run_command(
                    f'echo y | "{plink_exe}" -batch -l root -pw "{password}" '
                    f'"{ip}" "echo {otg_value} > {otg_path}"', timeout=10)
            time.sleep(2)

        ADBService._restart_adbd(ip, password)

    @staticmethod
    def list_devices():
        """解析 ``adb devices`` 输出为 ``{serial: state}``。

        仅统计 ``<serial>\\t<state>`` 形式的有效行，忽略 ``List of devices attached``
        与 daemon 提示行（``* daemon ...``）。
        """
        devices = {}
        try:
            stdout, _, returncode = run_command(f"{ADB_PATH} devices", timeout=10)
        except Exception:
            return devices
        if returncode != 0 or not stdout:
            return devices
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices[parts[0]] = parts[1]
        return devices

    @staticmethod
    def get_online_serial(ip, port=5555):
        """仅当 ``adb devices`` 中该设备状态为 ``device`` 时返回其 serial，否则 None。

        网络 ADB 的 serial 恒为 ``ip:port`` 形态，故**不能**用「serial 是否以 ip: 开头」
        判断可用性；必须看状态列——``offline`` / ``unauthorized`` / 未列出 均视为不可用。
        """
        target = f"{ip}:{port}"
        return target if ADBService.list_devices().get(target) == "device" else None

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
    def disconnect_device(ip):
        """断开**指定设备**的 adb 连接（不影响其它设备）。

        并行查询场景必须用本方法：``adb disconnect``（无参数）会断开**所有**连接，
        在多线程并行处理多台设备时会误伤别的设备。
        """
        cmd = f"{ADB_PATH} disconnect {ip}:5555"
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
    def verify_remote_file(ip, remote_file, local_md5, device_id=None, password=None):
        """推送后校验：终端侧**存在性 + MD5**（借鉴参考实现 file_pusher 的收尾校验）。

        返回 ``(是否通过, 说明)``：
        - 文件不存在 → 不通过
        - MD5 一致 → 通过
        - MD5 取不到但文件存在 → 降级通过（存在性校验），说明中标注
        """
        exists = ADBService.check_file_exists(
            ip, remote_file, max_retries=1, device_id=device_id, password=password)
        if not exists:
            return False, "终端侧文件不存在"

        remote_md5 = ADBService.calc_file_md5(
            ip, remote_file, device_id=device_id, password=password)
        if remote_md5 is None:
            return True, "终端侧文件存在（MD5 不可读，已降级为存在性校验）"
        if remote_md5 != local_md5:
            return False, f"MD5 不一致: 本地={local_md5} 远端={remote_md5}"
        return True, f"终端侧存在且 MD5 一致: {local_md5}"

    @staticmethod
    def push_file_reliable(ip, password, local_file, remote_file, max_retries=3, device_id=None):
        """可靠的adb推送文件方法，带有重试和MD5校验"""
        if not os.path.exists(local_file):
            return "", f"本地文件不存在: {local_file}", -1

        local_md5 = ADBService.local_md5_once(local_file)
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
                        ADBService._restart_adbd(ip, password)
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

                remote_md5_ok, verify_msg = ADBService.verify_remote_file(
                    ip, remote_file, local_md5, device_id=device_id, password=password)
                if remote_md5_ok:
                    ADBService.disconnect()
                    return f"推送成功，{verify_msg}", "", 0
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                ADBService.disconnect()
                return "", f"推送校验失败: {verify_msg}", -3

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                ADBService.disconnect()
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
        """重启设备的 ADB 服务（协议 Set Development 优先，plink 兜底）"""
        try:
            by_protocol = ADBService._restart_adbd(ip, password)
            return True, ("已通过协议开启 usb+tcp ADB" if by_protocol
                          else "已通过 plink 重启 adbd")
        except Exception as e:
            return False, f"重启ADB服务异常: {str(e)}"
