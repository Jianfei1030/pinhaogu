# -*- coding: utf-8 -*-
"""
Monitor Indicator Service - 监控指标数据准备服务层

将 monitor.py 中的指标数据准备、MACD 计算、多周期数据收集逻辑下沉到 service 层。
为 R5.3b 接线做准备。

Usage:
    from workspace.services.monitor_indicator_service import (
        build_indicator_df,
        calc_macd_from_rows,
        calc_macd_from_db,
        collect_indicator_frames,
        MonitorIndicatorServiceError,
    )
    
    # 从 rows 构建 DataFrame
    df = build_indicator_df(rows)
    
    # 计算 MACD
    macd_df = calc_macd_from_rows(rows, engine=indicator_engine)
    
    # 从数据库计算 MACD
    macd_df = calc_macd_from_db(db_path, table='kline_15min')
    
    # 收集多周期指标帧
    frames = collect_indicator_frames(db_path, base_period='15min', ref_periods=['5min', '30min'])
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class MonitorIndicatorServiceError(Exception):
    """Monitor Indicator Service 业务异常"""
    pass


def build_indicator_df(rows: list[dict]) -> pd.DataFrame:
    """
    将 K 线数据 rows 转换为 DataFrame 并进行 numeric 转换
    
    Args:
        rows: K 线数据列表，每条包含 bar_time, open, high, low, close, volume, amount 等字段
    
    Returns:
        转换后的 DataFrame，数值列已转为 numeric 类型
    
    Notes:
        - 空数据返回空 DataFrame
        - 数值转换失败时转为 NaN，与 monitor.py 行为一致
    
    Examples:
        >>> rows = [
        ...     {"bar_time": "09:30", "open": "100.5", "close": "101.2"},
        ...     {"bar_time": "09:35", "open": "101.2", "close": "100.8"},
        ... ]
        >>> df = build_indicator_df(rows)
        >>> df.columns.tolist()
        ['bar_time', 'open', 'close']
        >>> df['open'].dtype
        dtype('float64')
    """
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    
    # 对数值列进行转换，与 monitor.py._build_indicator_df 保持一致
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    return df


def calc_macd_from_rows(
    rows: list[dict],
    engine: Any | None = None,
) -> pd.DataFrame:
    """
    从 K 线数据 rows 计算 MACD 指标
    
    Args:
        rows: K 线数据列表（已包含多日历史数据，按时间排序）
        engine: IndicatorEngine 实例（可选，如不提供则创建新实例）
    
    Returns:
        包含 MACD 指标的 DataFrame，包含 macd, macd_dea, macd_hist, macd_slope, macd_dea_slope, macd_hist_slope 列
    
    Notes:
        - 使用 IndicatorEngine + MACD 计算，与 monitor.py._calc_macd 保持一致
        - 空数据返回空 DataFrame
        - 结果按 calc_time 排序
    
    Examples:
        >>> from indicators import IndicatorEngine
        >>> from indicators.macd import MACD
        >>> engine = IndicatorEngine()
        >>> engine.register(MACD())
        >>> rows = [...]  # K 线数据
        >>> macd_df = calc_macd_from_rows(rows, engine)
        >>> "macd" in macd_df.columns
        True
    """
    if not rows:
        return pd.DataFrame()
    
    # 构建 DataFrame
    # rows 格式：[{"calc_time": ..., "bar_time": ..., "open": ..., "high": ..., ...}, ...]
    df = pd.DataFrame(rows, columns=[
        "calc_time", "bar_time", "open", "high", "low", "close", "volume", "amount", "date"
    ])
    
    # 数值转换
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # 创建或使用现有引擎
    if engine is None:
        from indicators import IndicatorEngine
        from indicators.macd import MACD
        engine = IndicatorEngine()
        engine.register(MACD())
    
    # 计算 MACD
    result = engine.calc_all(df).sort_values(by=["calc_time"]).copy()
    
    return result


def calc_macd_from_db(
    db_path: str,
    table: str = "kline_15min",
    engine: Any | None = None,
) -> pd.DataFrame:
    """
    从数据库读取 K 线数据并计算 MACD
    
    Args:
        db_path: 数据库文件路径
        table: K 线表名（默认 kline_15min）
        engine: IndicatorEngine 实例（可选）
    
    Returns:
        包含 MACD 指标的 DataFrame
    
    Notes:
        - 内部调用 calc_macd_from_rows，先读 DB 再计算
        - 空数据返回空 DataFrame
        - 与 monitor.py._calc_macd 语义保持一致
    
    Examples:
        >>> macd_df = calc_macd_from_db("data/HK/00700/2026-04-07.db", "kline_15min")
        >>> macd_df.empty
        False
    """
    from database import query_kline
    
    # 读取 K 线数据
    rows = query_kline(db_path, table)
    
    if not rows:
        return pd.DataFrame()
    
    # 转换为 calc_macd_from_rows 需要的格式
    # query_kline 返回的格式：{"bar_time": ..., "open": ..., ...}
    # 需要添加 calc_time 和 date 字段
    formatted_rows = []
    for row in rows:
        formatted_row = {
            "calc_time": row.get("bar_time", ""),
            "bar_time": row.get("bar_time", ""),
            "open": row.get("open", 0),
            "high": row.get("high", 0),
            "low": row.get("low", 0),
            "close": row.get("close", 0),
            "volume": row.get("volume", 0),
            "amount": row.get("amount", 0),
            "date": "",  # 从 db_path 提取日期
        }
        formatted_rows.append(formatted_row)
    
    # 从 db_path 提取日期
    # db_path format: .../data/{market}/{symbol}/{date}.db
    try:
        parts = Path(db_path).parts
        date = parts[-1].replace(".db", "")
        for row in formatted_rows:
            row["date"] = date
    except Exception:
        pass  # 日期提取失败不影响计算
    
    return calc_macd_from_rows(formatted_rows, engine=engine)


def _load_multi_day_rows_for_macd(
    market: str,
    symbol: str,
    period: str,
    target_date: str,
    db_dir: str | None = None,
) -> list[dict]:
    """
    加载多日历史数据用于 MACD 计算（内部 helper）
    
    从 server.py._load_multi_day_rows 简化而来，只保留 MACD 计算所需的数据加载逻辑。
    
    Args:
        market: 市场标识（HK/A）
        symbol: 股票代码
        period: K 线周期（5min/15min/30min/60min 等）
        target_date: 目标日期（YYYY-MM-DD）
        db_dir: 数据根目录（可选）
    
    Returns:
        按时间排序的 K 线数据列表
    
    Notes:
        - 这是内部 helper，不直接暴露给外部调用
        - 逻辑与 server.py._load_multi_day_rows 保持一致
    """
    from database import list_db_dates, query_kline_multi_days
    
    if db_dir is None:
        from config import get_config
        db_dir = str(Path(get_config('data.root', 'data')).resolve())
    
    # 计算需要加载多少天的数据
    days_needed = _days_needed_for_macd(period)
    
    # 获取已知的数据库日期
    known_dates = [
        d for d in list_db_dates(market, symbol, db_dir=db_dir)
        if d <= target_date
    ]
    if target_date not in known_dates:
        known_dates.insert(0, target_date)
    known_dates = sorted(set(known_dates), reverse=True)
    
    # 查询多日数据
    dates_to_query = list(reversed(known_dates[:days_needed]))
    rows = query_kline_multi_days(
        market,
        symbol,
        f"kline_{period}",
        dates_to_query,
        db_dir=db_dir,
    )
    
    return rows


def _days_needed_for_macd(period: str) -> int:
    """
    根据 K 线周期计算需要加载多少天的历史数据才能保证 MACD 计算准确
    
    Args:
        period: K 线周期（5min/15min/30min/60min 等）
    
    Returns:
        需要的天数
    
    Notes:
        - MACD(12,26,9) 需要至少 34 根 bar 才能收敛
        - 推荐 500+ 根 bar 以匹配东财数值
        - 与 server.py._days_needed_for_macd 保持一致
    """
    # 每个周期一天大约有多少根 K 线（港股交易时间约 4 小时）
    bars_per_day = {
        "1min": 240,
        "5min": 48,
        "15min": 16,
        "30min": 8,
        "60min": 4,
    }
    
    bars = bars_per_day.get(period, 4)
    
    # 目标 bar 数：至少 500 根，确保 MACD 充分收敛并与东财对齐
    min_bars = 500
    days = min(120, max(30, min_bars // bars + 1))  # 至少 30 天，最多 120 天
    
    return days


def collect_indicator_frames(
    db_path: str,
    base_period: str,
    ref_periods: list[str],
    alert_rules: list[Any] | None = None,
    engine: Any | None = None,
) -> dict[str, pd.DataFrame]:
    """
    收集多周期指标帧，用于后续告警检测
    
    Args:
        db_path: 数据库文件路径
        base_period: 基础周期（如 '15min'）
        ref_periods: 引用周期列表（如 ['5min', '30min']）
        alert_rules: 告警规则列表（可选，用于自动提取 ref_periods）
        engine: IndicatorEngine 实例（可选）
    
    Returns:
        周期到 DataFrame 的映射字典，格式：{period: DataFrame, ...}
        - 基础周期的 DataFrame 包含合并后的引用周期数据
        - 列名格式：{ref_period}_{indicator}（如 '5min_macd', '30min_macd_dea'）
    
    Notes:
        - 与 monitor.py._collect_indicator_frames 语义保持一致
        - ref_periods 的列名/合并语义与原版一致
        - 使用 ffill() 填充缺失值
    
    Examples:
        >>> frames = collect_indicator_frames(
        ...     db_path="data/HK/00700/2026-04-07.db",
        ...     base_period="15min",
        ...     ref_periods=["5min", "30min"]
        ... )
        >>> "15min" in frames
        True
        >>> "5min_macd" in frames["15min"].columns
        True
    """
    from monitor import AlertRule
    
    # 1. 收集所有需要的周期
    all_periods: set[str] = {base_period}
    ref_period_map: dict[str, set[str]] = {}
    
    # 从告警规则中提取额外的周期需求
    if alert_rules:
        for rule in alert_rules:
            period = str(rule.period)
            all_periods.add(period)
            rule_ref_periods = {
                str(ref).strip()
                for ref in getattr(rule, "ref_periods", [])
                if str(ref).strip()
            }
            if rule_ref_periods:
                all_periods.update(rule_ref_periods)
                ref_period_map.setdefault(period, set()).update(rule_ref_periods)
    
    # 合并用户指定的 ref_periods
    if ref_periods:
        all_periods.update(ref_periods)
        ref_period_map.setdefault(base_period, set()).update(ref_periods)
    
    # 2. 为每个周期计算 MACD
    frames: dict[str, pd.DataFrame] = {}
    for period in sorted(all_periods):
        table = f"kline_{period}"
        frames[period] = calc_macd_from_db(db_path, table, engine=engine)
    
    # 3. 合并引用周期数据到基础周期
    mergeable_columns = set(AlertRule.FIELD_ALIASES.values())
    
    for base_period_key, ref_periods_set in ref_period_map.items():
        base_df = frames.get(base_period_key)
        if base_df is None or base_df.empty:
            continue
        
        merged_df = base_df.copy()
        
        for ref_period in sorted(ref_periods_set):
            ref_df = frames.get(ref_period)
            if ref_df is None or ref_df.empty:
                continue
            
            # 选择要合并的列
            ref_cols = ["bar_time"]
            for col in ref_df.columns:
                if col == "bar_time":
                    continue
                if col in mergeable_columns and col not in ref_cols:
                    ref_cols.append(col)
            
            if len(ref_cols) <= 1:
                continue
            
            # 重命名列
            ref_subset = ref_df[ref_cols].copy()
            rename_map = {
                col: f"{ref_period}_{col}"
                for col in ref_cols
                if col != "bar_time"
            }
            ref_subset = ref_subset.rename(columns=rename_map)
            
            # 合并
            merged_df = merged_df.merge(ref_subset, on="bar_time", how="left")
            
            # 前向填充缺失值
            for col in rename_map.values():
                merged_df[col] = merged_df[col].ffill()
        
        frames[base_period_key] = merged_df
    
    return frames


# 便捷函数：从数据库路径自动提取 market/symbol/date
def _extract_db_path_info(db_path: str) -> dict[str, str]:
    """
    从数据库路径提取 market, symbol, date 信息（内部 helper）
    
    Args:
        db_path: 数据库文件路径，格式：.../data/{market}/{market}{symbol}/{date}.db
    
    Returns:
        包含 market, symbol, date 的字典
    
    Examples:
        >>> _extract_db_path_info("data/HK/HK00700/2026-04-07.db")
        {'market': 'HK', 'symbol': '00700', 'date': '2026-04-07'}
    """
    parts = Path(db_path).parts
    date = parts[-1].replace(".db", "")
    symbol_dir = parts[-2]
    market = parts[-3]
    
    # 提取 symbol（去掉市场前缀）
    symbol = symbol_dir.replace(market, "", 1) if symbol_dir.startswith(market) else symbol_dir
    
    return {
        "market": market.upper(),
        "symbol": symbol,
        "date": date,
    }


def calc_macd_with_history(
    db_path: str,
    table: str = "kline_15min",
    engine: Any | None = None,
) -> pd.DataFrame:
    """
    从数据库读取 K 线数据并计算 MACD（自动加载多日历史数据）
    
    这是 calc_macd_from_db 的增强版，会自动加载足够的历史数据以确保 MACD 计算准确。
    
    Args:
        db_path: 数据库文件路径
        table: K 线表名（默认 kline_15min）
        engine: IndicatorEngine 实例（可选）
    
    Returns:
        包含 MACD 指标的 DataFrame
    
    Notes:
        - 自动从 db_path 提取 market/symbol/period
        - 自动加载足够的历史数据（30-120 天）以确保 MACD 收敛
        - 与 monitor.py._calc_macd 语义保持一致
    
    Examples:
        >>> macd_df = calc_macd_with_history("data/HK/HK00700/2026-04-07.db", "kline_15min")
        >>> macd_df.empty
        False
    """
    # 从 db_path 提取信息
    info = _extract_db_path_info(db_path)
    market = info["market"]
    symbol = info["symbol"]
    date = info["date"]
    
    # 从 table 提取 period
    period = table.replace("kline_", "")
    
    # 加载多日历史数据
    history_rows = _load_multi_day_rows_for_macd(market, symbol, period, date)
    
    if not history_rows:
        return pd.DataFrame()
    
    return calc_macd_from_rows(history_rows, engine=engine)
