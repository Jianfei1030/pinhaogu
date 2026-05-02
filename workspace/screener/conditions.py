from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_registry: dict[str, type] = {}


def register(name: str):
    """条件注册装饰器。"""

    def decorator(cls):
        _registry[name] = cls
        return cls

    return decorator


def get_registry() -> dict[str, type]:
    return dict(_registry)


@dataclass
class Condition:
    """条件基类。"""

    type: str = ""
    op: str = ""
    value: Any = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        raise NotImplementedError


@register("sector")
@dataclass
class SectorCondition(Condition):
    """所属板块。"""

    sector_code: str = ""

    def evaluate(self, stock: dict[str, Any]) -> bool:
        return self.sector_code in stock.get("sectors", [])


@register("change_pct")
@dataclass
class ChangePctCondition(Condition):
    """涨跌幅范围。"""

    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("change_pct")
        if val is None:
            return False
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("volume")
@register("成交量")
@dataclass
class VolumeCondition(Condition):
    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("volume")
        if val is None:
            return False
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("turnover")
@dataclass
class TurnoverCondition(Condition):
    """换手率。"""

    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("turnover")
        if val is None:
            return False
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("pe_ratio")
@dataclass
class PERatioCondition(Condition):
    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("pe_ratio")
        if val is None or val <= 0:
            return False
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("pb_ratio")
@dataclass
class PBCondition(Condition):
    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("pb_ratio")
        if val is None or val <= 0:
            return False
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("macd_dif_slope")
@dataclass
class MacdDifSlopeCondition(Condition):
    """DIF斜率 > 0（或按 min/max 范围过滤）。"""

    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("macd_dif_slope")
        if val is None:
            return False
        if self.min is None and self.max is None:
            return val > 0
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("macd_dea_slope")
@dataclass
class MacdDeaSlopeCondition(Condition):
    """DEA斜率 > 0（或按 min/max 范围过滤）。"""

    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("macd_dea_slope")
        if val is None:
            return False
        if self.min is None and self.max is None:
            return val > 0
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("macd_hist_slope")
@dataclass
class MacdHistSlopeCondition(Condition):
    """柱值斜率 > 0（或按 min/max 范围过滤）。"""

    min: float | None = None
    max: float | None = None

    def evaluate(self, stock: dict[str, Any]) -> bool:
        val = stock.get("macd_hist_slope")
        if val is None:
            return False
        if self.min is None and self.max is None:
            return val > 0
        if self.min is not None and val < self.min:
            return False
        if self.max is not None and val > self.max:
            return False
        return True


@register("macd_cross_up")
@dataclass
class MacdCrossUpCondition(Condition):
    """DIF上穿DEA（金叉）。"""

    def evaluate(self, stock: dict[str, Any]) -> bool:
        return stock.get("macd_cross_up", False) is True


@dataclass
class AndCondition:
    conditions: list[Any] = field(default_factory=list)

    def evaluate(self, stock: dict[str, Any]) -> bool:
        return all(condition.evaluate(stock) for condition in self.conditions)


@dataclass
class OrCondition:
    conditions: list[Any] = field(default_factory=list)

    def evaluate(self, stock: dict[str, Any]) -> bool:
        return any(condition.evaluate(stock) for condition in self.conditions)
