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

# 定义Android设备类型列表
ANDROID_DEV_TYPES = ['A3L', 'A4L', 'A5L', 'A6L', 'A7', 'A8', 'B6L', 'B8L', 'C16H', 'H4K', 'H6', 'H8', 'H20']
# 定义Linux设备类型列表
LINUX_DEV_TYPES = ['C08L', 'C16L', 'D16', 'D36']

# 加载device_info.json获取OTG配置
DEVICE_OTG_CONFIG = {}
try:
    device_info_path = os.path.join(PROJECT_ROOT, 'device_info.json')
    if os.path.exists(device_info_path):
        with open(device_info_path, 'r', encoding='utf-8') as f:
            device_info_list = json.load(f)
            for device_info in device_info_list:
                model = device_info.get('型号')
                otg_config = device_info.get('保存OTG属性')
                if model and otg_config and otg_config != 'nan':
                    # 解析命令格式："echo peripheral > /sys/.../otg_mode"
                    if '>' in otg_config:
                        parts = otg_config.split('>')
                        if len(parts) >= 2:
                            path = parts[1].strip()
                            value = parts[0].strip().split()[-1] if ' ' in parts[0] else 'peripheral'
                            DEVICE_OTG_CONFIG[model] = {'path': path, 'value': value}
except Exception as e:
    pass
             
             
             
