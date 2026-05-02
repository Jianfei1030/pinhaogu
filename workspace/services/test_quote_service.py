# -*- coding: utf-8 -*-
"""
Smoke tests for Quote Service
"""
import sys
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch

from data_source import DataSourceError

from services.quote_service import (
    QuoteServiceError,
    normalize_quote_request,
    resolve_quote_watch_item,
    build_quote_payload,
    _safe_number,
)


def test_safe_number():
    """Test _safe_number helper"""
    assert _safe_number(None) == 0.0
    assert _safe_number(123.456) == 123.456
    assert _safe_number("123.456") == 123.456
    assert _safe_number(float("nan")) == 0.0
    assert _safe_number(float("inf")) == 0.0
    assert _safe_number("invalid") == 0.0
    print("✓ _safe_number tests passed")


def test_normalize_quote_request():
    """Test parameter normalization"""
    sym, mkt = normalize_quote_request("  00700  ", "hk")
    assert sym == "00700"
    assert mkt == "HK"
    
    sym, mkt = normalize_quote_request("AAPL", None)
    assert sym == "AAPL"
    assert mkt == ""
    
    sym, mkt = normalize_quote_request("  600519  ", "  sh  ")
    assert sym == "600519"
    assert mkt == "SH"
    
    print("✓ normalize_quote_request tests passed")


def test_resolve_quote_watch_item():
    """Test watchlist resolution"""
    config = {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "Tencent"},
            {"symbol": "AAPL", "market": "US", "name": "Apple"},
            {"symbol": "600519", "market": "SH", "name": "Moutai"},
        ]
    }
    
    # Test with market provided
    mkt, item = resolve_quote_watch_item(config, "00700", "HK")
    assert mkt == "HK"
    assert item == {"symbol": "00700", "market": "HK", "name": "Tencent"}
    
    # Test without market (find by symbol only)
    mkt, item = resolve_quote_watch_item(config, "AAPL", None)
    assert mkt == "US"
    assert item == {"symbol": "AAPL", "market": "US", "name": "Apple"}
    
    # Test default market (HK) when not found
    mkt, item = resolve_quote_watch_item(config, "UNKNOWN", None)
    assert mkt == "HK"
    assert item == {}  # Returns empty dict, not None (matches original route behavior)
    
    # Test empty watchlist
    mkt, item = resolve_quote_watch_item({"watchlist": []}, "00700", None)
    assert mkt == "HK"
    assert item == {}
    
    print("✓ resolve_quote_watch_item tests passed")


def test_build_quote_payload_success():
    """Test successful quote payload building"""
    config = {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "Tencent Holdings"},
        ]
    }
    
    fake_quote = {
        "name": "腾讯控股",
        "current": 380.5,
        "change": 5.2,
        "change_pct": 1.39,
        "open": 378.0,
        "high": 382.0,
        "low": 376.5,
        "prev_close": 375.3,
        "volume": 12345678,
        "amount": 4567890123.45,
        "time": "2026-04-07 13:30:00",
        "source": "eastmoney",
    }
    
    with patch("services.quote_service.fetch_realtime", return_value=fake_quote):
        result = build_quote_payload(config, "00700", "HK")
    
    # Verify structure
    assert "error" not in result
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    assert result["name"] == "腾讯控股"
    assert result["price"] == 380.5
    assert result["change"] == 5.2
    assert result["change_pct"] == 1.39
    assert result["open"] == 378.0
    assert result["high"] == 382.0
    assert result["low"] == 376.5
    assert result["prev_close"] == 375.3
    assert result["volume"] == 12345678
    assert isinstance(result["amount"], float)
    assert result["time"] == "2026-04-07 13:30:00"
    assert result["source"] == "eastmoney"
    
    print("✓ build_quote_payload (success) tests passed")


def test_build_quote_payload_datasource_error():
    """Test error handling when fetch_realtime raises DataSourceError"""
    config = {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "Tencent Holdings"},
        ]
    }
    
    with patch("services.quote_service.fetch_realtime", side_effect=DataSourceError("Symbol not found")):
        result = build_quote_payload(config, "00700", "HK")
    
    # Verify error structure
    assert "error" in result
    assert result["error"] == "Symbol not found"
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    assert result["name"] == "Tencent Holdings"
    
    print("✓ build_quote_payload (DataSourceError) tests passed")


def test_build_quote_payload_generic_error():
    """Test error handling when fetch_realtime raises generic exception"""
    config = {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "Tencent Holdings"},
        ]
    }
    
    with patch("services.quote_service.fetch_realtime", side_effect=Exception("Network timeout")):
        result = build_quote_payload(config, "00700", "HK")
    
    # Verify error structure
    assert "error" in result
    assert "Network timeout" in result["error"]
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    
    print("✓ build_quote_payload (generic error) tests passed")


def test_build_quote_payload_no_market():
    """Test quote building without explicit market parameter"""
    config = {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "Tencent Holdings"},
        ]
    }
    
    fake_quote = {
        "current": 380.5,
        "change": 5.2,
        "change_pct": 1.39,
        "volume": 0,
        "amount": 0,
    }
    
    with patch("services.quote_service.fetch_realtime", return_value=fake_quote):
        result = build_quote_payload(config, "00700", None)
    
    # Should auto-resolve market from watchlist
    assert result["market"] == "HK"
    assert result["symbol"] == "00700"
    assert result["name"] == "Tencent Holdings"
    
    print("✓ build_quote_payload (no market) tests passed")


def run_all_tests():
    """Run all smoke tests"""
    print("=" * 60)
    print("Quote Service Smoke Tests")
    print("=" * 60)
    
    test_safe_number()
    test_normalize_quote_request()
    test_resolve_quote_watch_item()
    test_build_quote_payload_success()
    test_build_quote_payload_datasource_error()
    test_build_quote_payload_generic_error()
    test_build_quote_payload_no_market()
    
    print("=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
