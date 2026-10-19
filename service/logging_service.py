"""统一日志服务：文件轮转 + 开发态控制台输出。"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config import LOG_DIR

_LOGGER_NAME = "log_monitor"
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    _configured = True


def get_logger(name: str = "app") -> logging.Logger:
    """获取带统一格式与轮转文件的 logger。"""
    _configure()
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
