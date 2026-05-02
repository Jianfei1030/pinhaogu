# -*- coding: utf-8 -*-
"""
Alert Service - 告警规则的业务逻辑层

提供告警规则的 CRUD 操作、payload 校验与规范化功能。
不包含 FastAPI route 逻辑，不直接处理 HTTP 请求。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from monitor import AlertRule
from indicators import IndicatorEngine
from indicators.macd import MACD
from services.market_data_service import load_multi_day_rows, MarketDataNotFoundError


# =============================================================================
# A. 业务异常类
# =============================================================================

class AlertServiceError(Exception):
    """告警服务基础异常"""
    pass


class AlertValidationError(AlertServiceError):
    """告警校验异常：payload 不合法、条件树解析失败等"""
    pass


class AlertIndexError(AlertServiceError):
    """告警索引异常：index 越界"""
    pass


# =============================================================================
# B. 条件与 payload 规范化函数
# =============================================================================

def normalize_single_condition(item: Any, path: str = "conditions") -> dict[str, Any]:
    """
    规范化单个条件项。
    
    Args:
        item: 条件项（应为 dict，包含 indicator/op/value）
        path: 当前路径（用于错误提示）
    
    Returns:
        规范化后的条件 dict: {"indicator": str, "op": str, "value": float}
    
    Raises:
        AlertValidationError: 当 item 格式不合法时
    """
    if not isinstance(item, dict):
        raise AlertValidationError(f"{path} must be an object")

    indicator = str(item.get("indicator") or "").strip()
    op = str(item.get("op") or "").strip()
    if not indicator or not op:
        raise AlertValidationError(f"{path} missing indicator/op")

    try:
        value = float(item.get("value"))
    except (TypeError, ValueError) as exc:
        raise AlertValidationError(f"{path} has invalid value") from exc

    return {"indicator": indicator, "op": op, "value": value}


def normalize_conditions_tree(node: Any, path: str = "conditions") -> Any:
    """
    递归规范化条件树（支持 AND/OR 逻辑嵌套）。
    
    Args:
        node: 条件节点（可以是 list 或 dict）
        path: 当前路径（用于错误提示）
    
    Returns:
        规范化后的条件树：
        - 如果是叶子节点：{"indicator": str, "op": str, "value": float}
        - 如果是逻辑节点：{"logic": "AND"|"OR", "rules": [...]}
    
    Raises:
        AlertValidationError: 当节点格式不合法时
    """
    if isinstance(node, list):
        if not node:
            raise AlertValidationError(f"{path} must be a non-empty list")
        return [
            normalize_conditions_tree(item, f"{path}[{idx}]")
            for idx, item in enumerate(node)
        ]

    if not isinstance(node, dict):
        raise AlertValidationError(f"{path} must be an object or list")

    # 叶子节点：包含 indicator 字段
    if "indicator" in node:
        return normalize_single_condition(node, path)

    # 逻辑节点：包含 logic 和 rules
    logic = str(node.get("logic", "AND") or "AND").upper()
    if logic not in {"AND", "OR"}:
        raise AlertValidationError(f"{path}.logic must be AND or OR")

    rules = node.get("rules")
    if not isinstance(rules, list) or not rules:
        raise AlertValidationError(f"{path}.rules must be a non-empty list")

    return {
        "logic": logic,
        "rules": [
            normalize_conditions_tree(item, f"{path}.rules[{idx}]")
            for idx, item in enumerate(rules)
        ],
    }


def coerce_alert_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    校验并规范化告警 payload。
    
    Args:
        payload: 原始告警 payload，应包含：
            - name: 告警名称（必填，非空字符串）
            - period: 周期（必填，仅限 5min/15min/30min/60min）
            - conditions: 条件树（必填）
            - cooldown: 冷却时间（可选，默认 300，要求 int >= 0）
            - ref_periods: 引用周期列表（可选，默认 []）
    
    Returns:
        规范化后的 payload dict:
            {
                "name": str,
                "period": str,
                "ref_periods": list[str],
                "conditions": normalized_conditions,
                "cooldown": int,
            }
    
    Raises:
        AlertValidationError: 当 payload 不合法时
    """
    name = str(payload.get("name") or "").strip()
    period = str(payload.get("period") or "").strip()
    conditions = payload.get("conditions")
    cooldown_raw = payload.get("cooldown", 300)
    raw_ref_periods = payload.get("ref_periods", []) or []

    # 基础校验
    if not name:
        raise AlertValidationError("Alert name is required")
    if period not in {"5min", "15min", "30min", "60min"}:
        raise AlertValidationError(f"Unsupported alert period: {period}")

    # ref_periods 校验
    if not isinstance(raw_ref_periods, list):
        raise AlertValidationError("ref_periods must be a list")
    ref_periods = [str(p).strip() for p in raw_ref_periods if str(p).strip()]

    # 条件树规范化
    normalized_conditions = normalize_conditions_tree(conditions)

    # cooldown 校验
    try:
        cooldown = int(cooldown_raw)
    except (TypeError, ValueError) as exc:
        raise AlertValidationError("Cooldown must be an integer") from exc
    if cooldown < 0:
        raise AlertValidationError("Cooldown must be >= 0")

    # 使用 AlertRule 做最终合法性校验
    try:
        AlertRule(
            {
                "name": name,
                "period": period,
                "conditions": normalized_conditions,
                "ref_periods": ref_periods,
                "cooldown": cooldown,
            }
        )
    except Exception as exc:
        raise AlertValidationError(str(exc)) from exc

    return {
        "name": name,
        "period": period,
        "ref_periods": ref_periods,
        "conditions": normalized_conditions,
        "cooldown": cooldown,
    }


