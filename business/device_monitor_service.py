#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime, timedelta, timezone
import time
import os
import threading
from typing import Dict, Optional, Tuple
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
from service.protocol.set_time import set_time as protocol_set_time
from service.protocol.query_service import (
    build_device_time_info, build_uptime_info, parse_device_datetime, BEIJING_TZ,
)

logger = get_logger(__name__)

TIME_UPTIME_SPLIT = "___LM_TIME_UPTIME_SPLIT___"
"""SSH/ADB 通道「一次命令同时取回 设备时间 + uptime」的分段标记"""

LEGACY_STATUS_TTL_SECONDS = 5.0
"""SSH/ADB 通道合并取数的短时缓存（秒）：同一轮询内「设备时间」与「运行时长」复用"""

_LEGACY_STATUS_CACHE: Dict[str, Tuple[float, Tuple[str, str]]] = {}
_LEGACY_STATUS_LOCK = threading.Lock()


def _read_legacy_status(host: str) -> Optional[Tuple[str, str]]:
    """读缓存；未命中或过期返回 None。"""
    now = time.monotonic()
    with _LEGACY_STATUS_LOCK:
        entry = _LEGACY_STATUS_CACHE.get(host)
    if entry is not None and entry[0] > now:
        return entry[1]
    return None


def _write_legacy_status(host: str, value: Tuple[str, str]) -> None:
    with _LEGACY_STATUS_LOCK:
        _LEGACY_STATUS_CACHE[host] = (time.monotonic() + LEGACY_STATUS_TTL_SECONDS, value)


def clear_legacy_status_cache(host: Optional[str] = None) -> None:
    """清除合并取数缓存（测试/校时后刷新用）。"""
    with _LEGACY_STATUS_LOCK:
        if host is None:
            _LEGACY_STATUS_CACHE.clear()
        else:
            _LEGACY_STATUS_CACHE.pop(host, None)


