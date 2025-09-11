#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime, timedelta

class DataProcessingService:
    """数据处理服务类，负责解析和处理从设备获取的数据"""
    
    @staticmethod
    def parse_uptime(uptime_str):
        """
        综合解析运行时间字符串
        """
        # 统一处理空格和逗号分隔符
        clean_str = re.sub(r'\s{2,}', ' ', uptime_str).strip()
        
        # 核心正则：捕获当前时间、运行时间、用户段、负载段
        pattern = re.compile(
            r'^(\d{2}:\d{2}:\d{2})\s+up\s+((?:\d+\s+days?,?\s*)?(?:\d+:\d+|\d+\s+min|[\d]+))'
            r'(?:,\s*(\d+)\s+user[s]?\s*)?,\s*load\s*average:\s*([\d.]+,\s*[\d.]+,\s*[\d.]+)$'
        )
        match = pattern.match(clean_str)
        if not match:
            raise ValueError(f"无法解析的uptime格式: {uptime_str}")
        
        current_time_str, uptime_raw, user_count, loads = match.groups()
        
        # 运行时间解析（核心难点）
        if 'day' in uptime_raw:
            days = int(re.search(r'(\d+)\s+days?', uptime_raw).group(1))
            time_part = re.search(r'(\d+:\d+|\d+\s+min)$', uptime_raw)
            if time_part:
                part = time_part.group(1)
                if 'min' in part:
                    minutes = int(re.search(r'(\d+)', part).group(1))
                    delta = timedelta(days=days, minutes=minutes)
                else:
                    h, m = map(int, part.split(':'))
                    delta = timedelta(days=days, hours=h, minutes=m)
            else:
                delta = timedelta(days=days)
        elif 'min' in uptime_raw:
            minutes = int(re.search(r'(\d+)', uptime_raw).group(1))
            delta = timedelta(minutes=minutes)
        elif ':' in uptime_raw:
            h, m = map(int, uptime_raw.split(':'))
            delta = timedelta(hours=h, minutes=m)
        else:
            # 处理纯数字分钟数（如"up 45"）
            minutes = int(uptime_raw)
            delta = timedelta(minutes=minutes)
        
        
        # 构建格式化的带单位时间字符串
        formatted_uptime = ""
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        if days > 0:
            formatted_uptime += f"{days}天"
        if hours > 0:
            formatted_uptime += f"{hours}时"
        if minutes >= 0:  # 包括0分钟的情况
            formatted_uptime += f"{minutes}分"
        
        # 如果没有时间信息，则默认为0秒
        if not formatted_uptime:
            formatted_uptime = "0秒"
        
        return {
            'current_time': current_time_str,
            'uptime': str(delta),
            'user_count': int(user_count) if user_count else 0,
            'load_1min': float(loads.split(',')[0]),
            'load_5min': float(loads.split(',')[1]),
            'load_15min': float(loads.split(',')[2]),
            'formatted_uptime': formatted_uptime
        }
    
    @staticmethod
    def process_time_difference(initial_time_diff, current_time_diff, threshold=3):
        """
        处理设备时间差异数据，生成结构化错误信息
        
        参数:
        initial_time_diff: 初始时间差（秒）
        current_time_diff: 当前时间差（秒）
        threshold: 时间差异常阈值（秒）
        
        返回:
        结构化的错误信息字典
        """
        # 计算日均误差（假设数据收集周期为1天）
        daily_average = abs(current_time_diff - initial_time_diff) / 6  # 假设6天收集周期
        
        # 判断是否超过阈值
        is_abnormal = abs(current_time_diff) > threshold or daily_average > threshold / 6
        
        if not is_abnormal:
            return None
        
        # 生成结构化错误信息
        error_info = {
            'type': '时间同步异常',
            'process': f'初始时间差: {initial_time_diff}秒, 当前时间差: {current_time_diff}秒',
            'difference': f'日均{daily_average:.2f}秒'
        }
        
        return error_info
    
    @staticmethod
    def process_boot_count(last_count, current_count, threshold=5):
        """
        处理设备启动次数数据，生成结构化错误信息
        
        参数:
        last_count: 上次启动次数
        current_count: 当前启动次数
        threshold: 异常启动次数阈值
        
        返回:
        结构化的错误信息字典
        """
        # 计算启动次数变化
        count_diff = current_count - last_count
        
        # 判断是否异常（启动次数过多或减少）
        is_abnormal = count_diff > threshold or count_diff < 0
        
        if not is_abnormal:
            return None
        
        # 生成结构化错误信息
        error_info = {
            'type': '启动次数异常',
            'process': f'上次启动次数: {last_count}, 当前启动次数: {current_count}',
            'difference': f'启动次数变化: {count_diff}'
        }
        
        return error_info
    
    @staticmethod
    def format_error_message(device_id, ip, error_type, error_details):
        """格式化错误消息，使其更易读"""
        # 设置默认值和清理输入
        device_id = device_id if device_id and device_id != '通用' else '未知设备'
        ip = ip if ip and ip != 'N/A' else '未知IP'
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 构建消息头部
        lines = []
        lines.append("="*50)
        lines.append(f"错误报告 - {current_time}")
        lines.append("-"*50)
        lines.append(f"设备信息: {device_id} ({ip})")
        lines.append(f"错误类型: {error_type}")
        lines.append("\n错误详情:")

        # 处理错误详情
        if isinstance(error_details, list):
            for i, detail in enumerate(error_details, 1):
                lines.append(f"\n错误 {i}:")
                lines.extend(DataProcessingService._format_error_detail(detail))
        else:
            lines.extend(DataProcessingService._format_error_detail(error_details))
        
        lines.append("="*50)
        return "\n".join(lines)

    @staticmethod
    def _format_error_detail(detail):
        """格式化单个错误详情"""
        lines = []
        if isinstance(detail, dict):
            err_type = detail.get('type', '')
            if err_type:
                lines.append(f"  类型: {err_type}")
            
            process = detail.get('process', '')
            if process:
                # 移除重复的设备信息
                process = re.sub(r'设备ID[:：]\s*[^,，\s]+\s*[,，]?\s*IP[:：]?\s*[^,，\s]+\s*[,，]?\s*', '', process)
                lines.append(f"  过程: {process}")
            
            difference = detail.get('difference', '')
            if difference:
                # 清理并格式化差异信息
                difference = difference.replace('发现错误:', '').strip()
                lines.append(f"  差异: {difference}")
        else:
            # 处理字符串类型的错误详情
            lines.append(f"  详情: {str(detail)}")
        return lines

    @staticmethod
    def extract_device_info(message):
        """
        增强从错误消息中提取设备ID和IP地址的功能
        """
        # 尝试多种格式匹配
        patterns = [
            # 格式1: 设备 A5L-00-A7959 (192.168.1.43)
            (r'设备\s+([A-Z0-9-]+)\s+\(([^)]+)\)', lambda m: (m.group(1), m.group(2))),
            # 格式2: 设备ID: A5L-00-A7959, IP: 192.168.1.43
            (r'设备ID[:：]\s*([^,，\s]+).*?IP[:：][地址]?\s*([^,，\s]+)', lambda m: (m.group(1), m.group(2))),
            # 格式3: [A5L-00-A7959] IP地址: 192.168.1.43
            (r'\[([A-Z0-9-]+)\].*?IP[地址]?[:：]\s*([^,，\s]+)', lambda m: (m.group(1), m.group(2))),
            # 格式4: 设备 A5L-00-A7959 (ip: 192.168.1.43)
            (r'设备\s+([A-Z0-9-]+)\s+\(?ip[:：]?\s*([^)]+)\)?', lambda m: (m.group(1), m.group(2)))
        ]
        
        for pattern, extractor in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                device_id, ip = extractor(match)
                return device_id.strip(), ip.strip()
        
        # 如果无法提取，返回更有意义的默认值
        return "未知设备", "未知IP"