# =============================================================================
# C. Alert 列表读写函数（纯数据变换，不直接 save_config）
# =============================================================================

def list_alerts(config: dict) -> list[dict]:
    """
    从 config 中提取 alerts 列表。
    
    Args:
        config: 配置 dict（来自 load_config）
    
    Returns:
        alerts 列表（如果 config 中没有 alerts 或不是 list，返回 []）
    """
    alerts = config.get("alerts", [])
    if not isinstance(alerts, list):
        return []
    return alerts


def add_alert(config: dict, payload: dict) -> list[dict]:
    """
    向 alerts 列表添加一条新告警。
    
    Args:
        config: 配置 dict
        payload: 告警 payload（将被 coerce_alert_payload 校验）
    
    Returns:
        更新后的 alerts 列表（已添加新告警）
    
    Raises:
        AlertValidationError: 当 payload 不合法时
    """
    alert = coerce_alert_payload(payload)
    alerts = list_alerts(config)
    alerts.append(alert)
    return alerts


def update_alert(config: dict, index: int, payload: dict) -> list[dict]:
    """
    更新指定索引的告警。
    
    Args:
        config: 配置 dict
        index: 告警索引（0-based）
        payload: 新的告警 payload
    
    Returns:
        更新后的 alerts 列表
    
    Raises:
        AlertIndexError: 当 index 越界时
        AlertValidationError: 当 payload 不合法时
    """
    alerts = list_alerts(config)
    if index < 0 or index >= len(alerts):
        raise AlertIndexError(f"Alert index out of range: {index}")
    
    alerts[index] = coerce_alert_payload(payload)
    return alerts


def delete_alert(config: dict, index: int) -> list[dict]:
    """
    删除指定索引的告警。
    
    Args:
        config: 配置 dict
        index: 告警索引（0-based）
    
    Returns:
        删除后的 alerts 列表
    
    Raises:
        AlertIndexError: 当 index 越界时
    """
    alerts = list_alerts(config)
    if index < 0 or index >= len(alerts):
        raise AlertIndexError(f"Alert index out of range: {index}")
    
    alerts.pop(index)
    return alerts


