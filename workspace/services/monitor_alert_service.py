# -*- coding: utf-8 -*-
"""
Monitor Alert Service - 监控告警检测与消息构造服务层

将 monitor.py 中的告警上下文构建、告警消息拼装、规则检测逻辑下沉到 service 层。
为 R5.4b 接线做准备。

职责：
- 告警上下文构建（从 row + realtime 数据）
- 告警文案拼装（规则名称、股票信息、指标值、斜率箭头等）
- 规则评估流程（edge-trigger 检测、冷却判定）
- 不依赖 Monitor 实例
- 不直接发送消息

Usage:
    from workspace.services.monitor_alert_service import (
        slope_arrow,
        alert_context_from_row,
        build_rule_alert_message,
        detect_rule_alerts,
        detect_alerts,
        MonitorAlertServiceError,
    )
    
    # 构建告警上下文
    context = alert_context_from_row(row, period="15min", symbol="00700", market="HK", stock_name="腾讯控股")
    
    # 拼装告警消息
    message = build_rule_alert_message(rule, context)
    
    # 检测单条规则的告警
    alerts = detect_rule_alerts(rule, bars, symbol="00700", market="HK", stock_name="腾讯控股")
    
    # 检测所有规则的告警
    all_alerts = detect_alerts(alert_rules, bars_by_period, symbol="00700", market="HK", stock_name="腾讯控股")
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd


# =============================================================================
# A. 业务异常类
# =============================================================================

class MonitorAlertServiceError(Exception):
    """Monitor Alert Service 业务异常"""
    pass


# =============================================================================
# B. 核心函数 - 上下文构建与消息拼装
# =============================================================================

def slope_arrow(value: float) -> str:
    """
    根据斜率值返回箭头符号
    
    Args:
        value: 斜率值（MACD/DIF、DEA、HIST 的斜率）
    
    Returns:
        "↗" if value >= 0 else "↘"
    
    Examples:
        >>> slope_arrow(0.5)
        '↗'
        >>> slope_arrow(-0.3)
        '↘'
        >>> slope_arrow(0.0)
        '↗'
    """
    return "↗" if value >= 0 else "↘"


def alert_context_from_row(
    row: pd.Series,
    period: str,
    symbol: str,
    market: str,
    stock_name: str | None = None,
    realtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    从 DataFrame row 构建告警上下文
    
    Args:
        row: 指标 DataFrame 的最后一行（包含 MACD 指标值）
        period: 周期标识（如 "15min"）
        symbol: 股票代码
        market: 市场标识（如 "HK", "A"）
        stock_name: 股票名称（可选）
        realtime: 实时行情数据（可选，包含 current/prev_close/change_pct/time 等）
    
    Returns:
        告警上下文 dict，包含：
        - market: 市场标识
        - symbol: 股票代码
        - name: 股票名称
        - price: 当前价格
        - change_pct: 涨跌幅百分比
        - bar_time: K 线时间
        - realtime_time: 实时行情时间
        - macd, macd_dea, macd_hist: MACD 指标值
        - macd_slope, macd_dea_slope, macd_hist_slope: 斜率值
        - {ref_period}_macd_slope 等引用周期指标值（如存在）
    
    Notes:
        - 价格无效时（0 或负数）返回 price=0
        - 数值字段缺失或 NaN 时默认返回 0.0
    """
    realtime = realtime or {}
    
    # 提取价格与涨跌幅
    price = float(realtime.get("current") or row.get("close") or 0)
    prev_close = float(realtime.get("prev_close") or 0)
    change_pct = (
        ((price - prev_close) / prev_close * 100) if prev_close else float(realtime.get("change_pct") or 0)
    )
    
    # 辅助函数：安全提取数值
    def _series_value(key: str) -> float:
        value = row.get(key)
        if value is None or pd.isna(value):
            return 0.0
        return float(value)
    
    context = {
        "market": str(market).upper().strip(),
        "symbol": str(symbol).strip(),
        "name": str(stock_name or ""),
        "price": price,
        "change_pct": change_pct,
        "bar_time": str(row.get("bar_time", "--:--")),
        "realtime_time": str(realtime.get("time") or "--"),
        "macd": _series_value("macd"),
        "macd_dea": _series_value("macd_dea"),
        "macd_hist": _series_value("macd_hist"),
        "macd_slope": _series_value("macd_slope"),
        "macd_dea_slope": _series_value("macd_dea_slope"),
        "macd_hist_slope": _series_value("macd_hist_slope"),
    }
    
    # 提取引用周期指标值（如 5min_macd_slope 等）
    ref_col_pattern = re.compile(
        r"^[A-Za-z0-9]+_(macd|macd_dea|macd_hist|macd_slope|macd_dea_slope|macd_hist_slope)$"
    )
    for key in row.index:
        if isinstance(key, str) and ref_col_pattern.match(key):
            context[key] = _series_value(key)
    
    return context


