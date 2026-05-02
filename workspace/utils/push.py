#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一推送工具模块 - 兼容层

此模块是薄兼容层，实际实现已迁移至 services.push_service。
老代码可继续从 utils.push 导入，新代码建议导向 services.push_service。

用法:
    from utils.push import send_telegram, send_qq, send_both
    
    # 只推 Telegram
    send_telegram("消息内容")
    
    # 只推 QQ
    send_qq("消息内容")
    
    # 同时推送
    send_both("消息内容")
"""
import logging
from pathlib import Path
import sys

# 确保能导入 services
sys.path.insert(0, str(Path(__file__).parent.parent))

# 从 service 层重新导出，保持向后兼容
from services.push_service import send_telegram, send_qq, send_both, test_push

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    test_push()
