from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QTextEdit, QMenu, QAction
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from datetime import datetime

class ResultDisplayView(QWidget):
    """结果显示视图类，负责日志的显示和管理"""
    # 定义信号
    clear_log_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.result_display_group = QGroupBox("结果显示")
        result_display_layout = QVBoxLayout(self.result_display_group)
        
        # 创建日志显示框
        self.create_log_display(result_display_layout)
        
        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.result_display_group)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
    def create_log_display(self, parent_layout):
        """创建日志显示区域"""
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        
        # 为日志显示框添加右键菜单
        self.log_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_text.customContextMenuRequested.connect(self.show_log_context_menu)
        
        parent_layout.addWidget(self.log_text)
        
    def show_log_context_menu(self, position):
        """显示日志区域的右键菜单"""
        context_menu = QMenu(self)
        
        # 全选功能
        select_all_action = QAction("全选", self)
        select_all_action.triggered.connect(self.select_all_log)
        context_menu.addAction(select_all_action)
        
        # 复制功能
        copy_action = QAction("复制", self)
        copy_action.triggered.connect(self.copy_log_text)
        context_menu.addAction(copy_action)
        
        # 删除功能
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(self.delete_log_text)
        context_menu.addAction(delete_action)
        
        # 清空日志功能
        clear_action = QAction("清空日志", self)
        clear_action.triggered.connect(self.clear_log)
        context_menu.addAction(clear_action)
        
        context_menu.exec_(self.log_text.mapToGlobal(position))
        
    def select_all_log(self):
        """全选日志内容"""
        self.log_text.selectAll()
        
    def copy_log_text(self):
        """复制选中的日志内容"""
        self.log_text.copy()
        
    def delete_log_text(self):
        """删除选中的日志内容"""
        if self.log_text.textCursor().hasSelection():
            cursor = self.log_text.textCursor()
            cursor.removeSelectedText()
        
    def clear_log(self):
        """清空日志显示"""
        self.log_text.clear()
        self.clear_log_clicked.emit()
        
    def log(self, message, is_error=False, is_warning=False):
        """显示日志，支持错误(红色)、警告(黄色)、正常(黑色)"""
        from PyQt5.QtGui import QColor
        color = QColor('black')
        if is_error:
            color = QColor('red')
        elif is_warning:
            color = QColor('orange')
        # 假设 self.log_widget 是 QTextEdit
        self.log_text.setTextColor(color)
        self.log_text.append(message)
        
    def get_log_text(self):
        """获取日志文本"""
        return self.log_text.toPlainText()