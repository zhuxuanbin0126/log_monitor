#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys
import time
from datetime import datetime, timedelta
import re
import json
from config import supported_dev_types, getinfo_path
import html
import threading
import queue
import hashlib

from .device_utils import (
    get_project_root, PROJECT_ROOT, TOOLS_DIR, ADB_PATH,
    ANDROID_DEV_TYPES, LINUX_DEV_TYPES, DEVICE_OTG_CONFIG,
    get_tool_path, run_command, calculate_md5, is_android_device,
)
from .adb_service import ADBService
from .adb_device_manager import ADBDeviceManager
             
             
             
class ToolService:
    """工具服务类，负责与外部工具交互"""

    @staticmethod
    def is_android_device(device_id):
        """判断设备是否是Android类型"""
        return is_android_device(device_id)
    @staticmethod
    def get_tool_path(tool_name):
        """获取工具的完整路径"""
        return get_tool_path(tool_name)
    @staticmethod
    def run_command(cmd, encoding='utf-8', timeout=30):
        """执行命令并返回输出，支持超时控制"""
        return run_command(cmd, encoding, timeout)
    @staticmethod
    def get_device_list(dev_type="A-B-C-D-H"):
        """
        调用DeviceId.exe获取设备列表
        """
        # 构造grep模式
        pattern = dev_type.replace('-', '|')
        
        # 调用DeviceId.exe
        device_id_exe = ToolService.get_tool_path('DeviceId.exe')
        stdout, stderr, returncode = ToolService.run_command(device_id_exe)
        if stderr:
            print(f"DeviceId.exe 错误: {stderr}")
            return []
        
        # 过滤符合模式的设备
        devices = []
        for line in stdout.split('\n'):
            if line.split('-')[0] not in supported_dev_types:
                continue

            if re.match(f'^({pattern})', line):
                parts = line.strip().split()
                if len(parts) >= 2:
                    device_id = parts[0]
                    ip = parts[1]
                    password = ToolService.get_password(device_id)
                    # 初始设置为N/A
                    mac_address = "N/A"
                    device_name = "N/A"
                    system_type = "N/A"
                    
                    # 尝试获取MAC地址和设备名称
                    try:
                        # 使用新的统一接口获取设备信息
                        mac_address, device_name, system_type = ToolService.get_advanced_device_info(
                            device_id, ip, password
                        )
                    except Exception as e:
                        print(f"获取设备 {device_id} 详细信息时出错: {str(e)}")
                    
                    # 尝试获取OTA版本和主版本
                    ota_version = "N/A"
                    main_version = "N/A"
                    
                    try:
                        ota_version, main_version = ToolService.get_version_info(
                            device_id, ip, password
                        )
                    except Exception as e:
                        print(f"获取设备 {device_id} 版本信息时出错: {str(e)}")
                    
                    # 将所有设备信息存储为字典
                    devices.append({
                        'id': device_id,
                        'ip': ip,
                        'password': password,
                        'mac_address': mac_address,
                        'device_name': device_name,
                        'system_type': system_type,
                        'ota_version': ota_version,
                        'main_version': main_version,
                        'adb_status': ADBDeviceManager.get_cached_status(device_id)
                    })

        return devices

    @staticmethod
    def get_advanced_device_info(device_id, ip, password):
        """
        获取设备的高级信息（MAC、设备名称、系统类型）
        根据设备类型自动选择ADB或SSH方式
        
        返回:
            tuple: (mac_address, device_name, system_type)
        """
        mac_address = "N/A"
        device_name = "N/A"
        system_type = "N/A"
        
        try:
            if ToolService.is_android_device(device_id):
                # Android设备使用ADB方式
                # 连接设备
                ToolService.run_command(f"{ADB_PATH} connect {ip}:5555")
                time.sleep(0.5)
                serial = ToolService.adb_get_device_serial(ip)
                
                # 尝试通过getdeviceinfo.sh获取信息（如果存在）
                try:
                    # 先检查脚本是否存在
                    check_cmd = f"{ADB_PATH} -s {serial} shell ls /data/getdeviceinfo.sh"
                    stdout, stderr, returncode = ToolService.run_command(check_cmd, timeout=5)
                    
                    if not stderr and "No such" not in stdout:
                        # 脚本存在，执行它
                        cmd = f"{ADB_PATH} -s {serial} shell sh /data/getdeviceinfo.sh"
                        stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
                        if stdout and not stderr:
                            info_parts = stdout.strip().split()
                            if len(info_parts) >= 3:
                                mac_address = info_parts[0]
                                device_name = html.unescape(info_parts[1])
                                system_type = info_parts[2]
                except Exception as e:
                    print(f"使用getdeviceinfo.sh获取信息失败: {e}")
                
                # 如果没有获取到信息，尝试直接获取
                if mac_address == "N/A":
                    # 获取MAC地址
                    cmd = f"{ADB_PATH} -s {serial} shell cat /sys/class/net/eth0/address"
                    stdout, stderr, returncode = ToolService.run_command(cmd, timeout=5)
                    if stdout and not stderr:
                        mac_address = stdout.strip()
                    
                    # 获取设备名称
                    cmd = f"{ADB_PATH} -s {serial} shell getprop ro.product.model"
                    stdout, stderr, returncode = ToolService.run_command(cmd, timeout=5)
                    if stdout and not stderr:
                        device_name = stdout.strip()
                    
                    system_type = "Android"
                
                ToolService.run_command(f"{ADB_PATH} disconnect {ip}:5555")
            else:
                # Linux设备使用SSH方式
                # 初始化连接
                stdout, stderr, _ = ToolService.initialize_connection(ip, password)
                if not stderr:
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    getinfo_path_fixed = getinfo_path.replace('/', '\\')
                    cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {getinfo_path_fixed}'
                    stdout, stderr, returncode = ToolService.run_command(cmd, timeout=15)
                    if stdout and not stderr:
                        try:
                            info_parts = stdout.split()
                            if len(info_parts) >= 3:
                                mac_address = info_parts[0]
                                device_name = html.unescape(info_parts[1])
                                system_type = info_parts[2]
                        except Exception as parse_e:
                            print(f"解析设备信息失败: {parse_e}")
        except Exception as e:
            print(f"获取设备信息时出错: {e}")
        
        return mac_address, device_name, system_type

    @staticmethod
    def get_version_info(device_id, ip, password):
        """
        获取设备的版本信息（OTA版本、主版本）
        根据设备类型自动选择ADB或SSH方式
        
        返回:
            tuple: (ota_version, main_version)
        """
        ota_version = "N/A"
        main_version = "N/A"
        
        try:
            if ToolService.is_android_device(device_id):
                # Android设备使用ADB方式
                ToolService.run_command(f"{ADB_PATH} connect {ip}:5555")
                time.sleep(0.5)
                serial = ToolService.adb_get_device_serial(ip)
                
                # 获取OTA版本
                cmd = f"{ADB_PATH} -s {serial} shell getprop ro.build.version"
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
                if stdout and not stderr:
                    ota_version = stdout.strip()
                
                # 获取主版本
                cmd = f"{ADB_PATH} -s {serial} shell dumpsys package cn.huidu.lcd.player"
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
                if stdout and not stderr:
                    lines = stdout.strip().split('\n')
                    for line in lines:
                        if 'versionName' in line:
                            ver_parts = line.split('=', 1)
                            if len(ver_parts) > 1:
                                main_version = ver_parts[1].strip()
                                break
                
                ToolService.run_command(f"{ADB_PATH} disconnect {ip}:5555")
            else:
                # Linux设备使用SSH方式
                plink_exe = ToolService.get_tool_path('plink.exe')
                
                # 获取OTA版本
                ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "getprop ro.build.version"'
                stdout, stderr, returncode = ToolService.run_command(ssh_cmd, timeout=10)
                if stdout and not stderr:
                    ota_version = stdout.strip()
                
                # 获取主版本
                ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "dumpsys package cn.huidu.lcd.player | grep versionName"'
                stdout, stderr, returncode = ToolService.run_command(ssh_cmd, timeout=10)
                if stdout and not stderr:
                    lines = stdout.strip().split('\n')
                    for line in lines:
                        if 'versionName' in line:
                            ver_parts = line.split('=', 1)
                            if len(ver_parts) > 1:
                                main_version = ver_parts[1].strip()
                                break
        except Exception as e:
            print(f"获取版本信息时出错: {e}")
        
        return ota_version, main_version

    @staticmethod
    def get_device_info(device_stdout, pattern):
        """
        调用DeviceId.exe获取设备列表，增加健壮的异常处理。
        对于 Android 设备，会尝试先开启网络 ADB，再获取详细信息。
        """
        try:
            # 过滤符合模式的设备
            if not device_stdout or not device_stdout.strip():
                return None

            if device_stdout.split('-')[0] not in supported_dev_types:
                return None

            if not re.match(f'^({pattern})', device_stdout):
                return None

            parts = device_stdout.strip().split()
            if len(parts) < 2:
                return None

            device_id = parts[0]
            ip = parts[1]
            password = ToolService.get_password(device_id)

            # Android 设备：刷新时自动尝试开启网络 ADB
            adb_status = '未知'
            if ToolService.is_android_device(device_id):
                try:
                    print(f"[ToolService] 刷新设备 {device_id}，尝试确保网络 ADB 已开启")
                    adb_ok, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                    adb_status = '开启' if adb_ok else '未开启'
                    print(f"[ToolService] 设备 {device_id} ADB 状态: {adb_status}, serial={serial}")
                except Exception as adb_e:
                    adb_status = '未开启'
                    print(f"[ToolService] 设备 {device_id} 开启 ADB 失败: {adb_e}")
            else:
                adb_status = '不支持'

            # 获取设备信息
            mac_address, device_name, system_type = ToolService.get_advanced_device_info(
                device_id, ip, password
            )

            # 获取版本信息
            ota_version, main_version = ToolService.get_version_info(
                device_id, ip, password
            )

            # 将所有设备信息存储为字典
            device_info = {
                'id': device_id,
                'ip': ip,
                'password': password,
                'mac_address': mac_address,
                'device_name': device_name,
                'system_type': system_type,
                'ota_version': ota_version,
                'main_version': main_version,
                'adb_status': adb_status,
            }

            return device_info
        except Exception as e:
            import traceback
            print(f"处理设备信息时发生严重错误: {str(e)}")
            print(traceback.format_exc())
            return None
    
    @staticmethod
    def get_password(device_id):
        """
        调用HPassword.exe获取设备密码，增加重试机制
        """
        max_retries = 3
        for attempt in range(max_retries):
            hpassword_exe = ToolService.get_tool_path('HPassword.exe')
            stdout, stderr, returncode = ToolService.run_command(f'{hpassword_exe} "{device_id}"')
            if stderr:
                print(f"HPassword.exe 错误 (尝试 {attempt + 1}/{max_retries}): {stderr}")
                if "Access denied" in stderr or "password was not accepted" in stderr:
                    # 等待一段时间后重试
                    import time
                    time.sleep(2)
                    continue
                return ""
            
            password = stdout.strip()
            if password:
                return password
            
            # 如果密码为空，等待后重试
            import time
            time.sleep(2)
        
        print(f"HPassword.exe 获取设备 {device_id} 密码失败，已达到最大重试次数")
        return ""
    
    @staticmethod
    def ssh_execute_command(ip, password, command_script, base_dir):
        """
        通过plink执行远程命令 (仅用于Linux设备)
        """
        # 确保基础目录存在
        os.makedirs(base_dir, exist_ok=True)
        
        # 创建临时脚本文件
        script_filename = f"{base_dir}/{ip}temp_script.txt"
        with open(script_filename, 'w') as f:
            f.write(command_script)
            f.write('\nexit\n')
        
        # 执行远程命令
        plink_exe = ToolService.get_tool_path('plink.exe')
        cmd = f"{plink_exe} -batch -no-antispoof -l root -pw \"{password}\" \"{ip}\" -m {script_filename}"
        stdout, stderr, returncode = ToolService.run_command(cmd)
        # 清理临时文件
        if os.path.exists(script_filename):
            os.remove(script_filename)
        
        return stdout.strip(), stderr.strip(), returncode

    @staticmethod
    def adb_shell_command(ip, password, command_script=None):
        """通过adb shell执行命令 (仅用于Android设备)"""
        return ADBService.shell_command(ip, password, command_script)
    @staticmethod
    def execute_command(device_id, ip, password, command_script, base_dir="."):
        """
        统一的远程命令执行接口,根据设备类型自动选择SSH或ADB
        对于Android设备且网络ADB已成功开启的，强制使用 adb -s [serial] 执行命令。
        若 ADB 不可用，则回退到 SSH(plink) 执行。
        """
        if ToolService.is_android_device(device_id):
            # Android设备：如果 ADB 已开启，则使用 adb -s [serial] shell
            if ADBDeviceManager.should_use_adb(device_id):
                success, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                if success and serial:
                    return ADBDeviceManager.execute_adb_command(ip, serial, command_script)
            # ADB 不可用或 should_use_adb 为 False：回退到 SSH(plink)
            return ToolService.ssh_execute_command(ip, password, command_script, base_dir)
        else:
            # Linux设备使用SSH
            return ToolService.ssh_execute_command(ip, password, command_script, base_dir)

    
    @staticmethod
    def initialize_connection(ip, password):
        """
        首次连接时接受主机密钥，增加超时控制
        对于Android设备，此方法主要用于回退场景
        """
        plink_exe = ToolService.get_tool_path('plink.exe')
        cmd = f'echo y | {plink_exe} -l root -pw "{password}" "{ip}" "exit"'
        stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
        return stdout, stderr, returncode

    @staticmethod
    def adb_push_file(ip, password, local_file, remote_file, device_id=None):
        """完整的adb推送文件方法"""
        return ADBService.push_file(ip, password, local_file, remote_file, device_id)
    @staticmethod
    def adb_pull_file(ip, remote_file, local_file, device_id=None, password=None):
        """完整的adb拉取文件方法"""
        return ADBService.pull_file(ip, remote_file, local_file, device_id, password)
    @staticmethod
    def push_file(device_id, ip, password, local_file, remote_file, use_reliable=True):
        """
        统一的文件推送接口，根据设备类型自动选择ADB push或PSCP
        
        参数:
            device_id: 设备ID，用于判断设备类型
            ip: 设备IP地址
            password: 设备密码
            local_file: 本地文件路径
            remote_file: 远程文件路径
            use_reliable: 是否使用可靠推送方式（带MD5校验和重试）
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        # 首先检查本地文件是否存在
        import os
        if not os.path.exists(local_file):
            return "", f"本地文件不存在: {local_file} (当前工作目录: {os.getcwd()})", -1
        if not os.path.isfile(local_file):
            return "", f"路径不是文件: {local_file}", -1
        
        if ToolService.is_android_device(device_id):
            # Android设备使用ADB push
            if use_reliable:
                return ToolService.adb_push_file_reliable(ip, password, local_file, remote_file, device_id=device_id)
            else:
                return ToolService.adb_push_file(ip, password, local_file, remote_file, device_id=device_id)
        else:
            # Linux设备使用PSCP
            return ToolService.pscp_push_file(ip, password, local_file, remote_file)

    @staticmethod
    def pull_file(device_id, ip, password, remote_file, local_file):
        """
        统一的文件拉取接口，根据设备类型自动选择ADB pull或PSCP
        
        参数:
            device_id: 设备ID，用于判断设备类型
            ip: 设备IP地址
            password: 设备密码
            remote_file: 远程文件路径
            local_file: 本地文件路径
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        if ToolService.is_android_device(device_id):
            # Android设备使用ADB pull
            return ToolService.adb_pull_file(ip, remote_file, local_file, device_id=device_id, password=password)
        else:
            # Linux设备使用PSCP
            return ToolService.pscp_pull_file(ip, password, remote_file, local_file)

    @staticmethod
    def pscp_push_file(ip, password, local_file, remote_file):
        """
        使用pscp推送文件到Linux设备，返回stdout/stderr/returncode
        """
        pscp_exe = ToolService.get_tool_path('pscp.exe')
        cmd = f"{pscp_exe} -pw \"{password}\" \"{local_file}\" root@{ip}:{remote_file}"
        return ToolService.run_command(cmd)

    @staticmethod
    def pscp_pull_file(ip, password, remote_file, local_file):
        """
        使用pscp从Linux设备拉取文件，返回stdout/stderr/returncode
        """
        pscp_exe = ToolService.get_tool_path('pscp.exe')
        cmd = f"{pscp_exe} -pw \"{password}\" root@{ip}:{remote_file} \"{local_file}\""
        return ToolService.run_command(cmd)

    @staticmethod
    def adb_screencap(ip, remote_file):
        """使用adb执行屏幕截图命令"""
        return ADBService.screencap(ip, remote_file)
    @staticmethod
    def adb_prepare_connection(ip, need_remount=False, device_id=None, password=None):
        """准备ADB连接"""
        return ADBService.prepare_connection(ip, need_remount, device_id, password)
    @staticmethod
    def adb_connect(ip):
        """使用adb连接设备"""
        return ADBService.connect(ip)
    @staticmethod
    def adb_get_device_serial(ip):
        """从adb devices输出中获取设备序列号"""
        return ADBService.get_device_serial(ip)
    @staticmethod
    def adb_disconnect():
        """使用adb断开所有连接"""
        return ADBService.disconnect()
    @staticmethod
    def adb_rm_file(ip, remote_file):
        """使用adb删除设备上的文件"""
        return ADBService.rm_file(ip, remote_file)
    @staticmethod
    def calculate_md5(file_path):
        """计算本地文件的MD5值"""
        return calculate_md5(file_path)
    @staticmethod
    def adb_calculate_md5(ip, remote_file, device_id=None, password=None):
        """使用adb计算远程文件的MD5值"""
        return ADBService.calc_file_md5(ip, remote_file, device_id, password)
    @staticmethod
    def adb_ensure_directory(ip, remote_dir):
        """确保远程目录存在"""
        return ADBService.ensure_directory(ip, remote_dir)
    @staticmethod
    def adb_push_file_reliable(ip, password, local_file, remote_file, max_retries=3, device_id=None):
        """可靠的adb推送文件方法"""
        return ADBService.push_file_reliable(ip, password, local_file, remote_file, max_retries, device_id)
    @staticmethod
    def adb_remount_system(ip):
        """重新挂载/system分区为可读写模式"""
        return ADBService.remount_system(ip)
    @staticmethod
    def adb_set_permissions(ip, remote_file, permissions="777"):
        """设置远程文件的权限"""
        return ADBService.set_permissions(ip, remote_file, permissions)
    @staticmethod
    def adb_set_executable(ip, remote_file):
        """设置远程文件为可执行"""
        return ADBService.set_executable(ip, remote_file)
    @staticmethod
    def adb_check_file_exists(ip, remote_file, max_retries=3, device_id=None, password=None):
        """使用ADB检查远程文件是否存在"""
        return ADBService.check_file_exists(ip, remote_file, max_retries, device_id, password)
    @staticmethod
    def ssh_check_file_exists(ip, password, remote_file, max_retries=3):
        """
        使用SSH检查远程文件是否存在，带重试机制
        max_retries=1时为快速检查模式，不进行重试等待
        
        参数:
            ip: 设备IP地址
            password: 设备密码
            remote_file: 远程文件路径
            max_retries: 最大重试次数
            
        返回:
            bool: 文件存在返回True，否则返回False
        """
        is_fast_check = max_retries == 1
        
        for attempt in range(max_retries):
            try:

                plink_exe = ToolService.get_tool_path('plink.exe')
                cmd = f'echo y | {plink_exe} -batch -l root -pw "{password}" "{ip}" "ls -l {remote_file}"'
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=5 if is_fast_check else 10)
                

                
                if returncode == 0 and not stderr and "No such" not in stdout:
                    return True
                
                # 如果失败，等待后重试（仅非快速检查模式）
                if attempt < max_retries - 1 and not is_fast_check:
                    time.sleep(1)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        return False
    
    @staticmethod
    def check_file_exists(device_id, ip, password, remote_file, max_retries=3):
        """
        根据设备类型检查远程文件是否存在，带重试机制
        
        参数:
            device_id: 设备ID
            ip: 设备IP地址
            password: 设备密码
            remote_file: 远程文件路径
            max_retries: 最大重试次数
            
        返回:
            bool: 文件存在返回True，否则返回False
        """
        if ToolService.is_android_device(device_id):
            # 对于Android设备，优先使用SSH方式查询，避免ADB连接问题
            try:
                exists = ToolService.ssh_check_file_exists(ip, password, remote_file, max_retries)
                if exists:
                    return True
            except Exception as e:
                pass
            
            # SSH失败时尝试ADB
            try:
                return ToolService.adb_check_file_exists(ip, remote_file, max_retries, device_id=device_id, password=password)
            except Exception as e:
                return False
        else:
            # Linux设备使用SSH
            return ToolService.ssh_check_file_exists(ip, password, remote_file, max_retries)
    
    @staticmethod
    def execute_query_command(device_id, ip, password, cmd, working_dir=None, max_retries=3):
        """
        执行查询类命令
        - 对于已成功开启网络 ADB 的 Android 设备，强制使用 adb -s [serial] shell 执行。
        - 其他 Android 设备或 ADB 未开启时，使用 SSH(plink) 方式避免 ADB 连接冲突。
        
        参数:
            device_id: 设备ID
            ip: 设备IP地址
            password: 设备密码
            cmd: 要执行的命令
            working_dir: 工作目录（可选）
            max_retries: 最大重试次数
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        for attempt in range(max_retries):
            try:
                if ToolService.is_android_device(device_id):
                    # 优先：Android 且 ADB 已开启 → 使用 adb -s [serial]
                    if ADBDeviceManager.should_use_adb(device_id):
                        success, serial = ADBDeviceManager.ensure_adb_connected(ip, password, device_id)
                        if success and serial:
                            if working_dir:
                                command_script = f'cd {working_dir} && {cmd}'
                            else:
                                command_script = cmd
                            return ADBDeviceManager.execute_adb_command(ip, serial, command_script)
                    
                    # 否则使用 SSH(plink) 方式
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    if working_dir:
                        full_cmd = f'cd {working_dir} && {cmd}'
                    else:
                        full_cmd = cmd
                    ssh_cmd = f'echo y | {plink_exe} -batch -l root -pw "{password}" "{ip}" "{full_cmd}"'
                    stdout, stderr, returncode = ToolService.run_command(ssh_cmd, timeout=30)
                    
                    # 如果成功或者不是连接类错误，直接返回
                    if returncode == 0 or not stderr or not ("refused" in stderr.lower() or "unable" in stderr.lower()):
                        return stdout, stderr, returncode
                    
                    # SSH 失败时回退到通用 execute_command
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, cmd, working_dir)
                    if returncode == 0 or not stderr or not ("refused" in stderr.lower() or "unable" in stderr.lower()):
                        return stdout, stderr, returncode
                else:
                    # Linux 设备使用 SSH
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    if working_dir:
                        full_cmd = f'cd {working_dir} && {cmd}'
                    else:
                        full_cmd = cmd
                    ssh_cmd = f'echo y | {plink_exe} -batch -l root -pw "{password}" "{ip}" "{full_cmd}"'
                    stdout, stderr, returncode = ToolService.run_command(ssh_cmd, timeout=30)
                    
                    if returncode == 0 or not stderr or not ("refused" in stderr.lower() or "unable" in stderr.lower()):
                        return stdout, stderr, returncode
                
                # 如果失败且还有重试次数，等待后重试
                if attempt < max_retries - 1:
                    time.sleep(1)
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        # 所有重试都失败
        return "", f"执行命令失败，已重试{max_retries}次", -1

    @staticmethod
    def get_device_otg_config(device_id):
        """
        根据设备ID获取OTG配置
        
        参数:
            device_id: 设备ID，如"A3L-xxx"
            
        返回:
            dict: 包含path和value的字典，或None
        """
        try:
            dev_type_prefix = device_id.split('-')[0]
            return DEVICE_OTG_CONFIG.get(dev_type_prefix)
        except Exception as e:
            return None

    @staticmethod
    def set_device_otg_mode(ip, password, device_id):
        """通过SSH设置设备的OTG模式为peripheral模式"""
        return ADBService.set_otg_mode(ip, password, device_id)
    @staticmethod
    def verify_device_otg_mode(ip, password, device_id):
        """
        验证设备的OTG模式是否已设置为peripheral模式
        
        参数:
            ip: 设备IP
            password: 设备密码
            device_id: 设备ID
            
        返回:
            tuple: (success, current_value)
        """
        try:
            otg_config = ToolService.get_device_otg_config(device_id)
            if not otg_config:
                return True, "无配置需要验证"
            
            otg_path = otg_config['path']
            expected_value = otg_config['value']
            
            # 使用plink读取OTG模式值
            plink_exe = ToolService.get_tool_path('plink.exe')
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "cat {otg_path}"'
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
            
            current_value = stdout.strip()
            
            if current_value == expected_value:
                return True, current_value
            else:
                return False, f"当前值: {current_value}, 期望值: {expected_value}"
                
        except Exception as e:
            return False, f"验证异常: {str(e)}"

    @staticmethod
    def restart_adb_service(ip, password, device_id):
        """通过SSH重启设备的ADB服务"""
        return ADBService.restart_service(ip, password, device_id)