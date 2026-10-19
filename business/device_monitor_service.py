#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime, timedelta
import time
import os
from service.tool_service import ToolService
from service.data_processing_service import DataProcessingService
from service.file_service import FileService
from config import (
    get_base_dir, time_diff_threshold, daily_time_diff_threshold,
    tool_path, program_path, LOG_DIR, USE_PROTOCOL_QUERY,
)
from device_config import get_init_config, get_upgrade_config
from business.screenshot_service import ScreenshotService
from business.device_log_service import DeviceLogService
from data_models import DeviceState, OperationResult
from service.logging_service import get_logger
from service.protocol import get_device_status
from service.protocol.command_query import exec_if_supported
from service.protocol.query_service import (
    build_device_time_info, build_uptime_info, parse_device_datetime, BEIJING_TZ,
)

logger = get_logger(__name__)

class DeviceMonitorService:
    """设备监控业务服务类，负责设备监控的核心业务逻辑"""
    
    def __init__(self, dev_type):
        self.dev_type = dev_type
        self.base_dir = get_base_dir(dev_type)
        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        self.device_data = FileService.load_device_data()
        self.notepad_process = None  # 用于跟踪记事本进程
    
    def count_init_setting(self, ip, password, device_id, system_type, custom_file_paths=None):
        """
        设备初始化设置开关机
        
        功能：
        1. 从 device_info.json 动态加载配置，支持新增型号无需修改代码
        2. 使用可靠的文件推送方式（带MD5校验和重试）
        3. 自动设置文件执行权限
        4. 改进的错误处理和调试信息
        5. 完整的文件存在性验证
        
        参数:
            custom_file_paths: 自定义文件路径字典 {文件名: 本地路径}，如果为None则使用默认tool_path
        """
        def get_file_path(filename):
            if custom_file_paths and filename in custom_file_paths:
                return custom_file_paths[filename]
            return f"{tool_path}/{filename}"
        
        try:
            sync_result = self.ntptime_checkout_time(ip, password, device_id, system_type)
            if not sync_result.success:
                return OperationResult(
                    False,
                    error=f"{device_id} 设备校时失败 - {sync_result.error},请检查网络是否正常连接外网",
                )
        except Exception as e:
            return OperationResult(
                False,
                error=f"{device_id} 设备校时失败 - {str(e)},请检查网络是否正常连接外网",
            )

        try:
            dev_type_prefix = device_id.split('-')[0]
            
            # 从 device_info.json 动态加载初始化配置
            init_config = get_init_config(dev_type_prefix)
            if not init_config:
                return OperationResult(
                    False,
                    error=f"{device_id} 设置开关机失败 - 未在 device_info.json 中找到 {dev_type_prefix} 的开关机初始化配置",
                )
            
            is_android = ToolService.is_android_device(device_id)
            steps = []
            error = None
            files_to_check = []
            
            # 1. 推送所有文件
            for file_info in init_config.get("files", []):
                local_file = file_info["local"]
                remote_path = file_info["remote"]
                desc = file_info.get("desc", local_file)
                
                if not error:
                    use_reliable = is_android
                    stdout, stderr, returncode = ToolService.push_file(
                        device_id, ip, password, 
                        get_file_path(local_file), remote_path, 
                        use_reliable=use_reliable
                    )
                    if stderr or returncode != 0:
                        error = f"推送{local_file}失败: {stderr}"
                    else:
                        steps.append(f"{local_file}推送成功 ({stdout})")
                        files_to_check.append(remote_path)
                        
                        # Android设备：系统二进制文件需要设置执行权限
                        if is_android and remote_path.startswith("/system/bin/"):
                            stdout_chmod, stderr_chmod, returncode_chmod = ToolService.adb_set_executable(ip, remote_path)
                            if stderr_chmod or returncode_chmod != 0:
                                error = f"设置{local_file}执行权限失败: {stderr_chmod}"
                            else:
                                steps.append(f"{local_file}执行权限设置完成")
            
            # 2. 执行额外命令
            if not error:
                for cmd in init_config.get("extra_commands", []):
                    stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, cmd, ".")
                    if stderr or returncode != 0:
                        error = f"执行命令失败 '{cmd}': {stderr}"
                        break
                    else:
                        steps.append(f"执行命令成功: {cmd}")
            
            # 3. 创建flag文件
            flag_path = init_config.get("flag_path", "")
            if not error and flag_path:
                flag_cmd = f"touch {flag_path}/swich_counter_flag"
                stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, flag_cmd, ".")
                if stderr or returncode != 0:
                    error = f"创建swich_counter_flag失败: {stderr}"
                else:
                    steps.append("swich_counter_flag创建成功")
                    files_to_check.append(f"{flag_path}/swich_counter_flag")
            
            # 4. 执行sync同步
            if not error:
                stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, "sync", ".")
                steps.append("sync执行成功")
            
            # 5. 验证文件是否存在
            if not error and files_to_check:
                missing_files = []
                for file_path in files_to_check:
                    time.sleep(0.3)
                    exists = False
                    for attempt in range(3):
                        try:
                            exists = ToolService.check_file_exists(device_id, ip, password, file_path)
                            if exists:
                                break
                            if attempt < 2:
                                time.sleep(0.5)
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
                return OperationResult(False, error=f"{device_id} 设置开关机失败 - {error}")
            else:
                return OperationResult(
                    True,
                    data=f"{device_id} 设置开关机成功 - 执行步骤: {'; '.join(steps)}",
                )
                
        except Exception as e:
            return OperationResult(False, error=f"{device_id} 设置开关机失败 - {str(e)}")

    def sum_switch_count(self, ip, password, device_id, path):
        """设备累计开机次数"""
        return DeviceLogService.sum_switch_count(ip, password, device_id, path)
    def clean_switch_log(self, ip, password, device_id, path):
        """清除开关机日志"""
        return DeviceLogService.clean_switch_log(ip, password, device_id, path)
    def switch_log_output(self, ip, password, device_id, system_type, path):
        """导出开关机日志"""
        return DeviceLogService.switch_log_output(ip, password, device_id, system_type, path)
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
                    return OperationResult(False, error=f"{device_id} 推送ntpdate失败 - {stderr}")
            else:
                remote_file = "/bin/ntpdate"
                stdout, stderr, returncode = ToolService.push_file(device_id, ip, password, f"{tool_path}/ntpdate", remote_file)
                if stderr or returncode != 0:
                    return OperationResult(False, error=f"{device_id} 推送ntpdate失败 - {stderr}")
            
            ToolService.execute_command(device_id, ip, password, f"chmod +x {remote_file}", ".")
            
            ToolService.execute_command(device_id, ip, password, f"{remote_file} -server ntp.huidu.cn", ".")
            
            ToolService.execute_command(device_id, ip, password, "hwclock -w", ".")
            
            ToolService.execute_command(device_id, ip, password, f"rm -f {remote_file}", ".")
            
            stdout, _, _ = ToolService.execute_command(device_id, ip, password, "date", ".")
            return OperationResult(True, data=f"{device_id} 时间已校时成功，时间为：{stdout}")
        except Exception as e:
            return OperationResult(False, error=f"{device_id} 设置时间失败 - {str(e)}")

    def upgrade_program(self, ip, password, device_id, system_type, custom_file_paths=None):
        """
        更新设备节目
        
        参数:
            custom_file_paths: 自定义节目文件路径字典 {设备型号前缀: 本地路径}
        """
        try:
            dev_type_prefix = device_id.split('-')[0]
            
            # 从 device_info.json 动态加载发送节目配置
            upgrade_config = get_upgrade_config(dev_type_prefix)
            if not upgrade_config:
                return OperationResult(
                    False,
                    error=f"{device_id} 更新节目失败 - 未在 device_info.json 中找到 {dev_type_prefix} 的发送节目配置",
                )
            
            remote_dir = upgrade_config["remote_dir"]
            restart_cmd = upgrade_config.get("restart_cmd", "")
            pre_commands = upgrade_config.get("pre_commands", [])
            program_name = upgrade_config["program_name"].replace("{model}", dev_type_prefix)
            
            # 获取节目文件路径（优先使用自定义路径）
            if custom_file_paths and dev_type_prefix in custom_file_paths:
                local_program = custom_file_paths[dev_type_prefix]
            else:
                os.makedirs(program_path, exist_ok=True)
                local_program = f"{program_path}/{program_name}"
            
            if not os.path.exists(local_program):
                return OperationResult(False, error=f"设备节目不存在，请检查: {local_program}")
            
            # 执行前置命令
            for cmd in pre_commands:
                ToolService.execute_command(device_id, ip, password, cmd, ".")
            
            # 推送节目文件
            ToolService.push_file(device_id, ip, password, local_program, f"{remote_dir}/project.tar.gz")
            
            # 解压节目文件
            ToolService.execute_command(device_id, ip, password, f"tar -zxf {remote_dir}/project.tar.gz -C {remote_dir}", ".")
            
            # 删除压缩包
            ToolService.execute_command(device_id, ip, password, f"rm {remote_dir}/project.tar.gz", ".")
            
            # 重启播放器
            ToolService.execute_command(device_id, ip, password, restart_cmd, ".")
            return OperationResult(True, data=f"{device_id} 更新节目成功,重启播放器")
        except Exception as e:
            return OperationResult(False, error=f"{device_id} 更新节目失败 - {str(e)}")

    def _protocol_status(self, ip):
        """取协议通道状态；未启用或不支持时返回 None（不影响 adb/SSH 回落）。"""
        if not USE_PROTOCOL_QUERY:
            return None
        try:
            return get_device_status(ip)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("协议查询 %s 失败，回落 adb/SSH: %s", ip, exc)
            return None

    def get_uptime_info(self, ip, password, device_id):
        """
        获取设备运行时间信息（协议优先，失败回落 adb/SSH）
        """
        status = self._protocol_status(ip)
        if status and status.get("uptime_seconds") is not None:
            return build_uptime_info(
                status["uptime_seconds"],
                parse_device_datetime(status.get("date_time")),
            )

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
        获取设备时间信息（协议优先，失败回落 adb/SSH）
        """
        status = self._protocol_status(ip)
        if status:
            device_datetime = parse_device_datetime(status.get("date_time"))
            if device_datetime is not None:
                return build_device_time_info(device_datetime)

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
                    # 统一按北京时区渲染（UI 直接展示，无需再 +8）
                    formatted_remote_time = datetime.fromtimestamp(
                        remote_time, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
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
        获取安卓系列播放器启动次数（协议优先，失败回落 adb/SSH）
        """
        # 检查设备ID前缀是否为C08L、C16L或D16
        dev_type_prefix = device_id.split('-')[0]
        if dev_type_prefix in ["C08L", "C16L", "D16"]:
            # 这三种设备类型不支持获取播放器启动次数
            return "无法获取"

        start_count_script = "getprop huidu.player.start_count"

        # 协议通道：加密 Command.exec（ms 级，无需拉起 adb/SSH）
        if USE_PROTOCOL_QUERY:
            protocol_result = exec_if_supported(ip, start_count_script)
            if (protocol_result is not None and protocol_result.exit_code == 0
                    and protocol_result.text()):
                return protocol_result.text()

        stdout, stderr, returncode = ToolService.execute_command(device_id, ip, password, start_count_script, self.base_dir)
        result = stdout if not stderr else f"Error: {stderr}"
        return result
    
    def check_device_status(self, device_id, ip, password,
                             monitor_time=True, monitor_boot=True,
                             monitor_start_count=True):
        """检查设备状态并返回是否异常。已将各检查逻辑拆分为独立方法。"""
        errors = []
        os.makedirs(self.base_dir, exist_ok=True)

        # 1. 检查运行时间（启动时间误差验证）
        uptime_info = self.get_uptime_info(ip, password, device_id)
        formatted_uptime = uptime_info.get('formatted_uptime', 'N/A')
        self._write_uptime_log(device_id, ip, uptime_info)
        self._check_boot_deviation(device_id, uptime_info, errors)

        # 2. 检查设备时间（设备时间误差验证）
        if monitor_time:
            formatted_remote_time, time_diff = self.get_device_time_info(ip, password, device_id)
            self._write_cardtime_log(device_id, ip, formatted_remote_time, time_diff)
            self._check_time_deviation(device_id, uptime_info, time_diff, errors)
        else:
            formatted_remote_time, time_diff = "N/A", "N/A"

        # 3. 检查启动次数（启动次数一致性验证）
        if monitor_start_count:
            start_count = self.get_start_count(ip, password, device_id)
            self._write_startcount_log(device_id, ip, start_count)
            self._check_start_count_deviation(device_id, start_count, errors)
        else:
            start_count = "N/A"

        # 检查关键信息的完整性
        self._check_data_completeness(device_id, ip, formatted_uptime,
                                       formatted_remote_time, start_count,
                                       monitor_time, monitor_boot,
                                       monitor_start_count, errors)

        # 更新设备数据
        self._update_device_data(device_id, formatted_uptime)

        # 生成综合日志
        FileService.write_comprehensive_log(
            ip, password, device_id, self.base_dir,
            formatted_uptime if monitor_boot else "未监控",
            formatted_remote_time if monitor_time else "未监控",
            time_diff if monitor_time else "未监控",
            start_count if monitor_start_count else "未监控",
        )

        return errors

    # ---- 日志写入辅助方法 ----

    def _write_log_to_file(self, suffix, content):
        """统一的日志文件写入方法"""
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = f'{LOG_DIR}/{os.path.basename(self.base_dir)}_{suffix}.log'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(content)

    def _write_uptime_log(self, device_id, ip, uptime_info):
        entry = f"{device_id},{ip},{uptime_info.get('current_time', 'N/A')},{uptime_info.get('formatted_uptime', 'N/A')}\n"
        self._write_log_to_file('uptime', entry)

    def _write_cardtime_log(self, device_id, ip, formatted_remote_time, time_diff):
        # formatted_remote_time 已是北京时区墙钟，直接落盘，不再二次 +8
        entry = f"{device_id},{ip},{formatted_remote_time},{time_diff}s\n"
        self._write_log_to_file('cardtime', entry)


    def _write_startcount_log(self, device_id, ip, start_count):
        entry = f"{device_id},{ip},{start_count}\n"
        self._write_log_to_file('startcount', entry)

    # ---- 检查方法 ----

    def _check_boot_deviation(self, device_id, uptime_info, errors):
        """检查启动时间偏差"""
        if 'boot_time' not in uptime_info:
            return
        boot_time = datetime.fromisoformat(uptime_info['boot_time'])
        if device_id not in self.device_data:
            self.device_data[device_id] = {}
        data = self.device_data[device_id]
        if 'initial_boot_time' not in data:
            data['initial_os_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data['initial_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
            data['last_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')
            return
        initial_boot_time = datetime.fromisoformat(data['last_boot_time'])
        time_diff_from_initial = abs((boot_time - initial_boot_time).total_seconds())
        if time_diff_from_initial > time_diff_threshold:
            errors.append({
                'type': '启动时间误差',
                'process': f'初始启动时间: {initial_boot_time.isoformat()}, 当前启动时间: {boot_time.isoformat()}',
                'difference': f'{time_diff_from_initial}秒',
            })
            data['last_boot_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data['last_boot_time'] = boot_time.strftime('%Y-%m-%d %H:%M')

    def _check_time_deviation(self, device_id, uptime_info, time_diff, errors):
        """检查设备时间偏差"""
        if time_diff == "N/A":
            return
        try:
            time_diff_value = int(time_diff)
        except (ValueError, TypeError):
            return
        if device_id not in self.device_data:
            self.device_data[device_id] = {}
        data = self.device_data[device_id]
        if 'initial_time_diff' not in data:
            data['initial_time_diff'] = time_diff_value
            data['last_time_diff'] = time_diff_value
            data['initial_timestamp'] = datetime.now().timestamp()
            return

        days_passed = self._compute_days_passed(data, uptime_info)
        daily_deviation = abs(time_diff_value - data['last_time_diff']) / days_passed
        data['last_time_diff'] = time_diff_value

        if daily_deviation > daily_time_diff_threshold:
            errors.append({
                'type': '时间偏差异常',
                'process': f'初始时间差: {data["initial_time_diff"]}s, 当前时间差: {time_diff_value}s, 天数: {days_passed}天',
                'difference': f'日均偏差: {daily_deviation:.2f}s > {daily_time_diff_threshold}s',
            })
            data['last_card_time_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _compute_days_passed(self, data, uptime_info):
        """计算从初始时间到现在的天数"""
        if 'initial_timestamp' in data:
            days_passed = (datetime.now().timestamp() - data['initial_timestamp']) / (24 * 3600)
            return max(1, round(days_passed, 1))
        if 'uptime_delta' in uptime_info:
            days_part = re.search(r'(\d+) days?', uptime_info['uptime_delta'])
            if days_part:
                days = int(days_part.group(1))
                return max(1, days)
        return 1

    def _check_start_count_deviation(self, device_id, start_count, errors):
        """检查启动次数偏差"""
        try:
            current = int(start_count)
        except (ValueError, TypeError):
            return
        if device_id not in self.device_data:
            self.device_data[device_id] = {}
        data = self.device_data[device_id]
        if 'initial_start_count' not in data:
            data['initial_start_count'] = current
            data['last_start_count'] = current
            return
        if current != data['last_start_count']:
            errors.append({
                'type': '启动次数异常',
                'process': f'初始启动次数: {data["initial_start_count"]}, 当前启动次数: {current}',
                'difference': '启动次数异常',
            })
            data['last_start_count'] = current
            data['last_start_count_change_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _check_data_completeness(self, device_id, ip, formatted_uptime,
                                  formatted_remote_time, start_count,
                                  monitor_time, monitor_boot,
                                  monitor_start_count, errors):
        """检查关键信息的完整性"""
        if monitor_boot and (not formatted_uptime or "Error" in str(formatted_uptime)):
            errors.append({
                'type': '运行时长获取失败',
                'process': f'设备ID: {device_id}, IP: {ip}',
                'difference': '获取运行时长信息失败',
            })
        if monitor_time and (formatted_remote_time == "N/A" or "Error" in str(formatted_remote_time)):
            errors.append({
                'type': '设备时间获取失败',
                'process': f'设备ID: {device_id}, IP: {ip}',
                'difference': '获取设备时间信息失败',
            })
        if monitor_start_count:
            dev_type_prefix = device_id.split('-')[0]
            if dev_type_prefix not in ["C08L", "C16L", "D16"]:
                if not start_count or "Error" in str(start_count):
                    errors.append({
                        'type': '启动次数获取失败',
                        'process': f'设备ID: {device_id}, IP: {ip}',
                        'difference': '获取启动次数信息失败',
                    })

    def _update_device_data(self, device_id, formatted_uptime):
        """更新设备数据最后采样值"""
        if device_id not in self.device_data:
            self.device_data[device_id] = {}
        self.device_data[device_id]['last_uptime'] = formatted_uptime
        dev_type_prefix = device_id.split('-')[0]
        if dev_type_prefix in ["C08L", "C16L", "D16"]:
            self.device_data[device_id]['last_start_count'] = '无法获取'
    
    def capture_screenshot(self, device_id, ip, password, system_type, screenshot_path="./screenshot"):
        """捕获设备屏幕截图"""
        return ScreenshotService.capture_screenshot(device_id, ip, password, system_type, screenshot_path)
    def monitor_devices(self, delay_time=60):
        """
        监控所有设备
        """
        import subprocess
        
        while True:
            logger.info("开始监控 %s 类型设备...", self.dev_type)
            time.sleep(1)
            # 获取设备列表
            devices = ToolService.get_device_list(self.dev_type)
            device_count = len(devices)
            logger.info("发现 %s 台设备", device_count)
            
            has_new_errors = False  # 标记是否有新错误
            
            # 处理每个设备
            for device in devices:
                device_id = device['id']
                ip = device['ip']
                password = device['password']
                logger.info("检查设备: %s (%s)", device_id, ip)
                logger.debug("设备 %s 密码已获取", device_id)
                
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
            logger.info("所有设备检查完成，等待下一轮检查...")
            for i in range(delay_time, 0, -1):
                if i % 30 == 0:
                    logger.debug("下一轮检查倒计时: %s秒", i - 1)
                time.sleep(1)
            
            # 清空完成记录
            ok_ids_file = f"{self.base_dir}/{self.dev_type}_{datetime.now().strftime('%Y%m%d')}.log"
            if os.path.exists(ok_ids_file):
                os.remove(ok_ids_file)
