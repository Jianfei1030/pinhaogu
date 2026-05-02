# -*- coding: utf-8 -*-
"""
Stock Lookup Service

Provides stock name → code lookup functionality using local A-share data.

Data source: data/a_stock_list.json (约 5497 条 A 股映射)

Usage:
    from services.stock_lookup_service import lookup_a_stock_code_by_name

    result = lookup_a_stock_code_by_name("福晶科技")
    # Returns: {"stock_name": "福晶科技", "stock_code": "002222", "market": "A", "source": "..."}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# =============================================================================
# Configuration
# =============================================================================

# Default data file path (relative to workspace root)
DEFAULT_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "a_stock_list.json"


# =============================================================================
# Business Exceptions
# =============================================================================


class StockLookupError(Exception):
    """Base exception for stock lookup operations."""
    pass


class DataFileNotFoundError(StockLookupError):
    """Raised when the stock data file is not found."""
    pass


# =============================================================================
# Cache Management
# =============================================================================

# Simple module-level cache to avoid repeated file reads
_stock_cache: Optional[dict[str, dict]] = None
_cache_source: Optional[str] = None


def _load_stock_data(data_file: Optional[Path] = None, force_reload: bool = False) -> dict[str, dict]:
    """
    Load A-share stock data from JSON file with caching.

    Args:
        data_file: Path to the JSON data file. Defaults to DEFAULT_DATA_FILE.
        force_reload: If True, force reload from file even if cached.

    Returns:
        Dict mapping stock name to stock info:
        {
            "平安银行": {"symbol": "000001", "name": "平安银行", "list_date": "1991-04-03"},
            ...
        }

    Raises:
        DataFileNotFoundError: If the data file does not exist.
        StockLookupError: If JSON parsing fails.
    """
    global _stock_cache, _cache_source

    file_path = data_file or DEFAULT_DATA_FILE
    file_key = str(file_path)

    # Return cached data if available and not forcing reload
    if _stock_cache is not None and _cache_source == file_key and not force_reload:
        return _stock_cache

    # Check file existence
    if not file_path.exists():
        raise DataFileNotFoundError(f"Stock data file not found: {file_path}")

    # Load from file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            stock_list = json.load(f)
    except json.JSONDecodeError as e:
        raise StockLookupError(f"Failed to parse stock data file: {e}")

    # Build name → info mapping (exact name match)
    _stock_cache = {}
    for item in stock_list:
        name = item.get("name", "").strip()
        if name:
            _stock_cache[name] = item

    _cache_source = file_key

    return _stock_cache


def clear_cache() -> None:
    """Clear the stock data cache. Useful for testing or data refresh."""
    global _stock_cache, _cache_source
    _stock_cache = None
    _cache_source = None


# =============================================================================
# Main Lookup API
# =============================================================================


def lookup_a_stock_code_by_name(
    name: str,
    data_file: Optional[Path] = None
) -> Optional[dict]:
    """
    Lookup A-share stock code by exact name match with space-variant fallback.

    This is the primary API for stock name → code lookup.

    Lookup strategy:
    1. Exact match (stripped input against stripped dict key)
    2. Space-variant fallback: remove all whitespace from both sides and retry
       - Example: "怡亚通" can match "怡 亚 通"
       - Only handles whitespace differences, no fuzzy/pinyin matching

    Args:
        name: Stock name to search for.
              Example: "福晶科技", "天孚通信", "怡亚通"
        data_file: Optional custom data file path. Defaults to DEFAULT_DATA_FILE.

    Returns:
        If found:
            {
                "stock_name": "怡 亚 通",  # canonical name from dict
                "stock_code": "002183",
                "market": "A",
                "source": "data/a_stock_list.json",
                "match_type": "exact" or "space_variant"
            }
        If not found:
            None

    Raises:
        DataFileNotFoundError: If the stock data file does not exist.
        StockLookupError: If data loading fails.

    Example:
        >>> lookup_a_stock_code_by_name("福晶科技")
        {'stock_name': '福晶科技', 'stock_code': '002222', 'market': 'A', 'source': '...', 'match_type': 'exact'}

        >>> lookup_a_stock_code_by_name("怡亚通")  # matches "怡 亚 通"
        {'stock_name': '怡 亚 通', 'stock_code': '002183', 'market': 'A', 'source': '...', 'match_type': 'space_variant'}
    """
    if not name:
        return None

    # Load data (cached)
    stock_data = _load_stock_data(data_file)

    # Strategy 1: Exact match
    name_stripped = name.strip()
    if name_stripped in stock_data:
        item = stock_data[name_stripped]
        source_path = data_file or DEFAULT_DATA_FILE
        source_name = source_path.name
        return {
            "stock_name": name_stripped,  # canonical name
            "stock_code": item["symbol"],
            "market": "A",
            "source": f"data/{source_name}",
            "match_type": "exact"
        }

    # Strategy 2: Space-variant fallback
    # Remove ALL whitespace (spaces, tabs, newlines) from both sides
    name_no_space = "".join(name_stripped.split())  # removes all whitespace chars

    # Build a mapping: no-space-name → canonical name
    for canonical_name, item in stock_data.items():
        canonical_no_space = "".join(canonical_name.split())
        if canonical_no_space == name_no_space:
            source_path = data_file or DEFAULT_DATA_FILE
            source_name = source_path.name
            return {
                "stock_name": canonical_name,  # return canonical, not alias
                "stock_code": item["symbol"],
                "market": "A",
                "source": f"data/{source_name}",
                "match_type": "space_variant"
            }

    # Strategy 3: Fuzzy match (edit distance <= 1 for short names)
    # Only applies to names with 2-5 Chinese chars (A-share stock name range)
    # Catches OCR errors like 骐→骄, 鑫→蠡, 新能源→新能
    if 2 <= len(name_no_space) <= 5:
        best_match = None
        best_distance = 999
        for canonical_name, item in stock_data.items():
            canonical_no_space = "".join(canonical_name.split())
            # Only compare same-length or ±1 length names
            if abs(len(canonical_no_space) - len(name_no_space)) > 1:
                continue
            d = _edit_distance(name_no_space, canonical_no_space)
            if d < best_distance and d <= 1:  # max 1 edit for 2-5 char names
                best_distance = d
                best_match = (canonical_name, item)

        if best_match:
            canonical_name, item = best_match
            source_path = data_file or DEFAULT_DATA_FILE
            source_name = source_path.name
            return {
                "stock_name": canonical_name,
                "stock_code": item["symbol"],
                "market": "A",
                "source": f"data/{source_name}",
                "match_type": "fuzzy"
            }

    # Not found
    return None


def _edit_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]


def lookup_multiple_stocks(
    names: list[str],
    data_file: Optional[Path] = None
) -> dict[str, Optional[dict]]:
    """
    Batch lookup multiple stock names.

    Args:
        names: List of stock names to lookup.
        data_file: Optional custom data file path.

    Returns:
        Dict mapping each name to its lookup result (or None if not found).
        Example:
            {
                "福晶科技": {"stock_name": "福晶科技", "stock_code": "002222", ...},
                "不存在的股票": None
            }
    """
    results = {}
    for name in names:
        results[name] = lookup_a_stock_code_by_name(name, data_file)
    return results


# =============================================================================
# Utility Functions
# =============================================================================


def get_cache_stats() -> dict:
    """
    Get cache statistics.

    Returns:
        {
            "cached": bool,
            "stock_count": int or None,
            "source": str or None
        }
    """
    return {
        "cached": _stock_cache is not None,
        "stock_count": len(_stock_cache) if _stock_cache else None,
        "source": _cache_source
    }


def preload_cache(data_file: Optional[Path] = None) -> int:
    """
    Preload the stock data cache.

    Useful to warm up the cache before batch operations.

    Args:
        data_file: Optional custom data file path.

    Returns:
        Number of stocks loaded.
    """
    stock_data = _load_stock_data(data_file)
    return len(stock_data)