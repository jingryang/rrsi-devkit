#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
日志分离配置模块。

将系统日志（logging）与结果输出（print / stdout）分离：
- 系统日志  ->  log.txt（仅写入文件，不再刷屏）
- 结果输出  ->  result.txt（同时输出到屏幕和文件）

用法：
    import SingleOperatorLaunch
    SingleOperatorLaunch.setup_log_separation()
"""

import logging
import sys
from typing import Optional


class _Tee:
    """同时向屏幕和文件写入 stdout 内容。"""

    def __init__(self, file_path: str):
        self.file = open(file_path, "w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, data: str):
        self.stdout.write(data)
        self.file.write(data)
        self.flush()

    def flush(self):
        self.stdout.flush()
        self.file.flush()

    def isatty(self) -> bool:
        return False


def redirect_logging_to_file(
    log_file: str = "log.txt",
    level: int = logging.DEBUG,
    fmt: Optional[str] = None,
):
    """
    将 Python logging 模块的所有输出重定向到指定文件，
    同时移除所有输出到 stdout/stderr 的 StreamHandler，避免刷屏。

    Args:
        log_file: 日志文件路径，默认 ``log.txt``。
        level: 日志级别，默认 ``logging.DEBUG``。
        fmt: 自定义格式字符串，默认 ``%(asctime)s [%(name)s] %(levelname)s: %(message)s``。
    """
    if fmt is None:
        fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

    root_logger = logging.getLogger()

    # 1. 移除 root logger 中所有 StreamHandler
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            root_logger.removeHandler(handler)

    # 2. 移除所有已注册 logger 的 StreamHandler
    for logger_name in list(logging.root.manager.loggerDict):
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            if isinstance(handler, logging.StreamHandler):
                logger.removeHandler(handler)

    # 3. 添加统一的 FileHandler
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))

    root_logger.addHandler(file_handler)
    for logger_name in list(logging.root.manager.loggerDict):
        logging.getLogger(logger_name).addHandler(file_handler)


def redirect_stdout_to_file(result_file: str = "result.txt"):
    """
    将 ``sys.stdout`` 同时输出到屏幕和指定文件。

    Args:
        result_file: 结果文件路径，默认 ``result.txt``。
    """
    sys.stdout = _Tee(result_file)


def setup_log_separation(
    log_file: str = "log.txt",
    result_file: str = "result.txt",
    log_level: int = logging.DEBUG,
):
    """
    一键配置日志分离：
    - 系统日志（logging）写入 ``log_file``
    - 结果输出（print）同时打印到屏幕和 ``result_file``

    Args:
        log_file: 日志文件路径，默认 ``log.txt``。
        result_file: 结果文件路径，默认 ``result.txt``。
        log_level: 日志级别，默认 ``logging.DEBUG``。
    """
    redirect_logging_to_file(log_file=log_file, level=log_level)
    redirect_stdout_to_file(result_file=result_file)