def build_rule_alert_message(rule: Any, context: dict[str, Any]) -> str:
    """
    根据规则和上下文构建告警消息
    
    Args:
        rule: AlertRule 实例（或包含 name/period/cooldown/ref_periods 属性的对象）
        context: 告警上下文 dict（来自 alert_context_from_row）
    
    Returns:
        格式化的告警消息字符串，包含：
        - 规则名称
        - 股票信息与价格
        - 15min 周期 DIF/DEA/HIST 及斜率
        - 引用周期的斜率信息（如有）
        - Bar 时间与冷却时间
    
    Notes:
        - 与 monitor.py._build_rule_alert_message 保持一致的文案格式
    """
    arrow_d = slope_arrow(context["macd_slope"])
    arrow_e = slope_arrow(context["macd_dea_slope"])
    arrow_h = slope_arrow(context["macd_hist_slope"])
    
    # 获取周期标识（兼容 AlertRule.period 和直接 period 属性）
    period_label = str(getattr(rule, "period", "15min"))
    
    message_lines = [
        f"🔔 {rule.name}",
        f"📈 {context['name']} ({context['market']}{context['symbol']}) {context['price']:.2f} ({context['change_pct']:+.2f}%)",
        f"{period_label} DIF: {context['macd']:.4f} slope:{context['macd_slope']:.4f} {arrow_d}",
        f"{period_label} DEA: {context['macd_dea']:.4f} slope:{context['macd_dea_slope']:.4f} {arrow_e}",
        f"{period_label} Hist: {context['macd_hist']:.4f} slope:{context['macd_hist_slope']:.4f} {arrow_h}",
    ]
    
    # 添加引用周期信息
    ref_periods = getattr(rule, "ref_periods", []) or []
    for ref_period in ref_periods:
        ref_macd_key = f"{ref_period}_macd_slope"
        ref_dea_key = f"{ref_period}_macd_dea_slope"
        ref_hist_key = f"{ref_period}_macd_hist_slope"
        parts: list[str] = []
        
        if ref_macd_key in context:
            parts.append(f"DIF slope:{context[ref_macd_key]:.4f} {slope_arrow(context[ref_macd_key])}")
        if ref_dea_key in context:
            parts.append(f"DEA slope:{context[ref_dea_key]:.4f} {slope_arrow(context[ref_dea_key])}")
        if ref_hist_key in context:
            parts.append(f"Hist slope:{context[ref_hist_key]:.4f} {slope_arrow(context[ref_hist_key])}")
        
        if parts:
            message_lines.append(f"{ref_period} " + " | ".join(parts))
    
    message_lines.append(f"⏰ Bar: {context['bar_time']} | Cooldown: {rule.cooldown}s")
    message_lines.append(f"🕐 数据时间：{context['realtime_time']}")
    
    return "\n".join(message_lines)


# =============================================================================
# C. 规则检测函数
# =============================================================================

