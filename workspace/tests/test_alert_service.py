# -*- coding: utf-8 -*-
"""
Alert Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实 monitor 运行。
使用 monkeypatch 隔离 AlertRule 依赖。
"""
import os
import sys

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services import alert_service
from services.alert_service import (
    AlertServiceError,
    AlertValidationError,
    AlertIndexError,
    AlertTestError,
    AlertTestNotFoundError,
    normalize_single_condition,
    normalize_conditions_tree,
    coerce_alert_payload,
    list_alerts,
    add_alert,
    update_alert,
    delete_alert,
    apply_alerts_update,
    build_indicator_history_for_alert_test,
    test_alert_rule as run_alert_rule_test,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert alert_service is not None
    assert AlertServiceError is not None
    assert AlertValidationError is not None
    assert AlertIndexError is not None


def test_exception_hierarchy():
    """AlertValidationError / AlertIndexError 都继承自 AlertServiceError"""
    assert issubclass(AlertValidationError, AlertServiceError)
    assert issubclass(AlertIndexError, AlertServiceError)


# =============================================================================
# B. normalize_single_condition 测试
# =============================================================================

def test_normalize_single_condition_valid():
    """合法条件能转成 {indicator, op, value(float)}"""
    result = normalize_single_condition({
        "indicator": "macd",
        "op": ">",
        "value": "0.5"
    })
    assert result == {"indicator": "macd", "op": ">", "value": 0.5}
    assert isinstance(result["value"], float)


def test_normalize_single_condition_missing_indicator():
    """缺少 indicator 时抛 AlertValidationError"""
    with pytest.raises(AlertValidationError, match="missing indicator/op"):
        normalize_single_condition({"op": ">", "value": 0.5})


def test_normalize_single_condition_missing_op():
    """缺少 op 时抛 AlertValidationError"""
    with pytest.raises(AlertValidationError, match="missing indicator/op"):
        normalize_single_condition({"indicator": "macd", "value": 0.5})


def test_normalize_single_condition_invalid_value():
    """value 非法时抛 AlertValidationError"""
    with pytest.raises(AlertValidationError, match="invalid value"):
        normalize_single_condition({"indicator": "macd", "op": ">", "value": "not_a_number"})


# =============================================================================
# C. normalize_conditions_tree 测试
# =============================================================================

def test_normalize_conditions_tree_list():
    """list 形式条件可递归规范化"""
    result = normalize_conditions_tree([
        {"indicator": "macd", "op": ">", "value": 0},
        {"indicator": "rsi", "op": "<", "value": 30}
    ])
    assert len(result) == 2
    assert result[0]["indicator"] == "macd"
    assert result[1]["indicator"] == "rsi"


def test_normalize_conditions_tree_nested_logic():
    """logic=AND/OR 的嵌套树可规范化"""
    result = normalize_conditions_tree({
        "logic": "AND",
        "rules": [
            {"indicator": "macd", "op": ">", "value": 0},
            {
                "logic": "OR",
                "rules": [
                    {"indicator": "rsi", "op": "<", "value": 30},
                    {"indicator": "kdj", "op": ">", "value": 80}
                ]
            }
        ]
    })
    assert result["logic"] == "AND"
    assert len(result["rules"]) == 2
    assert result["rules"][1]["logic"] == "OR"


def test_normalize_conditions_tree_invalid_logic():
    """非法 logic 抛异常"""
    with pytest.raises(AlertValidationError, match="logic must be AND or OR"):
        normalize_conditions_tree({
            "logic": "XOR",
            "rules": [{"indicator": "macd", "op": ">", "value": 0}]
        })


def test_normalize_conditions_tree_empty_rules():
    """空 rules 抛异常"""
    with pytest.raises(AlertValidationError, match="non-empty"):
        normalize_conditions_tree({"logic": "AND", "rules": []})


def test_normalize_conditions_tree_empty_list():
    """空 list 抛异常"""
    with pytest.raises(AlertValidationError, match="non-empty"):
        normalize_conditions_tree([])


# =============================================================================
# D. coerce_alert_payload 测试
# =============================================================================

class FakeAlertRule:
    """用于 monkeypatch 的轻量 fake AlertRule"""
    def __init__(self, data):
        self.data = data


class FakeAlertRuleRaises:
    """用于测试异常转换的 fake AlertRule（总是抛异常）"""
    def __init__(self, data):
        raise ValueError("Fake validation error")


def test_coerce_alert_payload_valid(monkeypatch):
    """合法 payload -> 返回规范化结构"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    payload = {
        "name": "测试告警",
        "period": "5min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
        "cooldown": 300,
        "ref_periods": ["15min", "30min"]
    }
    
    result = coerce_alert_payload(payload)
    
    assert result["name"] == "测试告警"
    assert result["period"] == "5min"
    assert result["cooldown"] == 300
    assert result["ref_periods"] == ["15min", "30min"]
    assert len(result["conditions"]) == 1


def test_coerce_alert_payload_invalid_period(monkeypatch):
    """非法 period -> AlertValidationError"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    with pytest.raises(AlertValidationError, match="Unsupported alert period"):
        coerce_alert_payload({
            "name": "测试",
            "period": "1day",  # 非法
            "conditions": [{"indicator": "macd", "op": ">", "value": 0}]
        })


def test_coerce_alert_payload_ref_periods_not_list(monkeypatch):
    """ref_periods 不是 list -> AlertValidationError"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    with pytest.raises(AlertValidationError, match="ref_periods must be a list"):
        coerce_alert_payload({
            "name": "测试",
            "period": "5min",
            "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
            "ref_periods": "15min"  # 应该是 list
        })


def test_coerce_alert_payload_cooldown_invalid_type(monkeypatch):
    """cooldown 非 int -> AlertValidationError"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    with pytest.raises(AlertValidationError, match="Cooldown must be an integer"):
        coerce_alert_payload({
            "name": "测试",
            "period": "5min",
            "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
            "cooldown": "not_a_number"
        })


def test_coerce_alert_payload_cooldown_negative(monkeypatch):
    """cooldown < 0 -> AlertValidationError"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    with pytest.raises(AlertValidationError, match="Cooldown must be >= 0"):
        coerce_alert_payload({
            "name": "测试",
            "period": "5min",
            "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
            "cooldown": -100
        })


def test_coerce_alert_payload_alert_rule_error(monkeypatch):
    """AlertRule 抛异常 -> 转成 AlertValidationError"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRuleRaises)
    
    with pytest.raises(AlertValidationError, match="Fake validation error"):
        coerce_alert_payload({
            "name": "测试",
            "period": "5min",
            "conditions": [{"indicator": "macd", "op": ">", "value": 0}]
        })


# =============================================================================
# E. CRUD 函数测试
# =============================================================================

def test_list_alerts_empty():
    """list_alerts({}) == []"""
    assert list_alerts({}) == []


def test_list_alerts_with_data():
    """list_alerts 返回 config 中的 alerts"""
    config = {"alerts": [{"name": "a1"}, {"name": "a2"}]}
    assert list_alerts(config) == [{"name": "a1"}, {"name": "a2"}]


def test_add_alert(monkeypatch):
    """add_alert 返回新增后的 alerts 列表"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    config = {"alerts": []}
    payload = {
        "name": "新告警",
        "period": "15min",
        "conditions": [{"indicator": "rsi", "op": "<", "value": 30}]
    }
    
    result = add_alert(config, payload)
    
    assert len(result) == 1
    assert result[0]["name"] == "新告警"
    # 验证原地修改
    assert len(config["alerts"]) == 1


def test_update_alert(monkeypatch):
    """update_alert 正常更新"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    config = {"alerts": [{"name": "旧告警", "period": "5min", "conditions": [], "cooldown": 300, "ref_periods": []}]}
    payload = {
        "name": "新名字",
        "period": "30min",
        "conditions": [{"indicator": "kdj", "op": ">", "value": 80}]
    }
    
    result = update_alert(config, 0, payload)
    
    assert len(result) == 1
    assert result[0]["name"] == "新名字"
    assert result[0]["period"] == "30min"


def test_update_alert_index_out_of_range():
    """update_alert index 越界 -> AlertIndexError"""
    config = {"alerts": [{"name": "a1"}]}
    
    with pytest.raises(AlertIndexError, match="out of range"):
        update_alert(config, 5, {"name": "x"})
    
    with pytest.raises(AlertIndexError, match="out of range"):
        update_alert(config, -1, {"name": "x"})


def test_delete_alert(monkeypatch):
    """delete_alert 正常删除"""
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRule)
    
    config = {"alerts": [
        {"name": "a1", "period": "5min", "conditions": [], "cooldown": 300, "ref_periods": []},
        {"name": "a2", "period": "15min", "conditions": [], "cooldown": 300, "ref_periods": []},
        {"name": "a3", "period": "30min", "conditions": [], "cooldown": 300, "ref_periods": []}
    ]}
    
    result = delete_alert(config, 1)
    
    assert len(result) == 2
    assert result[0]["name"] == "a1"
    assert result[1]["name"] == "a3"
    # 验证原地修改
    assert len(config["alerts"]) == 2


