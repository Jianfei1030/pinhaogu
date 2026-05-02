# -*- coding: utf-8 -*-
"""
Monitor Schedule Service

交易时段判断、会话管理、等待日志判定逻辑的轻量级服务模块。
不依赖 Monitor 类实例，提供纯函数接口供上层调用。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


class MonitorScheduleServiceError(Exception):
    """业务异常基类"""
    pass


def parse_clock(value: str) -> tuple[int, int]:
    """
    解析时间字符串为 (hour, minute) 元组。
    
    Args:
        value: 时间字符串，格式 "HH:MM"
    
    Returns:
        (hour, minute) 元组
    
    Raises:
        MonitorScheduleServiceError: 解析失败时抛出
    """
    try:
        hour_text, minute_text = str(value).split(":", 1)
        return int(hour_text), int(minute_text)
    except (ValueError, IndexError) as exc:
        raise MonitorScheduleServiceError(f"Invalid time format: {value}") from exc


def combine_today(now: datetime, value: str) -> datetime:
    """
    将时间字符串组合到当前日期，生成完整的 datetime。
    
    Args:
        now: 当前时间基准
        value: 时间字符串，格式 "HH:MM"
    
    Returns:
        组合后的 datetime 对象
    """
    hour, minute = parse_clock(value)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def market_sessions(
    trading_hours: dict[str, dict[str, str]],
    market: str,
    now: datetime
) -> list[tuple[datetime, datetime]]:
    """
    获取指定市场在给定日期的交易时段列表。
    
    Args:
        trading_hours: 交易时段配置，格式 {"MARKET": {"start": "HH:MM", "end": "HH:MM", ...}}
        market: 市场标识（如 "A", "HK"）
        now: 当前时间基准
    
    Returns:
        交易时段列表，每个元素为 (start_dt, end_dt) 元组。
        如果市场无配置或配置不完整，返回空列表。
        如果有午休，返回两个时段；否则返回一个时段。
    """
    config = trading_hours.get(str(market).upper(), {})
    start = config.get("start")
    end = config.get("end")
    
    if not start or not end:
        return []
    
    start_dt = combine_today(now, start)
    end_dt = combine_today(now, end)
    
    break_start = config.get("break_start")
    break_end = config.get("break_end")
    
    if break_start and break_end:
        break_start_dt = combine_today(now, break_start)
        break_end_dt = combine_today(now, break_end)
        return [(start_dt, break_start_dt), (break_end_dt, end_dt)]
    
    return [(start_dt, end_dt)]


def trading_status(
    trading_hours: dict[str, dict[str, str]],
    now: datetime | None = None,
    watchlist: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """
    判断当前是否处于交易时段。
    
    Args:
        trading_hours: 交易时段配置
        now: 当前时间（默认使用 datetime.now()）
        watchlist: 监控股票列表，用于提取市场标识（可选）
    
    Returns:
        状态字典：
        - active: bool，是否处于交易时段
        - message: str，状态描述（非交易时段时提供等待信息）
        - next_open: datetime | None，下次开盘时间
    """
    now = now or datetime.now()
    
    # 从 watchlist 提取市场标识
    markets: set[str] = set()
    if watchlist:
        markets = {str(stock.get("market", "")).upper() for stock in watchlist if stock.get("market")}
    
    if not markets:
        return {"active": True, "message": "", "next_open": None}
    
    # 收集所有市场的交易时段
    sessions: list[tuple[datetime, datetime]] = []
    for market in sorted(markets):
        sessions.extend(market_sessions(trading_hours, market, now))
    
    if not sessions:
        return {"active": True, "message": "", "next_open": None}
    
    # 按时段开始时间排序
    sessions.sort(key=lambda item: item[0])
    
    # 检查是否在当前任一交易时段内
    for start_dt, end_dt in sessions:
        if start_dt <= now <= end_dt:
            return {"active": True, "message": "", "next_open": None}
    
    # 不在交易时段内，计算下次开盘时间
    # 1. 检查今天是否还有未开始的时段
    future_opens = [start_dt for start_dt, _ in sessions if now < start_dt]
    if future_opens:
        next_open = min(future_opens)
        message = f"非交易时段，等待开盘：{next_open.strftime('%H:%M')}"
        return {"active": False, "message": message, "next_open": next_open}
    
    # 2. 今天的时段都已结束，检查明天
    tomorrow = now + timedelta(days=1)
    tomorrow_opens: list[datetime] = []
    for market in sorted(markets):
        market_sessions_list = market_sessions(trading_hours, market, tomorrow)
        if market_sessions_list:
            tomorrow_opens.append(market_sessions_list[0][0])
    
    next_open = min(tomorrow_opens) if tomorrow_opens else None
    if next_open:
        message = f"非交易时段，已收盘，下次开盘：{next_open.strftime('%H:%M')}"
    else:
        message = "非交易时段，等待中..."
    
    return {"active": False, "message": message, "next_open": next_open}


def should_log_waiting(
    last_wait_log_at: float | None,
    now_ts: float,
    interval_seconds: float = 1800.0
) -> bool:
    """
    判断是否应该记录等待日志（节流控制）。
    
    Args:
        last_wait_log_at: 上次记录等待日志的时间戳（秒），None 表示从未记录
        now_ts: 当前时间戳（秒）
        interval_seconds: 最小间隔秒数，默认 1800 秒（30 分钟）
    
    Returns:
        True 表示应该记录，False 表示还在节流期内
    """
    return last_wait_log_at is None or (now_ts - last_wait_log_at) >= interval_seconds


def build_waiting_log_message(status: dict[str, Any], watchlist_text: str = "") -> str:
    """
    构建等待日志消息。
    
    Args:
        status: trading_status() 返回的状态字典
        watchlist_text: 自选股列表文本（可选，用于增强日志信息）
    
    Returns:
        等待日志消息字符串
    """
    message = status.get("message", "")
    if not message:
        return ""
    
    if watchlist_text:
        return f"[{watchlist_text}] {message}"
    
    return message
