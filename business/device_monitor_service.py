#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime, timedelta
import time
from service.tool_service import ToolService
from service.data_processing_service import DataProcessingService
from service.file_service import FileService
from config import get_base_dir, time_diff_threshold, daily_time_diff_threshold
import os
from config import tool_path, program_path

class DeviceMonitorService:
    """设备监控业务服务类，负责设备监控的核心业务逻辑"""
    
    def __init__(self, dev_type):
        self.dev_type = dev_type
        self.base_dir = get_base_dir(dev_type)
        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        self.device_data = FileService.load_device_data()
        self.notepad_process = None  # 用于跟踪记事本进程
    def count_init_setting(self, ip, password, device_id, system_type):
        """
        设备初始化设置开关机
        """
        try:
            resault_log = self.ntptime_checkout_time(ip, password, device_id, system_type)
            if "失败" in resault_log:
                Exception(resault_log)
        except Exception as e:
            return f"{device_id} 设备校时失败 - {str(e)},请检查网络是否正常连接外网"

        try:
            ToolService.initialize_connection(ip, password)
            if device_id.split('-')[0] == "C16H":
                ToolService.adb_push_file(ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/")
                ToolService.ssh_execute_command(ip, password, "touch /data/swich_counter_flag", ".")
            elif device_id.split('-')[0] in [ "C16L", "C08L", "D16", "D36" ]:
                ToolService.pscp_push_file(ip, password, f"{tool_path}/boot_counter.sh", "/root")
                ToolService.pscp_push_file(ip, password, f"{tool_path}/run.sh", "/root/Box")
                ToolService.ssh_execute_command(ip, password, "touch /root/Box/project/swich_counter_flag", ".")
                ToolService.ssh_execute_command(ip, password, "chmod +x /root/boot_counter.sh & chmod +x /root/Box/run.sh", ".")
            elif device_id.split('-')[0] in [ "A4L", "A5L", "A6L", "B6L" ]:
                ToolService.adb_push_file(ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/")
                ToolService.adb_push_file(ip, password, f"{tool_path}/init.huidu.rc", "/vendor/etc/init/hw")
                ToolService.ssh_execute_command(ip, password, "touch /data/swich_counter_flag", ".")
            elif device_id.split('-')[0] in [ "H4K", "H6", "H8", "B8L" ]:
                ToolService.adb_push_file(ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/")
                ToolService.adb_push_file(ip, password, f"{tool_path}/init.rk356x.rc", "/vendor/etc/init/hw")
                ToolService.ssh_execute_command(ip, password, "touch /data/swich_counter_flag", ".")
            ToolService.ssh_execute_command(ip, password, "sync", ".")
            return f"{device_id} 设置开关机成功"
        except Exception as e:
            return f"{device_id} 设置开关机失败 - {str(e)}"

    def sum_switch_count(self, ip, password, device_id, path):
        """
        设备累计开机次数
        """
        try:
            cmd = f"wc -l {path}/swich_counter.csv"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip,password, cmd, ".")
            stdout = stdout.strip()
            switch_time = int(stdout.split(' ')[0])-1

            cmd = f"wc -l {path}/network_counter.csv"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip,password, cmd, ".")
            stdout = stdout.strip()
            network_time = int(stdout.split(' ')[0])-1

        except Exception as e:
            return f"{device_id} 获取累计开机次数失败 - {str(e)}"
        return switch_time, network_time

    def clean_switch_log(self, ip, password, device_id, path):
        """
        清除开关机日志
        """
        try:
            cmd = f"ls {path}/swich_counter.csv && rm -rf {path}/swich_counter.csv"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, cmd, ".")
            cmd = f"ls {path}/network_counter.csv && rm -rf {path}/network_counter.csv"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, cmd, ".")
            cmd = f"ls {path}/logcat && rm -rf {path}/logcat"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, cmd, ".")
            cmd = f"ls {path}/ping && rm -rf {path}/ping"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, cmd, ".")
        except Exception as e:
            return f"{device_id} 清除累计开机次数失败 - {str(e)}"

    def switch_log_output(self, ip, password, device_id, system_type, path):
        try:
            if not os.path.exists("./switch_log"):
                os.mkdir("./switch_log")
            if not os.path.exists(f"./switch_log/{device_id}"):
                os.mkdir(f"./switch_log/{device_id}")
            if "Android" in system_type:
                time.sleep(1)
                stdout = ToolService.adb_pull_file(ip, password, f"{path}/network_counter.csv", f"./switch_log/{device_id}/network_counter.csv")
                time.sleep(1)
                stdout = ToolService.adb_pull_file(ip, password, f"{path}/swich_counter.csv", f"./switch_log/{device_id}/swich_counter.csv")
                cmd="adb disconnect"
                ToolService.run_command(cmd)
            elif "Linux" in system_type:
                stdout = ToolService.pscp_pull_file(ip, password, f"{path}/network_counter.csv", f"./switch_log/{device_id}/network_counter.csv")
                stdout = ToolService.pscp_pull_file(ip, password, f"{path}/swich_counter.csv", f"./switch_log/{device_id}/swich_counter.csv")
            return f"{device_id} 日志已保存至：./switch_log/{device_id}"
        except Exception as e:
            return f"{device_id} 获取日志失败 - {str(e)}"

    def ntptime_checkout_time(self, ip, password, device_id, system_type):
        """
        设置设备时间
        """
        try:
            remote_file = ""
            if "Android" in system_type:
                remote_file = "/system/bin/ntpdate"
                stdout = ToolService.adb_push_file(ip, password, f"{tool_path}/ntpdate", remote_file)
            elif "Linux" in system_type:
                remote_file = "/bin/ntpdate"
                stdout = ToolService.pscp_push_file(ip, password, f"{tool_path}/ntpdate", remote_file)
            else:
                return "不支持该系统类型"
            stdout = ToolService.ssh_execute_command(ip, password, f"chmod +x {remote_file}", ".")
            stdout = ToolService.ssh_execute_command(ip, password, f"{remote_file} -server ntp.huidu.cn", ".")
            stdout = ToolService.ssh_execute_command(ip, password, "hwclock -w", ".")
            stdout = ToolService.ssh_execute_command(ip, password, f"rm {remote_file}", ".")
            stdout, _, _ = ToolService.ssh_execute_command(ip, password, "date", ".")
            return f"{device_id} 时间已校时成功，时间为：{stdout}"
        except Exception as e:
            return f"{device_id} 设置时间失败 - {str(e)}"

    def upgrade_program(self, ip, password, device_id, system_type):
        """更新设备节目"""
        try:
            device_type = device_id.split('-')[0]
            remote_file = ""

            os.makedirs(program_path, exist_ok=True)

            if not os.path.exists(f"{program_path}/{device_type}_project.tar.gz"):
                return f"设备节目不存在，请检查, 并创建：{program_path}/{device_type}_project.tar.gz"

            if "Android" in system_type:
                remote_file = "/data/media/0/MagicPlayer"
                stdout= ToolService.adb_push_file(ip, password, f"{program_path}/{device_type}_project.tar.gz", f"{remote_file}/project.tar.gz")
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"tar -zxf {remote_file}/project.tar.gz -C {remote_file}", ".")
                restart_player_cmd = "am start -S cn.huidu.lcd.player/.PlayerActivity"
            elif "Linux" in system_type:
                remote_file = "/root/Box/project"
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "rm /root/Box/project/*.*", ".")
                stdout= ToolService.pscp_push_file(ip, password, f"{program_path}/{device_type}_project.tar.gz", f"{remote_file}/project.tar.gz")
                restart_player_cmd = "/root/Box/run.sh"
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"tar -zxf {remote_file}/project.tar.gz -C {remote_file}", ".")
                # stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"sed -i 's/.*Name=\"DeviceModel\".*/    <Attribute Name=\"DeviceModel\">C16L<\/Attribute>/' {remote_file}/*.boo ; sync ", ".")
            else:
                return "不支持该系统类型"
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"rm {remote_file}/project.tar.gz", ".")
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, restart_player_cmd, ".")
            return f"{device_id} 更新节目成功,重启播放器"
        except Exception as e:
            return f"{device_id} 更新节目失败 - {str(e)}"

    def get_uptime_info(self, ip, password, device_id):
        """
        获取设备运行时间信息
        """
        uptime_script = '''uptime'''
        
        stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, uptime_script, self.base_dir)
        if not stderr:
            try:
                # 使用 os 模块相关的 datetime 获取当前时间
                current_datetime = datetime.now()
                current_date_str = current_datetime.strftime('%Y-%m-%d')
                
                # 解析 uptime 输出
                uptime_info = DataProcessingService.parse_uptime(stdout)
                current_time_str = uptime_info['current_time']
                
                # 从解析结果中获取运行时间
                uptime = uptime_info['uptime']
                # 将字符串形式的 uptime 转换为 timedelta
                days_part = re.search(r'(\d+) days?', uptime)
                days = int(days_part.group(1)) if days_part else 0
                time_part = re.search(r'(\d+):(\d+):(\d+)', uptime)
                hours = int(time_part.group(1)) if time_part else 0
                minutes = int(time_part.group(2)) if time_part else 0
                seconds = int(time_part.group(3)) if time_part else 0
                uptime_delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
                
                # 计算启动时间
                boot_time = current_datetime - uptime_delta
                
                # 补充完整的 uptime 信息
                uptime_info['boot_time'] = boot_time.isoformat()
                uptime_info['current_datetime'] = current_datetime.isoformat()
                uptime_info['uptime_delta'] = str(uptime_delta)
                
                return uptime_info
            except Exception as e:
                return {
                    'error': f"计算启动时间失败 - {str(e)}",
                    'formatted_uptime': "N/A"
                }
        else:
            return {
                'error': str(stderr),
                'formatted_uptime': "N/A"
            }
    
    def get_device_time_info(self, ip, password, device_id):
        """
        获取设备时间信息
        """
        time_script = 'date +%s'
        
        stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, time_script, self.base_dir)
        date_result = stdout.strip() if not stderr else ""
        
        remote_time = "N/A"
        time_diff = "N/A"
        formatted_remote_time = "N/A"
        
        if date_result:
            try:
                # 获取本地电脑当前时间戳（秒）
                local_time = int(datetime.now().timestamp())
                
                # 检查远程时间和本地时间是否为合法数字
                if re.match(r'^[0-9]+$', date_result):
                    remote_time = int(date_result)
                    time_diff = remote_time - local_time
                    # 将UTC时间戳转换为年月日时分秒格式
                    formatted_remote_time = datetime.utcfromtimestamp(remote_time).strftime('%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                remote_time = "N/A"
                time_diff = "N/A"
                formatted_remote_time = "N/A"
                # 写入异常到 device_error.txt
                with open('device_error.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{datetime.now()} 设备:{device_id} 获取时间异常: {str(e)}\n")
        else:
            # 写入异常到 device_error.txt
            with open('device_error.txt', 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()} 设备:{device_id} 获取时间异常: {stderr}\n")
        
        return formatted_remote_time, time_diff
    
    def get_start_count(self, ip, password, device_id):
        """
        获取安卓系列播放器启动次数
        """
        # 检查设备ID前缀是否为C08L、C16L或D16
        if device_id.startswith('C08L') or device_id.startswith('C16L') or device_id.startswith('D16'):
            # 这三种设备类型不支持获取播放器启动次数
            return "无法获取"
        
        start_count_script = 'getprop huidu.player.start_count'
        
        stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, start_count_script, self.base_dir)
        result = stdout if not stderr else f"Error: {stderr}"
        return result
    
    def check_device_status(self, device_id, ip, password, monitor_time=True, monitor_boot=True, monitor_start_count=True):
        """
        检查设备状态并返回是否异常
        """
        errors = []
        
        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 1. 检查运行时间（启动时间误差验证）
        uptime_info = self.get_uptime_info(ip, password, device_id)
        
        # 写入运行时间日志
        formatted_uptime = uptime_info.get('formatted_uptime', 'N/A')
        current_time = uptime_info.get('current_time', 'N/A')
        uptime_log_entry = f"{device_id},{ip},{current_time},{formatted_uptime}\n"
        with open(f'{self.base_dir}/uptime.log', 'a', encoding='utf-8') as f:
            f.write(uptime_log_entry)

        if 'boot_time' in uptime_info:
            boot_time = datetime.fromisoformat(uptime_info['boot_time'])
            
            # 检查是否是第一次获取该设备数据
            if device_id not in self.device_data:
                # 第一次获取，保存为初始值，不进行验证
                # 确保设备数据字典存在，避免覆盖已有数据
                if device_id not in self.device_data:
                    self.device_data[device_id] = {}
                # 保存完整的 uptime 信息到设备数据中
                self.device_data[device_id]['initial_os_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # 保存精确到分钟的启动时间
                self.device_data[device_id]['initial_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
                self.device_data[device_id]['last_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
            else:
                # 非第一次获取，与初始值比较
                if 'initial_boot_time' in self.device_data[device_id]:
                    initial_boot_time = datetime.fromisoformat(self.device_data[device_id]['last_boot_time'])
                    time_diff_from_initial = abs((boot_time - initial_boot_time).total_seconds())
                    if time_diff_from_initial > time_diff_threshold:
                        errors.append({
                            'type': '启动时间误差',
                            'process': f'初始启动时间: {initial_boot_time.isoformat()}, 当前启动时间: {boot_time.isoformat()}',
                            'difference': f'{time_diff_from_initial}秒'
                        })
                        # 更新初始启动时间为当前值
                        self.device_data[device_id]['last_boot_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        # 保存精确到分钟的启动时间
                        self.device_data[device_id]['last_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
                else:
                    # 如果没有初始启动时间，保存当前时间
                    self.device_data[device_id]['os_now_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    # 保存精确到分钟的启动时间
                    self.device_data[device_id]['last_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
        
        # 2. 检查设备时间（设备时间误差验证）
        if monitor_time:
            formatted_remote_time, time_diff = self.get_device_time_info(ip, password, device_id)
            
            # 写入设备时间日志
            # 考虑时区差，设备时间比当地时间慢8小时，将设备时间加上8小时
            if formatted_remote_time != "N/A":
                try:
                    remote_dt = datetime.strptime(formatted_remote_time, '%Y-%m-%d %H:%M:%S')
                    adjusted_remote_time = (remote_dt + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
                    time_log_entry = f"{device_id},{ip},{adjusted_remote_time},{time_diff}s\n"
                except ValueError:
                    time_log_entry = f"{device_id},{ip},{formatted_remote_time},{time_diff}s\n"
            else:
                time_log_entry = f"{device_id},{ip},{formatted_remote_time},{time_diff}s\n"
            with open(f'{self.base_dir}/cardtime.log', 'a', encoding='utf-8') as f:
                f.write(time_log_entry)
            
            if time_diff != "N/A":
                time_diff_value = int(time_diff)
                
                # 检查是否是第一次获取该设备的设备时间
                if device_id in self.device_data:
                    if 'initial_time_diff' not in self.device_data[device_id]:
                        # 第一次获取，保存为初始值，不进行验证
                        self.device_data[device_id]['initial_card_time'] = adjusted_remote_time
                        self.device_data[device_id]['initial_time_diff'] = time_diff_value
                        self.device_data[device_id]['last_time_diff'] = time_diff_value
                    else:
                        # 非第一次获取，与初始值比较
                        initial_time_diff = self.device_data[device_id]['last_time_diff']
                        # 计算与初始时间差的差异
                        diff_from_initial = abs(time_diff_value - initial_time_diff)
                        # 日均时差计算（总时间差/运行时长（天））
                        if 'uptime_delta' in uptime_info:
                            try:
                                # 从字符串形式的 uptime_delta 解析出天数
                                days_part = re.search(r'(\d+) days?', uptime_info['uptime_delta'])
                                days_passed = int(days_part.group(1)) if days_part else 1  # 没有天数部分时设为1
                                if days_passed == 0:
                                    # 如果没有天数部分，尝试从秒数计算天数
                                    seconds_part = re.search(r'(\d+) days?,? (\d+):(\d+):(\d+)', uptime_info['uptime_delta'])
                                    if not seconds_part:
                                        # 处理只有时间部分的情况
                                        seconds_part = re.search(r'(\d+):(\d+):(\d+)', uptime_info['uptime_delta'])
                                    if seconds_part:
                                        hours = int(seconds_part.group(1 if len(seconds_part.groups()) == 4 else 0))
                                        minutes = int(seconds_part.group(2 if len(seconds_part.groups()) == 4 else 1))
                                        seconds = int(seconds_part.group(3 if len(seconds_part.groups()) == 4 else 2))
                                        total_seconds = hours * 3600 + minutes * 60 + seconds
                                        days_passed = total_seconds / (24 * 3600)  # 使用除法保留小数
                            except Exception:
                                days_passed = 1 # 设置一个极小值避免除零错误
                            
                            if days_passed > 0:
                                avg_daily_diff = diff_from_initial / days_passed
                                if abs(avg_daily_diff) > daily_time_diff_threshold:
                                    errors.append({
                                        'type': '设备时间日均误差',
                                        'process': f'初始时间差: {initial_time_diff}秒, 当前时间差: {time_diff_value}秒',
                                        'difference': f'日均{avg_daily_diff:.2f}秒'
                                    })
                                    # 更新初始时间差为当前值
                                    self.device_data[device_id]['last_card_time'] = adjusted_remote_time
                                    self.device_data[device_id]['last_time_diff'] = time_diff_value
                                    self.device_data[device_id]['last_card_time_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # 第一次获取设备信息，初始化设备数据并保存初始时间差
                    self.device_data[device_id] = {
                        'initial_time_diff': time_diff_value
                    }
        
        # 3. 检查启动次数（启动次数一致性验证）
        if monitor_start_count:
            start_count = self.get_start_count(ip, password, device_id)
            
            # 写入启动次数日志
            start_count_log_entry = f"{device_id},{ip},{start_count}\n"
            with open(f'{self.base_dir}/startcount.log', 'a', encoding='utf-8') as f:
                f.write(start_count_log_entry)

            # 尝试将启动次数转换为整数
            try:
                current_start_count = int(start_count)
            except (ValueError, TypeError):
                current_start_count = None

            if current_start_count is not None:
                # 检查是否是第一次获取该设备的启动次数
                if device_id in self.device_data:
                    if 'initial_start_count' not in self.device_data[device_id]:
                        # 第一次获取，保存为初始值，不进行验证
                        self.device_data[device_id]['initial_start_count'] = current_start_count
                        self.device_data[device_id]['last_start_count'] = current_start_count
                    else:
                        # 非第一次获取，与上一次的启动次数比较
                        initial_start_count = self.device_data[device_id]['initial_start_count']
                        last_start_count = self.device_data[device_id]['last_start_count']
                        if current_start_count != last_start_count:
                            # 更新初始启动次数为当前值，避免后续重复报错                        
                            self.device_data[device_id]['last_start_count'] = current_start_count
                            self.device_data[device_id]['last_start_count_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            # 启动次数减少，记录错误
                            errors.append({
                                'type': '启动次数异常',
                                'process': f'初始启动次数: {initial_start_count}, 当前启动次数: {current_start_count}',
                                'difference': '启动次数异常'
                            })
                            
                else:
                    # 第一次获取设备信息，初始化设备数据并保存初始启动次数
                    self.device_data[device_id] = {
                        'initial_start_count': current_start_count,
                        'last_start_count': current_start_count
                    }
        
        # 检查关键信息的完整性（仅检查用户选择监控的项目）
        # 1. 检查运行时长信息（与启动时间相关）
        if monitor_boot:
            if not formatted_uptime or formatted_uptime == "Error" or "Error" in formatted_uptime:
                errors.append({
                    'type': '运行时长获取失败',
                    'process': f'设备ID: {device_id}, IP: {ip}',
                    'difference': f'获取运行时长信息失败'
                })
            
        # 2. 检查设备时间信息
        if monitor_time:
            if formatted_remote_time == "N/A" or "Error" in str(formatted_remote_time):
                errors.append({
                    'type': '设备时间获取失败',
                    'process': f'设备ID: {device_id}, IP: {ip}',
                    'difference': f'获取设备时间信息失败'
                })
            
        # 3. 检查启动次数信息
        if monitor_start_count:
            # 对于C08L、C16L、D16设备类型，不检查启动次数获取失败
            if device_id.startswith('C08L') or device_id.startswith('C16L') or device_id.startswith('D16'):
                # 跳过检查，不记录错误
                pass
            elif not start_count or start_count == "" or "Error" in str(start_count):
                errors.append({
                    'type': '启动次数获取失败',
                    'process': f'设备ID: {device_id}, IP: {ip}',
                    'difference': f'获取启动次数信息失败'
                })
            
        # 确保设备数据字典中包含这三个关键信息
        if device_id not in self.device_data:
            self.device_data[device_id] = {}
        
        # 保存这三个关键信息到设备数据中
        self.device_data[device_id]['last_uptime'] = formatted_uptime
        
        # 如果是特殊设备类型，设置启动次数为'无法获取'
        if device_id.startswith('C08L') or device_id.startswith('C16L') or device_id.startswith('D16'):
            self.device_data[device_id]['last_start_count'] = '无法获取'
        
        # 生成综合日志（根据监控选项调整参数）
        if monitor_time and monitor_boot and monitor_start_count:
            # 全部监控的情况
            FileService.write_comprehensive_log(ip, password, device_id, self.base_dir, formatted_uptime, formatted_remote_time, time_diff, start_count)
        else:
            # 部分监控的情况，为未监控的项目提供默认值
            FileService.write_comprehensive_log(
                ip, password, device_id, self.base_dir, 
                formatted_uptime if monitor_boot else "未监控", 
                formatted_remote_time if monitor_time else "未监控", 
                time_diff if monitor_time else "未监控", 
                start_count if monitor_start_count else "未监控"
            )
        
        return errors
    
    def monitor_devices(self, delay_time=60):
        """
        监控所有设备
        """
        import subprocess
        
        while True:
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}开始监控 {self.dev_type} 类型设备...")
            time.sleep(1)
            # 获取设备列表
            devices = ToolService.get_device_list(self.dev_type)
            device_count = len(devices)
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}发现 {device_count} 台设备")
            
            has_new_errors = False  # 标记是否有新错误
            
            # 处理每个设备
            for device_id, ip in devices:
                print(f"\n检查设备: {device_id} ({ip})")
                password = ToolService.get_password(device_id)
                print(f"密码: {password}")
                # 初始化连接
                ToolService.initialize_connection(ip, password)
                
                # 检查设备状态
                errors = self.check_device_status(device_id, ip, password)
                
                # 如果有错误，使用改进的格式记录
                if errors:
                    # 使用DataProcessingService格式化错误消息
                    formatted_message = DataProcessingService.format_error_message(
                        device_id, 
                        ip, 
                        "设备监控异常",
                        errors
                    )
                    
                    # 写入错误日志文件
                    with open('device_errors.txt', 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*50}\n")  # 添加分隔线
                        f.write(formatted_message)
                        f.write(f"\n{'='*50}\n")  # 添加分隔线
                    
                    has_new_errors = True
            
            # 保存设备数据
            FileService.save_device_data(self.device_data)
            
            # 如果有新错误，处理记事本显示
            if has_new_errors:
                # 如果已经有记事本打开，先关闭它
                if self.notepad_process:
                    try:
                        self.notepad_process.terminate()
                        self.notepad_process.wait(timeout=3)
                    except:
                        pass  # 如果关闭失败，继续执行下一步
                
                # 打开新的记事本
                self.notepad_process = subprocess.Popen(['notepad.exe', 'device_errors.txt'])
            
            # 倒计时
            print("\n所有设备检查完成，等待下一轮检查...")
            for i in range(delay_time, 0, -1):
                print(f"\r下一轮检查倒计时: {i-1}秒", end='')
                time.sleep(1)
            print("\n")
            
            # 清空完成记录
            ok_ids_file = f"{self.base_dir}/{self.dev_type}_{datetime.now().strftime('%Y%m%d')}.log"
            if os.path.exists(ok_ids_file):
                os.remove(ok_ids_file)
# 导入os模块
import os
