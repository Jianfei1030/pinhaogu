# -*- coding: utf-8 -*-
"""数据源工具函数 - 代码转换/市场推断/时间格式化"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .base import DataSourceError


def _strip_js_wrapper(text: str) -> dict[str, Any]:
    """移除 JSONP 包装器"""
    payload = re.sub(r"^[^{]*", "", text).strip()
    if not payload:
        raise DataSourceError("empty response payload")
    return json.loads(payload)


def _safe_float(value: Any) -> float:
    """安全转换为 float"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    """安全转换为 int"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _normalize_symbol(symbol: str) -> str:
    """标准化股票代码"""
    return str(symbol).strip()


def _normalize_market(market: str | None) -> str:
    """标准化市场名称"""
    text = str(market or "HK").strip().upper()
    if text in {"A", "ASHARE", "A-SHARE", "CN"}:
        return "A"
    return "HK"


def _infer_a_prefix(symbol: str) -> str:
    """推断 A 股市场前缀（sh/sz/bj）。
    
    规则：
    - 920xxx: 北交所 → bj
    - 6xxxxx: 沪市 → sh
    - 5xxxxx: 沪市基金 → sh
    - 0xxxxx: 深市 → sz
    - 3xxxxx: 深市创业板 → sz
    """
    symbol = _normalize_symbol(symbol).lower()
    if symbol.startswith(("sh", "sz", "bj")) and len(symbol) >= 8:
        return symbol[:2]

    pure = symbol
    if pure.startswith("bj") and len(pure) >= 8:
        pure = pure[2:]

    if pure.startswith("920"):
        return "bj"
    
    if pure.startswith(("5", "6")):
        return "sh"
    
    return "sz"


def _market_code(symbol: str, market: str = "HK") -> str:
    """生成市场代码（如 hk01810, sh600000）"""
    symbol = _normalize_symbol(symbol)
    market = _normalize_market(market)

    lowered = symbol.lower()
    if lowered.startswith(("hk", "sh", "sz", "bj")) and len(lowered) >= 8:
        if market == "HK" and lowered.startswith("hk"):
            return lowered
        if market == "A" and lowered.startswith(("sh", "sz")):
            return lowered
        symbol = lowered[2:]

    if market == "HK":
        return f"hk{symbol}"

    prefix = _infer_a_prefix(symbol)
    pure = re.sub(r"^(?:sh|sz|bj)", "", symbol, flags=re.IGNORECASE)
    return f"{prefix}{pure}"


def _resolve_daily_args(
    start: str | None,
    end: str | None,
    count: int,
    market: str,
) -> tuple[str, str, int, str]:
    """解析日线参数"""
    if isinstance(start, str) and start.strip().upper() in {"HK", "A", "ASHARE", "A-SHARE", "CN"}:
        market = start
        start = None
        if isinstance(end, str) and end.strip().upper() in {"HK", "A", "ASHARE", "A-SHARE", "CN"}:
            end = None

    return start or "", end or "", int(count), _normalize_market(market)


def _normalize_realtime_time(value: str, fallback_date: str | None = None) -> str:
    """标准化实时数据时间戳"""
    text = str(value or "").strip()
    if not text:
        return ""

    patterns = [
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(text, pattern)
            return dt.strftime("%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue

    if fallback_date:
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                dt = datetime.strptime(f"{fallback_date} {text}", f"%Y/%m/%d {pattern}")
                return dt.strftime("%Y/%m/%d %H:%M:%S")
            except ValueError:
                continue

    return text
