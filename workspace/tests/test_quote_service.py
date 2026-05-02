#!/usr/bin/env python3
"""
Quote Service 单元测试 - 验证行情服务核心功能

测试范围：
- 模块导入与异常类
- _safe_number 数值安全转换
- normalize_quote_request 参数标准化
- resolve_quote_watch_item 自选股解析
- build_quote_payload 完整行情数据构建

用法：
    python -m pytest tests/test_quote_service.py -v
    或
    python tests/test_quote_service.py
"""
import math
import os
import sys

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入被测模块
from services.quote_service import (
    QuoteServiceError,
    _safe_number,
    normalize_quote_request,
    resolve_quote_watch_item,
    build_quote_payload,
)


# =============================================================================
# A. 基础接口与异常
# =============================================================================

def test_module_import():
    """测试模块可导入"""
    print("\n" + "="*60)
    print("测试：模块导入")
    print("="*60)
    
    # 如果能执行到这里，说明模块已成功导入
    assert QuoteServiceError is not None
    assert _safe_number is not None
    assert normalize_quote_request is not None
    assert resolve_quote_watch_item is not None
    assert build_quote_payload is not None
    
    print("✓ 所有导出项均可导入")
    print("\n✅ 模块导入测试通过")


def test_quote_service_error_exists():
    """测试 QuoteServiceError 异常类存在"""
    print("\n" + "="*60)
    print("测试：QuoteServiceError 异常类")
    print("="*60)
    
    # 验证是 Exception 的子类
    assert issubclass(QuoteServiceError, Exception)
    
    # 验证可以实例化
    exc = QuoteServiceError("test error")
    assert str(exc) == "test error"
    
    print("✓ QuoteServiceError 是 Exception 的子类")
    print("✓ 可以正常实例化")
    print("\n✅ QuoteServiceError 测试通过")


# =============================================================================
# B. _safe_number 数值安全转换
# =============================================================================

def test_safe_number_none():
    """测试 _safe_number 处理 None"""
    print("\n" + "="*60)
    print("测试：_safe_number(None)")
    print("="*60)
    
    result = _safe_number(None)
    assert result == 0.0, f"期望 0.0，得到 {result}"
    
    print("✓ None -> 0.0")
    print("\n✅ _safe_number(None) 测试通过")


def test_safe_number_nan():
    """测试 _safe_number 处理 NaN"""
    print("\n" + "="*60)
    print("测试：_safe_number(NaN)")
    print("="*60)
    
    result = _safe_number(float('nan'))
    assert result == 0.0, f"期望 0.0，得到 {result}"
    assert not math.isnan(result), "结果不应该是 NaN"
    
    print("✓ NaN -> 0.0")
    print("\n✅ _safe_number(NaN) 测试通过")


def test_safe_number_inf():
    """测试 _safe_number 处理 Inf"""
    print("\n" + "="*60)
    print("测试：_safe_number(Inf)")
    print("="*60)
    
    # 正无穷
    result_pos = _safe_number(float('inf'))
    assert result_pos == 0.0, f"期望 0.0，得到 {result_pos}"
    assert not math.isinf(result_pos), "结果不应该是 Inf"
    
    # 负无穷
    result_neg = _safe_number(float('-inf'))
    assert result_neg == 0.0, f"期望 0.0，得到 {result_neg}"
    assert not math.isinf(result_neg), "结果不应该是 Inf"
    
    print("✓ +Inf -> 0.0")
    print("✓ -Inf -> 0.0")
    print("\n✅ _safe_number(Inf) 测试通过")