def test_delete_alert_index_out_of_range():
    """delete_alert index 越界 -> AlertIndexError"""
    config = {"alerts": [{"name": "a1"}]}
    
    with pytest.raises(AlertIndexError, match="out of range"):
        delete_alert(config, 5)
    
    with pytest.raises(AlertIndexError, match="out of range"):
        delete_alert(config, -1)


# =============================================================================
# F. apply_alerts_update 测试
# =============================================================================

def test_apply_alerts_update():
    """apply_alerts_update 返回带新 alerts 的 config 副本（浅拷贝）"""
    original_config = {"alerts": [{"name": "old"}], "other_key": "value"}
    new_alerts = [{"name": "new1"}, {"name": "new2"}]
    
    result = apply_alerts_update(original_config, new_alerts)
    
    assert result["alerts"] == new_alerts
    assert result["other_key"] == "value"
    # 当前实现是浅拷贝，原始 config 的 alerts 保持不变
    assert original_config["alerts"] == [{"name": "old"}]


def test_apply_alerts_update_preserves_other_fields():
    """apply_alerts_update 保留原始 config 的其他字段"""
    original_config = {
        "alerts": [],
        "data_source": "eastmoney",
        "check_interval": 60,
        "nested": {"key": "value"}
    }
    new_alerts = [{"name": "test"}]
    
    result = apply_alerts_update(original_config, new_alerts)
    
    assert result["data_source"] == "eastmoney"
    assert result["check_interval"] == 60
    assert result["nested"] == {"key": "value"}


