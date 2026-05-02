# -*- coding: utf-8 -*-
"""
Test script for stock_lookup_service.py

Usage:
    cd workspace
    python3 test_stock_lookup.py
"""
from pathlib import Path
import sys

# Add workspace to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from services.stock_lookup_service import (
    lookup_a_stock_code_by_name,
    lookup_multiple_stocks,
    get_cache_stats,
    clear_cache,
    preload_cache,
)


def test_exact_matches():
    """Test cases that should match exactly."""
    test_cases = [
        ("福晶科技", "002222"),
        ("天孚通信", "300394"),
        ("中际旭创", "300308"),
        ("罗博特科", "300757"),
        ("汉鑫科技", "920092"),
        ("长芯博创", "300548"),
    ]

    print("=" * 60)
    print("Test: Exact Name Matches")
    print("=" * 60)

    passed = 0
    for name, expected_code in test_cases:
        result = lookup_a_stock_code_by_name(name)
        if result and result["stock_code"] == expected_code:
            print(f"✓ {name} → {expected_code}")
            passed += 1
        else:
            actual = result["stock_code"] if result else "None"
            print(f"✗ {name} → expected {expected_code}, got {actual}")

    total = len(test_cases)
    print(f"\nPassed: {passed}/{total}")
    return passed == total


def test_no_match():
    """Test cases that should NOT match."""
    test_cases = [
        "不存在股票XYZ123",  # Truly non-existent
        "不存在的股票ABC",
        "",
    ]

    print("\n" + "=" * 60)
    print("Test: No Match Cases (should return None)")
    print("=" * 60)

    passed = 0
    for name in test_cases:
        result = lookup_a_stock_code_by_name(name)
        if result is None:
            print(f"✓ '{name}' → None (not found)")
            passed += 1
        else:
            print(f"✗ '{name}' → unexpected match: {result}")

    total = len(test_cases)
    print(f"\nPassed: {passed}/{total}")
    return passed == total


def test_batch_lookup():
    """Test batch lookup."""
    print("\n" + "=" * 60)
    print("Test: Batch Lookup")
    print("=" * 60)

    names = ["福晶科技", "天孚通信", "不存在的股票", "中际旭创"]
    results = lookup_multiple_stocks(names)

    for name, result in results.items():
        if result:
            print(f"  {name} → {result['stock_code']}")
        else:
            print(f"  {name} → None (not found)")

    return True


def test_cache():
    """Test cache functionality."""
    print("\n" + "=" * 60)
    print("Test: Cache")
    print("=" * 60)

    # Clear cache
    clear_cache()
    stats = get_cache_stats()
    print(f"After clear: cached={stats['cached']}, count={stats['stock_count']}")

    # Preload
    count = preload_cache()
    print(f"After preload: {count} stocks loaded")

    # Check cache stats
    stats = get_cache_stats()
    print(f"Cache stats: cached={stats['cached']}, count={stats['stock_count']}")
    print(f"Source: {stats['source']}")

    return stats['cached'] and stats['stock_count'] > 5000


def test_result_structure():
    """Test result dict structure."""
    print("\n" + "=" * 60)
    print("Test: Result Structure")
    print("=" * 60)

    result = lookup_a_stock_code_by_name("福晶科技")

    if result is None:
        print("✗ Result is None")
        return False

    required_keys = ["stock_name", "stock_code", "market", "source"]
    for key in required_keys:
        if key not in result:
            print(f"✗ Missing key: {key}")
            return False
        print(f"  {key}: {result[key]}")

    print("✓ All required keys present")
    return True


def main():
    print("Stock Lookup Service Test\n")

    all_passed = True

    all_passed &= test_exact_matches()
    all_passed &= test_no_match()
    all_passed &= test_batch_lookup()
    all_passed &= test_cache()
    all_passed &= test_result_structure()

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())