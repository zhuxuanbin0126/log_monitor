#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
from datetime import datetime, timedelta
import re
import json

class ToolService:
    """工具服务类，负责与外部工具交互"""
    
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
        stdout, stderr, returncode = ToolService.run_command('DeviceId.exe')
        if stderr:
            print(f"DeviceId.exe 错误: {stderr}")
            return []
        
        # 过滤符合模式的设备
        devices = []
        for line in stdout.split('\n'):
            if re.match(f"^({pattern})", line):
                parts = line.strip().split()
                if len(parts) >= 2:
                    device_id = parts[0]
                    ip = parts[1]
                    password = ToolService.get_password(device_id)
                    # 初始设置为未知
                    mac_address = "未知"
                    device_name = "未知"
                    
                    # 尝试获取MAC地址和设备名称
                    try:
                        # 初始化连接
                        ToolService.initialize_connection(ip, password)
                        
                        # 获取MAC地址
                        mac_cmd = 'cat /sys/class/net/eth0/address'
                        mac_stdout, mac_stderr, _ = ToolService.ssh_execute_command(ip, password, mac_cmd, '.')
                        if mac_stdout and not mac_stderr:
                            mac_address = mac_stdout.strip()
                        
                        # 检查设备ID前缀是否为C08L、C16L或D16
                        if device_id.startswith('C08L') or device_id.startswith('C16L') or device_id.startswith('D16'):
                            # 这三种设备类型不支持获取设备名称
                            device_name = "无法获取"
                        else:
                            # 获取设备名称
                            device_name_cmd = 'cat /data/data/cn.huidu.lcd.player/files/config/DeviceInfoConfig.xml'
                            name_stdout, name_stderr, _ = ToolService.ssh_execute_command(ip, password, device_name_cmd, '.')
                            if name_stdout and not name_stderr:
                                name_match = re.search(r'<item name="DeviceName">(.*?)</item>', name_stdout)
                                if name_match:
                                    device_name = name_match.group(1)
                    except Exception as e:
                        print(f"获取设备 {device_id} 详细信息时出错: {str(e)}")
                    
                    # 将所有设备信息存储为字典
                    devices.append({
                        'id': device_id,
                        'ip': ip,
                        'password': password,
                        'mac_address': mac_address,
                        'device_name': device_name
                    })
        
        return devices
    
    @staticmethod
    def get_password(device_id):
        """
        调用HPassword.exe获取设备密码，增加重试机制
        """
        max_retries = 3
        for attempt in range(max_retries):
            stdout, stderr, returncode = ToolService.run_command(f'HPassword.exe "{device_id}"')
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
        script_filename = f'{base_dir}/temp_script.txt'
        with open(script_filename, 'w') as f:
            f.write(command_script)
            f.write('\nexit\n')
        
        # 执行远程命令
        cmd = f'plink -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {script_filename}'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        
        # 清理临时文件
        if os.path.exists(script_filename):
            os.remove(script_filename)
        
        return stdout.strip(), stderr.strip(), returncode
    
    @staticmethod
    def initialize_connection(ip, password):
        """
        首次连接时接受主机密钥
        """
        cmd = f'echo y | plink -l root -pw "{password}" "{ip}" "exit"'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        return stdout, stderr, returncode

    @staticmethod
    def adb_push_file(ip, password, local_file, remote_file):
        """
        使用adb将文件推送到远程设备
        """
        cmd = f'adb -s {ip} connect {ip}:5555'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        if not stderr:
            cmd = f"adb -s {ip} root & adb -s {ip} remount"
            stdout, stderr, returncode = ToolService.run_command(cmd)
            if not  stderr:
                cmd = f'adb -s {ip} push {local_file} {remote_file}'
                stdout, stderr, returncode = ToolService.run_command(cmd)
                if not stderr:
                    return stdout
            else:
                cmd="adb disconnect"
                ToolService.run_command(cmd)
        return stderr

    @staticmethod
    def pscp_push_file(ip, password, local_file, remote_file):
        """
        使用pscp将文件推送到远程设备
        """
        cmd = f'pscp -pw "{password}" {local_file} root@{ip}:{remote_file}'
        stdout, stderr, returncode = ToolService.run_command(cmd)
        if not stderr:
            return stdout
        else:
            return stderr