def test_safe_number_normal():
    """测试 _safe_number 处理正常数字"""
    print("\n" + "="*60)
    print("测试：_safe_number(正常数字)")
    print("="*60)
    
    # 整数
    assert _safe_number(100) == 100.0
    print("✓ 整数 100 -> 100.0")
    
    # 小数
    assert _safe_number(123.456789) == 123.456789
    print("✓ 小数 123.456789 -> 123.456789 (round 6 位)")
    
    # 字符串数字
    assert _safe_number("99.99") == 99.99
    print("✓ 字符串 '99.99' -> 99.99")
    
    # 超出 6 位小数的数字
    result = _safe_number(1.23456789)
    assert result == 1.234568, f"期望 1.234568，得到 {result}"
    print("✓ 1.23456789 -> 1.234568 (四舍五入)")
    
    print("\n✅ _safe_number(正常数字) 测试通过")


def test_safe_number_invalid():
    """测试 _safe_number 处理非法值"""
    print("\n" + "="*60)
    print("测试：_safe_number(非法值)")
    print("="*60)
    
    # 非法字符串
    result = _safe_number("not_a_number")
    assert result == 0.0, f"期望 0.0，得到 {result}"
    print("✓ 'not_a_number' -> 0.0")
    
    # 空字符串
    result = _safe_number("")
    assert result == 0.0, f"期望 0.0，得到 {result}"
    print("✓ '' -> 0.0")
    
    # 对象
    result = _safe_number(object())
    assert result == 0.0, f"期望 0.0，得到 {result}"
    print("✓ object() -> 0.0")
    
    print("\n✅ _safe_number(非法值) 测试通过")


# =============================================================================
# C. normalize_quote_request 参数标准化
# =============================================================================

def test_normalize_symbol_strip():
    """测试 symbol 去除空格"""
    print("\n" + "="*60)
    print("测试：normalize_quote_request - symbol strip")
    print("="*60)
    
    symbol, market = normalize_quote_request("  00700  ", "HK")
    assert symbol == "00700", f"期望 '00700'，得到 '{symbol}'"
    assert market == "HK"
    
    print("✓ '  00700  ' -> '00700'")
    print("\n✅ symbol strip 测试通过")


def test_normalize_market_upper_strip():
    """测试 market 大写和去除空格"""
    print("\n" + "="*60)
    print("测试：normalize_quote_request - market upper/strip")
    print("="*60)
    
    # 小写
    symbol, market = normalize_quote_request("00700", "hk")
    assert market == "HK", f"期望 'HK'，得到 '{market}'"
    print("✓ 'hk' -> 'HK'")
    
    # 带空格
    symbol, market = normalize_quote_request("00700", "  hk  ")
    assert market == "HK", f"期望 'HK'，得到 '{market}'"
    print("✓ '  hk  ' -> 'HK'")
    
    # 混合
    symbol, market = normalize_quote_request("00700", " Hk ")
    assert market == "HK", f"期望 'HK'，得到 '{market}'"
    print("✓ ' Hk ' -> 'HK'")
    
    print("\n✅ market upper/strip 测试通过")


def test_normalize_market_missing():
    """测试 market 缺失时的返回形态"""
    print("\n" + "="*60)
    print("测试：normalize_quote_request - market 缺失")
    print("="*60)
    
    # None
    symbol, market = normalize_quote_request("00700", None)
    assert market == "", f"期望 ''，得到 '{market}'"
    print("✓ None -> ''")
    
    # 空字符串
    symbol, market = normalize_quote_request("00700", "")
    assert market == "", f"期望 ''，得到 '{market}'"
    print("✓ '' -> ''")
    
    print("\n✅ market 缺失测试通过")


# =============================================================================
# D. resolve_quote_watch_item 自选股解析
# =============================================================================

def create_fake_config():
    """创建测试用的 fake config"""
    return {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "腾讯控股"},
            {"symbol": "09988", "market": "HK", "name": "阿里巴巴"},
            {"symbol": "BABA", "market": "US", "name": "阿里巴巴"},
            {"symbol": "600519", "market": "SH", "name": "贵州茅台"},
        ]
    }


