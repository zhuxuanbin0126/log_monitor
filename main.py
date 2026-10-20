#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import threading
import traceback

from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
    """把未捕获异常写进 ``output/logs/app.log``（打包后无控制台，这是唯一的现场线索）。"""
    try:
        from service.logging_service import get_logger
        get_logger('crash').error(
            "未捕获异常:\n%s",
            ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
    except Exception:  # pylint: disable=broad-except
        pass


def install_excepthooks() -> None:
    """安装全局异常钩子：主线程 + 子线程的未捕获异常都落盘后再交给原处理器。"""
    original_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        _log_uncaught(exc_type, exc_value, exc_tb)
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    original_thread_hook = getattr(threading, 'excepthook', None)

    def _thread_hook(args):
        if not getattr(args, 'excinfo', None) or args.exc_type is SystemExit:
            return
        _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)
        if original_thread_hook is not None:
            original_thread_hook(args)

    threading.excepthook = _thread_hook


def log_environment() -> None:
    """启动时记录路径与工具可用性，便于现场一眼定位「工具调不起来」的问题。"""
    try:
        from service.device_utils import app_root, tools_status
        from service.logging_service import get_logger

        logger = get_logger('startup')
        status = tools_status()
        logger.info("程序根目录: %s", app_root())
        logger.info("工具目录: 外部=%s（存在=%s） 内置=%s",
                    status['external_dir'], status['external_exists'],
                    status['bundled_dir'] or '无')
        if status['missing']:
            logger.error("缺少外部工具: %s（请确认发布包内的 tools/bin 是否完整）",
                         ", ".join(status['missing']))
        else:
            logger.info("外部工具齐全: %s", ", ".join(status['resolved'].values()))
    except Exception:  # pylint: disable=broad-except
        pass


def main():
    """主函数，启动应用程序"""
    install_excepthooks()
    log_environment()

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
