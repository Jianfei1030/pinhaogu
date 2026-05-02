"""
成分股等权指数计算工具

提供两个函数：
- calc_equal_weight_index: 纯计算函数，根据成分股等权计算板块指数
- fetch_prev_close: 获取 A 股前一交易日收盘价（akshare + 腾讯 fallback）
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger("component_index")


def calc_equal_weight_index(
    stocks: dict[str, dict],
    base_date: str = "2024-01-01",
    base_value: float = 1000.0,
) -> pd.DataFrame:
    """
    根据成分股等权计算板块指数。

    纯计算函数，不依赖任何外部数据源。

    参数:
        stocks: 成分股数据，格式为:
            {
                "symbol1": {
                    "dates": ["2024-01-01", "2024-01-02", ...],
                    "closes": [10.5, 10.8, ...],
                },
                "symbol2": {
                    "dates": ["2024-01-01", "2024-01-02", ...],
                    "closes": [20.0, 20.5, ...],
                },
                ...
            }
        base_date: 基准日期，用于确定指数的起始日
        base_value: 基准指数值，默认 1000.0

    返回:
        包含 date, index_value, pct_change 列的 DataFrame。
        如果输入为空或无法计算，返回空 DataFrame。
    """
    if not stocks:
        logger.warning("calc_equal_weight_index: 无成分股数据")
        return pd.DataFrame(columns=["date", "index_value", "pct_change"])

    # 构建每只股票的日收益率序列
    all_returns = {}
    all_dates = set()

    for symbol, data in stocks.items():
        dates = data.get("dates", [])
        closes = data.get("closes", [])
        if len(dates) != len(closes) or len(closes) < 2:
            logger.warning(f"calc_equal_weight_index: {symbol} 数据不完整，跳过")
            continue

        df = pd.DataFrame({"date": dates, "close": closes})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").dropna(subset=["close"])
        df["return"] = df["close"].pct_change()
        df = df.dropna(subset=["return"])

        if df.empty:
            continue

        for _, row in df.iterrows():
            all_dates.add(row["date"])

        all_returns[symbol] = df.set_index("date")["return"]

    if not all_returns or not all_dates:
        logger.warning("calc_equal_weight_index: 无法构建收益率序列")
        return pd.DataFrame(columns=["date", "index_value", "pct_change"])

    # 合并所有股票的收益率，按日期对齐
    returns_df = pd.DataFrame(all_returns)
    returns_df.index.name = "date"

    # 等权：每只股票权重相等
    n_stocks = len(returns_df.columns)
    weights = 1.0 / n_stocks

    # 计算每日等权平均收益率
    avg_returns = returns_df.mean(axis=1)
    avg_returns = avg_returns.dropna()
    avg_returns = avg_returns[avg_returns.index >= pd.to_datetime(base_date)]

    if avg_returns.empty:
        logger.warning("calc_equal_weight_index: 基准日期之后无数据")
        return pd.DataFrame(columns=["date", "index_value", "pct_change"])

    # 从基准值开始累积计算指数
    index_values = [base_value]
    dates = [avg_returns.index[0]]
    current = base_value

    for i in range(len(avg_returns)):
        ret = avg_returns.iloc[i]
        if pd.isna(ret):
            continue
        current *= 1 + ret
        index_values.append(current)
        dates.append(avg_returns.index[i])

    # 去掉第一个重复的基准日期对应的值
    # index_values[0] 是基准值，index_values[1:] 是计算值
    result = pd.DataFrame({
        "date": pd.to_datetime(dates[1:]).strftime("%Y-%m-%d"),
        "index_value": index_values[1:],
        "pct_change": [0.0] + [
            (index_values[i] / index_values[i - 1] - 1)
            for i in range(2, len(index_values))
        ],
    })

    if not result.empty:
        logger.info(
            f"calc_equal_weight_index: 计算完成, {n_stocks} 只股票, "
            f"{len(result)} 个交易日, 最新指数={result['index_value'].iloc[-1]:.2f}"
        )

    return result


def _normalize_a_share_code(symbol: str) -> str:
    """
    将 A 股代码转换为交易所前缀格式。

    规则：
    - 6 开头（主板）或 9 开头（北交所）→ sh
    - 其余（0 开头深主板、3 开头创业板）→ sz

    返回: "sh600000" 或 "sz000001" 格式
    """
    code = symbol.strip().lstrip("0") if symbol.strip() != "0" else "0"
    # 确保是 6 位代码
    code = code.zfill(6)

    if code.startswith("6") or code.startswith("9"):
        return f"sh{code}"
    else:
        return f"sz{code}"


def fetch_prev_close(symbol: str, ref_date: Optional[str] = None) -> Optional[float]:
    """
    获取 A 股指定日期前一交易日的收盘价。

    优先使用 akshare (stock_zh_a_hist)，失败时 fallback 到腾讯 qt.gtimg.cn。

    参数:
        symbol: A 股代码，如 "301308"、"600000"
        ref_date: 参考日期，格式 "YYYY-MM-DD"。默认为今天。

    返回:
        前一交易日收盘价，获取失败返回 None。
    """
    if ref_date is None:
        ref_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"fetch_prev_close: 获取 {symbol} 在 {ref_date} 前一交易日收盘价")

    # 先尝试 akshare
    price = _fetch_prev_close_akshare(symbol, ref_date)
    if price is not None:
        return price

    logger.warning(f"fetch_prev_close: akshare 获取 {symbol} 失败，尝试腾讯 fallback")

    # Fallback 到腾讯
    price = _fetch_prev_close_tencent(symbol)
    if price is not None:
        return price

    logger.error(f"fetch_prev_close: {symbol} 所有数据源均失败")
    return None


def _fetch_prev_close_akshare(symbol: str, ref_date: str) -> Optional[float]:
    """通过 akshare 获取 A 股历史日线数据，返回 ref_date 前一交易日收盘价。"""
    try:
        import akshare as ak

        # 确保代码是 6 位数字
        code = symbol.strip().zfill(6)

        # 计算查询窗口：从 ref_date 往前推 15 天
        try:
            ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"akshare: 日期格式错误 {ref_date}")
            return None

        start_date = (ref_dt - timedelta(days=15)).strftime("%Y%m%d")
        end_date = (ref_dt - timedelta(days=1)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        if df is None or df.empty:
            logger.warning(f"akshare: {symbol} 在 {start_date}~{end_date} 无数据")
            return None

        # 取最近一条的收盘价
        df = df.sort_values("日期", ascending=False)
        close = float(df.iloc[0]["收盘"])
        logger.info(f"akshare: {symbol} 前收盘价={close}")
        return close

    except Exception as e:
        logger.warning(f"akshare: 获取 {symbol} 失败: {e}")
        return None


def _fetch_prev_close_tencent(symbol: str) -> Optional[float]:
    """
    通过腾讯财经 qt.gtimg.cn 获取 A 股实时行情，返回前收盘价。

    腾讯接口返回格式: v_{market}{code}="...~名称~当前价~昨收~...";
    字段 3（从 0 开始数）为昨收价。
    """
    try:
        import requests

        market_code = _normalize_a_share_code(symbol)
        url = f"https://qt.gtimg.cn/q={market_code}"

        resp = requests.get(url, timeout=10)
        time.sleep(0.5)  # 避免限流

        if resp.status_code != 200:
            logger.warning(f"腾讯: HTTP {resp.status_code} for {market_code}")
            return None

        text = resp.text
        if not text or "=" not in text:
            logger.warning(f"腾讯: 返回数据为空 {market_code}")
            return None

        # 提取引号内的内容
        content = text.split('"')[1]
        if not content:
            return None

        fields = content.split("~")
        if len(fields) < 4:
            logger.warning(f"腾讯: 返回字段不足 {market_code}: {content[:100]}")
            return None

        # 字段 3 为昨收价
        prev_close = float(fields[3])
        logger.info(f"腾讯: {symbol} ({market_code}) 前收盘价={prev_close}")
        return prev_close

    except Exception as e:
        logger.warning(f"腾讯: 获取 {symbol} 失败: {e}")
        return None
