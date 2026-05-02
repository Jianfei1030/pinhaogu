from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import requests

from .conditions import AndCondition, OrCondition, SectorCondition, get_registry


class ScreenEngine:
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    TENCENT_DAILY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def __init__(self, sector_source, quote_source):
        self.sector_source = sector_source
        self.quote_source = quote_source

    def screen(self, conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        conditions: [{"type": "sector", "sector_code": "new_blhy"}, {"type": "change_pct", "min": 2}, ...]
        返回匹配的股票列表 [{code, name, price, change_pct, ...}, ...]
        """
        need_macd = self._has_macd_condition(conditions)
        condition_tree = self._build_tree(conditions)
        sector_codes = self._collect_sector_codes(condition_tree)
        candidates = self._build_candidates(sector_codes)
        if not candidates:
            return []

        quotes = self.quote_source.get_batch_quotes(list(candidates.keys()))
        quote_map = {quote["code"]: quote for quote in quotes if quote.get("code")}

        if need_macd:
            macd_map = self._load_macd_metrics(candidates, quote_map)
        else:
            macd_map = {}

        results: list[dict[str, Any]] = []
        for code, base_stock in candidates.items():
            merged = dict(base_stock)
            quote = quote_map.get(code, {})
            merged.update(quote)
            if code in macd_map:
                merged.update(macd_map[code])
            merged["code"] = code
            merged["turnover"] = base_stock.get("turnover")
            merged["sectors"] = sorted(base_stock.get("sectors", []))
            if condition_tree.evaluate(merged):
                results.append(merged)

        results.sort(
            key=lambda item: (
                item.get("change_pct") is None,
                -(item.get("change_pct") or 0),
                item.get("code") or "",
            )
        )
        return results

    def _build_tree(self, raw_conditions: list[dict[str, Any]]) -> AndCondition:
        parsed = [self._parse_condition(item) for item in raw_conditions]
        return AndCondition(parsed)

    def _parse_condition(self, item: dict[str, Any]):
        if not isinstance(item, dict):
            raise TypeError(f"条件必须是 dict，实际为: {type(item).__name__}")

        condition_type = item.get("type")
        if not condition_type:
            raise ValueError("条件缺少 type 字段")

        if condition_type == "or":
            children = item.get("conditions")
            if not isinstance(children, list) or not children:
                raise ValueError("OR 条件必须包含非空 conditions 列表")
            return OrCondition([self._parse_condition(child) for child in children])

        registry = get_registry()
        condition_cls = registry.get(condition_type)
        if condition_cls is None:
            raise ValueError(f"未知条件类型: {condition_type}")

        return condition_cls(**item)

    def _collect_sector_codes(self, node) -> set[str]:
        if isinstance(node, SectorCondition):
            return {node.sector_code} if node.sector_code else set()

        children = getattr(node, "conditions", None)
        if not children:
            return set()

        codes: set[str] = set()
        for child in children:
            codes.update(self._collect_sector_codes(child))
        return codes

    def _build_candidates(self, sector_codes: set[str]) -> dict[str, dict[str, Any]]:
        if sector_codes:
            codes_to_scan = sorted(sector_codes)
        else:
            codes_to_scan = [
                sector.get("code")
                for sector in self.sector_source.get_sectors()
                if sector.get("code")
            ]

        candidates: dict[str, dict[str, Any]] = {}
        for sector_code in codes_to_scan:
            stocks = self.sector_source.get_sector_stocks(sector_code)
            for stock in stocks:
                code = str(stock.get("code") or "").strip()
                if not code:
                    continue
                existing = candidates.setdefault(code, self._normalize_stock(stock))
                existing.setdefault("sectors", set()).add(sector_code)
                if not existing.get("name") and stock.get("name"):
                    existing["name"] = stock.get("name")
                existing["market"] = existing.get("market") or stock.get("market")
                if existing.get("turnover") is None and stock.get("turnover_ratio") is not None:
                    existing["turnover"] = stock.get("turnover_ratio")
                for key in ("price", "change_pct", "change", "volume", "amount", "pe_ratio", "pb_ratio"):
                    if existing.get(key) is None and stock.get(key) is not None:
                        existing[key] = stock.get(key)
        return candidates

    @staticmethod
    def _normalize_stock(stock: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(stock)
        normalized["code"] = str(stock.get("code") or "").strip()
        normalized["sectors"] = set()
        normalized["turnover"] = stock.get("turnover_ratio", stock.get("turnover"))
        return normalized

    def _has_macd_condition(self, raw_conditions: list[dict[str, Any]]) -> bool:
        for item in raw_conditions:
            if not isinstance(item, dict):
                continue
            condition_type = str(item.get("type") or "")
            if condition_type.startswith("macd_"):
                return True
            if condition_type == "or" and self._has_macd_condition(item.get("conditions") or []):
                return True
        return False

    def _load_macd_metrics(
        self,
        candidates: dict[str, dict[str, Any]],
        quote_map: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        metrics: dict[str, dict[str, Any]] = {}
        session = requests.Session()
        codes = list(candidates.keys())

        for index, code in enumerate(codes):
            stock = candidates.get(code, {})
            quote = quote_map.get(code, {})
            series = self._fetch_tencent_daily_series(session, code, stock, quote)
            if series:
                metrics[code] = self._compute_macd_metrics(series)
            if index < len(codes) - 1:
                time.sleep(0.08)
        return metrics

    def _fetch_tencent_daily_series(
        self,
        session: requests.Session,
        code: str,
        stock: dict[str, Any],
        quote: dict[str, Any],
    ) -> list[float]:
        symbol = self._to_tencent_symbol(code, stock.get("market") or quote.get("market"))
        params = {"param": f"{symbol},dayfq,,30,qfq"}
        try:
            response = session.get(self.TENCENT_DAILY_URL, params=params, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        data = payload.get("data") or {}
        symbol_data = data.get(symbol) or {}
        day_rows = symbol_data.get("qfqday") or symbol_data.get("day") or []

        closes: list[float] = []
        for row in day_rows:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            close_val = self._safe_float(row[2])
            if close_val is not None:
                closes.append(close_val)
        return closes

    def _compute_macd_metrics(self, closes: list[float]) -> dict[str, Any]:
        if len(closes) < 2:
            return {}

        dif_values = self._ema_diff(closes, self.MACD_FAST, self.MACD_SLOW)
        dea_values = self._ema(dif_values, self.MACD_SIGNAL)
        hist_values = [2 * (dif - dea) for dif, dea in zip(dif_values, dea_values)]
        if len(dif_values) < 2 or len(dea_values) < 2 or len(hist_values) < 2:
            return {}

        dif_now = dif_values[-1]
        dif_prev = dif_values[-2]
        dea_now = dea_values[-1]
        dea_prev = dea_values[-2]
        hist_now = hist_values[-1]
        hist_prev = hist_values[-2]

        return {
            "macd_dif": dif_now,
            "macd_dea": dea_now,
            "macd_hist": hist_now,
            "macd_dif_slope": dif_now - dif_prev,
            "macd_dea_slope": dea_now - dea_prev,
            "macd_hist_slope": hist_now - hist_prev,
            "macd_cross_up": dif_prev <= dea_prev and dif_now > dea_now,
        }

    @staticmethod
    def _ema_diff(closes: list[float], fast: int, slow: int) -> list[float]:
        ema_fast = ScreenEngine._ema(closes, fast)
        ema_slow = ScreenEngine._ema(closes, slow)
        return [fast_val - slow_val for fast_val, slow_val in zip(ema_fast, ema_slow)]

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        result = [float(values[0])]
        for value in values[1:]:
            result.append(alpha * float(value) + (1 - alpha) * result[-1])
        return result

    @staticmethod
    def _to_tencent_symbol(code: str, market: str | None) -> str:
        market_text = str(market or "").lower()
        if market_text in {"sh", "sha", "ss"}:
            prefix = "sh"
        elif market_text in {"sz", "sza", "szse"}:
            prefix = "sz"
        else:
            prefix = "sh" if str(code).startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{code}"

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
