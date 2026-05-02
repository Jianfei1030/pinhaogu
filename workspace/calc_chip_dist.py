#!/usr/bin/env python3
"""
筹码分布计算工具 - 改进版（参考东方财富/同花顺算法）

原理：
- 使用真实每日换手率（从 K 线数据获取）
- 筹码按价格区间转移（高价成交→低位筹码转移到高位）
- 回溯足够长的历史（默认 250 天）

用法:
  python calc_chip_dist.py --symbol 300548
  python calc_chip_dist.py --symbols "300548,002902" --days 250
  python calc_chip_dist.py --symbol 300548 --json
"""

import argparse
import json
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_VENV = os.path.join(SCRIPT_DIR, "../../../projects/stock-monitor/workspace/venv/lib")
if os.path.exists(WORKSPACE_VENV):
    for d in os.listdir(WORKSPACE_VENV):
        if d.startswith("python"):
            sys.path.insert(0, os.path.join(WORKSPACE_VENV, d, "site-packages"))
            break

import yfinance as yf
import pandas as pd
import numpy as np
import time


def calc_chip_distribution(
    symbol: str = None,
    market: str = "A",
    days: int = 250,
    use_real_turnover: bool = True,
    price_levels: int = 200,
    kline_data: list = None,  # 新增：直接传入 K 线数据
) -> dict:
    """
    基于历史成交数据模拟筹码分布（改进版）

    Args:
        symbol: 股票代码（如 "300548"），如传入 kline_data 则不需要
        market: 市场（A/HK，默认 A）
        days: 回溯天数（默认 250 天），如传入 kline_data 则不需要
        use_real_turnover: 是否使用真实换手率（默认 True）
        price_levels: 价格档位数（默认 200 档）
        kline_data: 直接传入 K 线数据列表（可选，包含 turnover 字段）

    Returns:
        dict: 筹码分布数据
    """
    # 如果直接传入 K 线数据，直接使用（不调用 API）
    if kline_data is not None and len(kline_data) > 0:
        close = np.array([row['close'] for row in kline_data])
        volume = np.array([row['volume'] for row in kline_data])
        high = np.array([row['high'] for row in kline_data])
        low = np.array([row['low'] for row in kline_data])
        
        # 从 K 线数据提取换手率
        if use_real_turnover and 'turnover' in kline_data[0] and kline_data[0]['turnover'] is not None:
            daily_turnovers = np.array([row.get('turnover', 0.02) / 100.0 for row in kline_data])  # 转为小数
        else:
            daily_turnovers = np.full(len(kline_data), 0.02)
    else:
        # 否则调用 API 获取数据（向后兼容）
        if symbol is None:
            return None
            
        # 获取历史 K 线数据（包含换手率）
        if market == "HK":
            import yfinance as yf
            ticker = yf.Ticker(f"{symbol.lstrip('0')}.HK")
            df = ticker.history(period=f"{days}d", interval="1d")
            base_turnover = 0.005  # 港股默认换手率
        else:
            # A 股：使用新浪接口（包含 turnover 字段）
            import akshare as ak
            df = ak.stock_zh_a_daily(symbol=f"sz{symbol}" if not symbol.startswith(('sz', 'sh')) else symbol, adjust="qfq")
            
            if use_real_turnover and "turnover" in df.columns:
                # 使用真实每日换手率（新浪 turnover 是小数，如 0.1061 表示 10.61%）
                daily_turnovers = df["turnover"].fillna(0.02).values
            else:
                daily_turnovers = np.full(len(df), 0.02)  # 默认 2%

        if df.empty or len(df) < 20:
            return None

        close = df["close"].values if "close" in df.columns else df["Close"].values
        volume = df["volume"].values if "volume" in df.columns else df["Volume"].values
        high = df["high"].values if "high" in df.columns else df["High"].values
        low = df["low"].values if "low" in df.columns else df["Low"].values

    # 价格网格（更密集）
    price_min = min(low) * 0.9
    price_max = max(high) * 1.1
    price_grid = np.linspace(price_min, price_max, price_levels)
    price_step = price_grid[1] - price_grid[0]

    # 初始化筹码分布（均匀分布）
    chips = np.ones(price_levels) / price_levels

    # 逐日模拟筹码转移
    for i in range(len(close)):
        price = close[i]
        vol = volume[i]
        
        # 获取当日换手率
        if use_real_turnover and i < len(daily_turnovers):
            daily_turnover = min(daily_turnovers[i], 0.50)  # 上限 50%
        else:
            daily_turnover = 0.02
        
        if daily_turnover <= 0 or vol <= 0:
            continue
        
        # 筹码转移模型（改进版）
        # 1. 旧筹码衰减（换手后部分筹码转移）
        decay_factor = 1 - daily_turnover
        chips *= decay_factor
        
        # 2. 新筹码分布（不是单点，而是按当日价格区间分布）
        # 使用当日最高/最低价确定成交区间
        day_high = high[i]
        day_low = low[i]
        
        # 在成交区间内均匀分布新筹码
        idx_low = max(0, int((day_low - price_min) / price_step))
        idx_high = min(price_levels - 1, int((day_high - price_min) / price_step))
        
        # 新筹码量 = 当日成交量 × 换手率影响因子
        new_chips_vol = vol * min(daily_turnover * 10, 1.0)  # 放大换手率影响
        
        # 在价格区间内均匀分布
        for idx in range(idx_low, idx_high + 1):
            chips[idx] += new_chips_vol / (idx_high - idx_low + 1)
    
    # 归一化
    total = chips.sum()
    chips_pct = chips / total if total > 0 else chips

    current_price = close[-1]
    current_idx = int((current_price - price_min) / price_step)
    current_idx = max(0, min(current_idx, len(chips) - 1))

    # 获利比例（当前价以下的筹码占比）
    profit_ratio = float(chips_pct[:current_idx + 1].sum())

    # 平均成本
    avg_cost = float((price_grid * chips_pct).sum())

    # 90% 成本区间
    cumsum = np.cumsum(chips_pct)
    low_90_idx = np.searchsorted(cumsum, 0.05)
    high_90_idx = np.searchsorted(cumsum, 0.95)
    low_90 = float(price_grid[low_90_idx])
    high_90 = float(price_grid[min(high_90_idx, len(price_grid) - 1)])
    concentration_90 = float((high_90 - low_90) / avg_cost) if avg_cost > 0 else 0

    # 70% 成本区间
    low_70_idx = np.searchsorted(cumsum, 0.15)
    high_70_idx = np.searchsorted(cumsum, 0.85)
    low_70 = float(price_grid[low_70_idx])
    high_70 = float(price_grid[min(high_70_idx, len(price_grid) - 1)])
    concentration_70 = float((high_70 - low_70) / avg_cost) if avg_cost > 0 else 0

    # 获取日期（如果有 kline_data）
    date_str = ""
    if kline_data is not None and len(kline_data) > 0 and 'bar_time' in kline_data[0]:
        date_str = kline_data[-1]['bar_time']
    
    return {
        "symbol": symbol,
        "date": date_str,
        "current_price": round(current_price, 2),
        "profit_ratio": round(profit_ratio, 4),
        "avg_cost": round(avg_cost, 2),
        "cost_90_low": round(low_90, 2),
        "cost_90_high": round(high_90, 2),
        "concentration_90": round(concentration_90, 4),
        "cost_70_low": round(low_70, 2),
        "cost_70_high": round(high_70, 2),
        "concentration_70": round(concentration_70, 4),
        "chips": [{"price": round(p, 2), "chip": round(c, 6)} for p, c in zip(price_grid, chips_pct)],
    }


