#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行时状态服务 (Runtime State Service)

提供轻量级的运行时开关读取接口，复用 R2 配置层。

## 设计原则
- 保持简单：只做状态读取，不做状态管理
- 单一来源：以 config.runtime.* 为唯一数据源
- 软迁移：不强制替换所有现有调用，逐步迁移

## 接口
- is_dry_run() -> bool: 读取 dry-run 开关
- is_notify_enabled() -> bool: 读取推送开关
- get_runtime_flags() -> dict: 获取完整运行时快照

## 用法
    from services.runtime_state_service import is_dry_run, is_notify_enabled
    
    if is_dry_run():
        print("Dry-run 模式")
    
    if is_notify_enabled():
        send_message("推送消息")
"""
from config import config


def is_dry_run() -> bool:
    """
    读取 dry-run 开关状态
    
    Returns:
        bool: True 表示开启 dry-run（不保存/不推送），False 表示正常运行
    """
    return config.runtime.dry_run


def is_notify_enabled() -> bool:
    """
    读取推送开关状态
    
    Returns:
        bool: True 表示开启推送，False 表示关闭推送
    """
    return config.runtime.notify_enabled


def get_runtime_flags() -> dict:
    """
    获取完整运行时快照
    
    Returns:
        dict: 包含所有运行时开关的字典
        {
            "dry_run": bool,
            "notify_enabled": bool,
        }
    """
    return {
        "dry_run": config.runtime.dry_run,
        "notify_enabled": config.runtime.notify_enabled,
    }