def test_resolve_explicit_market_hit():
    """测试显式 market + 命中 watchlist"""
    print("\n" + "="*60)
    print("测试：resolve_quote_watch_item - 显式 market + 命中")
    print("="*60)
    
    config = create_fake_config()
    market, item = resolve_quote_watch_item(config, "00700", "HK")
    
    assert market == "HK", f"期望 'HK'，得到 '{market}'"
    assert item is not None, "应该找到 watch item"
    assert item["symbol"] == "00700"
    assert item["name"] == "腾讯控股"
    
    print("✓ market='HK', symbol='00700' -> 命中")
    print(f"✓ 返回 item: {item}")
    print("\n✅ 显式 market + 命中测试通过")


def test_resolve_symbol_only_unique():
    """测试不带 market + 通过 symbol 找到唯一 watch item"""
    print("\n" + "="*60)
    print("测试：resolve_quote_watch_item - symbol 唯一匹配")
    print("="*60)
    
    config = create_fake_config()
    market, item = resolve_quote_watch_item(config, "00700", None)
    
    assert market == "HK", f"期望 'HK'，得到 '{market}'"
    assert item is not None, "应该找到 watch item"
    assert item["symbol"] == "00700"
    assert item["name"] == "腾讯控股"
    
    print("✓ symbol='00700', market=None -> 找到唯一匹配")
    print(f"✓ 提取 market='HK'")
    print("\n✅ symbol 唯一匹配测试通过")


def test_resolve_symbol_ambiguous():
    """测试 symbol 有多个匹配时返回 None"""
    print("\n" + "="*60)
    print("测试：resolve_quote_watch_item - symbol 多匹配")
    print("="*60)
    
    config = create_fake_config()
    # 09988 和 BABA 都是阿里巴巴，但 symbol 不同
    # 测试一个不存在的 symbol
    market, item = resolve_quote_watch_item(config, "NOTEXIST", None)
    
    assert market == "HK", f"期望默认 'HK'，得到 '{market}'"
    assert item is None or item == {}, "不应该找到 watch item"
    
    print("✓ symbol='NOTEXIST' -> 未找到")
    print(f"✓ 默认 market='HK'")
    print("\n✅ symbol 多匹配/无匹配测试通过")


def test_resolve_default_market():
    """测试都没找到时 default market = 'HK'"""
    print("\n" + "="*60)
    print("测试：resolve_quote_watch_item - 默认 market")
    print("="*60)
    
    config = create_fake_config()
    market, item = resolve_quote_watch_item(config, "UNKNOWN", None)
    
    assert market == "HK", f"期望默认 'HK'，得到 '{market}'"
    
    print("✓ 未找到 watch item -> market='HK'")
    print("\n✅ 默认 market 测试通过")


def test_resolve_base_payload_structure():
    """测试返回的 base payload / name 结构合理"""
    print("\n" + "="*60)
    print("测试：resolve_quote_watch_item - 返回结构")
    print("="*60)
    
    config = create_fake_config()
    
    # 找到的情况
    market, item = resolve_quote_watch_item(config, "00700", "HK")
    assert market == "HK"
    assert item is not None
    assert "symbol" in item
    assert "name" in item
    assert "market" in item
    print("✓ 找到时：返回完整 watch item")
    
    # 未找到的情况
    market, item = resolve_quote_watch_item(config, "UNKNOWN", "HK")
    assert market == "HK"
    # item 可能是 None 或 {}
    print("✓ 未找到时：item 为 None 或 {}")
    
    print("\n✅ 返回结构测试通过")


# =============================================================================
# E. build_quote_payload 完整行情数据构建
# =============================================================================

def create_fake_config_for_build():
    """创建用于 build_quote_payload 测试的 config"""
    return {
        "watchlist": [
            {"symbol": "00700", "market": "HK", "name": "腾讯控股"},
            {"symbol": "09988", "market": "HK", "name": "阿里巴巴"},
        ]
    }


def create_fake_quote():
    """创建 fake 实时行情数据"""
    return {
        "current": 350.5,
        "change": 5.5,
        "change_pct": 1.59,
        "open": 345.0,
        "high": 352.0,
        "low": 344.0,
        "prev_close": 345.0,
        "volume": 1000000,
        "amount": 350500000.0,
        "time": "2026-04-07 13:00:00",
        "source": "test",
        "name": "腾讯控股",
    }


