# -*- coding: utf-8 -*-
"""
Monitor Alert Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实 monitor 运行。
使用 fake bars / fake AlertRule / monkeypatch 隔离依赖。
测试稳定、快速、无外部副作用。
"""
import os
import sys

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from services.monitor_alert_service import (
    MonitorAlertServiceError,
    slope_arrow,
    alert_context_from_row,
    build_rule_alert_message,
    detect_rule_alerts,
    detect_alerts,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert MonitorAlertServiceError is not None
    assert slope_arrow is not None
    assert alert_context_from_row is not None
    assert build_rule_alert_message is not None
    assert detect_rule_alerts is not None
    assert detect_alerts is not None


def test_exception_exists():
    """MonitorAlertServiceError 存在且为 Exception 子类"""
    assert issubclass(MonitorAlertServiceError, Exception)


# =============================================================================
# B. slope_arrow 测试
# =============================================================================

def test_slope_arrow_positive():
    """正值返回 ↗"""
    assert slope_arrow(0.5) == "↗"
    assert slope_arrow(100.0) == "↗"
    assert slope_arrow(0.001) == "↗"


def test_slope_arrow_negative():
    """负值返回 ↘"""
    assert slope_arrow(-0.3) == "↘"
    assert slope_arrow(-100.0) == "↘"
    assert slope_arrow(-0.001) == "↘"


def test_slope_arrow_zero():
    """0 返回 ↗"""
    assert slope_arrow(0.0) == "↗"
    assert slope_arrow(-0.0) == "↗"


# =============================================================================
# C. alert_context_from_row 测试
# =============================================================================

def test_alert_context_from_row_basic():
    """基础 row → context 结构完整"""
    row = pd.Series({
        "close": 100.5,
        "macd": 0.1,
        "macd_dea": 0.05,
        "macd_hist": 0.02,
        "macd_slope": 0.01,
        "macd_dea_slope": 0.005,
        "macd_hist_slope": 0.003,
        "bar_time": "2026-04-07 14:30:00",
    })
    
    context = alert_context_from_row(
        row=row,
        period="15min",
        symbol="00700",
        market="HK",
        stock_name="腾讯控股",
    )
    
    assert context["market"] == "HK"
    assert context["symbol"] == "00700"
    assert context["name"] == "腾讯控股"
    assert context["price"] == 100.5
    assert context["macd"] == 0.1
    assert context["macd_dea"] == 0.05
    assert context["macd_hist"] == 0.02
    assert context["macd_slope"] == 0.01
    assert context["macd_dea_slope"] == 0.005
    assert context["macd_hist_slope"] == 0.003
    assert context["bar_time"] == "2026-04-07 14:30:00"


def test_alert_context_from_row_with_realtime():
    """有 realtime 时 price/change_pct 等优先/补充逻辑"""
    row = pd.Series({
        "close": 100.0,  # 会被 realtime 覆盖
        "macd": 0.1,
        "macd_dea": 0.05,
        "macd_hist": 0.02,
        "macd_slope": 0.01,
        "macd_dea_slope": 0.005,
        "macd_hist_slope": 0.003,
        "bar_time": "2026-04-07 14:30:00",
    })
    
    realtime = {
        "current": 105.5,
        "prev_close": 100.0,
        "change_pct": 5.5,
        "time": "14:35:00",
    }
    
    context = alert_context_from_row(
        row=row,
        period="15min",
        symbol="00700",
        market="HK",
        stock_name="腾讯控股",
        realtime=realtime,
    )
    
    # realtime 优先
    assert context["price"] == 105.5
    # change_pct 从 realtime 计算
    assert context["change_pct"] == 5.5
    assert context["realtime_time"] == "14:35:00"


def test_alert_context_from_row_no_stock_name():
    """stock_name 为 None 时 name 为空字符串"""
    row = pd.Series({
        "close": 100.0,
        "macd": 0.1,
        "macd_dea": 0.05,
        "macd_hist": 0.02,
        "macd_slope": 0.01,
        "macd_dea_slope": 0.005,
        "macd_hist_slope": 0.003,
        "bar_time": "2026-04-07 14:30:00",
    })
    
    context = alert_context_from_row(
        row=row,
        period="15min",
        symbol="00700",
        market="HK",
        stock_name=None,
    )
    
    assert context["name"] == ""


def test_alert_context_from_row_ref_periods():
    """引用周期指标值被提取到 context"""
    row = pd.Series({
        "close": 100.0,
        "macd": 0.1,
        "5min_macd_slope": 0.02,
        "5min_macd_dea_slope": 0.01,
        "30min_macd_hist_slope": -0.005,
        "bar_time": "2026-04-07 14:30:00",
    })
    
    context = alert_context_from_row(
        row=row,
        period="15min",
        symbol="00700",
        market="HK",
    )
    
    assert context["5min_macd_slope"] == 0.02
    assert context["5min_macd_dea_slope"] == 0.01
    assert context["30min_macd_hist_slope"] == -0.005


# =============================================================================
# D. build_rule_alert_message 测试
# =============================================================================

class FakeAlertRule:
    """Fake AlertRule 用于测试"""
    def __init__(self, name="测试规则", period="15min", cooldown=300, ref_periods=None, evaluate_result=True):
        self.name = name
        self.period = period
        self.cooldown = cooldown
        self.ref_periods = ref_periods or []
        self.last_triggered = None
        self._evaluate_result = evaluate_result
    
    def evaluate(self, current, prev, prev_prev):
        return self._evaluate_result
    
    def in_cooldown(self):
        return self.last_triggered is not None
    
    def mark_triggered(self):
        import time
        self.last_triggered = time.time()


def test_build_rule_alert_message_basic():
    """基础消息构造"""
    context = {
        "market": "HK",
        "symbol": "00700",
        "name": "腾讯控股",
        "price": 105.5,
        "change_pct": 5.5,
        "bar_time": "2026-04-07 14:30:00",
        "realtime_time": "14:35:00",
        "macd": 0.1,
        "macd_dea": 0.05,
        "macd_hist": 0.02,
        "macd_slope": 0.01,
        "macd_dea_slope": 0.005,
        "macd_hist_slope": 0.003,
    }
    
    rule = FakeAlertRule(name="MACD 金叉", period="15min", cooldown=300)
    message = build_rule_alert_message(rule, context)
    
    assert "🔔 MACD 金叉" in message
    assert "腾讯控股 (HK00700)" in message
    assert "105.50" in message
    assert "+5.50%" in message
    assert "DIF:" in message
    assert "DEA:" in message
    assert "Hist:" in message
    assert "↗" in message  # 斜率都为正
    assert "Cooldown: 300s" in message


def test_build_rule_alert_message_with_ref_periods():
    """带引用周期字段的消息构造"""
    context = {
        "market": "HK",
        "symbol": "00700",
        "name": "腾讯控股",
        "price": 105.5,
        "change_pct": 5.5,
        "bar_time": "2026-04-07 14:30:00",
        "realtime_time": "14:35:00",
        "macd": 0.1,
        "macd_dea": 0.05,
        "macd_hist": 0.02,
        "macd_slope": 0.01,
        "macd_dea_slope": 0.005,
        "macd_hist_slope": 0.003,
        "5min_macd_slope": 0.02,
        "5min_macd_dea_slope": 0.015,
        "30min_macd_hist_slope": -0.005,
    }
    
    rule = FakeAlertRule(
        name="多周期共振",
        period="15min",
        cooldown=600,
        ref_periods=["5min", "30min"],
    )
    message = build_rule_alert_message(rule, context)
    
    assert "5min" in message
    assert "30min" in message
    assert "DIF slope:" in message
    assert "DEA slope:" in message
    assert "Hist slope:" in message
    assert "↗" in message  # 5min 斜率为正
    assert "↘" in message  # 30min hist slope 为负


def test_build_rule_alert_message_negative_slopes():
    """斜率为负时显示 ↘"""
    context = {
        "market": "HK",
        "symbol": "00700",
        "name": "腾讯控股",
        "price": 95.0,
        "change_pct": -5.0,
        "bar_time": "2026-04-07 14:30:00",
        "realtime_time": "14:35:00",
        "macd": -0.1,
        "macd_dea": -0.05,
        "macd_hist": -0.02,
        "macd_slope": -0.01,
        "macd_dea_slope": -0.005,
        "macd_hist_slope": -0.003,
    }
    
    rule = FakeAlertRule(name="MACD 死叉", period="15min", cooldown=300)
    message = build_rule_alert_message(rule, context)
    
    assert "↘" in message  # 所有斜率都为负
    assert "-5.00%" in message


# =============================================================================
# E. detect_rule_alerts 测试
# =============================================================================

def test_detect_rule_alerts_insufficient_bars():
    """不足 3 条 bars -> 空结果"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    
    bars = [
        {"close": 100.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:00:00"},
    ]
    
    alerts = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
        stock_name="腾讯控股",
    )
    
    assert len(alerts) == 0


def test_detect_rule_alerts_triggered():
    """命中路径 -> 返回结构化 alert 列表"""
    rule = FakeAlertRule(name="MACD 金叉", period="15min", cooldown=300)
    
    # 构造 edge-trigger 场景：上上根不满足，上根和当前满足
    bars = [
        # 上上根：不满足 (macd_slope < 0)
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        # 上根：满足 (macd_slope > 0)
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        # 当前：满足 (macd_slope > 0)
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    alerts = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
        stock_name="腾讯控股",
    )
    
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["type"] == "rule"
    assert "HK00700" in alert["key"]
    assert "MACD 金叉" in alert["key"]
    assert alert["rule"] is rule
    assert "context" in alert
    assert "message" in alert


def test_detect_rule_alerts_cooldown():
    """冷却路径 -> 不触发"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    rule.last_triggered = None  # 初始未触发
    
    # 先触发一次进入冷却
    bars = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    # 第一次触发
    alerts1 = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
    )
    assert len(alerts1) == 1
    
    # 立即再次检测（仍在冷却中）
    alerts2 = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
    )
    # 由于 mark_triggered 已调用，in_cooldown() 返回 True，所以不会再触发
    assert len(alerts2) == 0


