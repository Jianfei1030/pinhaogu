from __future__ import annotations

import re
from typing import Any

import requests

from ..cache import SimpleCache
from .base import BaseSectorSource


class SinaSectorSource(BaseSectorSource):
    """新浪行业板块数据源。"""

    SECTOR_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
    STOCKS_URL = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
    )

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.cache = SimpleCache(default_ttl=300.0)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn",
            }
        )

    def get_sectors(self) -> list[dict[str, Any]]:
        cached = self.cache.get("sectors")
        if cached is not None:
            return cached

        response = self.session.get(self.SECTOR_URL, timeout=self.timeout)
        response.raise_for_status()
        payload = response.content.decode("gbk", errors="ignore")
        records = self._parse_js_object(payload)

        sectors: list[dict[str, Any]] = []
        for key, raw_value in records.items():
            fields = raw_value.split(",")
            if len(fields) < 3:
                continue

            count = self._to_int(fields[2])
            sectors.append(
                {
                    "code": fields[0] or key,
                    "name": fields[1],
                    "count": count,
                    "type": "industry",
                    "avg_price": self._to_float(fields[3]) if len(fields) > 3 else None,
                    "avg_change": self._to_float(fields[4]) if len(fields) > 4 else None,
                    "change_pct": self._to_float(fields[5]) if len(fields) > 5 else None,
                    "volume": self._to_int(fields[6]) if len(fields) > 6 else None,
                    "amount": self._to_float(fields[7]) if len(fields) > 7 else None,
                    "leader_symbol": fields[8] if len(fields) > 8 else None,
                    "leader_change_pct": self._to_float(fields[9]) if len(fields) > 9 else None,
                    "leader_price": self._to_float(fields[10]) if len(fields) > 10 else None,
                    "leader_change": self._to_float(fields[11]) if len(fields) > 11 else None,
                    "leader_name": fields[12] if len(fields) > 12 else None,
                }
            )

        self.cache.set("sectors", sectors)
        return sectors

    def get_sector_stocks(self, sector_code: str) -> list[dict[str, Any]]:
        cache_key = f"sector_stocks:{sector_code}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        page = 1
        page_size = 80
        items: list[dict[str, Any]] = []

        while True:
            params = {
                "page": page,
                "num": page_size,
                "sort": "symbol",
                "asc": 1,
                "node": sector_code,
                "symbol": "",
                "_s_r_a": "page",
            }
            response = self.session.get(self.STOCKS_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = "gbk"
            batch = response.json()
            if not batch:
                break

            for item in batch:
                symbol = str(item.get("symbol") or "")
                code = str(item.get("code") or symbol[-6:])
                items.append(
                    {
                        "code": code,
                        "symbol": symbol,
                        "name": item.get("name") or "",
                        "market": self._detect_market(symbol, code),
                        "price": self._to_float(item.get("trade")),
                        "change_pct": self._to_float(item.get("changepercent")),
                        "change": self._to_float(item.get("pricechange")),
                        "volume": self._to_int(item.get("volume")),
                        "amount": self._to_float(item.get("amount")),
                        "pe_ratio": self._to_float(item.get("per")),
                        "pb_ratio": self._to_float(item.get("pb")),
                        "turnover_ratio": self._to_float(item.get("turnoverratio")),
                    }
                )

            if len(batch) < page_size:
                break
            page += 1

        self.cache.set(cache_key, items)
        return items

    @staticmethod
    def _parse_js_object(payload: str) -> dict[str, str]:
        match = re.search(r"\{(.*)\}", payload, re.S)
        if not match:
            raise ValueError("Unexpected 新浪板块接口返回格式")

        return {key: value for key, value in re.findall(r'"([^"]+)":"([^"]*)"', match.group(1))}

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
