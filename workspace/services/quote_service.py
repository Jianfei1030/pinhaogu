# -*- coding: utf-8 -*-
"""
Quote Service for Stock Monitor

This module provides core quote functionality for the /api/quote/{symbol} endpoint.
It encapsulates quote fetching, watchlist resolution, and payload construction.

Style: Lightweight functional module (not class-based).
"""
from __future__ import annotations

import math
from typing import Any

from data_source import DataSourceError, fetch_realtime

# =============================================================================
# Business Exceptions
# =============================================================================


class QuoteServiceError(Exception):
    """Base exception for quote operations."""
    pass


# =============================================================================
# Helper Functions
# =============================================================================

def _safe_number(value: Any) -> float:
    """
    Safely convert a value to a float, handling None/NaN/Inf cases.
    
    Args:
        value: Any value to convert
        
    Returns:
        Float value, or 0.0 if conversion fails or value is invalid
    """
    if value is None:
        return 0.0
    try:
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return 0.0
        return round(num, 6)
    except Exception:
        return 0.0


def normalize_quote_request(symbol: str, market: str | None = None) -> tuple[str, str]:
    """
    Normalize quote request parameters.
    
    Args:
        symbol: Stock symbol (will be stripped)
        market: Market code (will be uppercased and stripped, optional)
        
    Returns:
        Tuple of (normalized_symbol, normalized_market)
        Note: market may be empty string if not provided - caller should handle default
    """
    symbol = str(symbol).strip()
    market = str(market or "").upper().strip()
    return symbol, market


def resolve_quote_watch_item(
    config: dict[str, Any],
    symbol: str,
    market: str | None = None
) -> tuple[str, dict[str, Any] | None]:
    """
    Resolve watchlist item and determine the market for a quote request.
    
    This function implements the same logic as the original /api/quote/{symbol} route:
    - If market is provided: look up by (market, symbol)
    - If market is not provided: look up by symbol only, and use the found item's market
    - Default market to "HK" if still not determined
    
    Args:
        config: Configuration dict containing watchlist
        symbol: Stock symbol
        market: Market code (optional)
        
    Returns:
        Tuple of (resolved_market, watch_item)
        - resolved_market: The determined market code (e.g., "HK", "US", "SH", "SZ")
        - watch_item: The watchlist item dict if found, None otherwise
    """
    # Helper: find by (market, symbol)
    def get_watch_item(cfg: dict, mkt: str, sym: str) -> dict[str, Any] | None:
        for item in cfg.get("watchlist", []):
            if str(item.get("market", "")).upper() == mkt and str(item.get("symbol", "")).strip() == sym:
                return item
        return None
    
    # Helper: find by symbol only
    def find_watch_item_by_symbol(cfg: dict, sym: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in cfg.get("watchlist", [])
            if str(item.get("symbol", "")).strip() == sym
        ]
        if len(matches) == 1:
            return matches[0]
        return None
    
    watch_item: dict[str, Any] | None = None
    
    if market:
        # Look up by (market, symbol)
        watch_item = get_watch_item(config, market, symbol)
    else:
        # Look up by symbol only, and extract market from found item
        watch_item = find_watch_item_by_symbol(config, symbol)
        if watch_item:
            market = str(watch_item.get("market") or "").upper().strip()
    
    # Default market to "HK" if still not determined
    market = market or "HK"
    
    # Final fallback: try to find watch item with the resolved market
    if not watch_item:
        watch_item = get_watch_item(config, market, symbol) or {}
    
    return market, watch_item


def build_quote_payload(
    config: dict[str, Any],
    symbol: str,
    market: str | None = None
) -> dict[str, Any]:
    """
    Build the complete quote payload for a stock symbol.
    
    This is the main entry point for the /api/quote/{symbol} route.
    It handles:
    - Parameter normalization
    - Watchlist resolution
    - Real-time quote fetching
    - Error handling (returns error payload instead of raising HTTPException)
    - Payload construction with safe number conversion
    
    Args:
        config: Configuration dict containing watchlist
        symbol: Stock symbol
        market: Market code (optional, defaults to "HK" if not provided)
        
    Returns:
        Dict containing quote data with the following structure:
        {
            "symbol": str,
            "market": str,
            "name": str,
            "price": float,
            "change": float,
            "change_pct": float,
            "open": float,
            "high": float,
            "low": float,
            "prev_close": float,
            "volume": int,
            "amount": float,
            "time": str,
            "source": str,
        }
        
        On error, returns:
        {
            "symbol": str,
            "market": str,
            "name": str,
            "error": str,
        }
    """
    # Normalize parameters
    symbol, normalized_market = normalize_quote_request(symbol, market)
    
    # Resolve watchlist item and determine market
    resolved_market, watch_item = resolve_quote_watch_item(config, symbol, normalized_market)
    
    # Build base payload (used for both success and error responses)
    base_name = str(watch_item.get("name") or symbol) if watch_item else symbol
    base_payload = {
        "symbol": symbol,
        "market": resolved_market,
        "name": base_name,
    }
    
    # Fetch real-time quote
    try:
        quote = fetch_realtime(symbol, resolved_market)
    except DataSourceError as exc:
        return {**base_payload, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {**base_payload, "error": f"Failed to fetch realtime quote: {exc}"}
    
    # Build successful response payload
    # Use quote name if available, fallback to watchlist name, then symbol
    final_name = str(quote.get("name") or watch_item.get("name") or symbol) if watch_item else str(quote.get("name") or symbol)
    
    return {
        "symbol": symbol,
        "market": resolved_market,
        "name": final_name,
        "price": _safe_number(quote.get("current")),
        "change": _safe_number(quote.get("change")),
        "change_pct": _safe_number(quote.get("change_pct")),
        "open": _safe_number(quote.get("open")),
        "high": _safe_number(quote.get("high")),
        "low": _safe_number(quote.get("low")),
        "prev_close": _safe_number(quote.get("prev_close")),
        "volume": int(float(quote.get("volume") or 0)),
        "amount": _safe_number(quote.get("amount")),
        "time": str(quote.get("time") or ""),
        "source": str(quote.get("source") or ""),
    }