def test_detect_rule_alerts_invalid_price():
    """price<=0 路径 -> 不触发"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    
    bars = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        {"close": 0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,  # price=0
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    alerts = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
    )
    
    assert len(alerts) == 0


def test_detect_rule_alerts_not_triggered():
    """未命中路径 -> 空结果"""
    # 使用 evaluate_result=False 让规则永远不满足条件
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300, evaluate_result=False)
    
    bars = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": -0.05, "macd_dea": -0.03, "macd_hist": -0.01,
         "macd_slope": -0.008, "macd_dea_slope": -0.004, "macd_hist_slope": -0.002,
         "bar_time": "14:15:00"},
        {"close": 102.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.015, "macd_dea_slope": -0.008, "macd_hist_slope": -0.005,
         "bar_time": "14:30:00"},
    ]
    
    alerts = detect_rule_alerts(
        rule=rule,
        bars=bars,
        symbol="00700",
        market="HK",
    )
    
    assert len(alerts) == 0


# =============================================================================
# F. detect_alerts 测试
# =============================================================================

def test_detect_alerts_multiple_rules():
    """多规则检测"""
    rule1 = FakeAlertRule(name="规则 1", period="15min", cooldown=300)
    rule2 = FakeAlertRule(name="规则 2", period="5min", cooldown=600)
    alert_rules = [rule1, rule2]
    
    bars_15min = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    bars_5min = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:05:00"},
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:10:00"},
    ]
    
    bars_by_period = {
        "15min": bars_15min,
        "5min": bars_5min,
    }
    
    alerts = detect_alerts(
        alert_rules=alert_rules,
        bars_by_period=bars_by_period,
        symbol="00700",
        market="HK",
    )
    
    # 两个规则都应该触发
    assert len(alerts) == 2


def test_detect_alerts_deduplication():
    """去重（last_alert_keys）"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    
    bars = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    bars_by_period = {"15min": bars}
    
    # 第一次检测
    alerts1 = detect_alerts(
        alert_rules=[rule],
        bars_by_period=bars_by_period,
        symbol="00700",
        market="HK",
        last_alert_keys=None,
    )
    assert len(alerts1) == 1
    
    # 第二次检测，使用 last_alert_keys 去重
    alert_key = alerts1[0]["key"]
    alerts2 = detect_alerts(
        alert_rules=[rule],
        bars_by_period=bars_by_period,
        symbol="00700",
        market="HK",
        last_alert_keys={alert_key},
    )
    assert len(alerts2) == 0


