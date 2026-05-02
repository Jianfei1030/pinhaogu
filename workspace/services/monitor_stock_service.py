# -*- coding: utf-8 -*-
"""
Monitor Stock Service - 单只股票处理服务层

将 monitor.py 中的 `_handle_stock` 组合逻辑下沉到 service 层。
为 R5.5b 接线做准备。

职责：
- 单只股票的完整处理流程
- 接收 stock/realtime/db_path
- 调用指标帧收集
- 调用告警检测
- 组装 line 文案
- 返回结构化结果（line, alerts, meta）

不依赖 Monitor 实例，不直接发送消息。

Usage:
    from workspace.services.monitor_stock_service import (
        process_stock,
        build_stock_line,
        stock_key,
        format_volume,
        MonitorStockServiceError,
    )
    
    # 处理单只股票
    line, alerts, meta = process_stock(
        stock=stock_dict,
        realtime=realtime_dict,
        db_path="/path/to/db",
        collect_indicator_frames_fn=collect_indicator_frames,
        detect_alerts_fn=detect_alerts,
        last_alert_keys=set(),
    )
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd


# =============================================================================
# A. 业务异常类
# =============================================================================

class MonitorStockServiceError(Exception):
    """Monitor Stock Service 业务异常"""
    pass


# =============================================================================
# B. 组合 helper 函数
# =============================================================================

def stock_key(stock: dict[str, Any]) -> str:
    """
    生成股票代码标识
    
    Args:
        stock: 股票字典，包含 market 和 symbol 字段
    
    Returns:
        格式：{MARKET}{SYMBOL}，如 "HK00700"
    
    Examples:
        >>> stock_key({"market": "HK", "symbol": "00700"})
        'HK00700'
        >>> stock_key({"market": "A", "symbol": "600519"})
        'A600519'
    """
    market = str(stock.get("market", "")).upper().strip()
    symbol = str(stock.get("symbol", "")).strip()
    return f"{market}{symbol}"


def format_volume(value: float | int) -> str:
    """
    格式化成交量显示
    
    Args:
        value: 成交量数值
    
    Returns:
        格式化后的字符串，如 "1.2 亿", "345.6 万", "1000"
    
    Examples:
        >>> format_volume(120000000)
        '1.20 亿'
        >>> format_volume(3456000)
        '345.6 万'
        >>> format_volume(1000)
        '1000'
    """
    value = float(value or 0)
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return f"{value:.0f}"


def build_stock_line(
    stock: dict[str, Any],
    realtime: dict[str, Any],
    indicator_df: pd.DataFrame,
    intraday_rows: list[dict],
) -> str:
    """
    构建单只股票的日志行文案
    
    Args:
        stock: 股票字典，包含 market, symbol, name 字段
        realtime: 实时行情数据，包含 current, prev_close, change_pct 等
        indicator_df: 15min 周期指标 DataFrame（包含 MACD 指标）
        intraday_rows: 5min 周期 K 线数据列表（用于获取最新成交量）
    
    Returns:
        格式化的日志行字符串，如：
        "[14:30:00] HK00700 腾讯控股 | 350.20 | +1.25% | MACD:0.1234 DEA:0.0567 ↑ | Vol: 1.2 亿"
    
    Notes:
        - 与 monitor.py._render_line 保持一致的文案格式
        - MACD 箭头：DEA 上升用 ↑，下降用 ↓
        - 数据缺失时显示 "--"
    """
    now_text = datetime.now().strftime("%H:%M:%S")
    code = stock_key(stock)
    name = stock.get("name", "")
    
    # 价格与涨跌幅
    price = float(realtime.get("current") or 0)
    prev_close = float(realtime.get("prev_close") or 0)
    if prev_close > 0:
        change_pct = (price - prev_close) / prev_close * 100
    else:
        change_pct = float(realtime.get("change_pct") or 0)
    
    # MACD 指标
    macd_text = "MACD:-- DEA:-- -"
    if not indicator_df.empty and len(indicator_df) >= 1:
        last = indicator_df.iloc[-1]
        macd_val = float(last.get("macd") or 0)
        dea_val = float(last.get("macd_dea") or 0)
        
        # 计算 DEA 变化方向
        if len(indicator_df) >= 2:
            dea_prev = float(indicator_df.iloc[-2].get("macd_dea") or 0)
        else:
            dea_prev = dea_val
        
        arrow = "↑" if dea_val >= dea_prev else "↓"
        macd_text = f"MACD:{macd_val:.2f} DEA:{dea_val:.2f} {arrow}"
    
    # 最新成交量
    latest_volume = intraday_rows[-1].get("volume", 0) if intraday_rows else 0
    
    return (
        f"[{now_text}] {code} {name} | {price:.2f} | {change_pct:+.2f}% | "
        f"{macd_text} | Vol: {format_volume(latest_volume)}"
    )


# =============================================================================
# C. 主入口函数
# =============================================================================

def process_stock(
    stock: dict[str, Any],
    realtime: dict[str, Any],
    db_path: str,
    collect_indicator_frames_fn: Callable[[str], dict[str, pd.DataFrame]],
    detect_alerts_fn: Callable[
        [dict[str, Any], list[dict], dict[str, pd.DataFrame], dict[str, Any]],
        list[dict[str, Any]]
    ],
    last_alert_keys: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """
    处理单只股票的完整流程
    
    这是 `_handle_stock` 的 service 层版本，将原本的组合逻辑下沉。
    
    Args:
        stock: 股票字典，包含：
            - market: 市场标识（HK/A）
            - symbol: 股票代码
            - name: 股票名称（可选）
        realtime: 实时行情数据，包含：
            - current: 当前价格
            - prev_close: 昨收价
            - change_pct: 涨跌幅（可选）
            - time: 行情时间（可选）
        db_path: 数据库文件路径
        collect_indicator_frames_fn: 指标帧收集函数
            签名：fn(db_path: str) -> dict[str, pd.DataFrame]
            如：monitor.py._collect_indicator_frames
        detect_alerts_fn: 告警检测函数
            签名：fn(stock, intraday_rows, indicator_frames, realtime) -> list[dict]
            如：monitor.py._detect_alerts
        last_alert_keys: 已发送的告警 key 集合（用于去重，可选）
    
    Returns:
        三元组 (line, alerts, meta)：
        - line: 日志行字符串
        - alerts: 告警列表，每项包含 {type, key, message}
        - meta: 元数据字典，包含：
            - code: 股票代码
            - has_data: 是否有数据
            - indicator_frames: 指标帧字典
            - intraday_rows: 5min K 线数据
    
    Raises:
        MonitorStockServiceError: 处理失败时抛出
    
    Notes:
        - 不依赖 Monitor 实例
        - 不直接发送消息
        - 对 realtime 缺字段时行为保持宽松
        - 无数据时返回空 line 和空 alerts
    
    Examples:
        >>> line, alerts, meta = process_stock(
        ...     stock={"market": "HK", "symbol": "00700", "name": "腾讯控股"},
        ...     realtime={"current": 350.20, "prev_close": 345.80},
        ...     db_path="data/HK/HK00700/2026-04-07.db",
        ...     collect_indicator_frames_fn=collect_indicator_frames,
        ...     detect_alerts_fn=detect_alerts,
        ... )
        >>> print(line)
        [14:30:00] HK00700 腾讯控股 | 350.20 | +1.27% | ...
    """
    meta: dict[str, Any] = {
        "code": stock_key(stock),
        "has_data": False,
        "indicator_frames": {},
        "intraday_rows": [],
    }
    
    # 1. 验证输入
    if not stock.get("symbol"):
        raise MonitorStockServiceError(f"股票代码缺失：{stock}")
    
    # 2. 收集指标帧
    #    collect_indicator_frames_fn 内部会：
    #    - 从 db_path 读取各周期 K 线
    #    - 计算 MACD 指标
    #    - 合并引用周期数据
    try:
        indicator_frames = collect_indicator_frames_fn(db_path)
    except Exception as e:
        raise MonitorStockServiceError(f"收集指标帧失败：{e}")
    
    meta["indicator_frames"] = indicator_frames
    
    # 3. 获取 5min 数据作为 intraday_rows
    intraday_rows_data = []
    if "5min" in indicator_frames and not indicator_frames["5min"].empty:
        # 从 DataFrame 转回 dict 列表
        df_5min = indicator_frames["5min"]
        intraday_rows_data = df_5min.to_dict(orient="records")
    
    meta["intraday_rows"] = intraday_rows_data
    
    # 4. 检查是否有数据
    if not intraday_rows_data:
        # 无数据时返回空结果
        now_text = datetime.now().strftime("%H:%M:%S")
        empty_line = f"[{now_text}] {meta['code']} 无数据"
        return empty_line, [], meta
    
    meta["has_data"] = True
    
    # 5. 检测告警
    try:
        alerts = detect_alerts_fn(stock, intraday_rows_data, indicator_frames, realtime)
    except Exception as e:
        raise MonitorStockServiceError(f"告警检测失败：{e}")
    
    # 6. 构建日志行
    indicator_df_15min = indicator_frames.get("15min", pd.DataFrame())
    line = build_stock_line(stock, realtime, indicator_df_15min, intraday_rows_data)
    
    return line, alerts, meta


# =============================================================================
# D. 辅助函数（用于独立调用场景）
# =============================================================================

def _default_collect_indicator_frames(
    db_path: str,
    base_period: str = "15min",
    ref_periods: list[str] | None = None,
    alert_rules: list[Any] | None = None,
    engine: Any | None = None,
) -> dict[str, pd.DataFrame]:
    """
    默认的指标帧收集函数（用于测试或独立调用）
    
    这是对 monitor_indicator_service.collect_indicator_frames 的薄封装。
    
    Args:
        db_path: 数据库文件路径
        base_period: 基础周期（默认 15min）
        ref_periods: 引用周期列表（可选）
        alert_rules: 告警规则列表（可选，用于自动提取 ref_periods）
        engine: IndicatorEngine 实例（可选）
    
    Returns:
        周期到 DataFrame 的映射字典
    """
    from workspace.services.monitor_indicator_service import collect_indicator_frames
    
    return collect_indicator_frames(
        db_path=db_path,
        base_period=base_period,
        ref_periods=ref_periods or [],
        alert_rules=alert_rules,
        engine=engine,
    )


def _default_detect_alerts(
    stock: dict[str, Any],
    intraday_rows: list[dict],
    indicator_frames: dict[str, pd.DataFrame],
    realtime: dict[str, Any],
    alert_rules: list[Any] | None = None,
    last_alert_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    默认的告警检测函数（用于测试或独立调用）
    
    这是对 monitor_alert_service.detect_alerts 的薄封装，
    同时保留 monitor.py._detect_alerts 中的 legacy 告警逻辑（change_pct/macd_cross）。
    
    Args:
        stock: 股票字典
        intraday_rows: 5min K 线数据列表
        indicator_frames: 指标帧字典
        realtime: 实时行情数据
        alert_rules: 告警规则列表（可选）
        last_alert_keys: 已发送的告警 key 集合（可选）
    
    Returns:
        告警列表
    """
    from workspace.services.monitor_alert_service import detect_alerts as detect_rule_alerts
    
    # 使用 service 层的 detect_alerts
    # 注意：这个函数只处理 rule-based alerts
    # legacy alerts（change_pct/macd_cross）需要在 monitor.py 中保留
    alert_rules = alert_rules or []
    last_alert_keys = last_alert_keys or set()
    
    return detect_rule_alerts(
        alert_rules=alert_rules,
        bars_by_period=indicator_frames,
        symbol=stock.get("symbol", ""),
        market=stock.get("market", ""),
        stock_name=stock.get("name"),
        realtime=realtime,
        last_alert_keys=last_alert_keys,
    )