# =============================================================================
# G. Alert Test 回放测试相关函数测试
# =============================================================================

# ------------------- build_indicator_history_for_alert_test 测试 -------------------

class FakeMACD:
    """Fake MACD for monkeypatch"""
    MIN_BARS = 34
    
    def __init__(self, *args, **kwargs):
        pass


class FakeIndicatorEngine:
    """Fake IndicatorEngine for monkeypatch"""
    
    def register(self, indicator):
        pass
    
    def calc_all(self, df):
        # 返回一个带 mock 结果的 DataFrame
        result_df = df.copy()
        result_df["macd"] = 0.5
        result_df["macd_dea"] = 0.3
        result_df["macd_hist"] = 0.2
        result_df["macd_slope"] = 0.01
        result_df["macd_dea_slope"] = 0.01
        result_df["macd_hist_slope"] = 0.01
        result_df.attrs["macd_data_status"] = "high"
        result_df.attrs["macd_data_info"] = {"bars": len(df), "min": 34, "recommend": 105}
        return result_df


def fake_load_multi_day_rows_success(market, symbol, period, target_date):
    """Fake load_multi_day_rows 返回成功数据"""
    # 返回 history_rows 和 target_rows
    history_rows = [
        {
            "calc_time": f"{target_date} 09:{i:02d}:00",
            "bar_time": f"09:{i:02d}:00",
            "open": 10.0 + i * 0.1,
            "high": 10.5 + i * 0.1,
            "low": 9.5 + i * 0.1,
            "close": 10.2 + i * 0.1,
            "volume": 1000 + i * 100,
            "amount": 10000 + i * 1000,
            "date": target_date,
        }
        for i in range(1, 25)  # 24 根 bar
    ]
    target_rows = history_rows  # 所有都是目标日期的
    return history_rows, target_rows


