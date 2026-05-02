# -*- coding: utf-8 -*-
"""腾讯数据源接口"""
from __future__ import annotations

import json
import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Any

from .base import (
    DataSourceError,
    TENCENT_MINUTE_URL,
    TENCENT_REALTIME_URL,
    REALTIME_TIMEOUT,
    session,
)
from .utils import (
    _strip_js_wrapper,
    _safe_float,
    _safe_int,
    _normalize_market,
    _market_code,
    _normalize_realtime_time,
)


def parse_tencent_resp(resp: requests.Response, market: str, code: str) -> dict[str, Any]:
    """解析腾讯实时行情响应"""
    text = resp.content.decode("gbk", errors="ignore").strip()
    if "~" not in text:
        raise DataSourceError(f"unexpected realtime response: {text[:120]}")

    fields = text.split("~")
    if len(fields) < 38:
        raise DataSourceError(f"unexpected realtime field count: {len(fields)}")

    name = fields[1].strip() or fields[0].strip()
    return {
        "name": name,
        "open": round(_safe_float(fields[5]), 3),
        "prev_close": round(_safe_float(fields[4]), 3),
        "high": round(_safe_float(fields[33]), 3),
        "low": round(_safe_float(fields[34]), 3),
        "current": round(_safe_float(fields[3]), 3),
        "change": round(_safe_float(fields[31]), 3),
        "change_pct": round(_safe_float(fields[32]), 3),
        "volume": _safe_int(fields[6]),
        "amount": round(_safe_float(fields[37]), 3),
        "time": _normalize_realtime_time(fields[30].strip()),
    }


def _fetch_tencent_realtime(market: str, code: str) -> dict[str, Any]:
    """获取腾讯实时行情"""
    resp = session.get(TENCENT_REALTIME_URL.format(code=code), timeout=REALTIME_TIMEOUT)
    resp.raise_for_status()
    return parse_tencent_resp(resp, market, code)


def _parse_tencent_minute_payload(symbol: str, market: str = "HK") -> list[dict[str, Any]]:
    """解析腾讯分钟 K 线数据"""
    code = _market_code(symbol, market)
    resp = session.get(TENCENT_MINUTE_URL, params={"code": code}, timeout=8)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type.lower():
        payload = resp.json()
    else:
        text = resp.text.strip()
        payload = json.loads(text) if text.startswith("{") else _strip_js_wrapper(text)

    minute_data = payload.get("data", {}).get(code, {}).get("data", {})
    
    # 尝试解析 day 格式（数组的数组）
    day_bars = minute_data.get("day", [])
    if day_bars:
        result: list[dict[str, Any]] = []
        for item in day_bars:
            if not isinstance(item, list) or len(item) < 6:
                continue
            bar_time = str(item[0]).strip()
            if not re.match(r"^\d{2}:\d{2}$", bar_time):
                continue
            result.append(
                {
                    "bar_time": bar_time,
                    "time": bar_time,
                    "open": round(_safe_float(item[1]), 3),
                    "close": round(_safe_float(item[2]), 3),
                    "high": round(_safe_float(item[3]), 3),
                    "low": round(_safe_float(item[4]), 3),
                    "volume": _safe_int(item[5]),
                }
            )
        return result

    # 尝试解析 min 格式（数组的数组）
    min_bars = minute_data.get("min", [])
    if min_bars:
        result = []
        for item in min_bars:
            if not isinstance(item, list) or len(item) < 6:
                continue
            result.append(
                {
                    "bar_time": str(item[0]),
                    "time": str(item[0]),
                    "open": round(_safe_float(item[1]), 3),
                    "close": round(_safe_float(item[2]), 3),
                    "high": round(_safe_float(item[3]), 3),
                    "low": round(_safe_float(item[4]), 3),
                    "volume": _safe_int(item[5]),
                }
            )
        return result
    
    # 尝试解析 data 格式（字符串数组，如 "0930 31.540 8337180 260324502.000"）
    data_bars = minute_data.get("data", [])
    if data_bars and isinstance(data_bars, list):
        result = []
        prev_close = None
        for item in data_bars:
            if not isinstance(item, str):
                continue
            parts = item.strip().split()
            if len(parts) < 4:
                continue
            # 格式: "时间 价格 成交量 成交额"
            # 注意：腾讯分钟线只返回当前价格，需要通过相邻bar计算open/high/low
            time_str = parts[0]
            # 格式化时间：0930 -> 09:30
            if len(time_str) == 4 and time_str.isdigit():
                bar_time = f"{time_str[:2]}:{time_str[2:]}"
            elif len(time_str) == 5 and ":" in time_str:
                bar_time = time_str
            else:
                continue
            
            close_price = round(_safe_float(parts[1]), 3)
            volume = _safe_int(parts[2])
            # amount = round(_safe_float(parts[3]), 3)  # 成交额暂不使用
            
            # 对于分钟线，腾讯只返回当前价格，我们用当前价格作为close
            # open/high/low 需要通过前后bar计算或使用相同值
            if prev_close is not None:
                open_price = prev_close
            else:
                open_price = close_price
            
            high_price = max(open_price, close_price)
            low_price = min(open_price, close_price)
            
            result.append(
                {
                    "bar_time": bar_time,
                    "time": bar_time,
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": volume,
                }
            )
            prev_close = close_price
        return result

    return []