def _calc_chip_from_bars(close_prices: list, volumes: list, daily_turnover: float = 0.02, price_levels: int = 100) -> dict:
    """
    从 K 线数据计算筹码分布（内部函数，简化版）
    """
    if len(close_prices) < 20:
        return None

    close = np.array(close_prices)
    volume = np.array(volumes)

    # 价格网格
    price_min = close.min() * 0.8
    price_max = close.max() * 1.2
    price_grid = np.linspace(price_min, price_max, price_levels)
    price_step = price_grid[1] - price_grid[0]

    # 模拟筹码分布
    chips = np.zeros_like(price_grid)
    for i in range(len(close)):
        price = close[i]
        vol = volume[i]

        idx = int((price - price_min) / price_step)
        idx = max(0, min(idx, len(chips) - 1))

        chips[idx] += vol
        chips *= (1 - daily_turnover)

    total = chips.sum()
    chips_pct = chips / total if total > 0 else chips

    current_price = close[-1]
    current_idx = int((current_price - price_min) / price_step)
    current_idx = max(0, min(current_idx, len(chips) - 1))

    # 获利比例
    profit_ratio = float(chips_pct[:current_idx + 1].sum())

    # 平均成本
    avg_cost = float((price_grid * chips_pct).sum())

    # 90% 成本区间
    cumsum = np.cumsum(chips_pct)
    low_90 = float(price_grid[np.searchsorted(cumsum, 0.05)])
    high_90 = float(price_grid[np.searchsorted(cumsum, 0.95)])
    concentration_90 = float((high_90 - low_90) / avg_cost) if avg_cost > 0 else 0

    # 70% 成本区间
    low_70 = float(price_grid[np.searchsorted(cumsum, 0.15)])
    high_70 = float(price_grid[np.searchsorted(cumsum, 0.85)])
    concentration_70 = float((high_70 - low_70) / avg_cost) if avg_cost > 0 else 0

    return {
        "current_price": round(current_price, 2),
        "profit_ratio": round(profit_ratio, 4),
        "avg_cost": round(avg_cost, 2),
        "cost_90_low": round(low_90, 2),
        "cost_90_high": round(high_90, 2),
        "concentration_90": round(concentration_90, 4),
        "cost_70_low": round(low_70, 2),
        "cost_70_high": round(high_70, 2),
        "concentration_70": round(concentration_70, 4),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="筹码分布计算工具（改进版）")
    parser.add_argument("--symbol", type=str, help="股票代码（A 股如 300548，港股如 01810）")
    parser.add_argument("--symbols", type=str, help="批量股票代码（逗号分隔）")
    parser.add_argument("--days", type=int, default=250, help="回溯天数（默认 250 天）")
    parser.add_argument("--market", type=str, default="A", help="市场（A/HK，默认 A）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--use-real-turnover", action="store_true", default=True, help="使用真实换手率（默认启用）")

    args = parser.parse_args()

    if args.symbols:
        symbols = args.symbols.split(",")
    elif args.symbol:
        symbols = [args.symbol]
    else:
        print("错误：请指定 --symbol 或 --symbols")
        sys.exit(1)

    results = []
    for symbol in symbols:
        print(f"\n计算 {symbol} 筹码分布...", file=sys.stderr)
        result = calc_chip_distribution(symbol, market=args.market, days=args.days, use_real_turnover=args.use_real_turnover)
        if result:
            results.append(result)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"当前价：{result['current_price']}")
                print(f"获利比例：{result['profit_ratio']*100:.2f}%")
                print(f"平均成本：{result['avg_cost']}")
                print(f"90% 集中度：{result['concentration_90']:.4f}")
                print(f"90% 成本区间：{result['cost_90_low']} - {result['cost_90_high']}")
        else:
            print(f"{symbol}: 数据不足")
        time.sleep(0.5)
