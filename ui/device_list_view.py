from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QGroupBox, QCheckBox, QMenu, QAction, QHeaderView, QLabel
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

class DeviceListView(QWidget):
    """设备列表视图类，负责设备列表的显示和管理"""
    # 定义信号
    device_selected = pyqtSignal(set)
    device_list_updated = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = []  # 存储设备信息字典的列表
        self.selected_devices = set()
        self.selected_devices_info = []
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.device_list_group = QGroupBox("设备列表")
        device_list_layout = QVBoxLayout(self.device_list_group)
        
        # 创建设备表格
        self.create_device_table(device_list_layout)
        
        # 列显示控制
        column_control_layout = QHBoxLayout()
        column_control_layout.addWidget(QLabel("列显示:"))
        
        # 可选显示列的按钮
        self.column_checkboxes = {}
        optional_columns = [
            (3, "主版本"),
            (4, "OTA版本"),
            (5, "MAC地址"),
            (6, "设备密码"),
            (7, "设备名称"),
            (8, "系统类型")
        ]
        
        for col_index, col_name in optional_columns:
            checkbox = QCheckBox(col_name)
            checkbox.setChecked(col_index in [3, 4])  # 默认显示主版本和OTA版本
            checkbox.stateChanged.connect(lambda state, idx=col_index: self.toggle_column_visibility(idx, state))
            self.column_checkboxes[col_index] = checkbox
            column_control_layout.addWidget(checkbox)
        
        column_control_layout.addStretch()
        device_list_layout.addLayout(column_control_layout)
        
        # 全选/取消全选
        select_layout = QHBoxLayout()
        self.select_all_check = QCheckBox("全选")
        self.select_all_check.stateChanged.connect(self.on_select_all_changed)
        select_layout.addWidget(self.select_all_check)
        select_layout.addStretch()
        
        device_list_layout.addLayout(select_layout)
        
        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.device_list_group)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
    def create_device_table(self, parent_layout):
        """创建设备表格"""
        col_list = ["选择", "设备ID", "IP地址", "主版本", "OTA版本", "MAC地址", "设备密码", "设备名称", "系统类型"]
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(len(col_list))
        self.device_table.setHorizontalHeaderLabels(col_list)
        
        # 设置表格样式：支持选中复制
        self.device_table.setSelectionBehavior(QTableWidget.SelectItems)  # 允许选择单个单元格
        self.device_table.setSelectionMode(QTableWidget.ContiguousSelection)  # 允许连续选择多个单元格
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止编辑
        
        # 启用文本选择功能
        self.device_table.setTextElideMode(Qt.ElideNone)  # 不截断文本
        self.device_table.setShowGrid(True)  # 显示表格网格线
        self.device_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)  # 连接右键菜单
        
        # 设置行高（行间距）
        self.device_table.verticalHeader().setDefaultSectionSize(30)  # 增加行高
        
        # 设置列宽：选项列稍微缩小，其他字段均匀分布
        header = self.device_table.horizontalHeader()
        
        # 选项列（第0列）设置为固定宽度50
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.device_table.setColumnWidth(0, 60)
        
        # 其他列均匀分布
        for i in range(1, self.device_table.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        header.setSectionsClickable(True)
        
        # 添加双击表头排序功能
        self.device_table.horizontalHeader().sectionDoubleClicked.connect(self.sort_table_by_column)
        self.device_table.cellClicked.connect(self.on_device_selected)
        
        parent_layout.addWidget(self.device_table)
        
        # 设置默认显示列
        self.set_default_column_visibility()
        
    def update_device_table(self, devices):
        """更新设备列表表格"""
        self.devices = list(devices)
        self.device_table.setRowCount(len(self.devices))
        
        for row, device_info in enumerate(self.devices):
            device_id = device_info['id']
            
            # 选择框
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked if device_id in self.selected_devices else Qt.Unchecked)
            self.device_table.setItem(row, 0, check_item)
            
            # 设备ID
            id_item = QTableWidgetItem(device_id)
            id_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 1, id_item)
            
            # IP地址
            ip_item = QTableWidgetItem(device_info['ip'])
            ip_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 2, ip_item)
            
            # 主版本
            main_version = device_info.get('main_version', 'N/A')
            main_version_item = QTableWidgetItem(main_version)
            main_version_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 3, main_version_item)
            
            # OTA版本
            ota_version = device_info.get('ota_version', 'N/A')
            ota_version_item = QTableWidgetItem(ota_version)
            ota_version_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 4, ota_version_item)
            
            # MAC地址
            mac_item = QTableWidgetItem(device_info['mac_address'])
            mac_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 5, mac_item)
            
            # 设备密码
            password_item = QTableWidgetItem(device_info['password'])
            password_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 6, password_item)
            
            # 设备名称
            name_item = QTableWidgetItem(device_info['device_name'])
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 7, name_item)

            # 系统类型
            system_type_item = QTableWidgetItem(device_info['system_type'])
            system_type_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.device_table.setItem(row, 8, system_type_item)
        
        # 保留手动设置的列宽，不自动调整
        # 确保选项列保持较小宽度
        if self.device_table.columnWidth(0) > 60:
            self.device_table.setColumnWidth(0, 60)
        self.device_table.viewport().update()
            
    def on_device_selected(self, row, column):
        """设备被选择时的处理"""
        if column == 0 and row < len(self.devices):
            device_id = self.devices[row]['id']
            check_state = self.device_table.item(row, 0).checkState()
            
            if check_state == Qt.Checked:
                self.selected_devices.add(device_id)
                for info in self.devices:
                    if info['id'] == device_id:
                        self.selected_devices_info.append(info)
                # self.selected_devices_info.append(dict(info for info in self.devices if info['id'] == device_id))
            else:
                self.selected_devices.discard(device_id)
                for info in self.devices:
                    if info['id'] == device_id:
                        # 检查设备信息是否在列表中，避免ValueError
                        if info in self.selected_devices_info:
                            self.selected_devices_info.remove(info)
                # self.selected_devices_info.remove(dict(info for info in self.devices if info['id'] == device_id))
            
            # 发出选中设备变化的信号
            self.device_selected.emit(self.selected_devices)
            
    def on_select_all_changed(self, state):
        """全选/取消全选时的处理"""
        if state == Qt.Checked:
            for device_info in self.devices:
                self.selected_devices.add(device_info['id'])
                self.selected_devices_info = self.devices
        else:
            self.selected_devices.clear()
            self.selected_devices_info = []
        
        # 只更新复选框状态，不重新创建表格，避免改变行间距
        for row in range(self.device_table.rowCount()):
            device_id = self.devices[row]['id']
            check_item = self.device_table.item(row, 0)
            if check_item:
                check_item.setCheckState(Qt.Checked if device_id in self.selected_devices else Qt.Unchecked)
        
        # 发出选中设备变化的信号
        self.device_selected.emit(self.selected_devices)
        
    def show_context_menu(self, position):
        """显示右键菜单，支持复制功能"""
        # 获取选中的单元格
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            return
            
        # 创建右键菜单
        context_menu = QMenu()
        copy_action = QAction("复制", self)
        copy_action.triggered.connect(self.copy_selected_text)
        context_menu.addAction(copy_action)
        
        # 在点击位置显示菜单
        context_menu.exec_(self.device_table.mapToGlobal(position))
        
    def copy_selected_text(self):
        """复制选中的文本到剪贴板"""
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            return
            
        # 获取选中的文本
        text_to_copy = []
        # 按照行和列组织文本
        rows = set()
        cols = set()
        
        for item in selected_items:
            rows.add(item.row())
            cols.add(item.column())
            
        # 按行列顺序构建文本
        for row in sorted(rows):
            row_text = []
            for col in sorted(cols):
                item = self.device_table.item(row, col)
                if item:
                    row_text.append(item.text())
                else:
                    row_text.append("")
            text_to_copy.append("\t".join(row_text))
            
        # 将文本设置到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(text_to_copy))
        
    def sort_table_by_column(self, column):
        """双击表头排序表格"""
        # 保存当前的选择
        selected_rows = []
        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected_rows.append(self.device_table.item(row, 1).text())
                
        # 排序表格
        current_sort_order = self.device_table.horizontalHeader().sortIndicatorOrder()
        new_sort_order = Qt.DescendingOrder if current_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        self.device_table.sortItems(column, new_sort_order)
        
        # 恢复选择状态
        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 1)
            if item and item.text() in selected_rows:
                check_item = self.device_table.item(row, 0)
                if check_item:
                    check_item.setCheckState(Qt.Checked)
            else:
                check_item = self.device_table.item(row, 0)
                if check_item:
                    check_item.setCheckState(Qt.Unchecked)
        
    def get_selected_devices(self):
        """获取选中的设备列表"""
        return self.selected_devices

    def get_selected_devices_info(self):
        """获取选中的设备列表信息"""
        # 每次调用时从当前设备列表中重新构建选中的设备信息
        selected_info = []
        for device_info in self.devices:
            if device_info['id'] in self.selected_devices:
                selected_info.append(device_info)
        return selected_info
        
    def get_devices(self):
        """获取所有设备列表"""
        return self.devices
        
    def set_selected_devices(self, device_ids):
        """设置选中的设备"""
        self.selected_devices = set(device_ids)
        self.update_device_table(self.devices)  # 更新表格以反映选择状态
        
    def set_default_column_visibility(self):
        """设置默认列的显示和隐藏"""
        # 必显示列：选择，设备ID，IP地址
        # 默认显示列：主版本，OTA版本
        # 默认隐藏列：MAC地址，设备密码，设备名称，系统类型
        
        # 显示列：0(选择), 1(设备ID), 2(IP地址), 3(主版本), 4(OTA版本)
        visible_columns = [0, 1, 2, 3, 4]
        
        # 隐藏列：5(MAC地址), 6(设备密码), 7(设备名称), 8(系统类型)
        hidden_columns = [5, 6, 7, 8]
        
        # 设置列的显示状态
        for col in range(self.device_table.columnCount()):
            if col in visible_columns:
                self.device_table.setColumnHidden(col, False)
            else:
                self.device_table.setColumnHidden(col, True)
                
    def toggle_column_visibility(self, column_index, state):
        """切换列的显示状态"""
        # 必显示列不能隐藏
        if column_index in [0, 1, 2]:
            return
        
        # 根据状态显示或隐藏列
        if state == Qt.Checked:
            self.device_table.setColumnHidden(column_index, False)
        else:
            self.device_table.setColumnHidden(column_index, True)