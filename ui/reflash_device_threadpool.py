from PyQt5.QtCore import QThread, pyqtSignal, QObject, QRunnable, QThreadPool, QTimer
from business.device_monitor_service import DeviceMonitorService
from service.tool_service import ToolService
import time


def run_time(func, *args):
    start = time.perf_counter()
    result = func(*args)
    end = time.perf_counter()
    print(f"耗时: {end - start:.6f} 秒")
    return result


class GetDeviceInfoManager(QObject):
    # 改进1：新增通用类型信号
    taskCompleted = pyqtSignal(dict)
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
                print(f"任务队列已满，丢弃任务 {devices_info}")

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
        try:
            devices = ToolService.get_device_info(self.devices_info, self.pattern)
            # 将获取到的信息返回给主线程
            self.completed_signal.emit(devices)
        except Exception as e:
            # 错误处理建议
            print(f"查询设备 {self.devices_info} 失败: {e}")
            self.completed_signal.emit(None)