# =============================================================================
# D. Helper 函数
# =============================================================================

def apply_alerts_update(config: dict, alerts: list[dict]) -> dict:
    """
    将更新后的 alerts 列表应用回 config。
    
    Args:
        config: 原始配置 dict
        alerts: 更新后的 alerts 列表
    
    Returns:
        新的配置 dict（包含更新后的 alerts）
    """
    new_config = dict(config)
    new_config["alerts"] = alerts
    return new_config


# =============================================================================
# E. Alert Test 回放测试相关函数
# =============================================================================

class AlertTestError(AlertServiceError):
    """告警回放测试异常：测试过程中出错"""
    pass


class AlertTestNotFoundError(AlertTestError):
    """告警回放测试数据缺失：找不到目标日期的数据"""
    pass


def build_indicator_history_for_alert_test(
    market: str,
    symbol: str,
    period: str,
    target_date: str
) -> list[dict[str, Any]]:
    """
    为 alert test 构建指标历史数据。
    
    职责：
    - 加载多日 K 线历史
    - 计算 MACD / slope 系列
    - 只返回目标日期最近若干 bars 的结构化列表
    
    Args:
        market: 市场标识（如 'HK', 'A'）
        symbol: 股票代码
        period: K 线周期（5min/15min/30min/60min）
        target_date: 目标日期（YYYY-MM-DD）
    
    Returns:
        bars 列表，每个 bar 包含：
        - time: 时间字符串
        - macd, dea, hist: MACD 指标值
        - macd_slope, dea_slope, hist_slope: 斜率
    
    Raises:
        AlertTestNotFoundError: 当目标日期没有数据时
    """
    try:
        history_rows, target_rows = load_multi_day_rows(market, symbol, period, target_date)
    except Exception as exc:
        raise AlertTestNotFoundError(f"Failed to load data for {market}{symbol} {target_date}: {exc}") from exc
    
    if not target_rows:
        raise AlertTestNotFoundError(f"No {period} data found for {market}{symbol} {target_date}")
    
    # 构建 DataFrame 并计算指标
    df = pd.DataFrame(
        history_rows,
        columns=["calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"]
    )
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    engine = IndicatorEngine()
    engine.register(MACD(12, 26, 9))
    result = engine.calc_all(df).sort_values(by=["calc_time"]).copy()
    result["period"] = period
    
    # 只保留目标日期的数据
    target_result = result[result["date"] == target_date].copy()
    if target_result.empty:
        raise AlertTestNotFoundError(f"No indicator result found for {market}{symbol} {target_date}")
    
    # 只返回最近 20 根 bar
    target_result = target_result.tail(20)
    
    bars: list[dict[str, Any]] = []
    for _, row in target_result.iterrows():
        bars.append(
            {
                "time": str(row.get("bar_time", ""))[-5:],
                "macd": _safe_number(row.get("macd")),
                "dea": _safe_number(row.get("macd_dea")),
                "hist": _safe_number(row.get("macd_hist")),
                "macd_slope": _safe_number(row.get("macd_slope")),
                "dea_slope": _safe_number(row.get("macd_dea_slope")),
                "hist_slope": _safe_number(row.get("macd_hist_slope")),
            }
        )
    
    return bars