class ToolService:
    """工具服务类，负责与外部工具交互"""

    @staticmethod
    def is_android_device(device_id):
        """
        判断设备是否是Android类型
        
        参数:
            device_id: 设备ID
            
        返回:
            bool: True如果是Android设备，False如果是Linux设备或无法判断
        """
        if not device_id:
            return False
        # 提取设备类型前缀
        if '-' in device_id:
            dev_type = device_id.split('-')[0]
        else:
            dev_type = device_id
        return dev_type in ANDROID_DEV_TYPES

    @staticmethod
    def get_tool_path(tool_name):
        """
        获取工具的完整路径，确保使用反斜杠格式（Windows）
        """
        path = os.path.join(TOOLS_DIR, tool_name)
        return path.replace('/', '\\')

    @staticmethod
    def run_command(cmd, encoding='utf-8', timeout=30):
        """
        执行命令并返回输出，支持超时控制
        
        参数:
            cmd: 要执行的命令
            encoding: 输出编码
            timeout: 超时时间（秒），默认30秒
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        result_queue = queue.Queue()
        
        def _run_command_thread():
            try:
                proc = subprocess.Popen(
                    cmd, 
                    shell=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True, 
                    encoding=encoding
                )
                stdout, stderr = proc.communicate(timeout=timeout)
                result_queue.put((stdout.strip(), stderr.strip(), proc.returncode))
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except:
                    pass
                result_queue.put(("", f"命令执行超时（{timeout}秒）", -2))
            except Exception as e:
                result_queue.put(("", str(e), -1))
        
        thread = threading.Thread(target=_run_command_thread, daemon=True)
        thread.start()
        thread.join(timeout=timeout + 2)
        
        if thread.is_alive():
            return "", f"命令执行超时（{timeout}秒）", -2
        
        try:
            return result_queue.get_nowait()
        except queue.Empty:
            return "", "命令执行失败", -1

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
                        'main_version': main_version
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
        调用DeviceId.exe获取设备列表，增加健壮的异常处理
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
                'main_version': main_version
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
        """
        通过adb shell执行命令 (仅用于Android设备)
        """
        # 连接设备
        ToolService.run_command(f"{ADB_PATH} connect {ip}:5555")
        time.sleep(0.5)  # 等待连接建立
        serial = ToolService.adb_get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell {command_script}"
        stdout, stderr, returncode = ToolService.run_command(cmd)
        # 断开连接
        ToolService.run_command(f"{ADB_PATH} disconnect {ip}:5555")
        return stdout.strip(), stderr.strip(), returncode
    @staticmethod
    def execute_command(device_id, ip, password, command_script, base_dir="."):
        """
        统一的远程命令执行接口,根据设备类型自动选择SSH或ADB
        
        """
        if ToolService.is_android_device(device_id):
            # Android设备使用ADB
            return ToolService.adb_shell_command(ip, password, command_script)
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
        """
        完整的adb推送文件方法，返回stdout/stderr/returncode
        """
        try:
            # 判断是否需要remount
            need_remount = remote_file.startswith("/system/") or "/system/" in remote_file
            
            # 使用新的连接准备方法
            stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=need_remount, device_id=device_id, password=password)
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                # 连接失败，尝试通过SSH开启ADB服务
                try:
                    print(f"[push] 连接失败，尝试通过SSH重启ADB服务")
                    plink_exe = ToolService.get_tool_path('plink.exe')
                    ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"setprop service.adb.tcp.port 5555\"", timeout=5)
                    ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"stop adbd\"", timeout=5)
                    ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"start adbd\"", timeout=5)
                    time.sleep(3)
                    # 重新准备连接
                    stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=need_remount, device_id=device_id, password=password)
                    if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                        return "", stderr, returncode
                except Exception as e:
                    return "", str(e), -1
            
            serial = ToolService.adb_get_device_serial(ip)
            # 推送文件
            print(f"[push] 开始推送文件: {local_file} -> {remote_file}")
            cmd = f"{ADB_PATH} -s {serial} push \"{local_file}\" \"{remote_file}\""
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=60)
            print(f"[push] 推送结果: stdout={stdout}, stderr={stderr}, code={returncode}")
            
            ToolService.adb_disconnect()
            return stdout.strip(), stderr.strip(), returncode
        except Exception as e:
            return "", str(e), -1

    @staticmethod
    def adb_pull_file(ip, remote_file, local_file, device_id=None, password=None):
        """
        完整的adb拉取文件方法，返回stdout/stderr/returncode
        执行pull前先执行adb root以确保权限
        """
        try:
            # 使用新的连接准备方法
            stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=False, device_id=device_id, password=password)
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                return "", stderr, returncode
            
            serial = ToolService.adb_get_device_serial(ip)
            # 在pull之前执行adb root以提升权限
            cmd = f"{ADB_PATH} -s {serial} root"
            ToolService.run_command(cmd, timeout=10)
            
            # 等待root生效，部分设备root后会短暂断开连接
            time.sleep(2)
            
            # 重新连接（如果需要）
            cmd = f"{ADB_PATH} connect {ip}:5555"
            ToolService.run_command(cmd)
            time.sleep(2)
            
            # 拉取文件
            cmd = f"{ADB_PATH} -s {serial} pull \"{remote_file}\" \"{local_file}\""
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=60)
            
            ToolService.adb_disconnect()
            return stdout.strip(), stderr.strip(), returncode
        except Exception as e:
            return "", str(e), -1

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
        """
        使用adb执行屏幕截图命令
        
        参数:
            ip: 设备IP地址
            remote_file: 远程保存路径
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        serial = ToolService.adb_get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell screencap -p {remote_file}"
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_prepare_connection(ip, need_remount=False, device_id=None, password=None):
        """
        准备ADB连接：断开已有连接 -> 连接设备 -> 可选root -> 可选remount
        当连接失败时，会尝试设置OTG模式并重启ADB服务
        
        参数:
            ip: 设备IP地址
            need_remount: 是否需要remount/system分区
            device_id: 设备ID（用于获取OTG配置）
            password: 设备密码（用于SSH连接）
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        try:
            # 1. 先断开所有连接
            cmd = f"{ADB_PATH} disconnect"
            ToolService.run_command(cmd)
            time.sleep(1)
            
            # 2. 连接设备
            cmd = f"{ADB_PATH} connect {ip}:5555"
            stdout, stderr, returncode = ToolService.run_command(cmd)
            time.sleep(2)  # 等待连接稳定
            
            # 3. 检查是否连接失败（积极拒绝等错误）
            connection_failed = (stderr and (
                "unable" in stderr.lower() or 
                "cannot" in stderr.lower() or 
                "refused" in stderr.lower() or
                "积极拒绝" in stderr)) or returncode != 0
            
            if connection_failed and device_id and password:
                # 4. 尝试设置OTG模式
                ToolService.set_device_otg_mode(ip, password, device_id)
                
                # 5. 重启ADB服务
                ToolService.restart_adb_service(ip, password, device_id)
                
                # 6. 再次尝试连接
                cmd = f"{ADB_PATH} disconnect"
                ToolService.run_command(cmd)
                time.sleep(1)
                
                cmd = f"{ADB_PATH} connect {ip}:5555"
                stdout, stderr, returncode = ToolService.run_command(cmd)
                time.sleep(2)
            
            # 7. 如果需要remount，执行root和remount
            if need_remount:
                ToolService.adb_remount_system(ip)
            
            return stdout, stderr, returncode
        except Exception as e:
            return "", str(e), -1
    
    @staticmethod
    def adb_connect(ip):
        """
        使用adb连接设备
        
        参数:
            ip: 设备IP地址
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        cmd = f"{ADB_PATH} connect {ip}:5555"
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_get_device_serial(ip):
        """
        从adb devices输出中获取设备序列号
        
        参数:
            ip: 设备IP地址
            
        返回:
            str: 设备序列号，失败时回退到 ip:5555 格式
        """
        try:
            cmd = f"{ADB_PATH} devices"
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
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
        # 回退到 ip:5555 格式
        return f"{ip}:5555"
    
    @staticmethod
    def adb_disconnect():
        """
        使用adb断开所有连接
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        cmd = f"{ADB_PATH} disconnect"
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
        serial = ToolService.adb_get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell rm {remote_file}"
        return ToolService.run_command(cmd)
    
    @staticmethod
    def calculate_md5(file_path):
        """
        计算本地文件的MD5值
        
        参数:
            file_path: 本地文件路径
            
        返回:
            str: MD5值，如果失败返回None
        """
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            return None
    
    @staticmethod
    def adb_calculate_md5(ip, remote_file, device_id=None, password=None):
        """
        使用adb计算远程文件的MD5值
        
        参数:
            ip: 设备IP地址
            remote_file: 远程文件路径
            device_id: 设备ID（用于获取OTG配置）
            password: 设备密码（用于SSH连接）
            
        返回:
            str: MD5值，如果失败返回None
        """
        try:
            # 使用新的连接准备方法
            stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=False, device_id=device_id, password=password)
            if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                return None
            
            serial = ToolService.adb_get_device_serial(ip)
            # 尝试使用md5sum命令
            cmd = f"{ADB_PATH} -s {serial} shell md5sum {remote_file}"
            stdout, stderr, returncode = ToolService.run_command(cmd)
            if not stderr and stdout:
                md5_value = stdout.strip().split()[0]
                ToolService.adb_disconnect()
                return md5_value
            
            # 如果md5sum不可用，尝试用dd读取文件然后在本地计算
            local_temp = f"temp_md5_{ip.replace('.', '_')}_{int(time.time())}"
            stdout, stderr, returncode = ToolService.adb_pull_file(ip, remote_file, local_temp, device_id=device_id, password=password)
            if not stderr and os.path.exists(local_temp):
                md5_value = ToolService.calculate_md5(local_temp)
                try:
                    os.remove(local_temp)
                except:
                    pass
                ToolService.adb_disconnect()
                return md5_value
            
            ToolService.adb_disconnect()
            return None
        except Exception as e:
            return None
    
    @staticmethod
    def adb_ensure_directory(ip, remote_dir):
        """
        确保远程目录存在
        
        参数:
            ip: 设备IP地址
            remote_dir: 远程目录路径
            
        返回:
            bool: True表示成功，False表示失败
        """
        try:
            serial = ToolService.adb_get_device_serial(ip)
            cmd = f"{ADB_PATH} -s {serial} shell mkdir -p {remote_dir}"
            stdout, stderr, returncode = ToolService.run_command(cmd)
            return returncode == 0 or (stderr and "File exists" in stderr)
        except Exception as e:
            return False
    
    @staticmethod
    def adb_push_file_reliable(ip, password, local_file, remote_file, max_retries=3, device_id=None):
        """
        可靠的adb推送文件方法，带有重试和MD5校验
        
        参数:
            ip: 设备IP地址
            password: 设备密码
            local_file: 本地文件路径
            remote_file: 远程文件路径
            max_retries: 最大重试次数
            device_id: 设备ID（用于获取OTG配置）
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        # 检查本地文件
        if not os.path.exists(local_file):
            return "", f"本地文件不存在: {local_file}", -1
        
        # 计算MD5
        local_md5 = ToolService.calculate_md5(local_file)
        if not local_md5:
            return "", "无法计算本地文件MD5", -2
        
        # 获取远程目录
        remote_dir = os.path.dirname(remote_file)
        # 判断是否需要remount
        need_remount = remote_file.startswith("/system/") or "/system/" in remote_file or remote_dir.startswith("/system/")
        
        serial = ToolService.adb_get_device_serial(ip)
        for attempt in range(max_retries):
            try:
                # 使用新的连接准备方法
                stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=need_remount, device_id=device_id, password=password)
                
                if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                    # 连接失败，尝试通过SSH开启ADB服务
                    try:
                        plink_exe = ToolService.get_tool_path('plink.exe')
                        ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"setprop service.adb.tcp.port 5555\"", timeout=5)
                        ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"stop adbd\"", timeout=5)
                        ToolService.run_command(f"echo y | {plink_exe} -l root -pw \"{password}\" \"{ip}\" \"start adbd\"", timeout=5)
                        time.sleep(3)
                        # 重新准备连接
                        stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=need_remount, device_id=device_id, password=password)
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
                
                # 确保远程目录存在
                if remote_dir and remote_dir != "/":
                    ToolService.adb_ensure_directory(ip, remote_dir)
                
                # 推送文件
                cmd = f"{ADB_PATH} -s {serial} push \"{local_file}\" \"{remote_file}\""
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=60)
                
                # 检查是否是只读文件系统错误
                if (stderr and ("Read-only file system" in stderr or "couldn't create file" in stderr)) or (stdout and ("Read-only file system" in stdout or "couldn't create file" in stdout)):
                    # 尝试重新挂载
                    remount_stdout, remount_stderr, remount_code = ToolService.adb_remount_system(ip)
                    if remount_code == 0 or not remount_stderr:
                        # 重新推送
                        stdout, stderr, returncode = ToolService.run_command(cmd, timeout=60)
                
                if stderr or returncode != 0:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    ToolService.adb_disconnect()
                    return stdout, stderr, returncode
                
                # MD5校验
                remote_md5 = ToolService.adb_calculate_md5(ip, remote_file, device_id=device_id, password=password)
                if remote_md5 and remote_md5 == local_md5:
                    ToolService.adb_disconnect()
                    return f"推送成功，MD5: {local_md5}", "", 0
                else:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    ToolService.adb_disconnect()
                    return "", f"MD5校验失败: 本地={local_md5}, 远程={remote_md5}", -3
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return "", str(e), -1
        
        ToolService.adb_disconnect()
        return "", f"已达到最大重试次数 ({max_retries})", -4
    
    @staticmethod
    def adb_remount_system(ip):
        """
        重新挂载/system分区为可读写模式
        
        参数:
            ip: 设备IP地址
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        try:
            # 1. 先断开所有连接
            cmd = f"{ADB_PATH} disconnect"
            ToolService.run_command(cmd)
            time.sleep(1)
            
            # 2. 连接设备
            cmd = f"{ADB_PATH} connect {ip}:5555"
            stdout, stderr, returncode = ToolService.run_command(cmd)
            time.sleep(2)
            
            serial = ToolService.adb_get_device_serial(ip)
            # 3. 尝试获取root权限
            cmd = f"{ADB_PATH} -s {serial} root"
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
            time.sleep(3)  # 等待root生效
            
            # 4. 重新连接（部分设备root后会断开连接）
            cmd = f"{ADB_PATH} connect {ip}:5555"
            ToolService.run_command(cmd)
            time.sleep(2)
            
            # 5. 尝试remount
            cmd = f"{ADB_PATH} -s {serial} remount"
            stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
            
            # 6. 如果remount失败，尝试使用mount命令
            if returncode != 0 or stderr:
                cmd = f"{ADB_PATH} -s {serial} shell \"mount -o remount,rw /system\""
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=10)
            
            # 无论是否完全成功，都返回最后一次执行的结果
            return stdout, stderr, returncode
        except Exception as e:
            return "", str(e), -1
    
    @staticmethod
    def adb_set_permissions(ip, remote_file, permissions="777"):
        """
        设置远程文件的权限
        
        参数:
            ip: 设备IP地址
            remote_file: 远程文件路径
            permissions: 权限设置，默认 "777"
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        serial = ToolService.adb_get_device_serial(ip)
        cmd = f"{ADB_PATH} -s {serial} shell chmod {permissions} {remote_file}"
        return ToolService.run_command(cmd)
    
    @staticmethod
    def adb_set_executable(ip, remote_file):
        """
        设置远程文件为可执行
        
        参数:
            ip: 设备IP地址
            remote_file: 远程文件路径
            
        返回:
            tuple: (stdout, stderr, returncode)
        """
        return ToolService.adb_set_permissions(ip, remote_file, "0755")
    
    @staticmethod
    def adb_check_file_exists(ip, remote_file, max_retries=3, device_id=None, password=None):
        """
        使用ADB检查远程文件是否存在，带重试机制
        max_retries=1时为快速检查模式，不进行重试等待
        
        参数:
            ip: 设备IP地址
            remote_file: 远程文件路径
            max_retries: 最大重试次数
            device_id: 设备ID（用于获取OTG配置）
            password: 设备密码（用于SSH连接）
            
        返回:
            bool: 文件存在返回True，否则返回False
        """
        is_fast_check = max_retries == 1
        
        serial = ToolService.adb_get_device_serial(ip)
        for attempt in range(max_retries):
            try:
                # 先准备连接 - 快速检查模式下简化处理
                if is_fast_check:
                    # 快速检查模式：直接连接，不使用OTG修复
                    cmd = f"{ADB_PATH} disconnect"
                    ToolService.run_command(cmd)
                    cmd = f"{ADB_PATH} connect {ip}:5555"
                    stdout, stderr, returncode = ToolService.run_command(cmd)
                    time.sleep(0.5)  # 短等待
                else:
                    stdout, stderr, returncode = ToolService.adb_prepare_connection(ip, need_remount=False, device_id=device_id, password=password)
                
                if stderr and ("unable" in stderr.lower() or "cannot" in stderr.lower() or "refused" in stderr.lower()):
                    if attempt < max_retries - 1 and not is_fast_check:
                        time.sleep(1)
                        continue
                    return False
                
                # 检查文件
                cmd = f"{ADB_PATH} -s {serial} shell ls -l {remote_file}"
                stdout, stderr, returncode = ToolService.run_command(cmd, timeout=5 if is_fast_check else 10)
                
                if returncode == 0 and not stderr and "No such" not in stdout:
                    ToolService.adb_disconnect()
                    return True
                
                # 如果失败，等待后重试（仅非快速检查模式）
                if attempt < max_retries - 1 and not is_fast_check:
                    time.sleep(1)
            except Exception as e:
                if attempt < max_retries - 1 and not is_fast_check:
                    time.sleep(1)
        
        ToolService.adb_disconnect()
        return False
    
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
        执行查询类命令 - 对于Android设备使用SSH方式，避免ADB连接冲突，带重试机制
        
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
                    # Android设备的查询操作使用SSH方式
                    try:
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
                        
                    except Exception as e:
                        # SSH失败时回退到ADB方式
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                
                # Linux设备或SSH回退，使用原有方式
                stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, cmd, working_dir)
                
                # 如果成功或者不是连接类错误，直接返回
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
        """
        通过SSH设置设备的OTG模式为peripheral模式
        
        参数:
            ip: 设备IP
            password: 设备密码
            device_id: 设备ID
            
        返回:
            tuple: (success, error_message)
        """
        try:
            otg_config = ToolService.get_device_otg_config(device_id)
            if not otg_config:
                return True, "无OTG配置"
            
            otg_path = otg_config['path']
            otg_value = otg_config['value']
            
            # 使用plink设置OTG模式
            plink_exe = ToolService.get_tool_path('plink.exe')
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "echo {otg_value} > {otg_path}"'
            ToolService.run_command(cmd, timeout=10)
            
            # 等待一段时间让设置生效
            time.sleep(2)
            
            # 验证设置是否成功
            verify_success, verify_msg = ToolService.verify_device_otg_mode(ip, password, device_id)
            if verify_success:
                return True, "OTG模式设置成功"
            else:
                return False, f"OTG模式设置成功但验证失败: {verify_msg}"
                
        except Exception as e:
            return False, f"设置OTG模式异常: {str(e)}"

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
        """
        通过SSH重启设备的ADB服务
        
        参数:
            ip: 设备IP
            password: 设备密码
            device_id: 设备ID
            
        返回:
            tuple: (success, error_message)
        """
        try:
            plink_exe = ToolService.get_tool_path('plink.exe')
            
            # 设置ADB端口
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "setprop service.adb.tcp.port 5555"'
            ToolService.run_command(cmd, timeout=5)
            
            # 停止ADB服务
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "stop adbd"'
            ToolService.run_command(cmd, timeout=5)
            
            # 等待一下
            time.sleep(1)
            
            # 启动ADB服务
            cmd = f'echo y | "{plink_exe}" -batch -l root -pw "{password}" "{ip}" "start adbd"'
            ToolService.run_command(cmd, timeout=5)
            
            # 等待ADB服务完全启动
            time.sleep(3)
            
            return True, "ADB服务重启成功"
            
        except Exception as e:
            return False, f"重启ADB服务异常: {str(e)}"
