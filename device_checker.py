#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备信息查询工具
用于灵活查询设备信息，方便调试问题
支持输入设备ID、设备IP进行查询
支持动态查询特定信息指标
"""

import sys
import os
import time
import argparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from service.tool_service import ToolService
from business.device_monitor_service import DeviceMonitorService
from config import tool_path
from contextlib import contextmanager


# ==================== 配置区域 - 在此配置您的设备信息 ====================
# 如果要使用命令行参数，请将这些值设为 None 或在命令行中覆盖
DEFAULT_DEVICE_ID = "C16L-00-A4512"       # 例如: "A3L-A00-A193B" 或 None
DEFAULT_IP = "192.168.2.100"              # 例如: "192.168.2.95" 或 None
DEFAULT_METRICS = ['all']      # 默认检查指标，例如: ['mac', 'device_name', 'main_version']
# ==========================================================================


class DeviceChecker:
    """设备信息检查器"""
    
    # 定义所有可用的检查指标
    CHECK_METRICS = {
        'connection': '设备连接检查',
        'system': '系统类型检查',
        'paths': '关键路径检查',
        'boot_counter': 'boot_counter检查',
        'init_rc': 'init.rc配置检查',
        'switch_count': '开关机次数检查',
        'device_info': '设备基本信息检查',
        'adb': 'ADB可用性检查',
        'logs': '日志文件检查',
        'mac': 'MAC地址检查',
        'device_name': '设备名称检查',
        'system_type': '系统类型详细检查',
        'main_version': '主版本号检查',
        'ota_version': 'OTA版本检查',
        'all': '全部检查'
    }
    
    # 常用检查组合，方便快速选择
    QUICK_CHECK_PRESETS = {
        'basic': ['connection', 'system', 'device_info'],
        'device_info': ['mac', 'device_name', 'main_version', 'ota_version'],
        'switch': ['paths', 'boot_counter', 'init_rc', 'switch_count'],
        'all': ['all']
    }
    
    def __init__(self):
        self.devices = []
        self.results = {}
        self._check_step = 0

    @contextmanager
    def _section(self, title, step_label=None):
        """上下文管理器：自动打印检查节的头尾分隔线"""
        if step_label is None:
            step_label = title
        print(f"\n{'='*60}")
        print(f"[{step_label}] {title}")
        print(f"{'='*60}")
        try:
            yield
        except Exception as e:
            print(f"  ⚠️ 检查异常: {e}")

    @staticmethod
    def _safe_parse_int(text, index=0, separator=None):
        """安全解析命令输出中的整数，失败时返回 None"""
        if not text or not text.strip():
            return None
        try:
            if separator:
                parts = text.strip().split(separator)
            else:
                parts = text.strip().split()
            if index < len(parts):
                return int(parts[index])
            return None
        except (ValueError, IndexError, TypeError):
            return None

    @staticmethod
    def _safe_extract_csv_field(line, index, default='N/A'):
        """安全提取 CSV 行的指定字段"""
        if not line or not line.strip():
            return default
        parts = line.strip().split(',')
        if len(parts) > index:
            return parts[index]
        return default
        
    def get_device_password(self, device_id):
        """获取设备密码"""
        try:
            return ToolService.get_password(device_id)
        except Exception as e:
            print(f"获取设备密码失败: {e}")
            return None
    
    def check_device_connection(self, ip, password):
        """检查设备连接状态"""
        with self._section(f"检查设备连接 - IP: {ip}", "1/10"):
            try:
                print("正在初始化SSH连接...")
                stdout, stderr, returncode = ToolService.initialize_connection(ip, password)
                if stderr:
                    print(f"⚠️  SSH连接警告: {stderr}")
                else:
                    print("✅ SSH连接初始化成功")
                
                return True
            except Exception as e:
                print(f"❌ 设备连接失败: {e}")
                return False
    
    def check_system_type(self, ip, password):
        """检查系统类型"""
        with self._section("检查系统类型", "2/10"):
            try:
                # 检查是否是Android系统
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "ls /data", ".")
                if not stderr and "No such" not in stdout:
                    print("✅ 检测到 Android 系统")
                    return "Android"
                
                # 检查是否是Linux系统
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "ls /root/Box", ".")
                if not stderr and "No such" not in stdout:
                    print("✅ 检测到 Linux 系统")
                    return "Linux"
                
                print("⚠️  无法确定系统类型")
                return "Unknown"
            except Exception as e:
                print(f"❌ 检查系统类型失败: {e}")
                return "Unknown"
    
    def check_paths(self, ip, password, system_type):
        """检查关键路径"""
        print(f"\n{'='*60}")
        print(f"[3/10] 检查关键路径")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        paths_to_check = [
            ("数据目录", base_path),
            ("swich_counter_flag", f"{base_path}/swich_counter_flag"),
            ("swich_counter.csv", f"{base_path}/swich_counter.csv"),
            ("network_counter.csv", f"{base_path}/network_counter.csv"),
            ("boot_counter.sh", "/system/bin/boot_counter.sh" if "Android" in system_type else "/root/boot_counter.sh"),
        ]
        
        for name, path in paths_to_check:
            try:
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"ls -la {path}", ".")
                if stderr or "No such" in stdout:
                    print(f"❌ {name}: 不存在 - {path}")
                else:
                    print(f"✅ {name}: 存在 - {path}")
                    print(f"   {stdout.strip()}")
            except Exception as e:
                print(f"❌ {name}: 检查失败 - {e}")
    
    def check_boot_counter(self, ip, password, system_type):
        """检查boot_counter脚本"""
        print(f"\n{'='*60}")
        print(f"[4/10] 检查boot_counter脚本")
        print(f"{'='*60}")
        
        script_path = "/system/bin/boot_counter.sh" if "Android" in system_type else "/root/boot_counter.sh"
        
        try:
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"ls -la {script_path}", ".")
            if stderr or "No such" in stdout:
                print(f"❌ boot_counter.sh 不存在")
            else:
                print(f"✅ boot_counter.sh 存在")
                print(f"   {stdout.strip()}")
                
                # 检查执行权限
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"stat -c %a {script_path}", ".")
                if not stderr:
                    print(f"   权限: {stdout.strip()}")
                
                # 检查脚本内容前几行
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"head -20 {script_path}", ".")
                if not stderr:
                    print(f"   脚本内容预览:")
                    for line in stdout.split('\n')[:10]:
                        if line.strip():
                            print(f"      {line}")
        except Exception as e:
            print(f"❌ 检查boot_counter失败: {e}")
    
    def check_init_rc(self, ip, password, system_type):
        """检查init.rc配置"""
        print(f"\n{'='*60}")
        print(f"[5/10] 检查init.rc配置")
        print(f"{'='*60}")
        
        if "Android" in system_type:
            rc_files = [
                "init.huidu.rc",
                "init.rk356x.rc",
                "init.rk3399.rc"
            ]
            
            for rc_file in rc_files:
                rc_path = f"/vendor/etc/init/hw/{rc_file}"
                try:
                    stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"ls -la {rc_path}", ".")
                    if stderr or "No such" in stdout:
                        print(f"❌ {rc_file}: 不存在")
                    else:
                        print(f"✅ {rc_file}: 存在")
                        print(f"   {stdout.strip()}")
                        
                        # 检查是否包含boot_counter服务
                        stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"grep -n 'boot_counter' {rc_path}", ".")
                        if not stderr and stdout.strip():
                            print(f"   boot_counter服务配置:")
                            for line in stdout.split('\n'):
                                if line.strip():
                                    print(f"      {line}")
                except Exception as e:
                    print(f"❌ 检查{rc_file}失败: {e}")
        else:
            print("Linux系统，跳过init.rc检查")
    
    def check_switch_count(self, ip, password, system_type):
        """检查开关机次数"""
        print(f"\n{'='*60}")
        print(f"[6/10] 检查开关机次数")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 检查swich_counter.csv
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"wc -l {base_path}/swich_counter.csv 2>/dev/null || echo 0", ".")
            if not stderr and stdout.strip() != "0":
                count = self._safe_parse_int(stdout)
                if count is not None:
                    count = max(0, count - 1)
                print(f"✅ 开关机次数: {count}")
                
                # 显示最新几条记录
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"tail -5 {base_path}/swich_counter.csv", ".")
                if not stderr:
                    print(f"   最新记录:")
                    for line in stdout.split('\n'):
                        if line.strip():
                            print(f"      {line}")
            else:
                print(f"⚠️  无法获取开关机次数或文件不存在")
            
            # 检查network_counter.csv
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"wc -l {base_path}/network_counter.csv 2>/dev/null || echo 0", ".")
            if not stderr and stdout.strip() != "0":
                count = self._safe_parse_int(stdout)
                if count is not None:
                    count = max(0, count - 1)
                print(f"✅ 网络开关机次数: {count}")
            else:
                print(f"⚠️  无法获取网络开关机次数或文件不存在")
        except Exception as e:
            print(f"❌ 检查开关机次数失败: {e}")
    
    def check_device_info(self, ip, password, system_type):
        """获取设备信息"""
        print(f"\n{'='*60}")
        print(f"[7/10] 获取设备基本信息")
        print(f"{'='*60}")
        
        try:
            # 获取设备时间
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "date", ".")
            if not stderr:
                print(f"✅ 设备时间: {stdout.strip()}")
            
            # 获取系统运行时间
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "cat /proc/uptime", ".")
            if not stderr:
                uptime = stdout.strip().split()[0]
                print(f"✅ 系统运行时间: {uptime}秒")
            
            # 获取网络配置
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "ifconfig eth0 2>/dev/null || ip addr show eth0", ".")
            if not stderr:
                print(f"✅ 网络配置:")
                for line in stdout.split('\n'):
                    if "inet" in line.lower() and "addr" in line.lower():
                        print(f"      {line.strip()}")
        except Exception as e:
            print(f"❌ 获取设备信息失败: {e}")
    
    def check_adb_available(self, ip, password, system_type):
        """检查ADB可用性"""
        print(f"\n{'='*60}")
        print(f"[8/10] 检查ADB可用性")
        print(f"{'='*60}")
        
        if "Android" in system_type:
            try:
                # 尝试ADB连接
                stdout, stderr, returncode = ToolService.adb_connect(ip)
                if returncode == 0 and not stderr:
                    print(f"✅ ADB连接成功")
                    
                    # 检查ADB可以执行的命令
                    stdout, stderr, returncode = ToolService.adb_shell_command(ip, password, "getprop ro.build.version.release")
                    if not stderr:
                        print(f"✅ Android版本: {stdout.strip()}")
                    
                    # 断开连接
                    ToolService.adb_disconnect()
                else:
                    print(f"⚠️  ADB连接可能有问题: {stderr}")
            except Exception as e:
                print(f"❌ ADB检查失败: {e}")
        else:
            print("Linux系统，跳过ADB检查")
    
    def check_logs(self, ip, password, system_type):
        """检查日志文件"""
        print(f"\n{'='*60}")
        print(f"[9/10] 检查日志文件")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 检查logcat目录
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"ls -la {base_path}/logcat 2>/dev/null | wc -l", ".")
            if not stderr and stdout.strip() != "0":
                count = int(stdout.strip())
                print(f"✅ logcat目录存在，包含 {count} 个文件")
            else:
                print(f"⚠️  logcat目录不存在或为空")
            
            # 检查ping目录
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, f"ls -la {base_path}/ping 2>/dev/null | wc -l", ".")
            if not stderr and stdout.strip() != "0":
                count = int(stdout.strip())
                print(f"✅ ping目录存在，包含 {count} 个文件")
            else:
                print(f"⚠️  ping目录不存在或为空")
        except Exception as e:
            print(f"❌ 检查日志失败: {e}")
    
    def generate_report(self, device_id, ip, system_type):
        """生成检查报告"""
        print(f"\n{'='*60}")
        print(f"检查报告汇总")
        print(f"{'='*60}")
        print(f"设备ID: {device_id}")
        print(f"设备IP: {ip}")
        print(f"系统类型: {system_type}")
        print(f"检查时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
    
    def check_mac_address(self, ip, password, system_type):
        """检查MAC地址获取"""
        print(f"\n{'='*60}")
        print(f"检查MAC地址")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 方式1: 尝试从network_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/network_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 4:
                    print(f"✅ 从network_counter.csv获取MAC: {parts[3]}")
                    self.results['mac_address'] = parts[3]
            
            # 方式2: 尝试从swich_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/swich_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 4:
                    print(f"✅ 从swich_counter.csv获取MAC: {parts[3]}")
                    if 'mac_address' not in self.results:
                        self.results['mac_address'] = parts[3]
            
            # 方式3: 直接从网络接口获取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                "cat /sys/class/net/eth0/address 2>/dev/null || ifconfig eth0 2>/dev/null | grep -i hwaddr", 
                "."
            )
            if not stderr and stdout.strip():
                print(f"✅ 从网络接口获取MAC: {stdout.strip()}")
                if 'mac_address' not in self.results:
                    self.results['mac_address'] = stdout.strip()
            
            if 'mac_address' not in self.results:
                print(f"⚠️  无法获取MAC地址")
                self.results['mac_address'] = 'N/A'
                
        except Exception as e:
            print(f"❌ 检查MAC地址失败: {e}")
            self.results['mac_address'] = 'N/A'
    
    def check_device_name(self, ip, password, system_type):
        """检查设备名称获取"""
        print(f"\n{'='*60}")
        print(f"检查设备名称")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 方式1: 尝试从network_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/network_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 5:
                    print(f"✅ 从network_counter.csv获取设备名称: {parts[4]}")
                    self.results['device_name'] = parts[4]
            
            # 方式2: 尝试从swich_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/swich_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 5:
                    print(f"✅ 从swich_counter.csv获取设备名称: {parts[4]}")
                    if 'device_name' not in self.results:
                        self.results['device_name'] = parts[4]
            
            # 方式3: 尝试从getdeviceinfo.sh相关文件获取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"ls {base_path}/*.sh 2>/dev/null; cat {base_path}/*.sh 2>/dev/null | head -30", 
                "."
            )
            if not stderr and stdout.strip():
                print(f"⚠️  检查相关脚本:\n{stdout.strip()}")
            
            if 'device_name' not in self.results:
                print(f"⚠️  无法获取设备名称")
                self.results['device_name'] = 'N/A'
                
        except Exception as e:
            print(f"❌ 检查设备名称失败: {e}")
            self.results['device_name'] = 'N/A'
    
    def check_system_type_detailed(self, ip, password, system_type):
        """检查系统类型详细信息"""
        print(f"\n{'='*60}")
        print(f"检查系统类型详细信息")
        print(f"{'='*60}")
        
        try:
            # 检查内核版本
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, "uname -a", "."
            )
            if not stderr and stdout.strip():
                print(f"✅ 内核版本: {stdout.strip()}")
                self.results['kernel_version'] = stdout.strip()
            
            # 检查系统版本
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, "cat /proc/version 2>/dev/null", "."
            )
            if not stderr and stdout.strip():
                print(f"✅ 系统版本: {stdout.strip()}")
                self.results['system_version'] = stdout.strip()
            
            # 检查Android版本（如果是Android系统）
            if "Android" in system_type:
                stdout, stderr, returncode = ToolService.ssh_execute_command(
                    ip, password, "getprop ro.build.version.release 2>/dev/null", "."
                )
                if not stderr and stdout.strip():
                    print(f"✅ Android版本: {stdout.strip()}")
                    self.results['android_version'] = stdout.strip()
            
            # 检查CPU信息
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, "cat /proc/cpuinfo 2>/dev/null | grep 'model name' | head -1", "."
            )
            if not stderr and stdout.strip():
                print(f"✅ CPU型号: {stdout.strip()}")
                self.results['cpu_model'] = stdout.strip()
            
            self.results['system_type'] = system_type
            
        except Exception as e:
            print(f"❌ 检查系统类型详细信息失败: {e}")
    
    def check_main_version(self, ip, password, system_type):
        """检查主版本号获取"""
        print(f"\n{'='*60}")
        print(f"检查主版本号")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 方式1: 尝试从network_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/network_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 6:
                    print(f"✅ 从network_counter.csv获取主版本号: {parts[5]}")
                    self.results['main_version'] = parts[5]
            
            # 方式2: 尝试从swich_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/swich_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 6:
                    print(f"✅ 从swich_counter.csv获取主版本号: {parts[5]}")
                    if 'main_version' not in self.results:
                        self.results['main_version'] = parts[5]
            
            # 方式3: 尝试从系统属性获取
            if "Android" in system_type:
                stdout, stderr, returncode = ToolService.ssh_execute_command(
                    ip, password, 
                    "dumpsys package cn.huidu.lcd.player 2>/dev/null | grep -m 1 versionName", 
                    "."
                )
                if not stderr and stdout.strip() and 'versionName' in stdout:
                    version = stdout.split('=', 1)[1].strip() if '=' in stdout else stdout.strip()
                    print(f"✅ 从系统属性获取主版本号: {version}")
                    if 'main_version' not in self.results:
                        self.results['main_version'] = version
            
            if 'main_version' not in self.results:
                print(f"⚠️  无法获取主版本号")
                self.results['main_version'] = 'N/A'
                
        except Exception as e:
            print(f"❌ 检查主版本号失败: {e}")
            self.results['main_version'] = 'N/A'
    
    def check_ota_version(self, ip, password, system_type):
        """检查OTA版本获取"""
        print(f"\n{'='*60}")
        print(f"检查OTA版本")
        print(f"{'='*60}")
        
        base_path = "/data" if "Android" in system_type else "/root/Box/project"
        
        try:
            # 方式1: 尝试从network_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/network_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 7:
                    print(f"✅ 从network_counter.csv获取OTA版本: {parts[6]}")
                    self.results['ota_version'] = parts[6]
            
            # 方式2: 尝试从swich_counter.csv读取
            stdout, stderr, returncode = ToolService.ssh_execute_command(
                ip, password, 
                f"tail -1 {base_path}/swich_counter.csv 2>/dev/null", 
                "."
            )
            if not stderr and stdout.strip():
                parts = stdout.strip().split(',')
                if len(parts) >= 7:
                    print(f"✅ 从swich_counter.csv获取OTA版本: {parts[6]}")
                    if 'ota_version' not in self.results:
                        self.results['ota_version'] = parts[6]
            
            # 方式3: 尝试从系统属性获取
            if "Android" in system_type:
                stdout, stderr, returncode = ToolService.ssh_execute_command(
                    ip, password, 
                    "getprop ro.build.version 2>/dev/null", 
                    "."
                )
                if not stderr and stdout.strip():
                    print(f"✅ 从系统属性获取OTA版本: {stdout.strip()}")
                    if 'ota_version' not in self.results:
                        self.results['ota_version'] = stdout.strip()
            
            if 'ota_version' not in self.results:
                print(f"⚠️  无法获取OTA版本")
                self.results['ota_version'] = 'N/A'
                
        except Exception as e:
            print(f"❌ 检查OTA版本失败: {e}")
            self.results['ota_version'] = 'N/A'
    
    def print_available_metrics(self):
        """打印可用的检查指标"""
        print(f"\n{'='*60}")
        print(f"可用的检查指标:")
        print(f"{'='*60}")
        for key, value in sorted(self.CHECK_METRICS.items()):
            print(f"  {key:<15} - {value}")
        print(f"{'='*60}")
    
    def check_device_by_metrics(self, device_id, ip, metrics=None):
        """根据指定指标检查设备"""
        if metrics is None:
            metrics = ['all']
        
        print(f"\n{'='*60}")
        print(f"开始检查设备")
        print(f"设备ID: {device_id}")
        print(f"设备IP: {ip}")
        print(f"检查指标: {', '.join(metrics)}")
        print(f"{'='*60}")
        
        # 获取设备密码
        password = self.get_device_password(device_id)
        if not password:
            print("❌ 无法获取设备密码，检查终止")
            return False
        
        print(f"✅ 设备密码获取成功")
        
        # 初始化连接（基础操作，总是需要）
        try:
            ToolService.initialize_connection(ip, password)
        except Exception as e:
            print(f"❌ 设备连接失败: {e}")
            return False
        
        # 获取系统类型（基础操作，总是需要）
        system_type = "Unknown"
        try:
            stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "ls /data", ".")
            if not stderr and "No such" not in stdout:
                system_type = "Android"
            else:
                stdout, stderr, returncode = ToolService.ssh_execute_command(ip, password, "ls /root/Box", ".")
                if not stderr and "No such" not in stdout:
                    system_type = "Linux"
        except Exception:
            pass
        
        # 执行各项检查
        check_functions = {
            'connection': lambda: self.check_device_connection(ip, password),
            'system': lambda: self.check_system_type(ip, password),
            'paths': lambda: self.check_paths(ip, password, system_type),
            'boot_counter': lambda: self.check_boot_counter(ip, password, system_type),
            'init_rc': lambda: self.check_init_rc(ip, password, system_type),
            'switch_count': lambda: self.check_switch_count(ip, password, system_type),
            'device_info': lambda: self.check_device_info(ip, password, system_type),
            'adb': lambda: self.check_adb_available(ip, password, system_type),
            'logs': lambda: self.check_logs(ip, password, system_type),
            'mac': lambda: self.check_mac_address(ip, password, system_type),
            'device_name': lambda: self.check_device_name(ip, password, system_type),
            'system_type': lambda: self.check_system_type_detailed(ip, password, system_type),
            'main_version': lambda: self.check_main_version(ip, password, system_type),
            'ota_version': lambda: self.check_ota_version(ip, password, system_type),
        }
        
        # 执行选中的检查
        if 'all' in metrics:
            # 执行所有检查
            for func in check_functions.values():
                try:
                    func()
                except Exception as e:
                    print(f"⚠️  检查出错: {e}")
            self.generate_report(device_id, ip, system_type)
        else:
            # 执行指定的检查
            for metric in metrics:
                if metric in check_functions:
                    try:
                        check_functions[metric]()
                    except Exception as e:
                        print(f"⚠️  检查{metric}出错: {e}")
                elif metric != 'all':
                    print(f"⚠️  未知的检查指标: {metric}")
        
        # 打印结果汇总
        print(f"\n{'='*60}")
        print(f"检查结果汇总:")
        print(f"{'='*60}")
        if self.results:
            for key, value in sorted(self.results.items()):
                print(f"  {key:<20}: {value}")
        else:
            print("  (没有检查结果)")
        print(f"{'='*60}")
        
        return True
    
    def check_device(self, device_id, ip):
        """检查单个设备"""
        print(f"\n{'='*60}")
        print(f"开始检查设备")
        print(f"设备ID: {device_id}")
        print(f"设备IP: {ip}")
        print(f"{'='*60}")
        
        # 获取设备密码
        password = self.get_device_password(device_id)
        if not password:
            print("❌ 无法获取设备密码，检查终止")
            return False
        
        print(f"✅ 设备密码获取成功")
        
        # 检查连接
        if not self.check_device_connection(ip, password):
            print("❌ 设备连接失败，检查终止")
            return False
        
        # 检查系统类型
        system_type = self.check_system_type(ip, password)
        
        # 检查关键路径
        self.check_paths(ip, password, system_type)
        
        # 检查boot_counter
        self.check_boot_counter(ip, password, system_type)
        
        # 检查init.rc
        self.check_init_rc(ip, password, system_type)
        
        # 检查开关机次数
        self.check_switch_count(ip, password, system_type)
        
        # 获取设备信息
        self.check_device_info(ip, password, system_type)
        
        # 检查ADB
        self.check_adb_available(ip, password, system_type)
        
        # 检查日志
        self.check_logs(ip, password, system_type)
        
        # 生成报告
        self.generate_report(device_id, ip, system_type)
        
        return True


def main():
    """主函数"""
    print(f"\n{'='*60}")
    print(f"设备信息查询工具 v3.1")
    print(f"{'='*60}")
    
    parser = argparse.ArgumentParser(
        description='设备信息查询工具 - 支持动态查询设备信息指标'
    )
    
    parser.add_argument(
        'args', 
        nargs='*',
        help='设备ID, 设备IP, 或检查指标 (根据位置自动识别)'
    )
    
    parser.add_argument(
        '-m', '--metrics',
        nargs='+',
        help='指定检查指标，可同时指定多个 (如: -m mac device_name main_version)'
    )
    
    parser.add_argument(
        '-p', '--preset',
        choices=['basic', 'device_info', 'switch', 'all'],
        help='使用预设检查组合 (basic:基础检查, device_info:设备信息, switch:开关机检查, all:全部检查)'
    )
    
    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help='列出所有可用的检查指标和预设组合'
    )
    
    args = parser.parse_args()
    
    checker = DeviceChecker()
    
    # 列出可用指标
    if args.list:
        print_help_info(checker)
        return
    
    # 智能参数解析
    device_id = DEFAULT_DEVICE_ID
    ip = DEFAULT_IP
    metrics = None
    
    # 处理位置参数
    positional_args = args.args
    
    if positional_args:
        # 情况1: 只有一个参数 - 可能是指标或预设
        if len(positional_args) == 1:
            arg = positional_args[0]
            # 检查是否是指标
            if arg in checker.CHECK_METRICS:
                metrics = [arg]
                print(f"📊 识别为检查指标: {arg}")
            # 检查是否是预设
            elif arg in checker.QUICK_CHECK_PRESETS:
                metrics = checker.QUICK_CHECK_PRESETS[arg]
                print(f"📊 识别为预设组合: {arg}")
            # 否则可能是设备ID（需要配合默认IP）
            else:
                device_id = arg
                print(f"📱 识别为设备ID: {arg}")
        # 情况2: 两个参数 - 可能是 设备ID+IP, 或者 设备ID+指标
        elif len(positional_args) == 2:
            arg1, arg2 = positional_args
            # 检查第二个参数是否是指标或预设
            if arg2 in checker.CHECK_METRICS:
                device_id = arg1
                metrics = [arg2]
                print(f"📱 识别为设备ID: {arg1}")
                print(f"📊 识别为检查指标: {arg2}")
            elif arg2 in checker.QUICK_CHECK_PRESETS:
                device_id = arg1
                metrics = checker.QUICK_CHECK_PRESETS[arg2]
                print(f"📱 识别为设备ID: {arg1}")
                print(f"📊 识别为预设组合: {arg2}")
            # 否则视为设备ID+IP
            else:
                device_id = arg1
                ip = arg2
                print(f"📱 识别为设备ID: {arg1}")
                print(f"🌐 识别为设备IP: {arg2}")
        # 情况3: 三个或更多参数 - 可能是 设备ID+IP+多个指标
        elif len(positional_args) >= 3:
            device_id = positional_args[0]
            ip = positional_args[1]
            # 检查后面的参数是否都是指标
            metric_candidates = positional_args[2:]
            valid_metrics = [m for m in metric_candidates if m in checker.CHECK_METRICS]
            if valid_metrics:
                metrics = valid_metrics
                print(f"📱 识别为设备ID: {device_id}")
                print(f"🌐 识别为设备IP: {ip}")
                print(f"📊 识别为检查指标: {', '.join(valid_metrics)}")
            else:
                print(f"⚠️  后面的参数无法识别为有效指标，只使用设备信息")
                print(f"📱 识别为设备ID: {device_id}")
                print(f"🌐 识别为设备IP: {ip}")
    
    # 优先使用 -m 或 -p 参数指定的指标
    if args.metrics:
        metrics = args.metrics
        print(f"📊 使用指定指标: {', '.join(args.metrics)}")
    elif args.preset:
        metrics = checker.QUICK_CHECK_PRESETS.get(args.preset, ['all'])
        print(f"📊 使用预设组合: {args.preset}")
    
    # 如果还没有指定指标，使用默认指标
    if metrics is None:
        if DEFAULT_METRICS:
            metrics = DEFAULT_METRICS
        else:
            metrics = ['all']
    
    # 检查是否需要进入交互式模式
    if not device_id or not ip:
        print("\n进入交互式配置模式...")
        print("(如果在脚本顶部配置了默认值，直接回车使用默认值)")
        
        # 获取设备ID
        prompt = f"设备ID (默认: {DEFAULT_DEVICE_ID}): " if DEFAULT_DEVICE_ID else "设备ID: "
        device_id_input = input(prompt).strip()
        device_id = device_id_input if device_id_input else DEFAULT_DEVICE_ID
        
        # 获取设备IP
        prompt = f"设备IP (默认: {DEFAULT_IP}): " if DEFAULT_IP else "设备IP: "
        ip_input = input(prompt).strip()
        ip = ip_input if ip_input else DEFAULT_IP
        
        if not device_id or not ip:
            print("\n❌ 设备ID或IP不能为空")
            print_usage_help()
            return
        
        # 如果还没有指定指标，让用户选择
        if metrics == ['all'] or (len(positional_args) > 0 and not positional_args[0] in checker.CHECK_METRICS and not positional_args[0] in checker.QUICK_CHECK_PRESETS):
            print("\n请选择检查方式:")
            print("  1. 使用预设组合")
            print("  2. 自定义选择指标")
            print("  3. 全部检查 (默认)")
            choice = input("\n请选择 (1/2/3, 直接回车默认全部): ").strip()
            
            if choice == '1':
                print("\n可用预设:")
                for preset_name, preset_metrics in checker.QUICK_CHECK_PRESETS.items():
                    print(f"  {preset_name}: {', '.join(preset_metrics)}")
                preset_choice = input("\n请选择预设 (basic/device_info/switch/all): ").strip()
                if preset_choice in checker.QUICK_CHECK_PRESETS:
                    metrics = checker.QUICK_CHECK_PRESETS[preset_choice]
                else:
                    print("⚠️  无效的预设，使用全部检查")
                    metrics = ['all']
            elif choice == '2':
                checker.print_available_metrics()
                print("\n请输入要检查的指标 (多个指标用空格分隔):")
                metrics_input = input().strip()
                if metrics_input:
                    metrics = [m.strip() for m in metrics_input.split()]
                else:
                    metrics = ['all']
            else:
                metrics = ['all']
    
    # 执行检查
    print(f"\n开始检查设备: {device_id} ({ip})")
    print(f"检查指标: {', '.join(metrics)}")
    print(f"{'-'*60}")
    
    checker.check_device_by_metrics(device_id, ip, metrics)


def print_help_info(checker):
    """打印帮助信息"""
    print("\n" + "="*60)
    print("可用检查指标:")
    print("="*60)
    for key, value in sorted(checker.CHECK_METRICS.items()):
        print(f"  {key:<15} - {value}")
    
    print("\n" + "="*60)
    print("预设检查组合:")
    print("="*60)
    for preset_name, preset_metrics in checker.QUICK_CHECK_PRESETS.items():
        print(f"  {preset_name:<15} - {', '.join(preset_metrics)}")
    
    print_usage_help()


def print_usage_help():
    """打印使用说明"""
    print("\n" + "="*60)
    print("使用说明:")
    print("="*60)
    print("  方式0: 在脚本顶部配置默认值（最简单）")
    print("    修改 DEFAULT_DEVICE_ID、DEFAULT_IP、DEFAULT_METRICS")
    print("    然后直接运行: python device_checker.py")
    print()
    print("  方式1: 仅指定检查指标（使用默认设备）")
    print("    python device_checker.py <指标>")
    print("    python device_checker.py <预设>")
    print()
    print("  方式2: 指定设备ID + 检查指标（使用默认IP）")
    print("    python device_checker.py <设备ID> <指标>")
    print("    python device_checker.py <设备ID> <预设>")
    print()
    print("  方式3: 完整指定设备 + 检查指标")
    print("    python device_checker.py <设备ID> <设备IP> <指标1> <指标2> ...")
    print()
    print("  方式4: 使用 -p 参数指定预设")
    print("    python device_checker.py <设备ID> <设备IP> -p basic")
    print("    python device_checker.py <设备ID> <设备IP> -p device_info")
    print("    python device_checker.py <设备ID> <设备IP> -p switch")
    print()
    print("  方式5: 使用 -m 参数指定检查指标")
    print("    python device_checker.py <设备ID> <设备IP> -m mac device_name main_version")
    print()
    print("  方式6: 查看帮助和列表")
    print("    python device_checker.py -l")
    print()
    print("示例:")
    print("  # 仅查询设备名称（使用默认设备）")
    print("  python device_checker.py device_name")
    print()
    print("  # 查询MAC地址和主版本号（使用默认设备）")
    print("  python device_checker.py mac main_version")
    print()
    print("  # 使用设备信息预设（使用默认设备）")
    print("  python device_checker.py device_info")
    print()
    print("  # 指定设备ID和查询指标（使用默认IP）")
    print("  python device_checker.py A3L-A00-A193B device_name")
    print()
    print("  # 完整指定设备信息和查询指标")
    print("  python device_checker.py A7-123456 192.168.1.100 device_name mac")
    print()
    print("  # 使用预设组合")
    print("  python device_checker.py A3L-A00-A193B 192.168.2.95 -p device_info")
    print()
    print("  # 使用 -m 参数指定指标")
    print("  python device_checker.py A8-654321 192.168.1.101 -m mac ota_version system_type")
    print()
    print("  # 查看所有可用选项")
    print("  python device_checker.py -l")
    print("="*60)


if __name__ == "__main__":
    main()
