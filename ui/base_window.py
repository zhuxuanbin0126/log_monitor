from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QSplitter, QStatusBar
from PyQt5.QtCore import Qt
from config import VERSION

class BaseWindow(QMainWindow):
    """基础窗口类，提供基本的窗口设置和布局"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("设备监控系统 V"+VERSION)
        self.resize(960, 800)
        
        # 设置中心部件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 创建主布局
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # 创建分割器
        self.splitter = QSplitter(Qt.Vertical)
        
        # 状态栏
        self.statusBar().showMessage("就绪")
        
    def add_widget_to_splitter(self, widget):
        """向分割器添加部件"""
        self.splitter.addWidget(widget)
        
    def finalize_layout(self):
        """完成布局设置"""
        # 设置分割器初始大小
        self.splitter.setSizes([600, 400])
        
        # 将分割器添加到主布局
        self.main_layout.addWidget(self.splitter)
        
    def update_status_bar(self, message):
        """更新状态栏消息"""
        self.statusBar().showMessage(message)
        
    def closeEvent(self, event):
        """窗口关闭时的处理"""
        # 子类可以重写此方法以实现特定的关闭逻辑
        event.accept()