#!/usr/bin/env python3
"""Verify stock_lookup_service with specified tests + full 206 names check."""

import json
import sys
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "workspace"))

from services.stock_lookup_service import lookup_a_stock_code_by_name, clear_cache


def test_specified_names():
    """Test specified stock names per requirements."""
    print("=" * 60)
    print("🔍 指定股票名验证")
    print("=" * 60)
    
    tests = [
        ("福晶科技", "002222"),
        ("天孚通信", "300394"),
        ("中际旭创", "300308"),
        ("罗博特科", "300757"),
        ("汉鑫科技", "920092"),
        ("长芯博创", "300548"),
        ("怡亚通", "002183"),  # space variant test
    ]
    
    results = []
    all_pass = True
    
    for name, expected_code in tests:
        result = lookup_a_stock_code_by_name(name)
        
        if result is None:
            status = "❌ 未命中"
            all_pass = False
            actual_code = None
        elif result["stock_code"] != expected_code:
            status = f"❌ 代码不符 (期望 {expected_code}, 实际 {result['stock_code']})"
            all_pass = False
            actual_code = result["stock_code"]
        else:
            status = f"✅ 命中 ({result['match_type']})"
            actual_code = result["stock_code"]
        
        canonical = result["stock_name"] if result else "N/A"
        results.append((name, expected_code, actual_code, status, canonical))
        
        print(f"  {name:15s} → {actual_code or 'N/A':8s} | {status} | canonical: {canonical}")
    
    print()
    return all_pass, results


def collect_unique_names(json_path: Path) -> list[str]:
    """Collect all unique stock names from JSON."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    names = set()
    for item in data["items"]:
        stock_text = item.get("stock_text_raw", "")
        # Split by whitespace
        for name in stock_text.split():
            if name:
                names.add(name.strip())
    
    return sorted(names)


def test_full_206_names(json_path: Path):
    """Test all 206 unique stock names."""
    print("=" * 60)
    print("🔍 全量 206 股票名验证")
    print("=" * 60)
    
    names = collect_unique_names(json_path)
    print(f"  唯一股票名数量: {len(names)}")
    
    missing = []
    hit_count = 0
    
    for name in names:
        result = lookup_a_stock_code_by_name(name)
        if result is None:
            missing.append(name)
        else:
            hit_count += 1
    
    print(f"  命中数量: {hit_count}")
    print(f"  未命中数量: {len(missing)}")
    
    if missing:
        print()
        print("  ❌ 未命中列表:")
        for name in missing:
            print(f"    - {name}")
    
    print()
    return len(missing) == 0, missing


def main():
    base_dir = Path(__file__).parent.parent
    json_path = base_dir / "output" / "path_ancestor_candidates_20260409_224845.json"
    
    if not json_path.exists():
        print(f"✗ JSON 文件不存在: {json_path}")
        return 1
    
    # Clear cache before testing
    clear_cache()
    
    # Test 1: specified names
    pass1, results1 = test_specified_names()
    
    # Test 2: full 206 names
    pass2, missing = test_full_206_names(json_path)
    
    # Summary
    print("=" * 60)
    print("📊 验证总结")
    print("=" * 60)
    print(f"  指定股票名: {'✅ 全部通过' if pass1 else '❌ 有失败'}")
    print(f"  全量 206 名: {'✅ 0 missing' if pass2 else f'❌ {len(missing)} missing'}")
    print()
    
    if pass1 and pass2:
        print("✅ 所有验证通过，可进入写库阶段")
        return 0
    else:
        print("❌ 验证未通过，需要进一步调试")
        return 1


if __name__ == "__main__":
    sys.exit(main())