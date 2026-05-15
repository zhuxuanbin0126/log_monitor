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
        
        功能：
        1. 使用可靠的文件推送方式（带MD5校验和重试）
        2. 自动设置文件执行权限
        3. 改进的错误处理和调试信息
        4. 完整的文件存在性验证
        """
        try:
            resault_log = self.ntptime_checkout_time(ip, password, device_id, system_type)
            if "失败" in resault_log:
                Exception(resault_log)
        except Exception as e:
            return f"{device_id} 设备校时失败 - {str(e)},请检查网络是否正常连接外网"

        try:
            dev_type_prefix = device_id.split('-')[0]
            steps = []
            error = None
            files_to_check = []
            
            if dev_type_prefix == "C16H":
                # C16H: Android设备，使用ADB推送
                # 1. 推送boot_counter.sh
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/boot_counter.sh", use_reliable=True)
                if stderr or returncode != 0:
                    error = f"推送boot_counter.sh失败: {stderr}"
                else:
                    steps.append(f"boot_counter.sh推送成功 ({stdout})")
                    files_to_check.append("/system/bin/boot_counter.sh")
                    # 设置执行权限
                    stdout_chmod, stderr_chmod, returncode_chmod = ToolService.adb_set_executable(ip, "/system/bin/boot_counter.sh")
                    steps.append("boot_counter.sh执行权限设置完成")
                
                # 2. 创建flag文件
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "touch /data/swich_counter_flag", ".")
                    if stderr or returncode != 0:
                        error = f"创建swich_counter_flag失败: {stderr}"
                    else:
                        steps.append("swich_counter_flag创建成功")
                        files_to_check.append("/data/swich_counter_flag")
                
            elif dev_type_prefix in ["C16L", "C08L", "D16", "D36"]:
                # Linux设备，使用PSCP推送
                # 1. 推送boot_counter.sh
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/boot_counter.sh", "/root/boot_counter.sh")
                if stderr or returncode != 0:
                    error = f"推送boot_counter.sh失败: {stderr}"
                else:
                    steps.append("boot_counter.sh推送成功")
                    files_to_check.append("/root/boot_counter.sh")
                
                # 2. 推送run.sh
                if not error:
                    stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/run.sh", "/root/Box/run.sh")
                    if stderr or returncode != 0:
                        error = f"推送run.sh失败: {stderr}"
                    else:
                        steps.append("run.sh推送成功")
                        files_to_check.append("/root/Box/run.sh")
                
                # 3. 创建flag文件
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "touch /root/Box/project/swich_counter_flag", ".")
                    if stderr or returncode != 0:
                        error = f"创建swich_counter_flag失败: {stderr}"
                    else:
                        steps.append("swich_counter_flag创建成功")
                        files_to_check.append("/root/Box/project/swich_counter_flag")
                
                # 4. 给权限
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "chmod +x /root/boot_counter.sh && chmod +x /root/Box/run.sh", ".")
                    if stderr or returncode != 0:
                        error = f"修改权限失败: {stderr}"
                    else:
                        steps.append("权限修改成功")
                
            elif dev_type_prefix in ["A3L", "A4L", "A5L", "A6L", "B6L"]:
                # Android设备，使用ADB推送
                # 1. 推送boot_counter.sh
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/boot_counter.sh", use_reliable=True)
                if stderr or returncode != 0:
                    error = f"推送boot_counter.sh失败: {stderr}"
                else:
                    steps.append(f"boot_counter.sh推送成功 ({stdout})")
                    files_to_check.append("/system/bin/boot_counter.sh")
                    # 设置执行权限
                    stdout_chmod, stderr_chmod, returncode_chmod = ToolService.adb_set_executable(ip, "/system/bin/boot_counter.sh")
                    steps.append("boot_counter.sh执行权限设置完成")
                
                # 2. 推送init.huidu.rc
                if not error:
                    stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/init.huidu.rc", "/vendor/etc/init/hw/init.huidu.rc", use_reliable=True)
                    if stderr or returncode != 0:
                        error = f"推送init.huidu.rc失败: {stderr}"
                    else:
                        steps.append(f"init.huidu.rc推送成功 ({stdout})")
                        files_to_check.append("/vendor/etc/init/hw/init.huidu.rc")
                
                # 3. 创建flag文件
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "touch /data/swich_counter_flag", ".")
                    if stderr or returncode != 0:
                        error = f"创建swich_counter_flag失败: {stderr}"
                    else:
                        steps.append("swich_counter_flag创建成功")
                        files_to_check.append("/data/swich_counter_flag")
                
            elif dev_type_prefix in ["H4K", "H6", "H8", "B8L"]:
                # Android设备，使用ADB推送
                # 1. 推送boot_counter.sh
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/boot_counter.sh", use_reliable=True)
                if stderr or returncode != 0:
                    error = f"推送boot_counter.sh失败: {stderr}"
                else:
                    steps.append(f"boot_counter.sh推送成功 ({stdout})")
                    files_to_check.append("/system/bin/boot_counter.sh")
                    # 设置执行权限
                    stdout_chmod, stderr_chmod, returncode_chmod = ToolService.adb_set_executable(ip, "/system/bin/boot_counter.sh")
                    steps.append("boot_counter.sh执行权限设置完成")
                
                # 2. 推送init.rk356x.rc
                if not error:
                    stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/init.rk356x.rc", "/vendor/etc/init/hw/init.rk356x.rc", use_reliable=True)
                    if stderr or returncode != 0:
                        error = f"推送init.rk356x.rc失败: {stderr}"
                    else:
                        steps.append(f"init.rk356x.rc推送成功 ({stdout})")
                        files_to_check.append("/vendor/etc/init/hw/init.rk356x.rc")
                
                # 3. 创建flag文件
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "touch /data/swich_counter_flag", ".")
                    if stderr or returncode != 0:
                        error = f"创建swich_counter_flag失败: {stderr}"
                    else:
                        steps.append("swich_counter_flag创建成功")
                        files_to_check.append("/data/swich_counter_flag")
                
            elif dev_type_prefix in ["A7", "A8"]:
                # Android设备，使用ADB推送
                # 1. 推送boot_counter.sh
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/boot_counter.sh", "/system/bin/boot_counter.sh", use_reliable=True)
                if stderr or returncode != 0:
                    error = f"推送boot_counter.sh失败: {stderr}"
                else:
                    steps.append(f"boot_counter.sh推送成功 ({stdout})")
                    files_to_check.append("/system/bin/boot_counter.sh")
                    # 设置执行权限
                    stdout_chmod, stderr_chmod, returncode_chmod = ToolService.adb_set_executable(ip, "/system/bin/boot_counter.sh")
                    steps.append("boot_counter.sh执行权限设置完成")
                
                # 2. 推送init.rk3399.rc
                if not error:
                    stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/init.rk3399.rc", "/vendor/etc/init/hw/init.rk3399.rc", use_reliable=True)
                    if stderr or returncode != 0:
                        error = f"推送init.rk3399.rc失败: {stderr}"
                    else:
                        steps.append(f"init.rk3399.rc推送成功 ({stdout})")
                        files_to_check.append("/vendor/etc/init/hw/init.rk3399.rc")
                
                # 3. 创建flag文件
                if not error:
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "touch /data/swich_counter_flag", ".")
                    if stderr or returncode != 0:
                        error = f"创建swich_counter_flag失败: {stderr}"
                    else:
                        steps.append("swich_counter_flag创建成功")
                        files_to_check.append("/data/swich_counter_flag")
            
            # 执行sync同步
            if not error:
                stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "sync", ".")
                steps.append("sync执行成功")
            
            # 验证文件是否存在 - 使用可靠的文件检查方法
            if not error and files_to_check:
                missing_files = []
                for file_path in files_to_check:
                    # 短暂延迟确保文件写入完成
                    time.sleep(0.3)
                    # 使用专门的文件检查方法，多次尝试
                    exists = False
                    for attempt in range(3):
                        try:
                            exists = ToolService.check_file_exists(device_id, ip, password, file_path)
                            if exists:
                                break
                            if attempt < 2:
                                time.sleep(0.5)  # 失败后等待再试
                        except Exception as e:
                            if attempt < 2:
                                time.sleep(0.5)
                    
                    if not exists:
                        missing_files.append(file_path)
                
                if missing_files:
                    error = f"文件验证失败，以下文件不存在: {', '.join(missing_files)}"
                else:
                    steps.append("文件验证成功")
            
            if error:
                return f"{device_id} 设置开关机失败 - {error} )"
            else:
                return f"{device_id} 设置开关机成功 - 执行步骤: {'; '.join(steps)}"
                
        except Exception as e:
            return f"{device_id} 设置开关机失败 - {str(e)}"

    def sum_switch_count(self, ip, password, device_id, path):
        """
        设备累计开机次数，优化错误处理和重试
        文件不存在时使用快速检查（不重试），尽快返回0
        
        返回:
            tuple: (switch_time, network_time, success, error_message)
        """
        try:
            switch_counter_path = f"{path}/swich_counter.csv"
            network_counter_path = f"{path}/network_counter.csv"
            
            switch_time = 0
            network_time = 0
            
            # 检查开关机计数文件
            switch_exists = ToolService.check_file_exists(device_id, ip, password, switch_counter_path, max_retries=2)
            if switch_exists:
                # 使用多种方法尝试读取文件
                for attempt in range(3):
                    try:
                        # 方法1: 使用wc -l (最常用)
                        cmd = f"wc -l {switch_counter_path}"
                        stdout, stderr, returncode = ToolService.execute_query_command(device_id, ip, password, cmd, ".")
                        if not stderr and returncode == 0 and stdout:
                            stdout = stdout.strip()
                            try:
                                switch_time = max(0, int(stdout.split()[0]) - 1)
                                break  # 成功读取，跳出循环
                            except (ValueError, IndexError):
                                pass  # 解析失败，尝试其他方法
                        
                        # 方法2: 使用grep统计行数
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
                    except Exception as e:
                        if attempt < 2:
                            time.sleep(0.5)
            
            # 检查网络计数文件 - 使用相同的逻辑
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
                    except Exception as e:
                        if attempt < 2:
                            time.sleep(0.5)
            
            # 无论文件是否存在，都返回成功（文件不存在时计数为0）
            return switch_time, network_time, True, None

        except Exception as e:
            # 即使异常，也返回0和成功状态
            return 0, 0, True, None

    def clean_switch_log(self, ip, password, device_id, path):
        """
        清除开关机日志，根据设备类型选择正确的路径
        重要：不删除swich_counter_flag，否则重启后boot_counter.sh不会执行
        
        返回:
            tuple: (success, error_message)
        """
        try:
            dev_type_prefix = device_id.split('-')[0]
            
            # 根据设备类型确定正确的删除路径
            if dev_type_prefix in ["C16L", "C08L", "D16", "D36"]:
                # Linux设备，删除/root/Box/project/目录下的文件
                delete_path = "/root/Box/project"
            else:
                # Android设备，删除/data/目录下的文件
                delete_path = "/data"
            
            # 执行删除操作 - 注意：不删除swich_counter_flag
            cmd = f"rm -f {delete_path}/swich_counter.csv"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            cmd = f"rm -f {delete_path}/network_counter.csv"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            cmd = f"rm -rf {delete_path}/logcat"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            cmd = f"rm -rf {delete_path}/ping"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            # 执行sync确保数据写入磁盘
            cmd = "sync"
            ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            # 稍作等待，确保删除完成
            time.sleep(1)
            
            # 验证文件是否已删除
            switch_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/swich_counter.csv", max_retries=1)
            network_exists = ToolService.check_file_exists(device_id, ip, password, f"{delete_path}/network_counter.csv", max_retries=1)
            
            if switch_exists or network_exists:
                # 尝试再次删除
                if switch_exists:
                    cmd = f"rm -f {delete_path}/swich_counter.csv"
                    ToolService.execute_command(device_id, ip, password, cmd, ".")
                if network_exists:
                    cmd = f"rm -f {delete_path}/network_counter.csv"
                    ToolService.execute_command(device_id, ip, password, cmd, ".")
                # 再次sync
                cmd = "sync"
                ToolService.execute_command(device_id, ip, password, cmd, ".")
                time.sleep(1)
            
            return True, f"{device_id} 开关机记录已清除"
        except Exception as e:
            return False, f"{device_id} 清除累计开机次数失败 - {str(e)}"

    def switch_log_output(self, ip, password, device_id, system_type, path):
        """
        导出开关机日志，优化错误处理
        
        返回:
            tuple: (success, message)
        """
        try:
            # 确保输出目录存在
            output_dir = f"./switch_log/{device_id}"
            if not os.path.exists("./switch_log"):
                os.mkdir("./switch_log")
            if not os.path.exists(output_dir):
                os.mkdir(output_dir)
            
            success_count = 0
            messages = []
            
            # 拉取network_counter.csv
            stdout, stderr, returncode = ToolService.pull_file(
                device_id, ip, password, f"{path}/network_counter.csv", f"{output_dir}/network_counter.csv"
            )
            
            if not stderr and returncode == 0:
                success_count += 1
            else:
                msg = f"network_counter.csv 拉取失败: {stderr}"
                messages.append(msg)
            
            # 拉取swich_counter.csv
            stdout, stderr, returncode = ToolService.pull_file(
                device_id, ip, password, f"{path}/swich_counter.csv", f"{output_dir}/swich_counter.csv"
            )
            
            if not stderr and returncode == 0:
                success_count += 1
            else:
                msg = f"swich_counter.csv 拉取失败: {stderr}"
                messages.append(msg)
            
            # 只要成功拉取至少一个文件就返回成功
            if success_count > 0:
                msg = f"{device_id} 日志已保存至：{output_dir}"
                if messages:
                    msg += f" (部分文件: {'; '.join(messages)})"
                return True, msg
            else:
                return False, f"{device_id} 所有日志文件拉取失败: {'; '.join(messages)}"
                
        except Exception as e:
            return False, f"{device_id} 获取日志失败 - {str(e)}"

    def ntptime_checkout_time(self, ip, password, device_id, system_type):
        """
        设置设备时间
        """
        try:
            remote_file = ""
            if ToolService.is_android_device(device_id):
                remote_file = "/system/bin/ntpdate"
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/ntpdate", remote_file, use_reliable=True)
                if stderr or returncode != 0:
                    return f"{device_id} 推送ntpdate失败 - {stderr}"
            else:
                remote_file = "/bin/ntpdate"
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/ntpdate", remote_file)
                if stderr or returncode != 0:
                    return f"{device_id} 推送ntpdate失败 - {stderr}"
            
            ToolService.execute_command(device_id, ip, password, f"chmod +x {remote_file}", ".")
            
            ToolService.execute_command(device_id, ip, password, f"{remote_file} -server ntp.huidu.cn", ".")
            
            ToolService.execute_command(device_id, ip, password, "hwclock -w", ".")
            
            ToolService.execute_command(device_id, ip, password, f"rm -f {remote_file}", ".")
            
            stdout, _, _ = ToolService.execute_command(device_id, ip, password, "date", ".")
            return f"{device_id} 时间已校时成功，时间为：{stdout}"
        except Exception as e:
            return f"{device_id} 设置时间失败 - {str(e)}"

    def upgrade_program(self, ip, password, device_id, system_type):
        """更新设备节目"""
        try:
            dev_type_prefix = device_id.split('-')[0]
            remote_file = ""

            os.makedirs(program_path, exist_ok=True)

            if not os.path.exists(f"{program_path}/{dev_type_prefix}_project.tar.gz"):
                return f"设备节目不存在，请检查, 并创建：{program_path}/{dev_type_prefix}_project.tar.gz"

            if ToolService.is_android_device(device_id):
                remote_file = "/data/media/0/MagicPlayer"
                ToolService.push_file(device_id, ip, password, f"{program_path}/{dev_type_prefix}_project.tar.gz", f"{remote_file}/project.tar.gz")
                ToolService.execute_command(device_id, ip, password, f"tar -zxf {remote_file}/project.tar.gz -C {remote_file}", ".")
                restart_player_cmd = "am start -S cn.huidu.lcd.player/.PlayerActivity"
            else:
                remote_file = "/root/Box/project"
                ToolService.execute_command(device_id, ip, password, "rm /root/Box/project/*.*", ".")
                ToolService.push_file(device_id, ip, password, f"{program_path}/{dev_type_prefix}_project.tar.gz", f"{remote_file}/project.tar.gz")
                restart_player_cmd = "/root/Box/run.sh"
                ToolService.execute_command(device_id, ip, password, f"tar -zxf {remote_file}/project.tar.gz -C {remote_file}", ".")
            
            ToolService.execute_command(device_id, ip, password, f"rm {remote_file}/project.tar.gz", ".")
            ToolService.execute_command(device_id, ip, password, restart_player_cmd, ".")
            return f"{device_id} 更新节目成功,重启播放器"
        except Exception as e:
            return f"{device_id} 更新节目失败 - {str(e)}"

    def get_uptime_info(self, ip, password, device_id):
        """
        获取设备运行时间信息
        """
        uptime_script = "uptime"
        
        stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, uptime_script, self.base_dir)
        if not stderr:
            try:
                # 使用 os 模块相关的 datetime 获取当前时间
                current_datetime = datetime.now()
                
                # 解析 uptime 输出
                uptime_info = DataProcessingService.parse_uptime(stdout)
                
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
        time_script = "date +%s"
        
        stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, time_script, self.base_dir)
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
        dev_type_prefix = device_id.split('-')[0]
        if dev_type_prefix in ["C08L", "C16L", "D16"]:
            # 这三种设备类型不支持获取播放器启动次数
            return "无法获取"
        
        start_count_script = "getprop huidu.player.start_count"
        
        stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, start_count_script, self.base_dir)
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
        
        # 确保日志目录存在
        logs_dir = "./output/logs"
        os.makedirs(logs_dir, exist_ok=True)
        
        # 写入日志文件
        with open(f'{logs_dir}/{os.path.basename(self.base_dir)}_uptime.log', 'a', encoding='utf-8') as f:
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
            
            # 确保日志目录存在
            logs_dir = "./output/logs"
            os.makedirs(logs_dir, exist_ok=True)
            
            # 写入日志文件
            with open(f'{logs_dir}/{os.path.basename(self.base_dir)}_cardtime.log', 'a', encoding='utf-8') as f:
                f.write(time_log_entry)
            
            if time_diff != "N/A":
                time_diff_value = int(time_diff)
                
                # 检查是否是第一次获取该设备的设备时间
                if device_id in self.device_data:
                    if 'initial_time_diff' not in self.device_data[device_id]:
                        # 第一次获取，保存为初始值，不进行验证
                        self.device_data[device_id]['initial_card_time'] = adjusted_remote_time
                        self.device_data[device_id]['last_card_time'] = adjusted_remote_time
                        self.device_data[device_id]['initial_time_diff'] = time_diff_value
                        self.device_data[device_id]['last_time_diff'] = time_diff_value
                        # 保存初始时间戳，用于计算运行天数
                        self.device_data[device_id]['initial_timestamp'] = datetime.now().timestamp()
                    else:
                        # 非第一次获取，与初始值比较
                        initial_time_diff = self.device_data[device_id]['last_time_diff']
                        
                        # 计算从初始时间到现在的天数
                        if 'initial_timestamp' in self.device_data[device_id]:
                            initial_timestamp = self.device_data[device_id]['initial_timestamp']
                            current_timestamp = datetime.now().timestamp()
                            # 计算天数差，保留一位小数
                            days_passed = (current_timestamp - initial_timestamp) / (24 * 3600)
                            # 确保至少为1天
                            days_passed = max(1, round(days_passed, 1))
                        else:
                            # 如果没有初始时间戳，使用运行时长
                            days_passed = 1
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
                                            # 确保至少为1天
                                            days_passed = max(1, round(days_passed, 1))
                                except Exception:
                                    days_passed = 1 # 设置为1天避免除零错误
                        
                        # 计算日均偏差
                        daily_deviation = abs(time_diff_value - initial_time_diff) / days_passed
                        
                        # 每次都更新设备时间，确保Excel中写入最新的时间
                        self.device_data[device_id]['last_card_time'] = adjusted_remote_time
                        self.device_data[device_id]['last_time_diff'] = time_diff_value
                        
                        # 只关注日均偏差是否大于±3s
                        if daily_deviation > 3:
                            errors.append({
                                'type': '时间偏差异常',
                                'process': f'初始时间差: {initial_time_diff}s, 当前时间差: {time_diff_value}s, 天数: {days_passed}天',
                                'difference': f'日均偏差: {daily_deviation:.2f}s > 3s'
                            })
                            # 记录时间变化
                            self.device_data[device_id]['last_card_time_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # 第一次获取设备信息，初始化设备数据并保存初始时间差
                    self.device_data[device_id] = {
                        'initial_time_diff': time_diff_value,
                        'last_time_diff': time_diff_value,
                        'initial_timestamp': datetime.now().timestamp()
                    }
        
        # 3. 检查启动次数（启动次数一致性验证）
        if monitor_start_count:
            start_count = self.get_start_count(ip, password, device_id)
            
            # 写入启动次数日志
            start_count_log_entry = f"{device_id},{ip},{start_count}\n"
            
            # 确保日志目录存在
            logs_dir = "./output/logs"
            os.makedirs(logs_dir, exist_ok=True)
            
            # 写入日志文件
            with open(f'{logs_dir}/{os.path.basename(self.base_dir)}_startcount.log', 'a', encoding='utf-8') as f:
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
            dev_type_prefix = device_id.split('-')[0]
            if dev_type_prefix in ["C08L", "C16L", "D16"]:
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
        
        # 如果是特殊设备类型，设置启动次数为"无法获取"
        dev_type_prefix = device_id.split('-')[0]
        if dev_type_prefix in ["C08L", "C16L", "D16"]:
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
    
    def capture_screenshot(self, device_id, ip, password, system_type, screenshot_path="./screenshot"):
        """
        捕获设备屏幕截图
        
        参数:
        device_id: 设备ID
        ip: 设备IP地址
        password: 设备密码
        system_type: 设备系统类型
        screenshot_path: 截图存储路径，默认值为"./screenshot"
        
        返回:
        str: 截图保存路径，失败返回错误信息
        """
        # 确保截图存储目录存在
        os.makedirs(screenshot_path, exist_ok=True)
        # 检查设备类型是否支持截图
        supported_dev_types = ["H6", "H8", "H4K", "B6L", "B8L", "A3L", "A4L", "A5L", "A6L", "C16H"]
        dev_type_prefix = device_id.split('-')[0] if '-' in device_id else device_id
        
        if dev_type_prefix not in supported_dev_types:
            return f"设备 {device_id} 不支持通过adb截图"
        
        if not ToolService.is_android_device(device_id):
            return f"设备 {device_id} 不支持通过adb截图"
        
        try:
            # 创建截图保存目录
            screenshot_dir = screenshot_path
            device_dir = f"{screenshot_dir}/{device_id}"
            os.makedirs(device_dir, exist_ok=True)
            
            # 生成截图文件名
            timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
            screenshot_file = f"{device_dir}/{device_id}_{timestamp}.jpg"
            remote_file = "/sdcard/screenshot.png"
            
            # 连接设备
            stdout, stderr, returncode = ToolService.adb_connect(ip)
            if returncode != 0:
                return f"连接设备失败: {stderr}"
            
            # 执行截图
            stdout, stderr, returncode = ToolService.adb_screencap(ip, remote_file)
            if returncode != 0:
                # 检查是否是设备未授权错误
                if "device unauthorized" in stderr:
                    # 使用SSH执行命令来重新启动ADB服务
                    try:
                        # 执行命令开启设备授权
                        ToolService.execute_command(device_id, ip, password, "setprop service.adb.tcp.port 5555", ".")
                        ToolService.execute_command(device_id, ip, password, "stop adbd", ".")
                        ToolService.execute_command(device_id, ip, password, "start adbd", ".")
                        # 等待ADB服务启动
                        time.sleep(3)
                        # 重新连接设备
                        ToolService.adb_disconnect()
                        time.sleep(1)
                        stdout, stderr, returncode = ToolService.adb_connect(ip)
                        if returncode != 0:
                            return f"重新连接设备失败: {stderr}"
                        # 再次尝试执行截图
                        stdout, stderr, returncode = ToolService.adb_screencap(ip, remote_file)
                        if returncode != 0:
                            return f"执行截图命令失败: {stderr}"
                    except Exception as e:
                        return f"处理设备授权失败: {str(e)}"
                else:
                    return f"执行截图命令失败: {stderr}"
            
            # 拉取截图文件
            stdout, stderr, returncode = ToolService.adb_pull_file(ip, remote_file, screenshot_file)
            if returncode != 0:
                return f"拉取截图文件失败: {stderr}"
            
            # 删除设备上的临时文件
            ToolService.adb_rm_file(ip, remote_file)
            
            # 断开连接
            ToolService.adb_disconnect()

            # 统一使用正斜杠
            screenshot_file = screenshot_file.replace('\\', '/')
            return screenshot_file
        except Exception as e:
            return f"截图失败: {str(e)}"
    
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
            for device in devices:
                device_id = device['id']
                ip = device['ip']
                password = device['password']
                print(f"\n检查设备: {device_id} ({ip})")
                print(f"密码: {password}")
                
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
