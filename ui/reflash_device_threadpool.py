from PySide6.QtCore import QThread, Signal, QObject, QRunnable, QThreadPool, QTimer
from business.device_monitor_service import DeviceMonitorService
from service import device_cache
from service.tool_service import ToolService
import time
import os
from config import (
    supported_dev_types, get_base_dir,
    PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_RECV_TIMEOUT,
)
from service.logging_service import get_logger

logger = get_logger(__name__)

# 单台设备信息补全的重试策略：「短超时首试 + 长超时兜底」。
# 找卡阶段已经确认设备在线，首试绝大多数能成功；首试失败才用更长的超时兜底，
# 既避免不可达设备把线程拖住（旧逻辑固定 3 次 × 3s ≈ 9.2s），又保住成功率。
_INFO_ATTEMPTS = (
    (PROTOCOL_CONNECT_TIMEOUT, PROTOCOL_RECV_TIMEOUT),                        # 首试 1.5s / 1.5s
    (PROTOCOL_CONNECT_TIMEOUT + 1.0, PROTOCOL_RECV_TIMEOUT + 1.0),            # 兜底 2.5s / 2.5s
)


def _split_device_line(device_stdout):
    """从 ``"<device_id> <ip> ..."`` 行里取设备 ID 与 IP（不合规返回空串）。"""
    parts = (device_stdout or "").split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", ""


def build_cached_payload(device_stdout):
    """缓存命中则返回可直接上表的完整字典，否则 ``None``。

    在主线程**提交任务时**调用（而不是等线程空闲），这样几十台设备无论线程池
    是否排满，已知设备都能立刻出信息，不必跟在真实查询后面排队。
    """
    device_id, ip = _split_device_line(device_stdout)
    if not device_id:
        return None
    cached = device_cache.get_cached(device_id, ip)
    if not cached:
        return None
    payload = dict(cached)
    payload.setdefault("id", device_id)
    payload.setdefault("ip", ip)
    payload.setdefault("password", ToolService.get_password(device_id))
    return payload


def run_time(func, *args):
    start = time.perf_counter()
    result = func(*args)
    end = time.perf_counter()
    logger.debug("耗时: %.6f 秒", end - start)
    return result


class GetDeviceInfoManager(QObject):
    # 改进1：新增通用类型信号
    taskCompleted = Signal(object)
    # 改进2：新增全局完成信号
    allTasksCompleted = Signal()
    # 内部：单个任务**线程真正结束**后回报（用于即时补位 + 精确的忙闲判定）
    taskFinished = Signal()

    def __init__(self, pattern, max_workers=4, queue_size=50):
        super().__init__()
        # **独立线程池**（不用 QThreadPool.globalInstance()）：
        # 全局池被进程内其它组件共享，关窗时无法安全地等待它排空，
        # 而且 setMaxThreadCount 会污染全局设置。
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max_workers)
        self.task_queue = []
        self.queue_size = queue_size
        self.check_timer = QTimer(self)      # 挂父对象，随 manager 一起回收
        self.check_timer.timeout.connect(self._check_queue)
        self.check_timer.start(100)
        self.pattern = pattern
        self._stopped = False
        # 在飞任务数（主线程读写）：QThreadPool.activeThreadCount() 在任务刚 start
        # 时可能还没计入，用它避免「刚提交就误判空闲 → 提前收尾」的竞态
        self._inflight = 0
        # 「全部完成」只在**忙 → 闲**跳变时发一次（旧实现空闲期每 100ms 重复 emit）
        self._idle_emitted = True
        # 任务结束立即补位（信号跨线程 → 排队回主线程执行），不用等 100ms 定时器；
        # 定时器保留为兜底（如任务被 pool.clear() 丢弃时）。
        self.taskFinished.connect(self._on_task_finished)

    def stop(self, timeout_ms=5000):
        """停止提交并**等待正在跑的任务结束**，再允许销毁本对象。

        不做这一步时：QRunnable 仍在后台线程里，
        而窗口关闭后 manager 已被释放 → 在已删除的 QObject 上 emit → 进程级崩溃
        （Windows 上表现为 ``0xC0000005`` access violation）。
        """
        self._stopped = True
        try:
            self.check_timer.stop()
        except RuntimeError:                 # QObject 已被销毁
            return False
        self.task_queue.clear()
        self.pool.clear()                    # 丢弃尚未开始的任务
        return self.pool.waitForDone(timeout_ms)

    def has_pending(self):
        """是否还有排队或在飞的任务（供调用方判断能否立即收尾）。"""
        return bool(self.task_queue) or self._inflight > 0

    def submit_task(self, devices_info):
        if self._stopped:
            return
        self._idle_emitted = False           # 有任务进来即视为「忙」
        # 缓存命中：**提交这一刻**就把已知信息发给 UI（毫秒级出首屏），
        # 不占用线程池、也不用排在真实查询后面等空闲线程。
        cached_payload = build_cached_payload(devices_info)
        if cached_payload:
            self._emit_result(cached_payload)
        if self.pool.activeThreadCount() < self.pool.maxThreadCount():
            self._execute_task(devices_info, self.pattern,
                               cache_hit=bool(cached_payload))
        else:
            if len(self.task_queue) < self.queue_size:
                self.task_queue.append((devices_info, bool(cached_payload)))
            else:
                logger.warning("任务队列已满，丢弃任务 %s", devices_info)
        # 有空闲线程就**立刻**派发，不再等下一个 100ms 定时器 tick
        self._check_queue()

    def _emit_result(self, payload):
        """后台线程回调：已停止则丢弃结果，绝不在半销毁状态下 emit。"""
        if self._stopped:
            return
        try:
            self.taskCompleted.emit(payload)
        except RuntimeError:                 # QObject 已销毁
            pass

    def _execute_task(self, devices_info, pattern, cache_hit=False):
        self._inflight += 1
        runnable = QRunnableWrapper(
            devices_info, pattern, self._emit_result, self._notify_finished,
            cache_hit=cache_hit)
        self.pool.start(runnable)

    def _notify_finished(self):
        """后台线程：任务 run() 已结束（在 finally 里调用），排队回主线程。"""
        if self._stopped:
            return
        try:
            self.taskFinished.emit()
        except RuntimeError:
            pass

    def _on_task_finished(self):
        """单个任务收尾：立即把队列里的下一台补位（免去 100ms 定时器空等）。"""
        if self._inflight > 0:
            self._inflight -= 1
        self._check_queue()

    def _check_queue(self):
        if self._stopped:
            return
        while self.pool.activeThreadCount() < self.pool.maxThreadCount() and self.task_queue:
            devices_info, cache_hit = self.task_queue.pop(0)
            self._execute_task(devices_info, self.pattern, cache_hit=cache_hit)

        # 只在「忙 → 闲」那一刻发一次全部完成（旧实现空闲期每 100ms 重复发）
        if self.task_queue or self._inflight:
            self._idle_emitted = False
            return
        if self._idle_emitted:
            return
        self._idle_emitted = True
        try:
            self.allTasksCompleted.emit()
        except RuntimeError:
            pass


