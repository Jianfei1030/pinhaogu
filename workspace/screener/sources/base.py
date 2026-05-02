from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSectorSource(ABC):
    """板块/概念数据源。"""

    @abstractmethod
    def get_sectors(self) -> list[dict[str, Any]]:
        """返回 [{code, name, count, type: "industry"|"concept"}, ...]。"""

    @abstractmethod
    def get_sector_stocks(self, sector_code: str) -> list[dict[str, Any]]:
        """返回板块内个股 [{code, name, market}, ...]。"""


class BaseQuoteSource(ABC):
    """行情数据源。"""

    @abstractmethod
    def get_quote(self, symbol: str) -> dict[str, Any]:
        """返回 {code, name, price, change_pct, volume, turnover, pe_ratio, pb_ratio, amount, ...}。"""

    @abstractmethod
    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取。"""
