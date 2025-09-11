#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from datetime import datetime
from config import device_data_file, error_log_file

class FileService:
    """文件服务类，负责文件读写和日志记录"""
    
    @staticmethod
    def init_log_files(base_dir):
        """初始化所有日志文件"""
        # 确保基础目录存在
        os.makedirs(base_dir, exist_ok=True)
        
        # 初始化设备监控数据文件所在目录
        with open(device_data_file, 'w') as f:
            json.dump({}, f)
        
        # 初始化错误日志文件
        with open(error_log_file, 'w') as f:
            f.write("")
        
        # 初始化运行时间日志文件
        with open(f'{base_dir}/uptime.log', 'w', encoding='utf-8') as f:
            f.write("")
        
        # 初始化设备时间日志文件
        with open(f'{base_dir}/cardtime.log', 'w', encoding='utf-8') as f:
            f.write("")
        
        # 初始化启动次数日志文件
        with open(f'{base_dir}/startcount.log', 'w', encoding='utf-8') as f:
            f.write("")
        
        # 初始化综合日志文件
        with open(f'{base_dir}/comprehensive.log', 'w', encoding='utf-8') as f:
            f.write("")
    
    @staticmethod
    def write_comprehensive_log(ip, password, device_id, base_dir, formatted_uptime, formatted_remote_time, time_diff, start_count):
        """
        输出一份综合的日志
        """
        # 确保基础目录存在
        os.makedirs(base_dir, exist_ok=True)
        
        # 获取当前系统时间
        os_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建综合日志条目
        log_entry = f"{os_time},{device_id},{ip},{password},{formatted_uptime},{formatted_remote_time},{time_diff}s,{start_count}\n"
        
        # 写入综合日志文件
        with open(f'{base_dir}/comprehensive.log', 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    @staticmethod
    def write_error_log(error_info):
        """写入错误日志，接受结构化错误信息字典"""
        try:
            # 确保文件以UTF-8编码写入，解决中文显示问题
            with open(error_log_file, 'a', encoding='utf-8') as f:
                # 写入分隔线和基本信息
                f.write(f"\n{'='*50}\n")
                f.write(f"时间: {error_info.get('时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}\n")
                f.write(f"设备ID: {error_info.get('设备ID', '未知设备')}\n")
                f.write(f"IP地址: {error_info.get('IP地址', 'N/A')}\n")
                f.write(f"错误类型: {error_info.get('错误类型', '未知错误类型')}\n")
                f.write("错误详情:\n")
                
                # 处理错误详情
                error_details = error_info.get('错误详情', '')
                
                # 如果错误详情为空，尝试从原始错误消息中提取
                if not error_details and '原始错误消息' in error_info:
                    error_details = error_info['原始错误消息']
                
                if isinstance(error_details, list):
                    for error in error_details:
                        if isinstance(error, dict):
                            # 获取错误类型、过程和差异信息
                            err_type = error.get('type', '未知')
                            process = error.get('process', '').strip()
                            difference = error.get('difference', '').strip()
                            
                            # 优化输出格式，使阅读更流畅
                            f.write(f"- 类型: {err_type}\n")
                            
                            # 只有当过程信息有意义时才写入
                            if process and process != 'N/A' and process != '':
                                f.write(f"  过程: {process}\n")
                            
                            # 只有当差异信息有意义时才写入，并且优化语言表达
                            if difference and difference != 'N/A' and difference != '':
                                # 改进差异描述的语言表达
                                if '发现错误' in difference:
                                    # 使用正则表达式清理各种格式的设备ID和IP信息
                                    import re
                                    # 匹配格式1: 设备ID: XXX, IP: YYY 发现错误:
                                    pattern1 = r'设备ID: [^,]+, IP: [^ ]+ '  # 保留发现错误部分
                                    difference = re.sub(pattern1, '', difference)
                                    
                                    # 匹配格式2: 设备 XXX (YYY) 发现错误:
                                    pattern2 = r'设备 [^ (]+ \([^)]+\) '  # 保留发现错误部分
                                    difference = re.sub(pattern2, '', difference)
                                    
                                    # 匹配格式3: 设备 XXX 发现错误:
                                    pattern3 = r'设备 [^ ]+ '  # 保留发现错误部分
                                    difference = re.sub(pattern3, '', difference)
                                f.write(f"  差异: {difference}\n")
                        else:
                            # 非字典格式的错误，直接写入并确保格式一致
                            error_str = str(error).strip()
                            if error_str:
                                f.write(f"- {error_str}\n")
                elif isinstance(error_details, dict):
                    # 获取错误类型、过程和差异信息
                    err_type = error_details.get('type', '未知')
                    process = error_details.get('process', '').strip()
                    difference = error_details.get('difference', '').strip()
                    
                    # 优化输出格式
                    f.write(f"- 类型: {err_type}\n")
                    if process and process != 'N/A' and process != '':
                        f.write(f"  过程: {process}\n")
                    if difference and difference != 'N/A' and difference != '':
                        # 改进差异描述的语言表达
                        if '发现错误' in difference:
                            # 使用正则表达式清理各种格式的设备ID和IP信息
                            import re
                            # 匹配格式1: 设备ID: XXX, IP: YYY 发现错误:
                            pattern1 = r'设备ID: [^,]+, IP: [^ ]+ '  # 保留发现错误部分
                            difference = re.sub(pattern1, '', difference)
                            
                            # 匹配格式2: 设备 XXX (YYY) 发现错误:
                            pattern2 = r'设备 [^ (]+ \([^)]+\) '  # 保留发现错误部分
                            difference = re.sub(pattern2, '', difference)
                            
                            # 匹配格式3: 设备 XXX 发现错误:
                            pattern3 = r'设备 [^ ]+ '  # 保留发现错误部分
                            difference = re.sub(pattern3, '', difference)
                        f.write(f"  差异: {difference}\n")
                else:
                    # 处理简单文本错误信息
                    error_text = str(error_details)
                    # 如果是简单错误信息，添加更清晰的格式
                    if "- 类型:" not in error_text:
                        # 优化错误文本的显示，确保语言流畅
                        # 将多个连续换行符替换为单个换行符
                        import re
                        error_text = re.sub(r'\n{2,}', '\n', error_text)
                        # 确保每行都以适当的格式开始
                        lines = error_text.split('\n')
                        formatted_lines = []
                        for line in lines:
                            line = line.strip()
                            if line:
                                if not line.startswith('- '):
                                    formatted_lines.append(f"- {line}")
                                else:
                                    formatted_lines.append(line)
                        error_text = '\n'.join(formatted_lines)
                    f.write(error_text + '\n')
                
                f.write(f"{'='*50}\n")
        except Exception as e:
            # 如果写入日志时出错，将错误信息打印到控制台
            print(f"写入错误日志失败: {str(e)}")
            # 尝试使用更简单的方式写入错误信息
            try:
                with open(error_log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*50}\n")
                    f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("设备ID: 未知设备\n")
                    f.write("IP地址: N/A\n")
                    f.write("错误类型: 日志记录异常\n")
                    f.write(f"错误详情: 写入日志失败: {str(e)}\n")
                    f.write(f"{'='*50}\n")
            except:
                pass
    
    @staticmethod
    def load_device_data():
        """加载设备历史数据"""
        try:
            with open(device_data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    @staticmethod
    def save_device_data(device_data):
        """保存设备数据"""
        with open(device_data_file, 'w', encoding='utf-8') as f:
            json.dump(device_data, f, indent=2, ensure_ascii=False, sort_keys=True)