# -*- coding: utf-8 -*-
"""数据源模块 - 统一导出接口"""
from __future__ import annotations

from typing import Any

from .base import DataSourceError, session, DEFAULT_TIMEOUT, REALTIME_TIMEOUT
from .utils import (
    _strip_js_wrapper,
    _safe_float,
    _safe_int,
    _normalize_symbol,
    _normalize_market,
    _infer_a_prefix,
    _market_code,
    _resolve_daily_args,
    _normalize_realtime_time,
)
from .tencent import (
    parse_tencent_resp,
    _fetch_tencent_realtime,
    _parse_tencent_minute_payload,
    fetch_1min,
    _fetch_a_kline_tencent,
)
from .sina import (
    parse_sina_resp,
    _fetch_sina_realtime,
)
from .akshare import (
    _sina_bar_to_dict,
    fetch_a_daily,
    fetch_a_weekly,
    fetch_a_monthly,
    _aggregate_period,
)
from .yfinance import (
    fetch_hk_kline,
    fetch_hk_daily,
    fetch_hk_weekly,
    fetch_hk_monthly,
    fetch_hk_minute,
)

# 重新导出主要接口（向后兼容）
__all__ = [
    "DataSourceError",
    "fetch_1min",
    "fetch_daily",
    "fetch_realtime",
    "fetch_kline",
    "fetch_a_daily",
    "fetch_a_weekly",
    "fetch_a_monthly",
    "fetch_turnover_rate",
    "fetch_chip_distribution",
]


# ===== 以下函数保持向后兼容，内部调用新模块 =====

def fetch_daily(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    count: int = 0,
    market: str = "HK",
) -> list[dict]:
    """获取日线数据（向后兼容）"""
    from .tencent import _parse_tencent_minute_payload
    
    start, end, count, norm_market = _resolve_daily_args(start, end, count, market)
    
    if norm_market == "A":
        return fetch_a_daily(symbol, count=count, with_indicators=False)
    
    return _parse_tencent_minute_payload(symbol, norm_market)[:count] if count > 0 else _parse_tencent_minute_payload(symbol, norm_market)


def _fetch_realtime_hk_sina(symbol: str) -> dict[str, Any]:
    """获取港股实时数据（新浪 fallback）"""
    from .sina import _fetch_sina_realtime
    return _fetch_sina_realtime("HK", f"hk{symbol}")


def fetch_realtime(symbol: str, market: str = "HK") -> dict:
    """获取实时行情（向后兼容）"""
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
    
    market = _normalize_market(market)
    code = _market_code(symbol, market)

    results: dict[str, dict[str, Any]] = {}
    tasks = {
        "tencent": lambda: _fetch_tencent_realtime(market, code),
        "sina": lambda: _fetch_sina_realtime(market, code),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(task): source for source, task in tasks.items()}
        try:
            for future in as_completed(future_map, timeout=REALTIME_TIMEOUT):
                source = future_map[future]
                try:
                    data = future.result()
                except Exception:
                    continue
                if data and data.get("time"):
                    results[source] = data
        except TimeoutError:
            pass

    if not results:
        if market == "HK":
            try:
                return _fetch_realtime_hk_sina(symbol)
            except Exception:
                pass
        raise DataSourceError(f"数据源不可用：{symbol}")

    best_source, best = max(results.items(), key=lambda item: item[1].get("time", ""))
    best = dict(best)
    best["source"] = best_source
    return best


def fetch_kline(symbol: str, market: str = "HK", period: str = "1min", count: int = 400) -> list[dict]:
    """获取 K 线数据（向后兼容）"""
    market = _normalize_market(market)
    
    if market == "A":
        # A 股：使用 akshare
        if period == "daily":
            return fetch_a_daily(symbol, count=count, with_indicators=False)
        elif period == "weekly":
            return fetch_a_weekly(symbol, count=count)
        elif period == "monthly":
            return fetch_a_monthly(symbol, count=count)
        else:
            # A 股分钟数据暂时返回空（不支持）
            return []
    else:
        # 港股：使用 yfinance
        if period in ["1d", "1wk", "1mo"]:
            return fetch_hk_kline(symbol, period=period, count=count)
        elif period in ["1min", "5min", "15min", "30min", "60min"]:
            return fetch_hk_minute(symbol, period=period, count=count)
        else:
            # 默认返回 1min 数据（腾讯源）
            return fetch_1min(symbol, "HK", count)


def fetch_turnover_rate(symbol: str, market: str = "A") -> float:
    """获取换手率（向后兼容）"""
    if market == "A":
        return _fetch_turnover_rate_a_sina(symbol)
    else:
        return _fetch_turnover_rate_hk_tencent(symbol)


def _fetch_turnover_rate_a_sina(symbol: str) -> float:
    """获取 A 股换手率（新浪源）"""
    import akshare as ak
    
    prefix = _infer_a_prefix(symbol)
    pure = re.sub(r"^(?:sh|sz|bj)", "", symbol, flags=re.IGNORECASE)
    sina_symbol = f"{prefix}{pure}"
    
    try:
        df = ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq")
        if df.empty:
            return 0.0
        latest = df.iloc[-1]
        return round(float(latest.get("turnover", 0)) * 100, 4)
    except Exception:
        return 0.0


def _fetch_turnover_rate_hk_tencent(symbol: str) -> float:
    """获取港股换手率（腾讯源）"""
    try:
        data = _fetch_tencent_realtime("HK", f"hk{symbol}")
        return round(float(data.get("change_pct", 0)), 4)
    except Exception:
        return 0.0


def fetch_chip_distribution(symbol: str, market: str = "A") -> dict:
    """获取筹码分布（向后兼容）"""
    from calc_chip_dist import calc_chip_distribution
    
    if market == "A":
        kline = fetch_a_daily(symbol, count=120, with_indicators=False)
    else:
        kline = fetch_1min(symbol, market, count=120)
    
    return calc_chip_distribution(kline_data=kline, use_real_turnover=True)
