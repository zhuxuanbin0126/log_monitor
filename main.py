#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import threading
import traceback

from PySide6.QtWidgets import QApplication
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
        from service.device_utils import app_root, tools_status, adb_resolution_status
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

        adb = adb_resolution_status()
        if adb['bundled_ok']:
            logger.info("ADB 解析: 使用随包 adb %s", adb['bundled_path'])
            if adb['hijacked']:
                logger.warning(
                    "ADB 解析: 系统 PATH 中另有 adb（%s），程序内部调用不受影响；"
                    "外部工具裸调 adb 时需注意区分", adb['path_adb'])
        else:
            logger.error(
                "ADB 解析: 未找到随包 adb（%s），已按降级策略回退系统 PATH"
                "（当前命中: %s）；存在被其它 adb 抢占的风险，请补齐 tools/bin",
                adb['bundled_path'], adb['path_adb'] or '未找到任何 adb')
    except Exception:  # pylint: disable=broad-except
        pass


def main():
    """主函数，启动应用程序"""
    install_excepthooks()
    log_environment()

    # 兼容补充：把 tools/bin 注入**当前进程** PATH（守护线程，静默，不改注册表）
    try:
        from service.path_setup import ensure_tools_on_path_async
        ensure_tools_on_path_async()
    except Exception:  # pylint: disable=broad-except
        pass

    # 缓存维护：后台静默清理 7 天未成功查询的设备记录（不写面板、不阻塞启动）
    try:
        from service.device_cache import purge_stale_async
        purge_stale_async()
    except Exception:  # pylint: disable=broad-except
        pass

    # 创建Qt应用程序实例
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainWindow()
    
    # 显示窗口
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
