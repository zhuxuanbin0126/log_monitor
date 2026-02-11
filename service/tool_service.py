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

# 获取项目根目录和工具路径
def get_project_root():
    """获取项目根目录，支持打包后的环境"""
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        else:
            return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROJECT_ROOT = get_project_root()

# 根据是否是打包环境确定工具目录
if getattr(sys, 'frozen', False):
    # 打包后的环境，工具文件在tools/bin目录
    TOOLS_DIR = os.path.join(PROJECT_ROOT, 'tools', 'bin')
else:
    # 开发环境，工具文件在tools/bin目录
    TOOLS_DIR = os.path.join(PROJECT_ROOT, 'tools', 'bin')

ADB_PATH = os.path.join(TOOLS_DIR, 'adb.exe')
# 确保路径使用反斜杠（Windows）
ADB_PATH = ADB_PATH.replace('/', '\\')
TOOLS_DIR = TOOLS_DIR.replace('/', '\\')

class ToolService:
    """工具服务类，负责与外部工具交互"""

    @staticmethod
    def get_tool_path(tool_name):
        """
        获取工具的完整路径，确保使用反斜杠格式（Windows）
        """
        path = os.path.join(TOOLS_DIR, tool_name)
        return path.replace('/', '\\')

    @staticmethod
    def run_command(cmd, encoding='utf-8'):
        """
        执行命令并返回输出
        """
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding=encoding)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except Exception as e:
            return "", str(e), -1
    
    @staticmethod
    def get_device_list(dev_type="A-B-C-D"):
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
            if line.split("-")[0] not in supported_dev_types:
                continue

            if re.match(f"^({pattern})", line):
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
                        # 初始化连接
                        stdout, stderr, _=ToolService.initialize_connection(ip, password)
                        print(f"初始化连接 {device_id} - stderr: {stderr}")
                        if not stderr:
                            plink_exe = ToolService.get_tool_path('plink.exe')
                            # 将路径转换为反斜杠格式
                            getinfo_path_fixed = getinfo_path.replace('/', '\\')
                            cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {getinfo_path_fixed}'
                            stdout, stderr, returncode = ToolService.run_command(cmd)
                            print(f"getdeviceinfo {device_id} - stdout: {stdout}, stderr: {stderr}, returncode: {returncode}")
                            if stdout and not stderr:
                                print(stdout)
                                mac_address = stdout.split(" ")[0]
                                device_name = html.unescape(stdout.split(" ")[1])
                                system_type = stdout.split(" ")[2]
                            else:
                                print(f"获取设备信息失败 - stdout: {stdout}, stderr: {stderr}")

                    except Exception as e:
                        print(f"获取设备 {device_id} 详细信息时出错: {str(e)}")
                    
                    # 尝试获取OTA版本和主版本
                    ota_version = "N/A"
                    main_version = "N/A"
                    
                    try:
                        # 当前支持ADB功能的设备类型：H6、H8、H4K、B6L、B8L、A4L、A5L、A6L                   
                        # 获取OTA版本
                        plink_exe = ToolService.get_tool_path('plink.exe')
                        ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "getprop ro.build.version"'
                        stdout, stderr, returncode = ToolService.run_command(ssh_cmd)
                        if stdout and not stderr:
                            ota_version = stdout.strip()
                        
                        # 获取播放器版本
                        plink_exe = ToolService.get_tool_path('plink.exe')
                        ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "dumpsys package cn.huidu.lcd.player | grep versionName"'
                        stdout, stderr, returncode = ToolService.run_command(ssh_cmd)
                        if stdout and not stderr:
                            lines = stdout.strip().split('\n')
                            for line in lines:
                                if 'versionName' in line:
                                    parts = line.split('=', 1)
                                    if len(parts) > 1:
                                        main_version = parts[1].strip()
                                        break
                    except Exception as e:
                        print(f"获取设备 {device_id} 版本信息时出错: {str(e)}")
                    
                    # 将所有设备信息存储为字典
                    devices.append({
                        'id': device_id,
                        'ip': ip,
                        'password': password,
                        'mac_address': mac_address,
                        'device_name': device_name,
                        "system_type": system_type,
                        "ota_version": ota_version,
                        "main_version": main_version
                    })
        
        return devices

    @staticmethod
    def get_device_info(device_stdout, pattern):
        """
        调用DeviceId.exe获取设备列表
        """

        # 过滤符合模式的设备
        if device_stdout.split("-")[0] not in supported_dev_types:
            return None

        if re.match(f"^({pattern})", device_stdout):
            parts = device_stdout.strip().split()
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
                    # 初始化连接
                    stdout, stderr, _ = ToolService.initialize_connection(ip, password)
                    if not stderr:
                        plink_exe = ToolService.get_tool_path('plink.exe')
                        # 将路径转换为反斜杠格式
                        getinfo_path_fixed = getinfo_path.replace('/', '\\')
                        cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {getinfo_path_fixed}'
                        stdout, stderr, returncode = ToolService.run_command(cmd)
                        # print(f"getdeviceinfo {device_id} {stdout}")
                        if stdout and not stderr:
                            mac_address = stdout.split(" ")[0]
                            device_name = html.unescape(stdout.split(" ")[1])
                            system_type = stdout.split(" ")[2]

                except Exception as e:
                    print(f"获取设备 {device_id} 详细信息时出错: {str(e)}")

                # 尝试获取OTA版本和主版本
                ota_version = "N/A"
                main_version = "N/A"
                
                try:

                    
                    # 获取OTA版本
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "getprop ro.build.version"'
                    stdout, stderr, returncode = ToolService.run_command(ssh_cmd)
                    if stdout and not stderr:
                        ota_version = stdout.strip()
                    
                    # 获取主版本（所有设备）
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    ssh_cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" "dumpsys package cn.huidu.lcd.player | grep versionName"'
                    stdout, stderr, returncode = ToolService.run_command(ssh_cmd)
                    if stdout and not stderr:
                        # 提取第一行"="后面的文本内容
                        lines = stdout.strip().split('\n')
                        for line in lines:
                            if 'versionName' in line:
                                # 找到第一个等号后的内容
                                parts = line.split('=', 1)
                                if len(parts) > 1:
                                    main_version = parts[1].strip()
                                    break
                except Exception as e:
                    print(f"获取设备 {device_id} 版本信息时出错: {str(e)}")

                # 将所有设备信息存储为字典
                device_info={
                    'id': device_id,
                    'ip': ip,
                    'password': password,
                    'mac_address': mac_address,
                    'device_name': device_name,
                    "system_type": system_type,
                    "ota_version": ota_version,
                    "main_version": main_version
                }

        return device_info
    
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
        通过plink执行远程命令
        """
        # 确保基础目录存在
        os.makedirs(base_dir, exist_ok=True)
        
        # 创建临时脚本文件
        script_filename = f'{base_dir}/{ip}temp_script.txt'
        with open(script_filename, 'w') as f:
            f.write(command_script)
            f.write('\nexit\n')
        
        # 执行远程命令
        plink_exe = ToolService.get_tool_path('plink.exe')
        cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {script_filename}'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        # 清理临时文件
        if os.path.exists(script_filename):
            os.remove(script_filename)
        
        return stdout.strip(), stderr.strip(), returncode

    def adb_shell_command(self, ip, password, command_script):

        ToolService.run_command(f"{ADB_PATH} connect {ip}:5555")
        cmd = f"{ADB_PATH} shell {command_script}"
        stdout, stderr, returncode = ToolService.run_command(cmd)
        ToolService.run_command(f"{ADB_PATH} disconnect {ip}:5555")

        return stdout.strip(), stderr.strip()


    @staticmethod
    def initialize_connection(ip, password):
        """
        首次连接时接受主机密钥
        """
        plink_exe = ToolService.get_tool_path('plink.exe')
        cmd = f'echo y | {plink_exe} -l root -pw "{password}" "{ip}" "exit"'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        return stdout, stderr, returncode

    @staticmethod
    def adb_push_file(ip, password, local_file, remote_file):
        """
        使用adb将文件推送到远程设备
        """
        try:
            cmd = f'{ADB_PATH} -s {ip} connect {ip}:5555'
            stdout, stderr, returncode = ToolService.run_command(cmd)
            if not stderr:
                cmd = f"{ADB_PATH} -s {ip} root & {ADB_PATH} -s {ip} remount"
                stdout, stderr, returncode = ToolService.run_command(cmd)
                if not  stderr:
                    cmd = f'{ADB_PATH} -s {ip} push {local_file} {remote_file}'
                    stdout, stderr, returncode = ToolService.run_command(cmd)
                    if not stderr:
                        return stdout
                else:
                    cmd=f"{ADB_PATH} disconnect"
                    ToolService.run_command(cmd)
        except Exception as e:
            print(f"Error: {str(e)}")
        return stderr

    @staticmethod
    def adb_pull_file(ip, password, local_file, remote_file):
        """
        使用adb将文件推送到远程设备
        """
        try:
            cmd = f'{ADB_PATH} -s {ip} connect {ip}:5555'
            stdout, stderr, returncode = ToolService.run_command(cmd)
            if not stderr:
                cmd = f"{ADB_PATH} -s {ip} root & {ADB_PATH} -s {ip} remount"
                stdout, stderr, returncode = ToolService.run_command(cmd)
                if not stderr:
                    cmd = f'{ADB_PATH} -s {ip} pull {local_file} {remote_file}'
                    stdout, stderr, returncode = ToolService.run_command(cmd)
                    if not stderr:
                        return stdout
        except Exception as e:
            return f"Error: {str(e)}"
        return stdout

    @staticmethod
    def pscp_push_file(ip, password, local_file, remote_file):
        """
        使用pscp将文件推送到远程设备
        """
        pscp_exe = ToolService.get_tool_path('pscp.exe')
        cmd = f'{pscp_exe} -pw "{password}" {local_file} root@{ip}:{remote_file}'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        if not stderr:
            return stdout
        else:
            return stderr

    @staticmethod
    def pscp_pull_file(ip, password, remote_file, local_file):
        """
        使用pscp将文件推送到远程设备
        """
        pscp_exe = ToolService.get_tool_path('pscp.exe')
        cmd = f'{pscp_exe} -pw "{password}" root@{ip}:{remote_file} {local_file}'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        if not stderr:
            return stdout
        else:
            return stderr
    
    @staticmethod
    def adb_screencap(ip, remote_file):
        """
        使用adb执行屏幕截图命令
        
        参数:
        ip: 设备IP地址
        remote_file: 远程保存路径
        
        返回:
        tuple: (stdout, stderr, returncode)
        """
        cmd = f'{ADB_PATH} -s {ip}:5555 shell screencap -p {remote_file}'
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_pull_file(ip, remote_file, local_file):
        """
        使用adb从设备拉取文件
        
        参数:
        ip: 设备IP地址
        remote_file: 远程文件路径
        local_file: 本地保存路径
        
        返回:
        tuple: (stdout, stderr, returncode)
        """
        cmd = f'{ADB_PATH} -s {ip}:5555 pull {remote_file} {local_file}'
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_connect(ip):
        """
        使用adb连接设备
        
        参数:
        ip: 设备IP地址
        
        返回:
        tuple: (stdout, stderr, returncode)
        """
        cmd = f'{ADB_PATH} connect {ip}:5555'
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_disconnect():
        """
        使用adb断开所有连接
        
        返回:
        tuple: (stdout, stderr, returncode)
        """
        cmd = f'{ADB_PATH} disconnect'
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_rm_file(ip, remote_file):
        """
        使用adb删除设备上的文件
        
        参数:
        ip: 设备IP地址
        remote_file: 远程文件路径
        
        返回:
        tuple: (stdout, stderr, returncode)
        """
        cmd = f'{ADB_PATH} -s {ip}:5555 shell rm {remote_file}'
        return ToolService.run_command(cmd)