def detect_rule_alerts(
    rule: Any,
    bars: list[dict],
    symbol: str,
    market: str,
    stock_name: str | None = None,
    realtime: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    检测单条规则的告警
    
    Args:
        rule: AlertRule 实例（包含 evaluate/in_cooldown/mark_triggered 方法）
        bars: 指标数据列表，按时间排序，每条包含 macd/macd_dea/macd_hist 等字段
        symbol: 股票代码
        market: 市场标识
        stock_name: 股票名称（可选）
        realtime: 实时行情数据（可选）
    
    Returns:
        命中的告警列表，每项包含：
        - type: "rule"
        - key: 告警唯一标识（格式：{market}{symbol}:rule:{rule.name}:{rule.period}:{bar_time}）
        - message: 告警消息文本
        - rule: 触发的规则实例
        - context: 告警上下文
    
    Notes:
        - 使用 edge-trigger 逻辑：当前 bar 满足 && 上一根 bar 满足 && 上上一根 bar 不满足
        - 检查规则冷却时间
        - 价格无效（<=0）时不发告警
        - bars 不足 3 条时返回空列表
    """
    alerts: list[dict[str, Any]] = []
    
    if len(bars) < 3:
        return alerts
    
    # 遍历 bars，从第 3 条开始（索引 2）
    for i in range(2, len(bars)):
        current = bars[i]
        prev = bars[i - 1]
        prev_prev = bars[i - 2]
        
        # Edge-trigger 评估
        if not rule.evaluate(current, prev, prev_prev):
            continue
        
        # 冷却检查
        if rule.in_cooldown():
            continue
        
        # 价格检查
        price = float(current.get("close") or (realtime.get("current") if realtime else 0))
        if price <= 0:
            continue
        
        # 构建上下文和消息
        row = pd.Series(current)
        context = alert_context_from_row(
            row=row,
            period=str(getattr(rule, "period", "15min")),
            symbol=symbol,
            market=market,
            stock_name=stock_name,
            realtime=realtime,
        )
        
        alert_message = build_rule_alert_message(rule, context)
        stock_code = f"{str(market).upper().strip()}{str(symbol).strip()}"
        alert_key = f"{stock_code}:rule:{rule.name}:{rule.period}:{context['bar_time']}"
        
        alerts.append({
            "type": "rule",
            "key": alert_key,
            "message": alert_message,
            "rule": rule,
            "context": context,
        })
        
        # 标记规则已触发（更新冷却时间）
        rule.mark_triggered()
    
    return alerts


def detect_alerts(
    alert_rules: list[Any],
    bars_by_period: dict[str, list[dict]],
    symbol: str,
    market: str,
    stock_name: str | None = None,
    realtime: dict[str, Any] | None = None,
    last_alert_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    检测所有规则的告警
    
    Args:
        alert_rules: AlertRule 实例列表
        bars_by_period: 按周期组织的指标数据 dict，如 {"15min": [...], "5min": [...]}
        symbol: 股票代码
        market: 市场标识
        stock_name: 股票名称（可选）
        realtime: 实时行情数据（可选）
        last_alert_keys: 已发送的告警 key 集合（用于去重，可选）
    
    Returns:
        命中的告警列表（已去重），每项包含：
        - type: "rule"
        - key: 告警唯一标识
        - message: 告警消息文本
        - rule: 触发的规则实例
        - context: 告警上下文
    
    Notes:
        - 遍历所有规则，调用 detect_rule_alerts 检测
        - 如果提供 last_alert_keys，则过滤掉已发送的告警
        - 返回结构化结果，由上层决定如何发送
    """
    all_alerts: list[dict[str, Any]] = []
    last_alert_keys = last_alert_keys or set()
    
    for rule in alert_rules:
        period = str(getattr(rule, "period", "15min"))
        bars = bars_by_period.get(period, [])
        
        if not bars or len(bars) < 3:
            continue
        
        rule_alerts = detect_rule_alerts(
            rule=rule,
            bars=bars,
            symbol=symbol,
            market=market,
            stock_name=stock_name,
            realtime=realtime,
        )
        all_alerts.extend(rule_alerts)
    
    # 去重：过滤掉已发送的告警
    fresh_alerts = [alert for alert in all_alerts if alert["key"] not in last_alert_keys]
    
    return fresh_alerts