def fake_load_multi_day_rows_empty(market, symbol, period, target_date):
    """Fake load_multi_day_rows 返回空数据"""
    return [], []


def test_build_indicator_history_for_alert_test_success(monkeypatch):
    """build_indicator_history_for_alert_test 成功返回 bars 列表"""
    monkeypatch.setattr(alert_service, "load_multi_day_rows", fake_load_multi_day_rows_success)
    monkeypatch.setattr(alert_service, "IndicatorEngine", FakeIndicatorEngine)
    monkeypatch.setattr(alert_service, "MACD", FakeMACD)
    
    bars = build_indicator_history_for_alert_test("HK", "00700", "15min", "2026-04-07")
    
    assert len(bars) > 0
    assert "time" in bars[0]
    assert "macd" in bars[0]
    assert "dea" in bars[0]
    assert "hist" in bars[0]
    assert "macd_slope" in bars[0]
    assert "dea_slope" in bars[0]
    assert "hist_slope" in bars[0]
    assert isinstance(bars[0]["macd"], float)


def test_build_indicator_history_for_alert_test_empty_target_rows(monkeypatch):
    """target_rows 为空时抛 AlertTestNotFoundError"""
    monkeypatch.setattr(alert_service, "load_multi_day_rows", fake_load_multi_day_rows_empty)
    
    with pytest.raises(AlertTestNotFoundError, match="No .* data found"):
        build_indicator_history_for_alert_test("HK", "00700", "15min", "2026-04-07")


def test_build_indicator_history_for_alert_test_load_error(monkeypatch):
    """load_multi_day_rows 抛异常时转成 AlertTestNotFoundError"""
    def fake_load_error(*args, **kwargs):
        raise ValueError("Database not found")
    
    monkeypatch.setattr(alert_service, "load_multi_day_rows", fake_load_error)
    
    with pytest.raises(AlertTestNotFoundError, match="Failed to load data"):
        build_indicator_history_for_alert_test("HK", "00700", "15min", "2026-04-07")


# ------------------- test_alert_rule 测试 -------------------

class FakeAlertRuleForTest:
    """Fake AlertRule 用于 test_alert_rule 测试"""
    
    def __init__(self, data):
        self.data = data
        self.evaluate_call_count = 0
    
    def evaluate(self, current, prev, prev_prev):
        # 简单逻辑：macd > 0 就触发
        self.evaluate_call_count += 1
        return current.get("macd", 0) > 0


def fake_coerce_alert_payload_success(payload):
    """Fake coerce_alert_payload 返回规范化 payload"""
    return {
        "name": payload.get("name", "test"),
        "period": payload.get("period", "15min"),
        "conditions": payload.get("conditions", []),
        "cooldown": payload.get("cooldown", 0),
    }


def fake_build_indicator_history_for_alert_test_success(market, symbol, period, target_date):
    """Fake build_indicator_history_for_alert_test 返回测试数据"""
    return [
        {"time": f"09:{i:02d}:00", "macd": 0.1 * i, "dea": 0.05 * i, "hist": 0.05 * i, 
         "macd_slope": 0.01, "dea_slope": 0.01, "hist_slope": 0.01}
        for i in range(1, 21)  # 20 根 bar
    ]