def test_alert_rule(
    payload: dict[str, Any],
    config: dict[str, Any],
    normalize_date_fn=None
) -> dict[str, Any]:
    """
    测试告警规则（回放测试）。
    
    职责：
    - 从 payload + config 解析：默认 symbol/market/date 等
    - 调用 coerce_alert_payload(...) 校验
    - 构造 AlertRule
    - 调用 build_indicator_history_for_alert_test(...)
    - 做 edge-trigger evaluation
    - 返回结构化结果 dict（不带 HTTP 细节）
    
    Args:
        payload: 测试请求 payload，包含：
            - name: 告警名称（可选）
            - period: 周期（必填）
            - conditions: 条件树（必填）
            - cooldown: 冷却时间（可选）
            - market: 市场（可选，默认从 watchlist 取）
            - symbol: 股票代码（可选，默认从 watchlist 取）
            - date: 目标日期（可选，默认今天）
        config: 配置 dict（包含 watchlist）
        normalize_date_fn: 日期规范化函数（可选，默认使用内置 normalize_date）
    
    Returns:
        dict 包含：
        - symbol: 股票代码
        - market: 市场标识
        - date: 测试日期
        - period: 周期
        - triggered_bars: 触发的 bar 时间列表
        - bar_details: 每个 bar 的详细信息（含 triggered 标记）
        - total_bars_tested: 测试的 bar 总数
        - edge_triggered_count: 触发的 bar 数量
    
    Raises:
        AlertValidationError: 当 payload 不合法时
        AlertTestNotFoundError: 当找不到数据时
        AlertTestError: 其他测试错误
    """
    from datetime import datetime
    
    # 日期规范化函数
    if normalize_date_fn is None:
        def normalize_date(value: str | None) -> str:
            DATE_FMT = "%Y-%m-%d"
            if value:
                return datetime.strptime(str(value).strip(), DATE_FMT).strftime(DATE_FMT)
            return datetime.now().strftime(DATE_FMT)
        normalize_date_fn = normalize_date
    
    # 从 config 获取默认 watchlist 标的
    watchlist = config.get("watchlist", [])
    default_stock = watchlist[0] if isinstance(watchlist, list) and watchlist else {}
    
    # 解析参数
    period = str(payload.get("period") or "15min").strip()
    conditions = payload.get("conditions")
    market = str(payload.get("market") or default_stock.get("market") or "HK").upper().strip()
    symbol = str(payload.get("symbol") or default_stock.get("symbol") or "").strip()
    target_date = normalize_date_fn(payload.get("date"))
    
    # 校验 symbol
    if not symbol:
        raise AlertTestError("No symbol provided and watchlist is empty")
    
    # 构建 rule payload 并校验
    rule_payload = {
        "name": str(payload.get("name") or "回放测试规则").strip() or "回放测试规则",
        "period": period,
        "conditions": conditions,
        "cooldown": int(payload.get("cooldown", 0) or 0),
    }
    normalized_rule = coerce_alert_payload(rule_payload)
    rule = AlertRule(normalized_rule)
    
    # 构建指标历史
    bars = build_indicator_history_for_alert_test(market, symbol, period, target_date)
    
    # 校验 bars 数量
    if len(bars) < 3:
        raise AlertTestError(f"Not enough bars to test rule: {len(bars)}")
    
    # 执行 edge-trigger evaluation
    triggered_bars: list[str] = []
    bar_details: list[dict[str, Any]] = []
    
    for i in range(2, len(bars)):
        current = bars[i]
        prev = bars[i - 1]
        prev_prev = bars[i - 2]
        triggered = rule.evaluate(current, prev, prev_prev)
        detail = dict(current)
        detail["triggered"] = triggered
        bar_details.append(detail)
        if triggered:
            triggered_bars.append(current["time"])
    
    return {
        "symbol": symbol,
        "market": market,
        "date": target_date,
        "period": period,
        "triggered_bars": triggered_bars,
        "bar_details": bar_details,
        "total_bars_tested": len(bars),
        "edge_triggered_count": len(triggered_bars),
    }


def _safe_number(value: Any) -> float:
    """
    安全地将值转换为 float，处理 None、NaN 和 Inf。
    
    Args:
        value: 要转换的值
    
    Returns:
        float 值，如果转换失败或值无效则返回 0.0
    """
    import math
    if value is None:
        return 0.0
    try:
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return 0.0
        return round(num, 6)
    except Exception:
        return 0.0
