from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QSpinBox, QCheckBox, QFileDialog, QLineEdit
)
from PyQt5.QtCore import pyqtSignal
from config import default_dev_type, supported_dev_types


class ControlPanel(QWidget):
    """控制面板类，负责顶部控制面板的功能"""
    # 定义信号
    refresh_clicked = pyqtSignal()
    dev_type_changed = pyqtSignal(str)
    manual_find_clicked = pyqtSignal(str)
    enable_adb_clicked = pyqtSignal()
    clear_history_clicked = pyqtSignal()
    start_monitor_clicked = pyqtSignal(int, bool, bool, bool, bool, str)
    stop_monitor_clicked = pyqtSignal()
    query_selected_clicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dev_type = default_dev_type
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        control_layout = QVBoxLayout(self)
        
        # 第一行：设备类型选择、刷新按钮和刷新状态显示
        self.create_top_row(control_layout)
        
        # 第二行：监控控制
        self.create_monitor_control(control_layout)
        
        # 第三行和第四行：查询/控制（两排按钮）
        self.create_query_control(control_layout)
        
        control_layout.setContentsMargins(5, 5, 5, 5)
        
    def create_top_row(self, parent_layout):
        """创建顶部行布局"""
        top_row_layout = QHBoxLayout()
        
        self.dev_type_label = QLabel("设备类型:")
        self.dev_type_combo = QComboBox()
        self.dev_type_combo.setEditable(True)  # 设置为可编辑，允许手动输入
        self.dev_type_combo.setMinimumWidth(150)  # 增加下拉框宽度
        for dev_type in supported_dev_types:
            self.dev_type_combo.addItem(dev_type)
        self.dev_type_combo.setCurrentText(self.dev_type)
        self.dev_type_combo.currentTextChanged.connect(self.on_dev_type_changed)
        
        self.refresh_button = QPushButton("刷新设备列表")
        self.refresh_button.clicked.connect(self.refresh_clicked.emit)
        
        # 手动找卡：输入 单IP / 区间 / CIDR（如 192.168.1.10 或 192.168.1.1-192.168.1.50）
        self.manual_targets_label = QLabel("手动找卡:")
        self.manual_targets_edit = QLineEdit()
        self.manual_targets_edit.setPlaceholderText("IP / 区间 / CIDR，如 192.168.1.10")
        self.manual_targets_edit.setMinimumWidth(200)
        self.manual_targets_edit.returnPressed.connect(self.on_manual_find_clicked)
        self.manual_find_button = QPushButton("手动找卡")
        self.manual_find_button.clicked.connect(self.on_manual_find_clicked)
        
        # 添加刷新状态显示标签
        self.refresh_status_label = QLabel("就绪")
        self.refresh_status_label.setStyleSheet("color: green;")
        self.refresh_status_label.setMinimumWidth(200)
        
        top_row_layout.addWidget(self.dev_type_label)
        top_row_layout.addWidget(self.dev_type_combo)
        top_row_layout.addWidget(self.refresh_button)
        top_row_layout.addWidget(self.manual_targets_label)
        top_row_layout.addWidget(self.manual_targets_edit)
        top_row_layout.addWidget(self.manual_find_button)
        top_row_layout.addWidget(self.refresh_status_label)
        top_row_layout.addStretch()
        
        parent_layout.addLayout(top_row_layout)
        
    def create_monitor_control(self, parent_layout):
        """创建监控控制区域"""
        self.monitor_group = QGroupBox("监控控制")
        monitor_layout = QHBoxLayout(self.monitor_group)
        
        self.start_monitor_button = QPushButton("开始监控")
        self.start_monitor_button.clicked.connect(self.on_start_monitor_clicked)
        
        self.stop_monitor_button = QPushButton("停止监控")
        self.stop_monitor_button.clicked.connect(self.stop_monitor_clicked.emit)
        self.stop_monitor_button.setEnabled(False)
        
        self.delay_label = QLabel("查询间隔(秒):")
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(10, 10000)  # 增加范围到10-100000秒
        self.delay_spin.setValue(60)
        self.delay_spin.setMinimumWidth(100)  # 增加输入框宽度
        # 添加值验证
        self.delay_spin.valueChanged.connect(self.validate_delay_input)
        
        # 添加监控选项
        self.monitor_time_check = QCheckBox("监控设备时间")
        self.monitor_time_check.setChecked(True)
        self.monitor_boot_check = QCheckBox("监控启动时间")
        self.monitor_boot_check.setChecked(True)
        self.monitor_start_count_check = QCheckBox("监控播放器启动次数")
        self.monitor_start_count_check.setChecked(True)
        self.monitor_screenshot_check = QCheckBox("获取运行画面")
        self.monitor_screenshot_check.setChecked(True)

        # 添加截图存储位置自定义按钮
        self.screenshot_path_button = QPushButton("截图存储位置")
        self.screenshot_path_button.clicked.connect(self.on_screenshot_path_clicked)
        self.screenshot_path = "./output/screenshot"  # 默认路径


        monitor_layout.addWidget(self.start_monitor_button)
        monitor_layout.addWidget(self.stop_monitor_button)
        monitor_layout.addWidget(self.delay_label)
        monitor_layout.addWidget(self.delay_spin)
        monitor_layout.addSpacing(20)
        monitor_layout.addWidget(self.monitor_time_check)
        monitor_layout.addWidget(self.monitor_boot_check)
        monitor_layout.addWidget(self.monitor_start_count_check)
        monitor_layout.addWidget(self.monitor_screenshot_check)
        monitor_layout.addWidget(self.screenshot_path_button)
        monitor_layout.addStretch()
        
        parent_layout.addWidget(self.monitor_group)
        
    def create_query_control(self, parent_layout):
        """创建查询控制区域 - 分为两排按钮"""
        self.query_group = QGroupBox("查询/控制")
        query_layout = QVBoxLayout(self.query_group)
        
        # 第一排按钮
        first_row_layout = QHBoxLayout()
        
        self.query_all_button = QPushButton("查询全部信息")
        self.query_all_button.clicked.connect(lambda: self.query_selected_clicked.emit("all"))
        
        self.query_time_button = QPushButton("设备时间")
        self.query_time_button.clicked.connect(lambda: self.query_selected_clicked.emit("time"))
        
        self.query_boot_button = QPushButton("启动时间")
        self.query_boot_button.clicked.connect(lambda: self.query_selected_clicked.emit("boot_time"))
        
        self.query_start_count_button = QPushButton("播放器启动次数")
        self.query_start_count_button.clicked.connect(lambda: self.query_selected_clicked.emit("start_count"))
        
        self.query_sum_switch_button = QPushButton("开关机次数")
        self.query_sum_switch_button.clicked.connect(lambda: self.query_selected_clicked.emit("sum_switch"))
        
        first_row_layout.addWidget(self.query_all_button)
        first_row_layout.addWidget(self.query_time_button)
        first_row_layout.addWidget(self.query_boot_button)
        first_row_layout.addWidget(self.query_start_count_button)
        first_row_layout.addWidget(self.query_sum_switch_button)
        first_row_layout.addStretch()
        
        query_layout.addLayout(first_row_layout)
        
        # 第二排按钮
        second_row_layout = QHBoxLayout()
        
        self.query_set_time_button = QPushButton("校时")
        self.query_set_time_button.clicked.connect(lambda: self.query_selected_clicked.emit("check_time"))
        
        self.query_screenshot_button = QPushButton("截图")
        self.query_screenshot_button.clicked.connect(lambda: self.query_selected_clicked.emit("screenshot"))
        
        self.query_upgrade_program_button = QPushButton("发送节目")
        self.query_upgrade_program_button.clicked.connect(lambda: self.query_selected_clicked.emit("upgrade_program"))
        
        self.query_count_init_button = QPushButton("开关机初始化")
        self.query_count_init_button.clicked.connect(lambda: self.query_selected_clicked.emit("count_init"))
        
        self.query_output_log_button = QPushButton("导出开关机日志")
        self.query_output_log_button.clicked.connect(lambda: self.query_selected_clicked.emit("output_log"))
        
        self.query_clean_switch_button = QPushButton("清空开关机次数")
        self.query_clean_switch_button.clicked.connect(lambda: self.query_selected_clicked.emit("clean_switch"))

        # 清理历史数据（控制类操作：选择范围 → 预览 → 后台执行）
        self.clear_history_button = QPushButton("清理历史数据")
        self.clear_history_button.clicked.connect(self.clear_history_clicked.emit)
        
        # 协议下发 Set Development 开启 ADB（仅 Android 设备）
        self.enable_adb_button = QPushButton("开启ADB")
        self.enable_adb_button.clicked.connect(self.enable_adb_clicked.emit)
        
        second_row_layout.addWidget(self.query_set_time_button)
        second_row_layout.addWidget(self.query_screenshot_button)
        second_row_layout.addWidget(self.query_upgrade_program_button)
        second_row_layout.addWidget(self.query_count_init_button)
        second_row_layout.addWidget(self.query_output_log_button)
        second_row_layout.addWidget(self.query_clean_switch_button)
        second_row_layout.addWidget(self.clear_history_button)
        second_row_layout.addWidget(self.enable_adb_button)
        second_row_layout.addStretch()
        
        query_layout.addLayout(second_row_layout)
        
        parent_layout.addWidget(self.query_group)
        
    def on_dev_type_changed(self, text):
        """设备类型改变时的处理"""
        self.dev_type = text
        self.dev_type_changed.emit(text)
        
    def on_manual_find_clicked(self):
        """手动找卡按钮/回车事件：把输入的目标下发给上层。"""
        targets = self.manual_targets_edit.text().strip()
        if not targets:
            self.update_refresh_status("请输入手动找卡目标（IP / 区间 / CIDR）", is_warning=True)
            return
        self.manual_find_clicked.emit(targets)
        
    def on_start_monitor_clicked(self):
        """开始监控按钮点击事件"""
        delay_time = self.delay_spin.value()
        monitor_time = self.monitor_time_check.isChecked()
        monitor_boot = self.monitor_boot_check.isChecked()
        monitor_start_count = self.monitor_start_count_check.isChecked()
        capture_screenshot = self.monitor_screenshot_check.isChecked()
        screenshot_path = self.screenshot_path

        self.start_monitor_clicked.emit(
            delay_time, monitor_time, monitor_boot, monitor_start_count,
            capture_screenshot, screenshot_path
        )
        
    def validate_delay_input(self):
        """验证查询间隔输入有效性"""
        value = self.delay_spin.value()
        # 确保输入在有效范围内
        if value < 10 or value > 86400:
            self.delay_spin.setValue(60)  # 非法输入默认使用60秒
            return False
        return True
        
    def set_monitor_status(self, is_monitoring):
        """设置监控状态"""
        self.start_monitor_button.setEnabled(not is_monitoring)
        self.stop_monitor_button.setEnabled(is_monitoring)
        
        # 禁用/启用其他控制
        self.refresh_button.setEnabled(not is_monitoring)
        self.dev_type_combo.setEnabled(not is_monitoring)
        self.manual_targets_edit.setEnabled(not is_monitoring)
        self.manual_find_button.setEnabled(not is_monitoring)
        
        # 禁用/启用监控控制区域的所有按钮和复选框
        self.delay_spin.setEnabled(not is_monitoring)
        self.monitor_time_check.setEnabled(not is_monitoring)
        self.monitor_boot_check.setEnabled(not is_monitoring)
        self.monitor_start_count_check.setEnabled(not is_monitoring)
        self.monitor_screenshot_check.setEnabled(not is_monitoring)
        self.screenshot_path_button.setEnabled(not is_monitoring)
        
        # 禁用/启用查询/控制区域的所有按钮
        self.query_all_button.setEnabled(not is_monitoring)
        self.query_time_button.setEnabled(not is_monitoring)
        self.query_boot_button.setEnabled(not is_monitoring)
        self.query_start_count_button.setEnabled(not is_monitoring)
        self.query_sum_switch_button.setEnabled(not is_monitoring)
        self.query_set_time_button.setEnabled(not is_monitoring)
        self.query_screenshot_button.setEnabled(not is_monitoring)
        self.query_upgrade_program_button.setEnabled(not is_monitoring)
        self.query_count_init_button.setEnabled(not is_monitoring)
        self.query_output_log_button.setEnabled(not is_monitoring)
        self.query_clean_switch_button.setEnabled(not is_monitoring)
        self.clear_history_button.setEnabled(not is_monitoring)
        self.enable_adb_button.setEnabled(not is_monitoring)
        
    def on_screenshot_path_clicked(self):
        """截图存储位置选择按钮点击事件"""
        options = QFileDialog.Options()
        options |= QFileDialog.ShowDirsOnly
        options |= QFileDialog.DontResolveSymlinks
        
        directory = QFileDialog.getExistingDirectory(
            self, "选择截图存储位置", 
            self.screenshot_path, 
            options=options
        )
        
        if directory:
            self.screenshot_path = directory
            self.update_refresh_status(f"截图存储位置已设置为: {directory}")
    
    def update_refresh_status(self, status, is_error=False, is_warning=False):
        """更新刷新状态标签"""
        self.refresh_status_label.setText(status)
        if is_error:
            self.refresh_status_label.setStyleSheet("color: red;")
        elif is_warning:
            self.refresh_status_label.setStyleSheet("color: orange;")
        else:
            self.refresh_status_label.setStyleSheet("color: green;")
