#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志工具模块

用法:
    from utils.logger import setup_logger
    
    # 创建 logger
    logger = setup_logger("my_module")
    
    # 使用
    logger.info("信息")
    logger.warning("警告")
    logger.error("错误")
"""
import logging
from pathlib import Path
from datetime import datetime
from config import config


def setup_logger(name: str, log_dir: Path = None, level: int = logging.INFO) -> logging.Logger:
    """
    配置日志系统
    
    Args:
        name: Logger 名称（也是日志文件名前缀）
        log_dir: 日志目录（默认使用 config.data.logs）
        level: 日志级别（默认 INFO）
    
    Returns:
        logging.Logger: 配置好的 logger 实例
    """
    if log_dir is None:
        log_dir = config.data.logs
    
    # 确保日志目录存在
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 日志文件：{name}_{YYYY-MM-DD}.log
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{name}_{today}.log"
    
    # 创建 logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    
    # 文件 handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(level)
    
    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取已存在的 logger（不重复配置）
    
    Args:
        name: Logger 名称
    
    Returns:
        logging.Logger: logger 实例
    """
    return logging.getLogger(name)


# ===== 测试函数 =====
def test_logger():
    """测试日志功能"""
    print("开始测试日志模块...")
    print()
    
    # 创建 logger
    logger = setup_logger("test_logger")
    
    # 测试各等级日志
    logger.info("📝 INFO 级别日志")
    logger.warning("⚠️ WARNING 级别日志")
    logger.error("❌ ERROR 级别日志")
    
    print()
    print(f"日志文件位置：{config.data.logs}")
    print(f"日志文件名：test_logger_{datetime.now().strftime('%Y-%m-%d')}.log")
    print()
    print("✅ 日志模块测试完成")
    
    return logger


if __name__ == "__main__":
    from datetime import datetime
    test_logger()
