# -*- coding: utf-8 -*-
"""KDJ 随机指标模块。

公式:
  RSV = (close - LOW(N)) / (HIGH(N) - LOW(N)) * 100
  K   = EMA(RSV, M1), 初始值 50
  D   = EMA(K, M2),   初始值 50
  J   = 3*K - 2*D
  斜率: k_slope = K - K_prev, ...
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from . import IndicatorBase

INDICATOR_META = {
    "name": "kdj",
    "display": "KDJ(9,3,3)",
    "params": {"n": 9, "m1": 3, "m2": 3},
    "columns": ["k", "d", "j", "k_slope", "d_slope", "j_slope"],
    "description": "随机指标，判断超买超卖",
}


def _ema_with_seed(series: pd.Series, span: int, seed: float) -> pd.Series:
    """带初始值 seed 的 EMA。第一根直接取 seed，后续正常 ewm。"""
    result = series.copy()
    # 用 seed 填充 NaN 起点：将 series 的 NaN 用 seed 替代再 ewm
    filled = result.fillna(seed)
    ema = filled.ewm(span=span, adjust=False).mean()
    return ema


class KDJ(IndicatorBase):
    """KDJ 随机指标。

    默认参数: N=9, M1=3, M2=3。
    K/D 初始值为 50。
    """

    name = "kdj"

    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3):
        self.n = int(n)
        self.m1 = int(m1)
        self.m2 = int(m2)

    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        required = {"close", "high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"KDJ calc requires {required}, missing: {missing}")

        result = df.copy()
        close = pd.to_numeric(result["close"], errors="coerce").values.astype(float)
        high = pd.to_numeric(result["high"], errors="coerce").values.astype(float)
        low = pd.to_numeric(result["low"], errors="coerce").values.astype(float)

        n = self.n
        length = len(close)

        # RSV 计算
        rsv = np.full(length, np.nan)
        for i in range(n - 1, length):
            low_n = np.nanmin(low[i - n + 1 : i + 1])
            high_n = np.nanmax(high[i - n + 1 : i + 1])
            if high_n == low_n:
                rsv[i] = 50.0  # 避免除零
            else:
                rsv[i] = (close[i] - low_n) / (high_n - low_n) * 100.0

        # K = EMA(RSV, M1), 初始值 50
        k = np.full(length, 50.0)
        alpha_k = 2.0 / (self.m1 + 1)
        for i in range(1, length):
            if np.isnan(rsv[i]):
                k[i] = k[i - 1]
            else:
                k[i] = alpha_k * rsv[i] + (1 - alpha_k) * k[i - 1]

        # D = EMA(K, M2), 初始值 50
        d = np.full(length, 50.0)
        alpha_d = 2.0 / (self.m2 + 1)
        for i in range(1, length):
            d[i] = alpha_d * k[i] + (1 - alpha_d) * d[i - 1]

        # J = 3*K - 2*D
        j = 3.0 * k - 2.0 * d

        # 斜率
        k_slope = np.zeros(length)
        d_slope = np.zeros(length)
        j_slope = np.zeros(length)
        k_slope[1:] = np.diff(k)
        d_slope[1:] = np.diff(d)
        j_slope[1:] = np.diff(j)

        result["k"] = k
        result["d"] = d
        result["j"] = j
        result["k_slope"] = k_slope
        result["d_slope"] = d_slope
        result["j_slope"] = j_slope

        return result