def fetch_1min(symbol: str, market: str = "HK", count: int = 400) -> list[dict]:
    """获取 1 分钟 K 线数据"""
    return _parse_tencent_minute_payload(symbol, market)[:count]


def _infer_a_prefix(symbol: str) -> str | None:
    """推断 A 股代码的交易所前缀。

    - 60/68 开头 → sh（沪市，含科创板）
    - 00/30 开头 → sz（深市，含创业板）
    - 920/8/4 开头 → bj（北交所）→ 返回 None（腾讯不支持）
    - 其他 → None
    """
    if symbol.startswith(("60", "68")):
        return "sh"
    if symbol.startswith(("00", "30")):
        return "sz"
    # 北交所：920xxx / 8xxxxx / 4xxxxx
    if symbol.startswith(("920", "8", "4")):
        return None  # 北交所，腾讯不支持
    return None


def _fetch_a_kline_tencent(
    symbol: str,
    start_date: str,
    end_date: str,
    count: int,
) -> list[dict[str, Any]]:
    """从腾讯接口获取 A 股日线数据（前复权）。

    Args:
        symbol: 6 位股票代码，如 '600519', '000001'
        start_date: 起始日期，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        count: 请求条数

    Returns:
        与 _sina_bar_to_dict 统一格式的日线列表。
        北交所股票直接返回 []。
    """
    prefix = _infer_a_prefix(symbol)
    if prefix is None:
        # 北交所或不支持的市场
        return []

    # 日期格式：保持 YYYY-MM-DD（腾讯接口要求此格式，空字符串则返回最近 count 条）
    s = start_date.strip()
    e = end_date.strip()

    # 腾讯是国内服务器，临时清空代理
    old_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    old_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        os.environ["HTTP_PROXY"] = ""
        os.environ["HTTPS_PROXY"] = ""
        os.environ["http_proxy"] = ""
        os.environ["https_proxy"] = ""

        full_code = f"{prefix}{symbol}"
        param = f"{full_code},day,{s},{e},{count},qfq"
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

        resp = requests.get(url, params={"_var": "k", "param": param}, timeout=15)
        resp.raise_for_status()

        # 去除 JS 变量前缀（'var k=' 或 'k='）
        text = resp.text.strip()
        if text.startswith("var k="):
            text = text[6:]
        elif text.startswith("k="):
            text = text[2:]

        payload = json.loads(text)

        if payload.get("code") != 0:
            return []

        data = payload.get("data", {})
        stock_data = data.get(full_code, {})

        # qfqday: [[date, open, close, high, low, volume], ...]
        raw_bars = stock_data.get("qfqday", [])
        if not raw_bars:
            return []

        result = []
        for bar in raw_bars:
            if not isinstance(bar, list) or len(bar) < 6:
                continue
            result.append(
                {
                    "bar_time": str(bar[0])[:10],
                    "open": round(_safe_float(bar[1]), 3),
                    "high": round(_safe_float(bar[3]), 3),
                    "low": round(_safe_float(bar[4]), 3),
                    "close": round(_safe_float(bar[2]), 3),
                    "volume": _safe_int(bar[5]),
                    "amount": 0.0,
                    "turnover": None,
                }
            )

        return result

    finally:
        # 恢复代理设置
        if old_http:
            os.environ["HTTP_PROXY"] = old_http
            os.environ["http_proxy"] = old_http
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("http_proxy", None)
        if old_https:
            os.environ["HTTPS_PROXY"] = old_https
            os.environ["https_proxy"] = old_https
        else:
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("https_proxy", None)
