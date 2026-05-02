# -*- coding: utf-8 -*-
"""指标引擎包 — 支持可插拔架构。

IndicatorBase 抽象基类和 IndicatorEngine 引擎定义于此。
具体指标实现分散在同目录各 .py 模块中，通过 load_from_dir() 自动加载。
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd


class IndicatorBase(ABC):
    """指标基类"""

    name: str = ""

    @abstractmethod
    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        """输入: 包含 open/high/low/close/volume 的 DataFrame
        输出: 添加了指标列的 DataFrame
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 向后兼容: 旧 MACD 实现（已移至 indicators/macd.py）
# ---------------------------------------------------------------------------
class MACD(IndicatorBase):
    """@deprecated: 请使用 indicators.macd.MACD。
    保留此类以兼容旧代码，通过 IndicatorEngine.load_from_dir() 加载后会自动覆盖。
    """

    name = "macd"
    MIN_BARS = 34
    RECOMMEND_BARS = 78

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        warnings.warn(
            "MACD class in indicators package root is deprecated. "
            "Use IndicatorEngine.load_from_dir() to load indicators/macd.py instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if fast <= 0 or slow <= 0 or signal <= 0:
            raise ValueError("fast, slow, signal must be positive integers")
        self.fast = int(fast)
        self.slow = int(slow)
        self.signal = int(signal)
        self.MIN_BARS = slow + signal - 1
        self.RECOMMEND_BARS = slow * 3

    def check_data(self, n: int) -> str:
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
        result["macd_slope"] = result["macd"].diff().fillna(0)
        result["macd_dea_slope"] = result["macd_dea"].diff().fillna(0)
        result["macd_hist_slope"] = result["macd_hist"].diff().fillna(0)

        n = len(df)
        status = self.check_data(n)
        result.attrs["macd_data_status"] = status
        result.attrs["macd_data_info"] = {
            "bars": n,
            "min": self.MIN_BARS,
            "recommend": self.RECOMMEND_BARS,
        }
        return result


# ---------------------------------------------------------------------------
# IndicatorEngine
# ---------------------------------------------------------------------------
class IndicatorEngine:
    """指标引擎，管理多个指标的注册和批量计算"""

    def __init__(self):
        self._indicators: dict[str, IndicatorBase] = {}

    def register(self, indicator: IndicatorBase):
        """注册一个指标"""
        if not indicator.name:
            raise ValueError("indicator.name cannot be empty")
        self._indicators[indicator.name] = indicator

    def unregister(self, name: str):
        """移除已注册的指标"""
        self._indicators.pop(name, None)

    def load_from_dir(self, dir_path: str | Path, *, verbose: bool = False):
        """自动扫描目录，用 importlib 加载所有指标模块并注册。

        扫描规则:
        - 目录下所有 .py 文件（除 __init__.py）视为潜在指标模块
        - 模块需定义 INDICATOR_META dict（含 "name" 字段）和 IndicatorBase 子类
        - 若模块中存在 IndicatorBase 子类且其 .name 与 INDICATOR_META["name"] 一致，
          则实例化并注册

        Args:
            dir_path: 指标目录路径（相对或绝对）
            verbose: 是否打印加载日志

        Returns:
            已注册的指标名列表
        """
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Indicator directory not found: {dir_path}")

        # 确保父目录在 sys.path 中（用于跨模块 import）
        import sys
        parent = str(dir_path.parent.resolve())
        if parent not in sys.path:
            sys.path.insert(0, parent)

        # 确保 indicators 包自身在 sys.modules 中（指标模块做 `from indicators import IndicatorBase` 需要）
        import types
        pkg_name = dir_path.name  # "indicators"
        if pkg_name not in sys.modules:
            sys.modules[pkg_name] = sys.modules[__name__]

        loaded = []
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name == "__init__.py":
                continue

            module_name = f"{pkg_name}.{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                # 注册到 sys.modules 以便其他模块能导入它
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                if verbose:
                    print(f"[IndicatorEngine] 跳过 {py_file.name}: {e}")
                continue

            # 检查 INDICATOR_META
            meta = getattr(mod, "INDICATOR_META", None)
            if not isinstance(meta, dict) or "name" not in meta:
                if verbose:
                    print(f"[IndicatorEngine] 跳过 {py_file.name}: 缺少 INDICATOR_META")
                continue

            indicator_name = meta["name"]

            # 查找 IndicatorBase 子类
            indicator_cls = None
            for _, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, IndicatorBase)
                    and obj is not IndicatorBase
                    and getattr(obj, "name", "") == indicator_name
                ):
                    indicator_cls = obj
                    break

            if indicator_cls is None:
                if verbose:
                    print(f"[IndicatorEngine] 跳过 {py_file.name}: 未找到匹配的 IndicatorBase 子类")
                continue

            try:
                instance = indicator_cls()
                self.register(instance)
                loaded.append(indicator_name)
                if verbose:
                    print(f"[IndicatorEngine] 已注册: {indicator_name} ({meta.get('display', '')})")
            except Exception as e:
                if verbose:
                    print(f"[IndicatorEngine] 实例化 {indicator_name} 失败: {e}")

        return loaded

    def calc_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """遍历所有已注册指标，依次计算并合并结果"""
        result = df.copy()
        for indicator in self._indicators.values():
            result = indicator.calc(result)
        return result

    def calc_one(self, name: str, df: pd.DataFrame) -> pd.DataFrame:
        """只计算指定指标"""
        indicator = self._indicators.get(name)
        if indicator is None:
            raise KeyError(f"indicator not registered: {name}")
        return indicator.calc(df.copy())

    def list_indicators(self) -> list[str]:
        """列出所有已注册指标名"""
        return list(self._indicators.keys())

    def get_meta(self, name: str) -> dict | None:
        """获取指标元信息（如果加载时保留了 meta）"""
        indicator = self._indicators.get(name)
        if indicator is None:
            return None
        return getattr(indicator, "INDICATOR_META", None)