def test_detect_alerts_empty_bars():
    """空 bars_by_period"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    
    alerts = detect_alerts(
        alert_rules=[rule],
        bars_by_period={},
        symbol="00700",
        market="HK",
    )
    
    assert len(alerts) == 0


def test_detect_alerts_multiple_periods():
    """多周期输入"""
    rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
    
    bars_15min = [
        {"close": 100.0, "macd": -0.1, "macd_dea": -0.05, "macd_hist": -0.02,
         "macd_slope": -0.01, "macd_dea_slope": -0.005, "macd_hist_slope": -0.003,
         "bar_time": "14:00:00"},
        {"close": 101.0, "macd": 0.05, "macd_dea": 0.03, "macd_hist": 0.01,
         "macd_slope": 0.01, "macd_dea_slope": 0.005, "macd_hist_slope": 0.003,
         "bar_time": "14:15:00"},
        {"close": 102.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.02,
         "macd_slope": 0.015, "macd_dea_slope": 0.008, "macd_hist_slope": 0.005,
         "bar_time": "14:30:00"},
    ]
    
    bars_by_period = {
        "15min": bars_15min,
        "30min": [],  # 空周期
        "60min": bars_15min,  # 重复周期（但规则只匹配 15min）
    }
    
    alerts = detect_alerts(
        alert_rules=[rule],
        bars_by_period=bars_by_period,
        symbol="00700",
        market="HK",
    )
    
    assert len(alerts) == 1


# =============================================================================
# G. 轻量 wrapper 接线验证
# =============================================================================

def test_monitor_wrapper_slope_arrow():
    """验证 Monitor._slope_arrow 调用 service.slope_arrow"""
    from monitor import Monitor
    from pathlib import Path
    import tempfile
    
    # 创建临时配置文件
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("watchlist: []\nalerts: []\ntrading_hours: {}\n", encoding="utf-8")
        
        monitor = Monitor(config_path=str(config_path), interval=30)
        
        # 验证 wrapper 调用
        assert monitor._slope_arrow(0.5) == "↗"
        assert monitor._slope_arrow(-0.3) == "↘"
        assert monitor._slope_arrow(0.0) == "↗"


def test_monitor_wrapper_build_rule_alert_message():
    """验证 Monitor._build_rule_alert_message 调用 service.build_rule_alert_message"""
    from monitor import Monitor
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("watchlist: []\nalerts: []\ntrading_hours: {}\n", encoding="utf-8")
        
        monitor = Monitor(config_path=str(config_path), interval=30)
        
        context = {
            "market": "HK",
            "symbol": "00700",
            "name": "腾讯控股",
            "price": 105.5,
            "change_pct": 5.5,
            "bar_time": "2026-04-07 14:30:00",
            "realtime_time": "14:35:00",
            "macd": 0.1,
            "macd_dea": 0.05,
            "macd_hist": 0.02,
            "macd_slope": 0.01,
            "macd_dea_slope": 0.005,
            "macd_hist_slope": 0.003,
        }
        
        rule = FakeAlertRule(name="测试规则", period="15min", cooldown=300)
        message = monitor._build_rule_alert_message(rule, context)
        
        assert "🔔 测试规则" in message
        assert "腾讯控股" in message