def test_build_happy_path(monkeypatch):
    """测试 happy path - fake config + monkeypatch fetch_realtime"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - happy path")
    print("="*60)
    
    config = create_fake_config_for_build()
    fake_quote = create_fake_quote()
    
    # monkeypatch fetch_realtime
    def mock_fetch_realtime(symbol, market):
        assert symbol == "00700"
        assert market == "HK"
        return fake_quote
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime)
    
    result = build_quote_payload(config, "00700", "HK")
    
    # 验证基本字段
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    assert result["name"] == "腾讯控股"
    print("✓ symbol, market, name 正确")
    
    # 验证价格字段
    assert result["price"] == 350.5
    assert result["change"] == 5.5
    assert result["change_pct"] == 1.59
    print("✓ price, change, change_pct 正确")
    
    # 验证 OHLC 字段
    assert result["open"] == 345.0
    assert result["high"] == 352.0
    assert result["low"] == 344.0
    assert result["prev_close"] == 345.0
    print("✓ open, high, low, prev_close 正确")
    
    # 验证成交量字段
    assert result["volume"] == 1000000
    assert result["amount"] == 350500000.0
    print("✓ volume, amount 正确")
    
    # 验证时间和来源
    assert result["time"] == "2026-04-07 13:00:00"
    assert result["source"] == "test"
    print("✓ time, source 正确")
    
    # 验证没有 error 字段
    assert "error" not in result
    print("✓ 无 error 字段（成功路径）")
    
    print("\n✅ happy path 测试通过")


def test_build_default_market(monkeypatch):
    """测试默认 market 路径"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - 默认 market")
    print("="*60)
    
    config = create_fake_config_for_build()
    fake_quote = create_fake_quote()
    
    def mock_fetch_realtime(symbol, market):
        assert symbol == "00700"
        assert market == "HK"  # 默认 market
        return fake_quote
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime)
    
    # 不提供 market 参数
    result = build_quote_payload(config, "00700")
    
    assert result["market"] == "HK"
    assert result["symbol"] == "00700"
    print("✓ 未提供 market -> 默认 'HK'")
    
    print("\n✅ 默认 market 测试通过")


def test_build_datasource_error(monkeypatch):
    """测试 DataSourceError 路径"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - DataSourceError")
    print("="*60)
    
    config = create_fake_config_for_build()
    
    def mock_fetch_realtime_error(symbol, market):
        from data_source import DataSourceError
        raise DataSourceError("数据源失败")
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime_error)
    
    result = build_quote_payload(config, "00700", "HK")
    
    # 验证错误路径返回
    assert "error" in result
    assert "数据源失败" in result["error"]
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    assert result["name"] == "腾讯控股"
    print("✓ 返回 error 字段")
    print(f"✓ error 内容：{result['error']}")
    
    # 验证没有价格字段
    assert "price" not in result
    assert "change" not in result
    print("✓ 无价格字段（错误路径）")
    
    print("\n✅ DataSourceError 测试通过")


def test_build_generic_exception(monkeypatch):
    """测试通用异常路径"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - 通用异常")
    print("="*60)
    
    config = create_fake_config_for_build()
    
    def mock_fetch_realtime_exception(symbol, market):
        raise ValueError("未知错误")
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime_exception)
    
    result = build_quote_payload(config, "00700", "HK")
    
    # 验证错误路径返回
    assert "error" in result
    assert "Failed to fetch realtime quote" in result["error"]
    assert "未知错误" in result["error"]
    print("✓ 返回 error 字段")
    print(f"✓ error 内容：{result['error']}")
    
    # 验证基本字段仍在
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    print("✓ 基本字段仍存在")
    
    print("\n✅ 通用异常测试通过")