def test_test_alert_rule_happy_path(monkeypatch):
    """test_alert_rule happy path: 返回完整结构"""
    monkeypatch.setattr(alert_service, "coerce_alert_payload", fake_coerce_alert_payload_success)
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRuleForTest)
    monkeypatch.setattr(alert_service, "build_indicator_history_for_alert_test", 
                        fake_build_indicator_history_for_alert_test_success)
    
    config = {
        "watchlist": [
            {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        ]
    }
    
    payload = {
        "period": "15min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
        "date": "2026-04-07"
    }
    
    result = run_alert_rule_test(payload, config)
    
    # 验证返回结构完整
    assert "symbol" in result
    assert "market" in result
    assert "date" in result
    assert "period" in result
    assert "triggered_bars" in result
    assert "bar_details" in result
    assert "total_bars_tested" in result
    assert "edge_triggered_count" in result
    
    # 验证默认从 watchlist 取 symbol/market
    assert result["symbol"] == "00700"
    assert result["market"] == "HK"
    assert result["date"] == "2026-04-07"
    assert result["period"] == "15min"
    
    # 验证 triggered_bars 和 bar_details 合理
    assert result["total_bars_tested"] == 20
    assert len(result["bar_details"]) == 18  # 从 index 2 开始
    assert isinstance(result["triggered_bars"], list)
    assert isinstance(result["edge_triggered_count"], int)


def test_test_alert_rule_explicit_symbol(monkeypatch):
    """test_alert_rule: payload 显式指定 symbol/market"""
    monkeypatch.setattr(alert_service, "coerce_alert_payload", fake_coerce_alert_payload_success)
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRuleForTest)
    monkeypatch.setattr(alert_service, "build_indicator_history_for_alert_test", 
                        fake_build_indicator_history_for_alert_test_success)
    
    config = {
        "watchlist": [
            {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        ]
    }
    
    payload = {
        "symbol": "09988",
        "market": "HK",
        "period": "15min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
    }
    
    result = run_alert_rule_test(payload, config)
    
    # 验证使用 payload 中的 symbol/market
    assert result["symbol"] == "09988"
    assert result["market"] == "HK"


def test_test_alert_rule_no_symbol_empty_watchlist(monkeypatch):
    """test_alert_rule: 没有 symbol 且 watchlist 为空 -> 抛 AlertTestError"""
    monkeypatch.setattr(alert_service, "coerce_alert_payload", fake_coerce_alert_payload_success)
    
    config = {
        "watchlist": []
    }
    
    payload = {
        "period": "15min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
    }
    
    with pytest.raises(AlertTestError, match="No symbol provided"):
        run_alert_rule_test(payload, config)


def test_test_alert_rule_not_enough_bars(monkeypatch):
    """test_alert_rule: bars 数量 < 3 -> 抛 AlertTestError"""
    monkeypatch.setattr(alert_service, "coerce_alert_payload", fake_coerce_alert_payload_success)
    monkeypatch.setattr(alert_service, "AlertRule", FakeAlertRuleForTest)
    
    def fake_build_only_2_bars(*args, **kwargs):
        return [
            {"time": "09:01:00", "macd": 0.1, "dea": 0.05, "hist": 0.05, 
             "macd_slope": 0.01, "dea_slope": 0.01, "hist_slope": 0.01},
            {"time": "09:02:00", "macd": 0.2, "dea": 0.1, "hist": 0.1, 
             "macd_slope": 0.01, "dea_slope": 0.01, "hist_slope": 0.01},
        ]
    
    monkeypatch.setattr(alert_service, "build_indicator_history_for_alert_test", 
                        fake_build_only_2_bars)
    
    config = {
        "watchlist": [{"market": "HK", "symbol": "00700", "name": "腾讯控股"}]
    }
    
    payload = {
        "period": "15min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
    }
    
    with pytest.raises(AlertTestError, match="Not enough bars"):
        run_alert_rule_test(payload, config)


def test_test_alert_rule_coerce_error(monkeypatch):
    """test_alert_rule: coerce_alert_payload 抛异常时正确向上传递"""
    def fake_coerce_error(payload):
        raise AlertValidationError("Invalid payload: name is required")
    
    monkeypatch.setattr(alert_service, "coerce_alert_payload", fake_coerce_error)
    
    config = {
        "watchlist": [{"market": "HK", "symbol": "00700", "name": "腾讯控股"}]
    }
    
    payload = {
        "period": "15min",
        "conditions": [{"indicator": "macd", "op": ">", "value": 0}],
    }
    
    with pytest.raises(AlertValidationError, match="Invalid payload"):
        run_alert_rule_test(payload, config)
