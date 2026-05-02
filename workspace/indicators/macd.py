# -*- coding: utf-8 -*-
"""MACD 指标模块（从 indicators.py 提取）。"""
from __future__ import annotations

import pandas as pd

from . import IndicatorBase

INDICATOR_META = {
    "name": "macd",
    "display": "MACD(12,26,9)",
    "params": {"fast": 12, "slow": 26, "signal": 9},
    "columns": ["macd", "macd_dea", "macd_hist", "macd_slope", "macd_dea_slope", "macd_hist_slope"],
    "description": "指数平滑异同移动平均线",
}


class MACD(IndicatorBase):
    """MACD指标。

    计算公式:
    - EMA(fast) = EMA of close, span=fast
    - EMA(slow) = EMA of close, span=slow
    - macd = EMA(fast) - EMA(slow)
    - dea = EMA(macd, span=signal)
    - hist = 2 * (macd - dea)

    数据量要求:
    - 最少需要 slow + signal - 1 = 34 根bar (EMA能输出有效值)
    - 推荐 slow * 2~3 = 52~78 根bar (EMA基本收敛)
    - 与东财对齐需要 >=200 根 (完全收敛)
    """

    name = "macd"
    MIN_BARS = 34       # slow + signal - 1
    RECOMMEND_BARS = 78  # slow * 3

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        if fast <= 0 or slow <= 0 or signal <= 0:
            raise ValueError("fast, slow, signal must be positive integers")
        self.fast = int(fast)
        self.slow = int(slow)
        self.signal = int(signal)
        self.MIN_BARS = slow + signal - 1
        self.RECOMMEND_BARS = slow * 3

    def check_data(self, n: int) -> str:
        """检查数据量是否充足，返回状态: 'ok' / 'warn' / 'low'"""
        if n >= self.RECOMMEND_BARS:
            return "ok"
        elif n >= self.MIN_BARS:
            return "warn"
        else:
            return "low"

    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        if "close" not in df.columns:
            raise ValueError("MACD calc requires 'close' column")

        result = df.copy()
        close = pd.to_numeric(result["close"], errors="coerce")
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()

        result["macd"] = ema_fast - ema_slow
        result["macd_dea"] = result["macd"].ewm(span=self.signal, adjust=False).mean()
        result["macd_hist"] = 2 * (result["macd"] - result["macd_dea"])

        # 斜率: 当前值 - 上一根值 (第一根为0)
        result["macd_slope"] = result["macd"].diff().fillna(0)
        result["macd_dea_slope"] = result["macd_dea"].diff().fillna(0)
        result["macd_hist_slope"] = result["macd_hist"].diff().fillna(0)

        # 标记数据充足度
        n = len(df)
        status = self.check_data(n)
        result.attrs["macd_data_status"] = status
        result.attrs["macd_data_info"] = {
            "bars": n,
            "min": self.MIN_BARS,
            "recommend": self.RECOMMEND_BARS,
        }
        return result