class DeviceMonitorService:
    """设备监控业务服务类，负责设备监控的核心业务逻辑"""
    
    def __init__(self, dev_type):
        self.dev_type = dev_type
        self.base_dir = get_base_dir(dev_type)
        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        self.device_data = FileService.load_device_data()
        self.notepad_process = None  # 用于跟踪记事本进程
        # 并行监控下保护「设备基准数据 + 日志落盘」的可重入锁：
        # 耗时的网络取数在锁外并行，仅短小的状态读写/落盘进锁，兼顾并发与一致性
        self._state_lock = threading.RLock()
    
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
                        
                        # Android 系统二进制需要执行权限：走**统一命令通道**
                        # （协议 exec 优先 → adb → SSH）。旧实现直接用 adb chmod，
                        # adb 连接抖动时会误报 "device 'ip:5555' not found"，
                        # 而设备其实已经收到文件、初始化也已经生效。
                        if is_android and remote_path.startswith("/system/bin/"):
                            _, stderr_chmod, rc_chmod = ToolService.execute_command(
                                device_id, ip, password, f"chmod +x {remote_path}", ".")
                            if rc_chmod != 0:
                                error = (f"设置{local_file}执行权限失败: "
                                         f"{stderr_chmod or '返回码 %s' % rc_chmod}")
                            else:
                                steps.append(f"{local_file}执行权限设置完成")
            
            # 2. 额外命令 + flag 创建 + sync 合并成**一条**远端命令（少 N 次往返）
            if not error:
                flag_path = init_config.get("flag_path", "")
                batch = list(init_config.get("extra_commands", []))
                if flag_path:
                    batch.append(f"touch {flag_path}/swich_counter_flag")
                    files_to_check.append(f"{flag_path}/swich_counter_flag")
                batch.append("sync")
                command = " && ".join(batch)
                stdout, stderr, returncode = ToolService.execute_command(
                    device_id, ip, password, command, ".")
                if returncode != 0:
                    error = f"执行命令失败 '{command}': {stderr or '返回码 %s' % returncode}"
                else:
                    steps.append("脚本授权 / flag 创建 / sync 完成")
            
            # 3. 验证文件是否存在（**一次往返**校验全部文件，必要时重试一次）
            if not error and files_to_check:
                missing = self._missing_remote_files(device_id, ip, password, files_to_check)
                if missing:
                    time.sleep(0.5)
                    missing = self._missing_remote_files(device_id, ip, password, files_to_check)
                if missing:
                    error = f"文件验证失败，以下文件不存在: {', '.join(missing)}"
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

    @staticmethod
    def _missing_remote_files(device_id, ip, password, paths):
        """**一次往返**校验多个远端文件是否存在，返回缺失清单（空 = 全部存在）。

        旧实现每个文件一次 ``check_file_exists``（还带 3 次重试与 sleep），
        4 个文件就要 4 次往返 + 约 2s 等待；这里合成一条 ``test -e`` 命令。
        通道无任何输出时按「全部未验证」处理，避免误判成功。
        """
        checks = "; ".join(
            f"[ -e {path} ] && echo 'OK {index}' || echo 'MISS {index}'"
            for index, path in enumerate(paths))
        stdout, _stderr, _rc = ToolService.execute_command(
            device_id, ip, password, checks, ".")

        missing = []
        answered = False
        for line in (stdout or "").splitlines():
            parts = line.strip().split()
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            answered = True
            index = int(parts[1])
            if parts[0] == "MISS" and index < len(paths):
                missing.append(paths[index])
        return list(paths) if not answered else missing

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
        """设置设备时间。

        - **Android**：协议 ``Set Time`` 优先（``dateTime`` 为 UTC-0 墙钟，时区由
          ``timeZone`` 声明），失败回落 ntpdate 推送；
        - **Linux**：只有 SSH 一条通道，且这些机型本就不支持协议 —— 因此**不做协议探测**
          （省掉每次约 1.7s 的白等），改为**以本机时钟为基准**、一条 SSH 直接
          ``date -s`` + ``hwclock -w`` 并回读 epoch 校验：免推 ntpdate、免等外网 NTP
          （现场设备常访问不到 ``ntp.huidu.cn``），实测单台从约 9s 降到约 1s。
          ``date -s`` 失败或回读 epoch 偏差过大时才回落 ntpdate。
        """
        is_android = ToolService.is_android_device(device_id)

        # ---- Android：协议优先（免 adb/SSH、免外网） ----
        if USE_PROTOCOL_QUERY and is_android:
            try:
                ok, msg = protocol_set_time(ip)
            except Exception as exc:  # pylint: disable=broad-except
                ok, msg = False, str(exc)
            if ok:
                local_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                return OperationResult(
                    True, data=f"{device_id} 时间已校时成功（协议），本机时间为：{local_now}")
            logger.info("设备 %s 协议校时不可用（%s），回落 ntpdate 推送", device_id, msg)

        # ---- Linux：SSH 直接设时（以本机时钟为准） ----
        if not is_android:
            result = self._set_time_over_ssh(ip, password, device_id)
            if result is not None:
                return result
            logger.info("设备 %s SSH 直接设时未生效，回落 ntpdate 推送", device_id)

        try:
            remote_file = ""
            if is_android:
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

    TIME_VERIFY_TOLERANCE_SECONDS = 30
    """SSH 设时后允许的 epoch 偏差（秒）：超过即判定未生效，回落 ntpdate"""

    def _set_time_over_ssh(self, ip, password, device_id):
        """Linux 校时：以本机时钟为基准，两次 SSH 往返完成设时并校验。

        1. ``date +%z`` 取设备时区偏移（设时要用**设备本地时间**，否则 epoch 会偏）；
        2. ``date -s`` 设系统时间（失败则用 ``MMDDhhmmYYYY.ss`` 老格式再试一次）
           → ``hwclock -w`` 写 RTC → ``date +%s`` 回读 epoch 校验。

        Returns:
            成功返回 :class:`OperationResult`；未生效返回 ``None``（交调用方走 ntpdate 兜底）。
        """
        try:
            offset_text, _, _ = ToolService.execute_command(
                device_id, ip, password, "date +%z", ".")
            offset = self._parse_utc_offset(offset_text)
            if offset is None:
                logger.info("设备 %s 读不到时区偏移（%r），无法直设时间", device_id, offset_text)
                return None

            target = datetime.now(timezone.utc) + offset
            stamp = target.strftime('%Y-%m-%d %H:%M:%S')
            legacy_stamp = target.strftime('%m%d%H%M%Y.%S')
            command = (
                f'date -s "{stamp}" >/dev/null 2>&1 || date {legacy_stamp} >/dev/null 2>&1; '
                f'hwclock -w >/dev/null 2>&1; '
                f'date +%s'
            )
            stdout, stderr, _ = ToolService.execute_command(
                device_id, ip, password, command, ".")

            epoch_text = (stdout or "").strip().splitlines()
            epoch = int(epoch_text[-1].strip()) if epoch_text else None
            if epoch is None:
                logger.info("设备 %s 设时后回读 epoch 失败（%r / %r）",
                            device_id, stdout, stderr)
                return None

            skew = abs(epoch - int(time.time()))
            if skew > self.TIME_VERIFY_TOLERANCE_SECONDS:
                logger.info("设备 %s 设时后 epoch 偏差 %ss（阈值 %ss），判定未生效",
                            device_id, skew, self.TIME_VERIFY_TOLERANCE_SECONDS)
                return None

            shown = datetime.fromtimestamp(epoch, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
            logger.info("设备 %s SSH 校时成功（偏差 %ss，设备显示 %s）", device_id, skew, shown)
            return OperationResult(
                True, data=f"{device_id} 时间已校时成功（SSH），时间为：{shown}")
        except Exception as exc:  # pylint: disable=broad-except
            logger.info("设备 %s SSH 直接设时异常（%s），回落 ntpdate", device_id, exc)
            return None

    @staticmethod
    def _parse_utc_offset(text):
        """``+0800`` / ``-0530`` → :class:`datetime.timedelta`；无法解析返回 None。"""
        match = re.match(r'^\s*([+-])(\d{2})(\d{2})\s*$', text or "")
        if not match:
            return None
        sign = -1 if match.group(1) == '-' else 1
        return sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))

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
            
            # 推送节目文件（Linux 走 SFTP 复用连接，Android 走 adb push）
            stdout, stderr, returncode = ToolService.push_file(
                device_id, ip, password, local_program, f"{remote_dir}/project.tar.gz")
            if returncode != 0:
                return OperationResult(
                    False, error=f"{device_id} 推送节目失败 - {stderr or '返回码 %s' % returncode}")
            if stderr:
                logger.info("设备 %s 推送节目完成但有提示: %s", device_id, stderr)
            
            # 解压 + 清理压缩包合并为**一条**命令（少一次往返；解压失败不重启播放器）
            extract_cmd = (f"tar -zxf {remote_dir}/project.tar.gz -C {remote_dir} "
                           f"&& rm -f {remote_dir}/project.tar.gz")
            stdout, stderr, returncode = ToolService.execute_command(
                device_id, ip, password, extract_cmd, ".")
            if returncode != 0:
                return OperationResult(
                    False, error=f"{device_id} 解压节目失败 - {stderr or '返回码 %s' % returncode}")
            
            # 重启播放器
            ToolService.execute_command(device_id, ip, password, restart_cmd, ".")
            return OperationResult(True, data=f"{device_id} 更新节目成功,重启播放器")
        except Exception as e:
            return OperationResult(False, error=f"{device_id} 更新节目失败 - {str(e)}")

    def _protocol_status(self, ip, device_id=None):
        """取协议通道状态；未启用/非 Android/不支持时返回 None（走 adb/SSH）。

        Linux 设备（C08L/C16L/D16/D36）**不支持 MagicPlayer 协议**，直接跳过探测，
        省掉每次取数的建连尝试。
        """
        if not USE_PROTOCOL_QUERY:
            return None
        if device_id is not None and not ToolService.is_android_device(device_id):
            return None
        try:
            return get_device_status(ip)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("协议查询 %s 失败，回落 adb/SSH: %s", ip, exc)
            return None

    def _legacy_status(self, device_id, ip, password):
        """SSH/ADB 通道**一次命令**取回 ``(epoch 字符串, uptime 文本)``；失败返回 None。

        ``date +%s`` 与 ``uptime`` 合成一条命令下发，替代原先两次 plink 往返
        （Linux 设备实测每次往返约 2~3s）。结果按设备短时缓存，供同一轮询内的
        「设备时间」与「运行时长」两次取数复用，等于一次往返取全两项。
        """
        cached = _read_legacy_status(ip)
        if cached is not None:
            logger.debug("设备 %s 命中合并取数缓存（时间/运行时长）", device_id)
            return cached

        command = f"date +%s; echo {TIME_UPTIME_SPLIT}; uptime"
        stdout, stderr, _ = ToolService.execute_command(
            device_id, ip, password, command, self.base_dir)
        if not stdout:
            logger.info("设备 %s 合并取「时间/运行时长」无输出: %s", device_id, stderr)
            return None
        parts = stdout.split(TIME_UPTIME_SPLIT)
        if len(parts) < 2:
            logger.info("设备 %s 合并命令输出无法分段（前 200 字符）: %r",
                        device_id, stdout[:200])
            return None
        value = (parts[0].strip(), parts[1].strip())
        _write_legacy_status(ip, value)
        logger.info("设备 %s 一次往返取回时间/运行时长（epoch=%s）", device_id, value[0])
        return value

    def get_uptime_info(self, ip, password, device_id):
        """
        获取设备运行时间信息（协议优先，失败回落 adb/SSH 一次往返）
        """
        status = self._protocol_status(ip, device_id)
        if status and status.get("uptime_seconds") is not None:
            return build_uptime_info(
                status["uptime_seconds"],
                parse_device_datetime(status.get("date_time")),
            )

        legacy = self._legacy_status(device_id, ip, password)
        if legacy is None:
            return {
                'error': "获取运行时长失败（SSH/ADB 通道无响应）",
                'formatted_uptime': "N/A",
            }

        try:
            current_datetime = datetime.now()
            uptime_info = DataProcessingService.parse_uptime(legacy[1])

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
    
    def get_device_time_info(self, ip, password, device_id):
        """
        获取设备时间信息（协议优先，失败回落 adb/SSH 一次往返）
        """
        status = self._protocol_status(ip, device_id)
        if status:
            device_datetime = parse_device_datetime(status.get("date_time"))
            if device_datetime is not None:
                return build_device_time_info(device_datetime)

        legacy = self._legacy_status(device_id, ip, password)
        date_result = legacy[0] if legacy else ""

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
                f.write(f"{datetime.now()} 设备:{device_id} 获取时间异常: SSH/ADB 通道无响应\n")

        return formatted_remote_time, time_diff
    
    def get_start_count(self, ip, password, device_id):
        """
        获取播放器启动次数（Android 走协议 exec 优先、adb/SSH 兜底）。

        **Linux 设备（C08L/C16L/D16/D36）本身没有 MagicPlayer 播放器概念**，
        因此恒为「无法获取」，也不再尝试任何协议/取数命令。
        """
        if not ToolService.is_android_device(device_id):
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
        """统一的日志文件写入方法（并行监控下加锁，避免多设备日志行交错）"""
        with self._state_lock:
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
        """检查启动时间偏差（基准数据读写在锁内，避免并行监控互相覆盖）"""
        if 'boot_time' not in uptime_info:
            return
        boot_time = datetime.fromisoformat(uptime_info['boot_time'])
        with self._state_lock:
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
        """检查设备时间偏差（基准数据读写在锁内，避免并行监控互相覆盖）"""
        if time_diff == "N/A":
            return
        try:
            time_diff_value = int(time_diff)
        except (ValueError, TypeError):
            return
        with self._state_lock:
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
        """检查启动次数偏差（基准数据读写在锁内，避免并行监控互相覆盖）"""
        try:
            current = int(start_count)
        except (ValueError, TypeError):
            return
        with self._state_lock:
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
            if not ToolService.is_android_device(device_id):
                return          # Linux 无播放器概念，无「启动次数获取失败」之说
            if not start_count or "Error" in str(start_count):
                errors.append({
                    'type': '启动次数获取失败',
                    'process': f'设备ID: {device_id}, IP: {ip}',
                    'difference': '获取启动次数信息失败',
                })

    def _update_device_data(self, device_id, formatted_uptime):
        """更新设备数据最后采样值（锁内，避免并行监控互相覆盖）"""
        with self._state_lock:
            if device_id not in self.device_data:
                self.device_data[device_id] = {}
            self.device_data[device_id]['last_uptime'] = formatted_uptime
            if not ToolService.is_android_device(device_id):
                # Linux 无播放器概念 → 启动次数恒为「无法获取」
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