def test_build_watchlist_name_fallback(monkeypatch):
    """测试 watchlist 名称覆盖 - quote 返回 name 为空时回退"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - watchlist name fallback")
    print("="*60)
    
    config = create_fake_config_for_build()
    
    # quote 返回 name 为空
    fake_quote_no_name = create_fake_quote()
    fake_quote_no_name["name"] = ""
    
    def mock_fetch_realtime(symbol, market):
        return fake_quote_no_name
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime)
    
    result = build_quote_payload(config, "00700", "HK")
    
    # 应该回退到 watchlist name
    assert result["name"] == "腾讯控股"
    print("✓ quote name 为空 -> 回退到 watchlist name")
    
    # 测试 quote 完全没有 name 字段
    fake_quote_missing_name = create_fake_quote()
    del fake_quote_missing_name["name"]
    
    def mock_fetch_realtime_missing(symbol, market):
        return fake_quote_missing_name
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime_missing)
    
    result = build_quote_payload(config, "00700", "HK")
    
    assert result["name"] == "腾讯控股"
    print("✓ quote name 缺失 -> 回退到 watchlist name")
    
    print("\n✅ watchlist name fallback 测试通过")


def test_build_safe_number_in_payload(monkeypatch):
    """测试 _safe_number 在 payload 中的应用"""
    print("\n" + "="*60)
    print("测试：build_quote_payload - _safe_number 应用")
    print("="*60)
    
    config = create_fake_config_for_build()
    
    # 构造包含 None/NaN 的 quote
    fake_quote_with_none = {
        "current": 350.5,
        "change": None,  # None
        "change_pct": float('nan'),  # NaN
        "open": 345.0,
        "high": float('inf'),  # Inf
        "low": 344.0,
        "prev_close": 345.0,
        "volume": 1000000,
        "amount": None,
        "time": "2026-04-07 13:00:00",
        "source": "test",
    }
    
    def mock_fetch_realtime(symbol, market):
        return fake_quote_with_none
    
    monkeypatch.setattr("services.quote_service.fetch_realtime", mock_fetch_realtime)
    
    result = build_quote_payload(config, "00700", "HK")
    
    # 验证 None/NaN/Inf 都被转换为 0.0
    assert result["change"] == 0.0, f"change 应该是 0.0，得到 {result['change']}"
    assert result["change_pct"] == 0.0, f"change_pct 应该是 0.0，得到 {result['change_pct']}"
    assert result["high"] == 0.0, f"high 应该是 0.0，得到 {result['high']}"
    assert result["amount"] == 0.0, f"amount 应该是 0.0，得到 {result['amount']}"
    
    print("✓ change=None -> 0.0")
    print("✓ change_pct=NaN -> 0.0")
    print("✓ high=Inf -> 0.0")
    print("✓ amount=None -> 0.0")
    
    print("\n✅ _safe_number 应用测试通过")


# =============================================================================
# 主入口
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Quote Service 单元测试套件")
    print("="*60)
    
    try:
        # A. 基础接口与异常
        test_module_import()
        test_quote_service_error_exists()
        
        # B. _safe_number
        test_safe_number_none()
        test_safe_number_nan()
        test_safe_number_inf()
        test_safe_number_normal()
        test_safe_number_invalid()
        
        # C. normalize_quote_request
        test_normalize_symbol_strip()
        test_normalize_market_upper_strip()
        test_normalize_market_missing()
        
        # D. resolve_quote_watch_item
        test_resolve_explicit_market_hit()
        test_resolve_symbol_only_unique()
        test_resolve_symbol_ambiguous()
        test_resolve_default_market()
        test_resolve_base_payload_structure()
        
        # E. build_quote_payload
        test_build_happy_path()
        test_build_default_market()
        test_build_datasource_error()
        test_build_generic_exception()
        test_build_watchlist_name_fallback()
        test_build_safe_number_in_payload()
        
        print("\n" + "="*60)
        print("🎉 全部测试通过！")
        print("="*60 + "\n")
        
    except AssertionError as e:
        print(f"\n❌ 测试失败：{e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常：{e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
