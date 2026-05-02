# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from data_source import fetch_1min
from database import get_db_path, init_db, upsert_kline


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _bar_label(dt: datetime, interval_min: int) -> str:
    minute = dt.minute

    if interval_min == 5:
        if minute == 0:
            return _format_time(dt)
        end_minute = ((minute - 1) // 5 + 1) * 5
        if end_minute == 60:
            return _format_time(dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        return _format_time(dt.replace(minute=end_minute, second=0, microsecond=0))

    if interval_min == 15:
        if dt.hour == 12 and minute == 0:
            return "13:00"
        if minute == 0:
            return _format_time(dt)
        if minute <= 15:
            end_minute = 15
        elif minute <= 30:
            end_minute = 30
        elif minute <= 45:
            end_minute = 45
        else:
            end_minute = 60
        if end_minute == 60:
            return _format_time(dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        return _format_time(dt.replace(minute=end_minute, second=0, microsecond=0))

    if interval_min == 30:
        if dt.hour == 12 and minute == 0:
            return "13:00"
        if minute == 0:
            return _format_time(dt)
        if minute <= 30:
            return _format_time(dt.replace(minute=30, second=0, microsecond=0))
        return _format_time(dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

    if interval_min == 60:
        if minute == 0:
            return _format_time(dt)
        if dt.hour == 9 and minute == 30:
            return "09:00"
        return _format_time(dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

    raise ValueError(f"unsupported interval: {interval_min}")


def aggregate(records: list[dict], interval_min: int, override_close: bool = False) -> list[dict]:
    """聚合1分钟K线为多分钟K线。
    
    Args:
        override_close: 如果True，用1分钟线最后一根的close覆盖最后一个bar的close。
                        用于处理尾盘竞价（如港股16:00-16:08）导致最后一个bar的close不准确的情况。
    """
    if interval_min not in {5, 15, 30, 60}:
        raise ValueError(f"unsupported interval: {interval_min}")
    if not records:
        return []

    grouped: OrderedDict[str, dict] = OrderedDict()

    for row in records:
        bar_time = _bar_label(_parse_time(row["time"]), interval_min)
        if bar_time not in grouped:
            grouped[bar_time] = {
                "bar_time": bar_time,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": int(row.get("volume", 0)),
                "amount": float(row.get("amount", 0.0)),
            }
            continue

        target = grouped[bar_time]
        target["high"] = max(target["high"], row["high"])
        target["low"] = min(target["low"], row["low"])
        target["close"] = row["close"]
        target["volume"] += int(row.get("volume", 0))
        target["amount"] += float(row.get("amount", 0.0))

    result = list(grouped.values())
    
    # 过滤掉 close=0 的异常bar（开盘初瞬时数据异常）
    result = [row for row in result if row["close"] > 0]
    
    # 用1分钟线最后一根的收盘价覆盖最后一个bar的close（处理尾盘竞价）
    if override_close and records:
        last_close = float(records[-1].get("close", result[-1]["close"]))
        result[-1]["close"] = round(last_close, 3)
    
    for row in result:
        row["amount"] = round(row["amount"], 3)
    return result


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_db_path(market: str, symbol: str, date: str) -> str:
    relative = get_db_path(market, symbol, date)
    return (_project_root() / relative).as_posix()


def run_pipeline(symbol: str, market: str = "HK", date: str | None = None) -> str:
    """完整数据管道。"""
    market = str(market).upper().strip()
    symbol = str(symbol).strip()
    date = date or datetime.now().strftime("%Y-%m-%d")

    records_1min = fetch_1min(symbol, market)
    if not records_1min:
        raise RuntimeError(f"no 1min records fetched for {market}{symbol}")

    db_path = _resolve_db_path(market, symbol, date)
    init_db(db_path)

    rows_1min = [
        {
            "bar_time": row["time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": int(row.get("volume", 0)),
            "amount": float(row.get("amount", 0.0)),
        }
        for row in records_1min
    ]
    upsert_kline(db_path, "kline_1min", rows_1min)

    for interval in (5, 15, 30, 60):
        upsert_kline(db_path, f"kline_{interval}min", aggregate(records_1min, interval, override_close=True))

    return db_path


def aggregate_120min(records_60min: list[dict]) -> list[dict]:
    """聚合 60min K 线为 120min K 线。
    
    每 2 根 60min bar 合并为 1 根 120min bar:
    - open = 第一根的 open
    - high = max(两根)
    - low = min(两根)
    - close = 第二根的 close
    - volume = 两根相加
    - bar_time 格式："HH:MM"
    """
    if not records_60min:
        return []
    
    # 按 bar_time 排序
    sorted_records = sorted(records_60min, key=lambda r: r["bar_time"])
    
    result = []
    i = 0
    while i < len(sorted_records):
        first = sorted_records[i]
        
        # 如果有下一根，合并两根
        if i + 1 < len(sorted_records):
            second = sorted_records[i + 1]
            bar = {
                "bar_time": first["bar_time"],
                "open": first["open"],
                "high": max(first["high"], second["high"]),
                "low": min(first["low"], second["low"]),
                "close": second["close"],
                "volume": int(first.get("volume", 0)) + int(second.get("volume", 0)),
                "amount": round(
                    float(first.get("amount", 0.0)) + float(second.get("amount", 0.0)),
                    3
                ),
            }
            i += 2
        else:
            # 最后一根单独处理（如果总数是奇数）
            bar = {
                "bar_time": first["bar_time"],
                "open": first["open"],
                "high": first["high"],
                "low": first["low"],
                "close": first["close"],
                "volume": int(first.get("volume", 0)),
                "amount": round(float(first.get("amount", 0.0)), 3),
            }
            i += 1
        
        result.append(bar)
    
    return result


def _query_table(db_path: str, table: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT bar_time, open, high, low, close, volume, amount FROM {table} ORDER BY bar_time ASC"
        ).fetchall()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    target_symbol = "01810"
    target_market = "HK"
    target_date = "2026-03-23"

    db_file = run_pipeline(target_symbol, target_market, target_date)
    print(f"db_path: {db_file}")

    for table in ("kline_1min", "kline_5min", "kline_15min", "kline_30min", "kline_60min"):
        rows = _query_table(db_file, table)
        print(f"{table}: count={len(rows)}")
        for row in rows[:3]:
            print("  ", row)

    rows_15 = _query_table(db_file, "kline_15min")
    row_1415 = next((row for row in rows_15 if row["bar_time"] == "14:15"), None)
    if row_1415 is None:
        raise RuntimeError("14:15 bar not found in kline_15min")
    print(f"15min 14:15 close = {row_1415['close']}")


def aggregate_120min(records_60min: list[dict]) -> list[dict]:
    """从 60min 数据聚合 120min。每 2 根 60min bar 合并为 1 根。"""
    if not records_60min:
        return []
    result = []
    for i in range(0, len(records_60min) - 1, 2):
        a = records_60min[i]
        b = records_60min[i + 1]
        result.append({
            "bar_time": a["bar_time"],
            "time": a["bar_time"],
            "open": a["open"],
            "high": max(a["high"], b["high"]),
            "low": min(a["low"], b["low"]),
            "close": b["close"],
            "volume": a["volume"] + b["volume"],
            "amount": a.get("amount", 0) + b.get("amount", 0),
        })
    return result
