# -*- coding: utf-8 -*-
"""
Monitor Service 独立单元测试

纯 tmp_path / monkeypatch 测试，不启动真实 monitor 主循环。
不依赖真实行情/推送/校准。
测试稳定、快速。
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.monitor_service import (
    MonitorServiceError,
    resolve_monitor_path,
    load_monitor_config,
    load_monitor_alert_rules,
    load_monitor_trading_hours,
    build_monitor_runtime_config,
)


# =============================================================================
# A. Service Helper 测试
# =============================================================================

class TestResolveMonitorPath:
    """resolve_monitor_path 测试"""

    def test_relative_path(self, tmp_path):
        """相对路径解析：workspace / path"""
        result = resolve_monitor_path(tmp_path, "config.yaml")
        assert result == tmp_path / "config.yaml"

    def test_absolute_path(self, tmp_path):
        """绝对路径直接返回"""
        abs_path = Path("/absolute/config.yaml")
        result = resolve_monitor_path(tmp_path, str(abs_path))
        assert result == abs_path

    def test_nested_relative_path(self, tmp_path):
        """嵌套相对路径"""
        result = resolve_monitor_path(tmp_path, "configs/monitor.yaml")
        assert result == tmp_path / "configs" / "monitor.yaml"


class TestLoadMonitorConfig:
    """load_monitor_config 测试"""

    def test_valid_yaml(self, tmp_path):
        """有效 YAML 文件正常加载"""
        config_file = tmp_path / "config.yaml"
        config_data = {"watchlist": [{"symbol": "00700"}], "refresh_interval": 60}
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        result = load_monitor_config(config_file)

        assert result == config_data
        assert result["watchlist"] == [{"symbol": "00700"}]
        assert result["refresh_interval"] == 60

    def test_empty_yaml(self, tmp_path):
        """空 YAML 文件返回空字典"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")

        result = load_monitor_config(config_file)

        assert result == {}

    def test_file_not_exists(self, tmp_path):
        """文件不存在抛出 MonitorServiceError"""
        non_existent = tmp_path / "not_exists.yaml"

        with pytest.raises(MonitorServiceError) as exc_info:
            load_monitor_config(non_existent)

        assert "配置文件不存在" in str(exc_info.value)

    def test_invalid_yaml(self, tmp_path):
        """YAML 解析失败抛出 MonitorServiceError"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [", encoding="utf-8")

        with pytest.raises(MonitorServiceError) as exc_info:
            load_monitor_config(config_file)

        assert "配置文件解析失败" in str(exc_info.value)


class TestLoadMonitorAlertRules:
    """load_monitor_alert_rules 测试"""

    def test_normal_alerts(self, tmp_path, monkeypatch):
        """alerts 正常构建"""
        # Monkeypatch AlertRule 为 fake class
        class FakeAlertRule:
            def __init__(self, config):
                self.config = config

        # 延迟导入的 patch：需要 patch monitor.AlertRule
        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config = {
            "alerts": [
                {"name": "rule1", "period": "15min", "conditions": []},
                {"name": "rule2", "period": "5min", "conditions": []},
            ]
        }

        result = load_monitor_alert_rules(config)

        assert len(result) == 2
        assert isinstance(result[0], FakeAlertRule)
        assert result[0].config["name"] == "rule1"

    def test_empty_alerts(self, tmp_path, monkeypatch):
        """alerts 为空返回空列表"""
        config = {"alerts": []}

        result = load_monitor_alert_rules(config)

        assert result == []

    def test_missing_alerts(self, tmp_path, monkeypatch):
        """alerts 字段缺失返回空列表"""
        config = {"watchlist": []}

        result = load_monitor_alert_rules(config)

        assert result == []

    def test_alerts_as_dict(self, tmp_path, monkeypatch):
        """alerts 为字典（旧版）返回空列表"""
        config = {"alerts": {"old_format": True}}

        result = load_monitor_alert_rules(config)

        assert result == []

    def test_alerts_with_non_dict_items(self, tmp_path, monkeypatch):
        """alerts 包含非字典项被过滤"""
        class FakeAlertRule:
            def __init__(self, config):
                self.config = config

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config = {
            "alerts": [
                {"name": "valid", "period": "15min"},
                "invalid_string",
                123,
                None,
            ]
        }

        result = load_monitor_alert_rules(config)

        assert len(result) == 1
        assert result[0].config["name"] == "valid"


class TestLoadMonitorTradingHours:
    """load_monitor_trading_hours 测试"""

    def test_normal_trading_hours(self):
        """正常读取交易时间"""
        config = {
            "trading_hours": {
                "SH": {"start": "09:30", "end": "15:00"},
                "HK": {"start": "09:30", "end": "16:00"},
            }
        }

        result = load_monitor_trading_hours(config)

        assert "SH" in result
        assert "HK" in result
        assert result["SH"]["start"] == "09:30"
        assert result["HK"]["end"] == "16:00"

    def test_trading_hours_uppercase(self):
        """市场代码自动转大写"""
        config = {
            "trading_hours": {
                "sh": {"start": "09:30", "end": "15:00"},
                "hk": {"start": "09:30", "end": "16:00"},
            }
        }

        result = load_monitor_trading_hours(config)

        assert "SH" in result
        assert "HK" in result
        assert "sh" not in result
        assert "hk" not in result

    def test_missing_trading_hours(self):
        """trading_hours 缺失返回空字典"""
        config = {"watchlist": []}

        result = load_monitor_trading_hours(config)

        assert result == {}

    def test_trading_hours_not_dict(self):
        """trading_hours 不是字典返回空字典"""
        config = {"trading_hours": "invalid"}

        result = load_monitor_trading_hours(config)

        assert result == {}

    def test_trading_hours_with_non_dict_values(self):
        """trading_hours 值不是字典时被过滤"""
        config = {
            "trading_hours": {
                "SH": {"start": "09:30", "end": "15:00"},
                "HK": "invalid",
                "US": None,
            }
        }

        result = load_monitor_trading_hours(config)

        assert "SH" in result
        assert "HK" not in result
        assert "US" not in result


# =============================================================================
# B. build_monitor_runtime_config 测试
# =============================================================================

class TestBuildMonitorRuntimeConfig:
    """build_monitor_runtime_config 测试"""

    def test_full_config(self, tmp_path, monkeypatch):
        """完整配置场景"""
        # Monkeypatch AlertRule
        class FakeAlertRule:
            def __init__(self, config):
                self.name = config.get("name", "")

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        # 创建配置文件
        config_file = tmp_path / "config.yaml"
        config_data = {
            "watchlist": [{"symbol": "00700", "market": "HK", "name": "腾讯"}],
            "refresh_interval": 60,
            "alerts": [{"name": "test_rule", "period": "15min", "conditions": []}],
            "trading_hours": {"SH": {"start": "09:30", "end": "15:00"}},
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        assert result["workspace"] == tmp_path
        assert result["config_path"] == tmp_path / "config.yaml"
        assert result["config"] == config_data
        assert result["watchlist"] == [{"symbol": "00700", "market": "HK", "name": "腾讯"}]
        assert result["interval"] == 60
        assert len(result["alert_rules"]) == 1
        assert result["alert_rules"][0].name == "test_rule"
        assert result["trading_hours"] == {"SH": {"start": "09:30", "end": "15:00"}}

    def test_interval_parameter_priority(self, tmp_path, monkeypatch):
        """interval 参数优先级最高"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": [], "refresh_interval": 60}),
            encoding="utf-8"
        )

        # interval 参数覆盖 config.refresh_interval
        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
            interval=120,
        )

        assert result["interval"] == 120

    def test_config_refresh_interval_fallback(self, tmp_path, monkeypatch):
        """config.refresh_interval 回退"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": [], "refresh_interval": 45}),
            encoding="utf-8"
        )

        # 不传 interval 参数，使用 config.refresh_interval
        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        assert result["interval"] == 45

    def test_default_interval_30(self, tmp_path, monkeypatch):
        """默认 interval 回退到 30"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        # 没有 refresh_interval
        config_file.write_text(
            yaml.dump({"watchlist": []}),
            encoding="utf-8"
        )

        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        assert result["interval"] == 30

    def test_refresh_interval_none_uses_default(self, tmp_path, monkeypatch):
        """refresh_interval 为 None 时使用默认值 30"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": [], "refresh_interval": None}),
            encoding="utf-8"
        )

        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        assert result["interval"] == 30

    def test_watchlist_not_list(self, tmp_path, monkeypatch):
        """watchlist 不是列表时返回空列表"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": "invalid"}),
            encoding="utf-8"
        )

        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        assert result["watchlist"] == []

    def test_return_structure(self, tmp_path, monkeypatch):
        """返回结构包含所有必需字段"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": []}),
            encoding="utf-8"
        )

        result = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config.yaml",
        )

        # 验证所有必需字段
        assert "workspace" in result
        assert "config_path" in result
        assert "config" in result
        assert "watchlist" in result
        assert "interval" in result
        assert "alert_rules" in result
        assert "trading_hours" in result

        # 验证类型
        assert isinstance(result["workspace"], Path)
        assert isinstance(result["config_path"], Path)
        assert isinstance(result["config"], dict)
        assert isinstance(result["watchlist"], list)
        assert isinstance(result["interval"], int)
        assert isinstance(result["alert_rules"], list)
        assert isinstance(result["trading_hours"], dict)


# =============================================================================
# C. Monitor.__init__ 接线验证
# =============================================================================

class TestMonitorInit:
    """Monitor.__init__ 接线验证"""

    def test_monitor_init_core_fields(self, tmp_path, monkeypatch):
        """Monitor 初始化核心字段正确赋值"""
        # Monkeypatch signal.signal 避免真实注册
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        # Monkeypatch AlertRule
        class FakeAlertRule:
            def __init__(self, config):
                self.name = config.get("name", "")
                self.period = config.get("period", "")

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        # Monkeypatch IndicatorEngine
        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        # 创建配置文件（使用绝对路径，因为 Monitor 使用 __file__ 父目录作为 workspace）
        config_file = tmp_path / "config.yaml"
        config_data = {
            "watchlist": [
                {"symbol": "00700", "market": "HK", "name": "腾讯"},
                {"symbol": "600519", "market": "A", "name": "茅台"},
            ],
            "refresh_interval": 45,
            "alerts": [
                {"name": "macd_cross", "period": "15min", "conditions": []},
            ],
            "trading_hours": {
                "HK": {"start": "09:30", "end": "16:00"},
            },
        }
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        # 从 monitor 模块导入 Monitor 类
        from monitor import Monitor

        # 实例化 Monitor（不启动主循环）- 使用绝对路径
        monitor = Monitor(
            config_path=str(config_file),  # 绝对路径
            interval=60,
        )

        # 验证核心字段（workspace 是 monitor.py 所在目录，config_path 是绝对路径）
        assert monitor.config_path == config_file
        assert monitor.config == config_data
        assert monitor.watchlist == config_data["watchlist"]
        assert monitor.interval == 60  # 参数优先级高于 config
        assert len(monitor.alert_rules) == 1
        assert monitor.alert_rules[0].name == "macd_cross"
        assert monitor.trading_hours == {"HK": {"start": "09:30", "end": "16:00"}}

    def test_monitor_init_default_fields(self, tmp_path, monkeypatch):
        """Monitor 初始化其他字段保持默认值"""
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        # 创建最小配置文件
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": []}),
            encoding="utf-8"
        )

        from monitor import Monitor

        monitor = Monitor(config_path=str(config_file))

        # 验证其他初始化字段
        assert monitor.running is True
        assert monitor.tick_count == 0
        assert monitor.alert_count == 0
        assert monitor.last_prices == {}
        assert monitor.engine is not None

    def test_monitor_init_with_absolute_path(self, tmp_path, monkeypatch):
        """Monitor 支持绝对路径配置文件"""
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        # 创建配置文件（使用绝对路径）
        config_file = tmp_path / "monitor_config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": [{"symbol": "00700", "market": "HK"}]}),
            encoding="utf-8"
        )

        from monitor import Monitor

        # 使用绝对路径
        monitor = Monitor(
            config_path=str(config_file),
            interval=30,
        )

        # 验证路径解析正确（config_path 应该等于传入的绝对路径）
        assert monitor.config_path == config_file
        assert monitor.config_path.exists()

    def test_monitor_init_alert_rules_empty(self, tmp_path, monkeypatch):
        """Monitor 初始化 alerts 为空时正确处理"""
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": [], "alerts": []}),
            encoding="utf-8"
        )

        from monitor import Monitor

        monitor = Monitor(config_path=str(config_file))

        assert monitor.alert_rules == []

    def test_monitor_init_trading_hours_default(self, tmp_path, monkeypatch):
        """Monitor 初始化 trading_hours 缺失时默认为空字典"""
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"watchlist": []}),  # 没有 trading_hours
            encoding="utf-8"
        )

        from monitor import Monitor

        monitor = Monitor(config_path=str(config_file))

        assert monitor.trading_hours == {}


# =============================================================================
# D. 集成场景测试
# =============================================================================

class TestIntegrationScenarios:
    """集成场景测试"""

    def test_interval_priority_chain(self, tmp_path, monkeypatch):
        """interval 回退链完整测试：参数 > config > 默认 30"""
        class FakeAlertRule:
            def __init__(self, config):
                pass

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)

        # 场景 1: 参数优先级最高
        config_file1 = tmp_path / "config1.yaml"
        config_file1.write_text(
            yaml.dump({"watchlist": [], "refresh_interval": 90}),
            encoding="utf-8"
        )
        result1 = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config1.yaml",
            interval=15,
        )
        assert result1["interval"] == 15

        # 场景 2: 无参数时使用 config.refresh_interval
        config_file2 = tmp_path / "config2.yaml"
        config_file2.write_text(
            yaml.dump({"watchlist": [], "refresh_interval": 45}),
            encoding="utf-8"
        )
        result2 = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config2.yaml",
        )
        assert result2["interval"] == 45

        # 场景 3: 无参数且 config 无 refresh_interval 时使用默认值 30
        config_file3 = tmp_path / "config3.yaml"
        config_file3.write_text(
            yaml.dump({"watchlist": []}),
            encoding="utf-8"
        )
        result3 = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="config3.yaml",
        )
        assert result3["interval"] == 30

    def test_full_runtime_config_workflow(self, tmp_path, monkeypatch):
        """完整运行时配置工作流测试"""
        class FakeAlertRule:
            def __init__(self, config):
                self.name = config.get("name", "")

        monkeypatch.setattr("monitor.AlertRule", FakeAlertRule)
        monkeypatch.setattr("signal.signal", lambda sig, handler: None)

        class FakeIndicatorEngine:
            def register(self, indicator):
                pass

        monkeypatch.setattr("monitor.IndicatorEngine", FakeIndicatorEngine)

        # 创建完整配置
        config_file = tmp_path / "full_config.yaml"
        full_config = {
            "watchlist": [
                {"symbol": "00700", "market": "HK", "name": "腾讯控股"},
                {"symbol": "600519", "market": "A", "name": "贵州茅台"},
            ],
            "refresh_interval": 60,
            "alerts": [
                {
                    "name": "macd_golden_cross",
                    "period": "15min",
                    "conditions": [
                        {"indicator": "macd", "op": ">", "value": 0},
                    ],
                },
            ],
            "trading_hours": {
                "SH": {"start": "09:30", "end": "15:00", "break_start": "11:30", "break_end": "13:00"},
                "HK": {"start": "09:30", "end": "16:00"},
            },
        }
        config_file.write_text(yaml.dump(full_config), encoding="utf-8")

        # 使用 build_monitor_runtime_config
        runtime_cfg = build_monitor_runtime_config(
            workspace=tmp_path,
            config_path="full_config.yaml",
            interval=45,
        )

        # 验证 service 层返回
        assert runtime_cfg["interval"] == 45  # 参数优先级
        assert len(runtime_cfg["watchlist"]) == 2
        assert len(runtime_cfg["alert_rules"]) == 1
        assert "SH" in runtime_cfg["trading_hours"]
        assert "HK" in runtime_cfg["trading_hours"]

        # 使用 Monitor 实例化
        from monitor import Monitor

        monitor = Monitor(
            config_path=str(config_file),
            interval=45,
        )

        # 验证 Monitor 字段与 runtime_cfg 一致
        assert monitor.interval == runtime_cfg["interval"]
        assert monitor.watchlist == runtime_cfg["watchlist"]
        assert len(monitor.alert_rules) == len(runtime_cfg["alert_rules"])
        assert monitor.trading_hours == runtime_cfg["trading_hours"]
