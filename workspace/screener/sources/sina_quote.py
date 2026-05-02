from __future__ import annotations

import re
from typing import Any

import requests

from .base import BaseQuoteSource


class SinaQuoteSource(BaseQuoteSource):
    """新浪行情数据源。"""

    QUOTE_URL = "https://hq.sinajs.cn/list="
    BATCH_SIZE = 200

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn",
            }
        )

    def get_quote(self, symbol: str) -> dict[str, Any]:
        results = self.get_batch_quotes([symbol])
        if not results:
            raise ValueError(f"未找到证券行情: {symbol}")
        return results[0]

    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []

        normalized = [self._normalize_symbol(symbol) for symbol in symbols]
        quotes: list[dict[str, Any]] = []

        for i in range(0, len(normalized), self.BATCH_SIZE):
            batch_symbols = normalized[i : i + self.BATCH_SIZE]
            response = self.session.get(
                f"{self.QUOTE_URL}{','.join(batch_symbols)}",
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.content.decode("gbk", errors="ignore")

            for raw_symbol, body in re.findall(r'var hq_str_([^=]+)="([^"]*)";', payload):
                quote = self._parse_quote(raw_symbol, body)
                if quote is not None:
                    quotes.append(quote)
        return quotes

    def _parse_quote(self, raw_symbol: str, body: str) -> dict[str, Any] | None:
        fields = body.split(",")
        if len(fields) < 10 or not fields[0]:
            return None

        code = raw_symbol[-6:]
        market = self._detect_market(raw_symbol, code)
        open_price = self._to_float(fields[1])
        prev_close = self._to_float(fields[2])
        price = self._to_float(fields[3])
        high = self._to_float(fields[4])
        low = self._to_float(fields[5])
        volume = self._to_int(fields[8])
        amount = self._to_float(fields[9])

        change = None
        change_pct = None
        if price is not None and prev_close not in (None, 0):
            change = price - prev_close
            change_pct = change / prev_close * 100

        return {
            "code": code,
            "symbol": raw_symbol,
            "market": market,
            "name": fields[0],
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "open": open_price,
            "prev_close": prev_close,
            "high": high,
            "low": low,
            "volume": volume,
            "turnover": amount,
            "amount": amount,
            "bid": self._to_float(fields[6]) if len(fields) > 6 else None,
            "ask": self._to_float(fields[7]) if len(fields) > 7 else None,
            "date": fields[30] if len(fields) > 30 else None,
            "time": fields[31] if len(fields) > 31 else None,
            "pe_ratio": None,
            "pb_ratio": None,
        }

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        value = symbol.strip().lower()
        if re.fullmatch(r"(sh|sz|bj)\d{6}", value):
            return value
        if re.fullmatch(r"\d{6}", value):
            if value.startswith(("6", "9")):
                return f"sh{value}"
            if value.startswith(("0", "2", "3")):
                return f"sz{value}"
            if value.startswith(("4", "8")):
                return f"bj{value}"
        raise ValueError(f"不支持的证券代码: {symbol}")

    @staticmethod
    def _detect_market(symbol: str, code: str) -> str:
        value = (symbol or code).lower()
        if value.startswith("sh") or code.startswith(("6", "9")):
            return "sh"
        if value.startswith("sz") or code.startswith(("0", "2", "3")):
            return "sz"
        if value.startswith("bj") or code.startswith(("4", "8")):
            return "bj"
        return "unknown"

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value in (None, "", "null"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
