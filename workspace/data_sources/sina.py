# -*- coding: utf-8 -*-
"""新浪数据源接口"""
from __future__ import annotations

import re
import requests
from typing import Any

from .base import DataSourceError, SINA_REALTIME_URL, session
from .utils import _safe_float, _safe_int, _normalize_realtime_time, _normalize_market, _market_code


def parse_sina_resp(resp: requests.Response, market: str, code: str) -> dict[str, Any]:
    """解析新浪实时行情响应"""
    text = resp.content.decode("gbk", errors="ignore").strip()
    match = re.search(r'var\s+hq_str_[^=]+="([^"]*)";', text)
    if not match:
        raise DataSourceError(f"unexpected sina realtime response: {text[:120]}")

    fields = match.group(1).split(",")
    
    if market == "HK":
        if len(fields) < 19 or not fields[0]:
            raise DataSourceError(f"unexpected HK sina realtime field count: {len(fields)}")
        return {
            "name": fields[0].strip(),
            "open": round(_safe_float(fields[2]), 3),
            "prev_close": round(_safe_float(fields[3]), 3),
            "high": round(_safe_float(fields[4]), 3),
            "low": round(_safe_float(fields[5]), 3),
            "current": round(_safe_float(fields[6]), 3),
            "change": round(_safe_float(fields[7]), 3),
            "change_pct": round(_safe_float(fields[8]), 3),
            "volume": _safe_int(fields[12]),
            "amount": round(_safe_float(fields[11]), 3),
            "time": _normalize_realtime_time(fields[18], fallback_date=fields[17]),
        }

    if len(fields) < 32 or not fields[0]:
        raise DataSourceError(f"unexpected A-share sina realtime field count: {len(fields)}")

    open_price = round(_safe_float(fields[1]), 3)
    prev_close = round(_safe_float(fields[2]), 3)
    current = round(_safe_float(fields[3]), 3)
    change = round(current - prev_close, 3)
    change_pct = round((change / prev_close * 100) if prev_close else 0.0, 3)
    return {
        "name": fields[0].strip(),
        "open": open_price,
        "prev_close": prev_close,
        "high": round(_safe_float(fields[4]), 3),
        "low": round(_safe_float(fields[5]), 3),
        "current": current,
        "change": change,
        "change_pct": change_pct,
        "volume": _safe_int(fields[8]),
        "amount": round(_safe_float(fields[9]), 3),
        "time": _normalize_realtime_time(f"{fields[30]} {fields[31]}"),
    }


def _fetch_sina_realtime(market: str, code: str) -> dict[str, Any]:
    """获取新浪实时行情"""
    resp = session.get(
        SINA_REALTIME_URL.format(code=code),
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=5,
    )
    resp.raise_for_status()
    return parse_sina_resp(resp, market, code)
