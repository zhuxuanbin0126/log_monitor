import os
import time
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QTextEdit, QMenu, QAction, QPushButton, QHBoxLayout, QMessageBox
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

        self.msg = None

        # 创建日志显示框
        self.create_log_display(result_display_layout,self.result_display_group)
        
        # 设置主布局
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.result_display_group)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
    def create_log_display(self, parent_layout, result_display_group):
        """创建日志显示区域"""

        result_layout = QHBoxLayout()
        result_layout.setAlignment(Qt.AlignLeft)

        self.result_display_clear_button = QPushButton("清除日志面板")
        self.result_display_clear_button.setFixedSize(80,25)
        self.result_display_clear_button.clicked.connect(self.clear_log)

        self.result_display_outlog_button = QPushButton("导出结果日志")
        self.result_display_outlog_button.setFixedSize(80,25)
        self.result_display_outlog_button.clicked.connect(self.output_log_text)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        
        # 为日志显示框添加右键菜单
        self.log_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_text.customContextMenuRequested.connect(self.show_log_context_menu)
        
        result_layout.addWidget(self.result_display_clear_button)
        result_layout.addWidget(self.result_display_outlog_button)
        parent_layout.addLayout(result_layout)
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

    def output_log_text(self):
        """输出日志"""
        log_out_time = time.strftime("%Y%m%d_%H%M%S",time.localtime())
        if not os.path.exists("./result_log"):
            os.mkdir("./result_log")
        path = f"./result_log/result_{log_out_time}.log"
        with open(path, "a", encoding="utf-8") as f:
            f.write(self.log_text.toPlainText())
        # 统一使用正斜杠
        path = path.replace('\\', '/')
        QMessageBox.information(None, '提示', f'日志导出成功\n导出位置：{path}',QMessageBox.Ok)
        self.log(f"日志导出成功,导出位置：{path}")

    def log(self, message, is_error=False, is_warning=False, stamp=False):
        """追加一行日志：错误(红)/警告(橙)/正常(黑)。

        颜色**逐行显式写入**（不复用 ``setTextColor`` 的全局格式状态）：
        旧写法会受上一行颜色或用户选区影响，导致「上线/下线」这类正常日志
        偶尔被染成红色。``stamp=True`` 时在行首加系统时间。
        """
        from PyQt5.QtGui import QColor, QTextBlockFormat, QTextCharFormat
        from PyQt5.QtGui import QTextCursor

        text = message
        if stamp:
            text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"

        color = QColor('black')
        if is_error:
            color = QColor('#d32f2f')
        elif is_warning:
            color = QColor('#e67e22')

        char_format = QTextCharFormat()
        char_format.setForeground(color)

        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self.log_text.document().characterCount() > 1:   # 已有内容才另起一段
            cursor.insertBlock(QTextBlockFormat(), char_format)
        cursor.insertText(text, char_format)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()
        
    def get_log_text(self):
        """获取日志文本"""
        return self.log_text.toPlainText()