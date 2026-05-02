# -*- coding: utf-8 -*-
"""
Monitor Schedule Service 独立单元测试

纯 datetime / 纯内存测试，不依赖 Monitor 主循环。
不依赖行情/推送/校准。
测试稳定、快速。
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.monitor_schedule_service import (
    MonitorScheduleServiceError,
    parse_clock,
    combine_today,
    market_sessions,
    trading_status,
    should_log_waiting,
    build_waiting_log_message,
)


# =============================================================================
# A. 基础接口与异常
# =============================================================================

class TestModuleImport:
    """模块导入测试"""

    def test_module_importable(self):
        """模块可导入"""
        from services import monitor_schedule_service
        assert monitor_schedule_service is not None

    def test_error_class_exists(self):
        """MonitorScheduleServiceError 异常类存在"""
        assert MonitorScheduleServiceError is not None
        assert issubclass(MonitorScheduleServiceError, Exception)


# =============================================================================
# B. parse_clock 测试
# =============================================================================

class TestParseClock:
    """parse_clock 函数测试"""

    def test_valid_time_morning(self):
        """合法时间：上午"""
        assert parse_clock("09:30") == (9, 30)

    def test_valid_time_afternoon(self):
        """合法时间：下午"""
        assert parse_clock("15:00") == (15, 0)

    def test_valid_time_midnight(self):
        """合法时间：午夜"""
        assert parse_clock("00:00") == (0, 0)

    def test_invalid_format_no_colon(self):
        """非法格式：无冒号"""
        with pytest.raises(MonitorScheduleServiceError):
            parse_clock("0930")

    def test_invalid_format_extra_colon(self):
        """非法格式：多个冒号"""
        with pytest.raises(MonitorScheduleServiceError):
            parse_clock("09:30:00")

    def test_invalid_format_non_numeric(self):
        """非法格式：非数字"""
        with pytest.raises(MonitorScheduleServiceError):
            parse_clock("ab:cd")


# =============================================================================
# C. combine_today 测试
# =============================================================================

class TestCombineToday:
    """combine_today 函数测试"""

    def test_combine_morning(self):
        """组合上午时间"""
        now = datetime(2026, 4, 7, 10, 30, 45, 123456)
        result = combine_today(now, "09:30")
        assert result == datetime(2026, 4, 7, 9, 30, 0, 0)

    def test_combine_afternoon(self):
        """组合下午时间"""
        now = datetime(2026, 4, 7, 10, 30, 45, 123456)
        result = combine_today(now, "13:00")
        assert result == datetime(2026, 4, 7, 13, 0, 0, 0)

    def test_combine_preserves_date(self):
        """保留日期部分"""
        now = datetime(2026, 12, 25, 8, 0, 0)
        result = combine_today(now, "14:30")
        assert result.year == 2026
        assert result.month == 12
        assert result.day == 25
        assert result.hour == 14
        assert result.minute == 30


# =============================================================================
# D. market_sessions 测试
# =============================================================================

class TestMarketSessions:
    """market_sessions 函数测试"""

    def test_a_share_double_session(self):
        """A 股双时段（上午 + 下午）"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"}
        }
        now = datetime(2026, 4, 7, 10, 0, 0)
        sessions = market_sessions(trading_hours, "A", now)
        
        assert len(sessions) == 2
        # 上午时段
        assert sessions[0][0] == datetime(2026, 4, 7, 9, 30, 0, 0)
        assert sessions[0][1] == datetime(2026, 4, 7, 11, 30, 0, 0)
        # 下午时段
        assert sessions[1][0] == datetime(2026, 4, 7, 13, 0, 0, 0)
        assert sessions[1][1] == datetime(2026, 4, 7, 15, 0, 0, 0)

    def test_hk_single_session(self):
        """HK 单时段（无午休）"""
        trading_hours = {
            "HK": {"start": "09:30", "end": "16:00"}
        }
        now = datetime(2026, 4, 7, 10, 0, 0)
        sessions = market_sessions(trading_hours, "HK", now)
        
        assert len(sessions) == 1
        assert sessions[0][0] == datetime(2026, 4, 7, 9, 30, 0, 0)
        assert sessions[0][1] == datetime(2026, 4, 7, 16, 0, 0, 0)

    def test_no_config_returns_empty(self):
        """无配置市场返回空列表"""
        trading_hours = {"A": {"start": "09:30", "end": "15:00"}}
        now = datetime(2026, 4, 7, 10, 0, 0)
        sessions = market_sessions(trading_hours, "US", now)
        assert sessions == []

    def test_incomplete_config_returns_empty(self):
        """配置不完整（缺少 end）返回空列表"""
        trading_hours = {"A": {"start": "09:30"}}
        now = datetime(2026, 4, 7, 10, 0, 0)
        sessions = market_sessions(trading_hours, "A", now)
        assert sessions == []

    def test_case_insensitive_market(self):
        """市场标识大小写不敏感"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00"}
        }
        now = datetime(2026, 4, 7, 10, 0, 0)
        assert market_sessions(trading_hours, "a", now) == market_sessions(trading_hours, "A", now)


# =============================================================================
# E. trading_status 测试
# =============================================================================

class TestTradingStatus:
    """trading_status 函数测试"""

    def test_during_trading_morning(self):
        """交易中：上午时段"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"}
        }
        now = datetime(2026, 4, 7, 10, 30, 0)
        watchlist = [{"symbol": "00700", "market": "A"}]
        
        result = trading_status(trading_hours, now, watchlist)
        
        assert result["active"] is True
        assert result["message"] == ""
        assert result["next_open"] is None

    def test_lunch_break(self):
        """午休时段"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"}
        }
        now = datetime(2026, 4, 7, 12, 0, 0)
        watchlist = [{"symbol": "00700", "market": "A"}]
        
        result = trading_status(trading_hours, now, watchlist)
        
        assert result["active"] is False
        assert "13:00" in result["message"]
        assert result["next_open"] == datetime(2026, 4, 7, 13, 0, 0, 0)

    def test_before_market_open(self):
        """未开盘：开盘前"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"}
        }
        now = datetime(2026, 4, 7, 8, 0, 0)
        watchlist = [{"symbol": "00700", "market": "A"}]
        
        result = trading_status(trading_hours, now, watchlist)
        
        assert result["active"] is False
        assert "09:30" in result["message"]
        assert result["next_open"] == datetime(2026, 4, 7, 9, 30, 0, 0)

    def test_after_market_close(self):
        """已收盘：收盘后"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"}
        }
        now = datetime(2026, 4, 7, 16, 0, 0)
        watchlist = [{"symbol": "00700", "market": "A"}]
        
        result = trading_status(trading_hours, now, watchlist)
        
        assert result["active"] is False
        assert "下次开盘" in result["message"] or "等待中" in result["message"]
        # next_open 应该是明天的 09:30
        assert result["next_open"] is not None
        assert result["next_open"].day == 8  # 明天

    def test_multi_market_any_active(self):
        """多市场联合判断：任一市场交易中即 active=True"""
        trading_hours = {
            "A": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"},
            "HK": {"start": "09:30", "end": "16:00"}
        }
        # A 股午休，但 HK 还在交易
        now = datetime(2026, 4, 7, 12, 0, 0)
        watchlist = [
            {"symbol": "00700", "market": "A"},
            {"symbol": "09988", "market": "HK"}
        ]
        
        result = trading_status(trading_hours, now, watchlist)
        
        assert result["active"] is True

    def test_no_watchlist_returns_active(self):
        """无 watchlist 时默认 active=True"""
        trading_hours = {"A": {"start": "09:30", "end": "15:00"}}
        now = datetime(2026, 4, 7, 20, 0, 0)
        
        result = trading_status(trading_hours, now, None)
        
        assert result["active"] is True
        assert result["message"] == ""

    def test_empty_watchlist_returns_active(self):
        """空 watchlist 时默认 active=True"""
        trading_hours = {"A": {"start": "09:30", "end": "15:00"}}
        now = datetime(2026, 4, 7, 20, 0, 0)
        
        result = trading_status(trading_hours, now, [])
        
        assert result["active"] is True


# =============================================================================
# F. should_log_waiting 测试
# =============================================================================

class TestShouldLogWaiting:
    """should_log_waiting 函数测试"""

    def test_first_time_none_returns_true(self):
        """首次（None）-> True"""
        now_ts = time.time()
        assert should_log_waiting(None, now_ts) is True

    def test_within_interval_returns_false(self):
        """未到节流间隔 -> False"""
        now_ts = 1000000.0
        last_log_at = now_ts - 600  # 10 分钟前
        assert should_log_waiting(last_log_at, now_ts, interval_seconds=1800.0) is False

    def test_beyond_interval_returns_true(self):
        """超过节流间隔 -> True"""
        now_ts = 1000000.0
        last_log_at = now_ts - 2000  # 超过 30 分钟
        assert should_log_waiting(last_log_at, now_ts, interval_seconds=1800.0) is True

    def test_exactly_at_interval(self):
        """刚好在间隔边界"""
        now_ts = 1000000.0
        last_log_at = now_ts - 1800  # 刚好 30 分钟
        assert should_log_waiting(last_log_at, now_ts, interval_seconds=1800.0) is True


# =============================================================================
# G. build_waiting_log_message 测试
# =============================================================================

class TestBuildWaitingLogMessage:
    """build_waiting_log_message 函数测试"""

    def test_basic_message(self):
        """基础消息构建"""
        status = {"message": "非交易时段，等待开盘：09:30", "next_open": datetime(2026, 4, 7, 9, 30)}
        result = build_waiting_log_message(status)
        assert result == "非交易时段，等待开盘：09:30"

    def test_with_watchlist_text(self):
        """带 watchlist_text 的消息构建"""
        status = {"message": "非交易时段，等待开盘：09:30"}
        watchlist_text = "A00700(腾讯), HK09988(阿里)"
        result = build_waiting_log_message(status, watchlist_text)
        assert result == "[A00700(腾讯), HK09988(阿里)] 非交易时段，等待开盘：09:30"

    def test_empty_message_returns_empty(self):
        """空 message 返回空字符串"""
        status = {"message": "", "active": True}
        result = build_waiting_log_message(status)
        assert result == ""

    def test_no_message_key_returns_empty(self):
        """无 message 键返回空字符串"""
        status = {"active": True}
        result = build_waiting_log_message(status)
        assert result == ""


# =============================================================================
# H. 轻量接线验证
# =============================================================================

class TestMonitorWrapperIntegration:
    """Monitor wrapper 接线验证（monkeypatch）"""

    def test_monitor_trading_status_uses_service(self, monkeypatch):
        """验证 Monitor._trading_status 调用 service（通过 monitor 模块）"""
        # 先导入 monitor 模块（触发导入）
        import monitor
        from monitor import Monitor
        
        # Mock monitor 模块中的 trading_status（因为是从 services 直接导入的）
        mock_result = {"active": False, "message": "mocked", "next_open": None}
        mock_calls = []
        
        def mock_trading_status(trading_hours, now, watchlist):
            mock_calls.append((trading_hours, now, watchlist))
            return mock_result
        
        # monkeypatch monitor 模块中的函数引用
        monkeypatch.setattr(monitor, "trading_status", mock_trading_status)
        
        # 创建最小化的 Monitor 实例
        monitor_instance = Monitor.__new__(Monitor)
        monitor_instance.trading_hours = {"A": {"start": "09:30", "end": "15:00"}}
        monitor_instance.watchlist = [{"symbol": "00700", "market": "A"}]
        
        # 调用 wrapper
        now = datetime(2026, 4, 7, 10, 0, 0)
        result = monitor_instance._trading_status(now)
        
        # 验证
        assert result == mock_result
        assert len(mock_calls) == 1

    def test_monitor_should_log_waiting_uses_service(self, monkeypatch):
        """验证 Monitor._should_log_waiting 调用 service（通过 monitor 模块）"""
        import monitor
        from monitor import Monitor
        
        mock_calls = []
        
        def mock_should_log_waiting(last_wait_log_at, now_ts, interval_seconds):
            mock_calls.append((last_wait_log_at, now_ts, interval_seconds))
            return True
        
        # monkeypatch monitor 模块中的函数引用
        monkeypatch.setattr(monitor, "should_log_waiting", mock_should_log_waiting)
        
        # 创建最小化的 Monitor 实例
        monitor_instance = Monitor.__new__(Monitor)
        monitor_instance.last_wait_log_at = None
        
        # 调用 wrapper
        now_ts = 1000000.0
        result = monitor_instance._should_log_waiting(now_ts)
        
        # 验证
        assert result is True
        assert len(mock_calls) == 1
        assert mock_calls[0][0] is None  # last_wait_log_at
        assert mock_calls[0][2] == 1800.0  # interval_seconds


# Import time for timestamp tests
import time