class QRunnableWrapper(QRunnable):
    def __init__(self, devices_info, pattern, emit_result, notify_finished=None,
                 cache_hit=False):
        super().__init__()
        # 持有 manager 的**绑定方法**（而非裸信号）：既能在停止后短路，
        # 也保证 manager 的 Python 对象在任务跑完前不会被回收。
        self.emit_result = emit_result
        self.notify_finished = notify_finished
        self.devices_info = devices_info
        self.pattern = pattern
        # 提交时已命中缓存并上表：真实查询失败时保留缓存行，不再 emit None
        self.cache_hit = cache_hit

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            logger.exception("查询设备 %s 失败: %s", self.devices_info, e)
            if not self.cache_hit:
                self.emit_result(None)
        finally:
            if self.notify_finished is not None:
                self.notify_finished()

    def _run_impl(self):
        """真实查询并校正/回写缓存（缓存已在 ``submit_task`` 时先出过一次）。

        - 查询成功：emit 新结果（覆盖缓存行）并回写缓存；
        - 查询失败但有缓存：保留缓存行，**不** emit None（否则会把行打回「查询中…」）；
        - 查询失败且无缓存：emit None（与原行为一致）。

        重试采用「短超时首试 + 长超时兜底」两档，去掉旧实现的固定 3 次 + 0.1s sleep。
        """
        device_id, ip = _split_device_line(self.devices_info)
        devices = None
        for attempt, (connect_timeout, recv_timeout) in enumerate(_INFO_ATTEMPTS, start=1):
            try:
                devices = ToolService.get_device_info(
                    self.devices_info, self.pattern,
                    connect_timeout=connect_timeout, recv_timeout=recv_timeout)
            except Exception as inner_e:     # pylint: disable=broad-except
                logger.warning("查询设备 %s 第 %s 次尝试失败: %s",
                               self.devices_info, attempt, inner_e)
                devices = None
            if devices:
                break
            if attempt < len(_INFO_ATTEMPTS):
                logger.info("设备 %s 首试未取到，使用长超时兜底重试", self.devices_info)

        if devices:
            device_cache.put_cached(device_id, ip, devices)
            self.emit_result(devices)
        elif not self.cache_hit:
            self.emit_result(None)


class GetDeviceListThread(QThread):
    """异步获取设备列表的线程类，避免主线程阻塞"""
    
    progress_signal = Signal(str)
    raw_list_signal = Signal(list)
    error_signal = Signal(str)
    finished_signal = Signal()
    
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
