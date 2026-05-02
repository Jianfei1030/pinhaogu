#!/usr/bin/env python3
"""
Market Data Service 单元测试

纯 monkeypatch / 纯内存测试，不依赖真实 DB 或网络。
覆盖 service 最核心的行为。

用法：
    python -m pytest workspace/tests/test_market_data_service.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.market_data_service import (
    MarketDataError,
    MarketDataNotFoundError,
    period_to_table,
    resolve_db_path,
    days_needed_for_macd,
    get_kline_api_payload,
    set_project_root,
    _get_project_root,
)


# =============================================================================
# A. 基础接口与异常
# =============================================================================

def test_module_importable():
    """A1: 模块可导入，核心函数可调用"""
    # 如果能执行到这里，说明模块已成功导入
    assert callable(period_to_table)
    assert callable(get_kline_api_payload)
    assert callable(set_project_root)


def test_market_data_not_found_inherits_from_market_data_error():
    """A2: MarketDataNotFoundError 继承自 MarketDataError"""
    assert issubclass(MarketDataNotFoundError, MarketDataError)
    
    # 验证可以用父类捕获
    try:
        raise MarketDataNotFoundError("test error")
    except MarketDataError as e:
        assert str(e) == "test error"


# =============================================================================
# B. period_to_table
# =============================================================================

@pytest.mark.parametrize("period,expected_table", [
    ("1min", "kline_1min"),
    ("5min", "kline_5min"),
    ("15min", "kline_15min"),
    ("30min", "kline_30min"),
    ("60min", "kline_60min"),
    ("daily", "kline_daily"),
])
def test_period_to_table_valid(period, expected_table):
    """B1: 合法 period 返回正确的表名"""
    assert period_to_table(period) == expected_table


def test_period_to_table_invalid():
    """B2: 非法 period 抛出 MarketDataError"""
    with pytest.raises(MarketDataError) as exc_info:
        period_to_table("bad-period")
    assert "Unsupported period" in str(exc_info.value)
    assert "bad-period" in str(exc_info.value)


# =============================================================================
# C. days_needed_for_macd
# =============================================================================

def test_days_needed_for_macd_returns_int():
    """C1: 返回值是整数且在合理区间"""
    for period in ["1min", "5min", "15min", "30min", "60min", "daily"]:
        days = days_needed_for_macd(period)
        assert isinstance(days, int)
        assert 30 <= days <= 120, f"{period} 返回 {days} 不在合理区间"


def test_days_needed_for_macd_varies_by_period():
    """C2: 不同 period 返回不同的天数"""
    days_1min = days_needed_for_macd("1min")
    days_60min = days_needed_for_macd("60min")
    days_daily = days_needed_for_macd("daily")
    
    # 1min 周期每天 bars 多，需要的天数少
    # 60min 周期每天 bars 少，需要的天数多
    assert days_1min < days_60min
    assert days_60min <= days_daily  # daily 按默认 4 bars/天计算


# =============================================================================
# D. resolve_db_path / set_project_root
# =============================================================================

def test_resolve_db_path_uses_project_root(tmp_path):
    """D1: resolve_db_path 返回路径以设定的 project root 为前缀"""
    # 设置临时的 project root
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    set_project_root(fake_root)
    
    # 验证 _get_project_root 返回设定的值
    assert _get_project_root() == fake_root
    
    # 调用 resolve_db_path
    db_path = resolve_db_path("HK", "01810", "2026-04-07")
    
    # 验证路径以设定的 root 为前缀
    assert str(db_path).startswith(str(fake_root))
    
    # 清理：重置 project root
    set_project_root(None)


# =============================================================================
# E. get_kline_api_payload 的 daily 路径 (Happy Path)
# =============================================================================

def test_get_kline_api_payload_daily_happy_path(monkeypatch, tmp_path):
    """E1: daily 路径纯内存 happy path"""
    # 准备假的 daily 数据
    fake_daily_rows = [
        {"date": "2026-04-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
        {"date": "2026-04-06", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.5, "volume": 1200},
        {"date": "2026-04-07", "open": 10.5, "high": 11.0, "low": 10.3, "close": 10.8, "volume": 1500},
    ]
    
    # Monkeypatch fetch_daily
    def fake_fetch_daily(symbol, start, end, limit, market):
        return fake_daily_rows
    
    monkeypatch.setattr("services.market_data_service.fetch_daily", fake_fetch_daily)
    
    # Monkeypatch IndicatorEngine 和 MACD，避免真实指标计算
    fake_result = MagicMock()
    fake_result.attrs = {
        "macd_data_status": "high",
        "macd_data_info": {"bars": 3, "min": 34, "recommend": 200},
    }
    fake_result.__iter__ = lambda self: iter([0, 1, 2])
    fake_result.__len__ = lambda self: 3
    fake_result.iterrows = lambda: [
        (0, {"bar_time": "2026-04-05", "macd": 0.1, "macd_dea": 0.08, "macd_hist": 0.02,
             "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003}),
        (1, {"bar_time": "2026-04-06", "macd": 0.15, "macd_dea": 0.1, "macd_hist": 0.05,
             "macd_slope": 0.02, "macd_dea_slope": 0.01, "macd_hist_slope": 0.008}),
        (2, {"bar_time": "2026-04-07", "macd": 0.2, "macd_dea": 0.12, "macd_hist": 0.08,
             "macd_slope": 0.03, "macd_dea_slope": 0.015, "macd_hist_slope": 0.01}),
    ]
    fake_result.apply = lambda fn, axis=0: [True, True, True]
    
    fake_macd = MagicMock()
    fake_macd.MIN_BARS = 34
    
    fake_engine = MagicMock()
    fake_engine.register = lambda x: None
    fake_engine.calc_all = lambda df: fake_result
    
    monkeypatch.setattr("services.market_data_service.IndicatorEngine", lambda: fake_engine)
    monkeypatch.setattr("services.market_data_service.MACD", lambda f, s, t: fake_macd)
    
    # 调用 API
    result = get_kline_api_payload(
        market='A',
        symbol='600000',
        period='daily',
        target_date='2026-04-07',
        name='浦发银行'
    )
    
    # 断言返回结构完整
    assert result["symbol"] == "600000"
    assert result["name"] == "浦发银行"
    assert result["period"] == "daily"
    assert result["date"] == "2026-04-07"
    assert result["market"] == "A"
    
    assert "data_status" in result
    assert "data_bars" in result
    assert "data_min_bars" in result
    assert "data_recommend_bars" in result
    
    assert isinstance(result["kline"], list)
    assert isinstance(result["macd"], list)
    assert len(result["kline"]) == 3
    assert len(result["macd"]) == 3
    
    assert result["prev_close"] is not None  # 应该有前一日收盘价
    assert result["today_close"] is not None  # 应该有今日收盘价


# =============================================================================
# F. get_kline_api_payload 的非法 period 路径
# =============================================================================

def test_get_kline_api_payload_invalid_period():
    """F1: 非法 period 抛出 MarketDataError"""
    with pytest.raises(MarketDataError) as exc_info:
        get_kline_api_payload(
            market='A',
            symbol='600000',
            period='bad-period',
            target_date='2026-04-07',
            name='浦发银行'
        )
    assert "Unsupported period" in str(exc_info.value)


# =============================================================================
# G. get_kline_api_payload 的 intraday 路径 (Smoke Test)
# =============================================================================

def test_get_kline_api_payload_intraday_smoke(monkeypatch, tmp_path):
    """G1: intraday 路径轻量 smoke test"""
    # 准备假的数据库路径
    fake_db_path = tmp_path / "fake_db.sqlite"
    fake_db_path.touch()  # 创建空文件表示存在
    
    # Monkeypatch ensure_db 返回存在的假路径
    monkeypatch.setattr("services.market_data_service.ensure_db", lambda m, s, d: fake_db_path)
    
    # Monkeypatch query_kline 返回假的当前表数据
    fake_current_rows = [
        {"bar_time": "10:00", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "amount": 0},
        {"bar_time": "10:30", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.5, "volume": 1200, "amount": 0},
        {"bar_time": "11:00", "open": 10.5, "high": 11.0, "low": 10.3, "close": 10.8, "volume": 1500, "amount": 0},
    ]
    monkeypatch.setattr("services.market_data_service.query_kline", lambda path, table: fake_current_rows)
    
    # Monkeypatch load_multi_day_rows 返回假的历史数据
    fake_history_rows = [
        {"calc_time": "2026-04-07 10:00", "bar_time": "10:00", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000, "amount": 0, "date": "2026-04-07"},
        {"calc_time": "2026-04-07 10:30", "bar_time": "10:30", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.5, "volume": 1200, "amount": 0, "date": "2026-04-07"},
        {"calc_time": "2026-04-07 11:00", "bar_time": "11:00", "open": 10.5, "high": 11.0, "low": 10.3, "close": 10.8, "volume": 1500, "amount": 0, "date": "2026-04-07"},
    ]
    fake_target_rows = fake_history_rows  # 简化：target_rows 和 history_rows 一样
    monkeypatch.setattr("services.market_data_service.load_multi_day_rows", lambda m, s, p, d: (fake_history_rows, fake_target_rows))
    
    # Monkeypatch calc_macd_payload 返回假的结果
    fake_macd_payload = [
        {"time": "10:00", "macd": 0.1, "dea": 0.08, "hist": 0.02, "macd_slope": 0.01, "dea_slope": 0.005, "hist_slope": 0.003},
        {"time": "10:30", "macd": 0.15, "dea": 0.1, "hist": 0.05, "macd_slope": 0.02, "dea_slope": 0.01, "hist_slope": 0.008},
        {"time": "11:00", "macd": 0.2, "dea": 0.12, "hist": 0.08, "macd_slope": 0.03, "dea_slope": 0.015, "hist_slope": 0.01},
    ]
    fake_data_status = "high"
    fake_data_info = {"bars": 3, "min": 34, "recommend": 105}
    monkeypatch.setattr("services.market_data_service.calc_macd_payload", lambda h, t: (fake_macd_payload, fake_data_status, fake_data_info))
    
    # Monkeypatch list_db_dates 返回空列表（避免真实 DB 查询）
    monkeypatch.setattr("services.market_data_service.list_db_dates", lambda m, s, db_dir: [])
    
    # Monkeypatch get_db_path 返回假路径
    monkeypatch.setattr("services.market_data_service.get_db_path", lambda m, s, d: Path("/fake/db/path"))
    
    # Monkeypatch fetch_daily 返回空（避免真实网络请求）
    monkeypatch.setattr("services.market_data_service.fetch_daily", lambda s, start, end, limit, market: [])
    
    # 调用 API
    result = get_kline_api_payload(
        market='HK',
        symbol='01810',
        period='60min',
        target_date='2026-04-07',
        name='小米'
    )
    
    # 断言返回结构完整
    assert result["symbol"] == "01810"
    assert result["name"] == "小米"
    assert result["period"] == "60min"
    assert result["date"] == "2026-04-07"
    assert result["market"] == "HK"
    
    assert "data_status" in result
    assert "data_bars" in result
    assert "data_min_bars" in result
    assert "data_recommend_bars" in result
    
    assert isinstance(result["kline"], list)
    assert isinstance(result["macd"], list)
    assert len(result["kline"]) > 0
    assert len(result["macd"]) > 0
    
    # prev_close 可能为 None（因为 monkeypatch 了 fetch_daily 返回空）
    # today_close 应该存在
    assert "prev_close" in result
    assert result["today_close"] is not None


# =============================================================================
# H. Not Found 路径
# =============================================================================

def test_get_kline_api_payload_daily_not_found(monkeypatch):
    """H1: daily 路径下 fetch_daily 返回空时抛出 MarketDataNotFoundError"""
    # Monkeypatch fetch_daily 返回空列表
    monkeypatch.setattr("services.market_data_service.fetch_daily", lambda s, start, end, limit, market: [])
    
    with pytest.raises(MarketDataNotFoundError) as exc_info:
        get_kline_api_payload(
            market='A',
            symbol='600000',
            period='daily',
            target_date='2026-04-07',
            name='浦发银行'
        )
    assert "No daily kline data found" in str(exc_info.value)


def test_get_kline_api_payload_intraday_db_not_found(monkeypatch):
    """H2: intraday 路径中 DB 不存在时抛出 MarketDataNotFoundError"""
    # 准备一个不存在的路径
    fake_db_path = Path("/tmp/this_file_does_not_exist_12345.sqlite")
    
    # Monkeypatch ensure_db 返回不存在的路径
    monkeypatch.setattr("services.market_data_service.ensure_db", lambda m, s, d: fake_db_path)
    
    with pytest.raises(MarketDataNotFoundError) as exc_info:
        get_kline_api_payload(
            market='HK',
            symbol='01810',
            period='60min',
            target_date='2026-04-07',
            name='小米'
        )
    assert "Database not found" in str(exc_info.value)


def test_get_kline_api_payload_intraday_table_empty(monkeypatch, tmp_path):
    """H3: intraday 路径中表为空时抛出 MarketDataNotFoundError"""
    # 准备假的数据库路径（存在）
    fake_db_path = tmp_path / "fake_db.sqlite"
    fake_db_path.touch()
    
    # Monkeypatch ensure_db 返回存在的路径
    monkeypatch.setattr("services.market_data_service.ensure_db", lambda m, s, d: fake_db_path)
    
    # Monkeypatch query_kline 返回空列表
    monkeypatch.setattr("services.market_data_service.query_kline", lambda path, table: [])
    
    with pytest.raises(MarketDataNotFoundError) as exc_info:
        get_kline_api_payload(
            market='HK',
            symbol='01810',
            period='60min',
            target_date='2026-04-07',
            name='小米'
        )
    assert "No data in" in str(exc_info.value)


# =============================================================================
# 额外覆盖：calc_macd_payload 的 not found 路径
# =============================================================================

def test_calc_macd_payload_no_target_rows(monkeypatch):
    """额外：calc_macd_payload 在 target_rows 为空时抛出 MarketDataNotFoundError"""
    from services.market_data_service import calc_macd_payload
    
    fake_history_rows = [{"calc_time": "2026-04-07 10:00", "bar_time": "10:00", "close": 10.0}]
    fake_target_rows = []  # 空 target_rows
    
    with pytest.raises(MarketDataNotFoundError) as exc_info:
        calc_macd_payload(fake_history_rows, fake_target_rows)
    assert "No kline data found for target date" in str(exc_info.value)
