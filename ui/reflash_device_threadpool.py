from PyQt5.QtCore import QThread, pyqtSignal, QObject, QRunnable, QThreadPool, QTimer
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService
import time
import os
from config import supported_dev_types, get_base_dir
from service.logging_service import get_logger

logger = get_logger(__name__)


def run_time(func, *args):
    start = time.perf_counter()
    result = func(*args)
    end = time.perf_counter()
    logger.debug("耗时: %.6f 秒", end - start)
    return result


class GetDeviceInfoManager(QObject):
    # 改进1：新增通用类型信号
    taskCompleted = pyqtSignal(object)
    # 改进2：新增全局完成信号
    allTasksCompleted = pyqtSignal()

    def __init__(self, pattern, max_workers=4, queue_size=50):
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max_workers)
        self.task_queue = []
        self.queue_size = queue_size
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self._check_queue)
        self.check_timer.start(100)
        self.pattern = pattern

    def submit_task(self, devices_info):
        if self.pool.activeThreadCount() < self.pool.maxThreadCount():
            self._execute_task(devices_info, self.pattern)
        else:
            if len(self.task_queue) < self.queue_size:
                self.task_queue.append(devices_info)
            else:
                logger.warning("任务队列已满，丢弃任务 %s", devices_info)

    def _execute_task(self, devices_info, pattern):
        # print(f"查询设备{devices_info}")
        runnable = QRunnableWrapper(devices_info, pattern, self.taskCompleted)
        self.pool.start(runnable)

    def _check_queue(self):
        while self.pool.activeThreadCount() < self.pool.maxThreadCount() and self.task_queue:
            devices_info = self.task_queue.pop(0)
            self._execute_task(devices_info, self.pattern)

        # 改进3：新增队列状态检测
        if not self.task_queue and self.pool.activeThreadCount() == 0:
            self.allTasksCompleted.emit()


class QRunnableWrapper(QRunnable):
    def __init__(self, devices_info, pattern, completed_signal):
        super().__init__()
        self.completed_signal = completed_signal
        self.devices_info = devices_info
        self.pattern = pattern

    def run(self):
        devices = None
        try:
            """增加重试机制"""
            for i in range(3):
                try:
                    devices = ToolService.get_device_info(self.devices_info, self.pattern)
                    # print(f"查询设备 {self.devices_info} 第 {i+1} 次结果: {devices}")
                    if devices and devices.get("mac_address") and devices["mac_address"] != "未知":
                        break
                except Exception as inner_e:
                    logger.warning("查询设备 %s 第 %s 次尝试失败: %s", self.devices_info, i + 1, inner_e)
                
                if i < 2:
                    time.sleep(0.1)

            # 将获取到的信息返回给主线程
            if devices:
                self.completed_signal.emit(devices)
            else:
                self.completed_signal.emit(None)
        except Exception as e:
            logger.exception("查询设备 %s 失败: %s", self.devices_info, e)
            self.completed_signal.emit(None)


class GetDeviceListThread(QThread):
    """异步获取设备列表的线程类，避免主线程阻塞"""
    
    progress_signal = pyqtSignal(str)
    raw_list_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    
    def __init__(self, dev_type, tools_dir, timeout=60):
        super().__init__()
        self.dev_type = dev_type
        self.tools_dir = tools_dir
        self.timeout = timeout
        self._should_stop = False
    
    def stop(self):
        self._should_stop = True
    
    def run(self):
        try:
            self.progress_signal.emit("正在扫描设备...")
            
            device_id_exe = os.path.join(self.tools_dir, 'DeviceId.exe')
            
            self.progress_signal.emit(f"执行 DeviceId.exe (超时: {self.timeout}秒)...")
            
            stdout, stderr, returncode = ToolService.run_command(
                device_id_exe, 
                timeout=self.timeout
            )
            
            if self._should_stop:
                return
            
            if returncode == -2:
                error_msg = f"DeviceId.exe 执行超时（{self.timeout}秒）"
                self.error_signal.emit(error_msg)
                return
            
            if stderr:
                error_msg = f"DeviceId.exe 错误: {stderr}"
                self.error_signal.emit(error_msg)
                return
            
            if returncode != 0 and returncode != -2:
                error_msg = f"DeviceId.exe 返回错误代码: {returncode}"
                self.error_signal.emit(error_msg)
                return
            
            if not stdout.strip():
                self.progress_signal.emit("未发现设备")
                self.raw_list_signal.emit([])
                return
            
            lines = stdout.split('\n')
            pattern = self.dev_type.replace('-', '|')
            
            filtered_lines = []
            total_lines = len(lines)
            
            for i, line in enumerate(lines):
                if self._should_stop:
                    return
                
                line = line.strip()
                if not line:
                    continue
                
                if i % 10 == 0:
                    self.progress_signal.emit(f"解析设备列表... ({i+1}/{total_lines})")
                
                if line.split("-")[0] in supported_dev_types:
                    if __import__('re').match(f"^({pattern})", line):
                        filtered_lines.append(line)
            
            self.progress_signal.emit(f"发现 {len(filtered_lines)} 台设备")
            self.raw_list_signal.emit(filtered_lines)
            
        except Exception as e:
            error_msg = f"获取设备列表时出错: {str(e)}"
            self.error_signal.emit(error_msg)
            logger.exception("获取设备列表时出错")
        finally:
            self.finished_signal.emit()
