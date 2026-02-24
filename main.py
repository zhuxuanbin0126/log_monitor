#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    """主函数，启动应用程序"""
    # 创建Qt应用程序实例
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainWindow()
    
    # 显示窗口
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()