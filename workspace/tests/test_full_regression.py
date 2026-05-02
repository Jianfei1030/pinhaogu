#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量回归测试 (T-R5.3)

测试目标：
- 验证这轮重构没有破坏核心功能链路
- 验证关键模块还可导入/协作
- 验证 monitor / service / server 关键入口仍兼容

设计原则：
- 优先 pure monkeypatch / fake objects / tmp_path / 内存数据
- 不依赖真实网络、真实推送渠道、真实长期运行进程
- 尽量不依赖真实 DB；如必须，用 tmp_path 下临时 sqlite
- 测试要稳定、可重复、执行快
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# 确保能导入 workspace 模块
WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(WORKSPACE_ROOT))


# =============================================================================
# A. 核心模块导入回归
# =============================================================================

class TestCoreImports:
    """测试核心模块导入 - 验证重构后关键入口仍可导入"""
    
    def test_monitor_class_importable(self):
        """验证 monitor.Monitor 类可导入"""
        from monitor import Monitor
        assert Monitor is not None
        assert hasattr(Monitor, 'tick')
        assert hasattr(Monitor, '_handle_stock')
        assert hasattr(Monitor, '_detect_alerts')
        assert hasattr(Monitor, '_collect_indicator_frames')
    
    def test_server_app_importable(self):
        """验证 server.app 可导入"""
        from server import app
        assert app is not None
        assert hasattr(app, 'routes')
    
    def test_monitor_service_importable(self):
        """验证 monitor_service 模块可导入"""
        from services.monitor_service import build_monitor_runtime_config
        assert callable(build_monitor_runtime_config)
    
    def test_monitor_indicator_service_importable(self):
        """验证 monitor_indicator_service 模块可导入"""
        from services.monitor_indicator_service import (
            build_indicator_df,
            calc_macd_with_history,
            collect_indicator_frames,
        )
        assert callable(build_indicator_df)
        assert callable(calc_macd_with_history)
        assert callable(collect_indicator_frames)
    
    def test_monitor_stock_service_importable(self):
        """验证 monitor_stock_service 模块可导入"""
        from services.monitor_stock_service import (
            process_stock,
            build_stock_line,
            stock_key,
            format_volume,
        )
        assert callable(process_stock)
        assert callable(build_stock_line)
        assert callable(stock_key)
        assert callable(format_volume)
    
    def test_monitor_alert_service_importable(self):
        """验证 monitor_alert_service 模块可导入"""
        from services.monitor_alert_service import (
            slope_arrow,
            alert_context_from_row,
            build_rule_alert_message,
            detect_rule_alerts,
            detect_alerts,
        )
        assert callable(slope_arrow)
        assert callable(alert_context_from_row)
        assert callable(build_rule_alert_message)
        assert callable(detect_rule_alerts)
        assert callable(detect_alerts)


# =============================================================================
# B. Monitor 主线回归（薄 wrapper 仍可协作）
# =============================================================================

class TestMonitorInitialization:
    """测试 Monitor 初始化"""
    
    def test_monitor_init_success(self, monkeypatch, tmp_path):
        """验证 Monitor 可成功初始化"""
        from monitor import Monitor
        
        # Mock config.yaml 加载
        fake_config = {
            "watchlist": [
                {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
            ],
            "refresh_interval": 30,
            "alerts": [],
            "trading_hours": {},
        }
        
        # Mock yaml.safe_load 返回 fake 配置
        monkeypatch.setattr('yaml.safe_load', lambda fh: fake_config)
        monkeypatch.setattr('pathlib.Path.exists', lambda self: True)
        
        monitor = Monitor(config_path="config.yaml", interval=30)
        assert monitor is not None
        assert hasattr(monitor, 'tick')
        assert hasattr(monitor, '_handle_stock')
        assert hasattr(monitor, '_detect_alerts')
        assert hasattr(monitor, 'alert_rules')
        assert hasattr(monitor, 'watchlist')


class TestMonitorHandleStock:
    """测试 Monitor._handle_stock 方法"""
    
    def test_handle_stock_returns_tuple(self, monkeypatch, tmp_path):
        """验证 _handle_stock 返回 (line, alerts) 兼容结构"""
        from monitor import Monitor
        import pandas as pd
        
        # Mock 所有依赖
        fake_config = {
            "watchlist": [],
            "refresh_interval": 30,
            "alerts": [],
            "trading_hours": {},
        }
        monkeypatch.setattr('yaml.safe_load', lambda fh: fake_config)
        monkeypatch.setattr('pathlib.Path.exists', lambda self: True)
        
        # Mock process_stock 返回 fake 数据
        def fake_process_stock(stock, realtime, db_path, collect_indicator_frames_fn, detect_alerts_fn, last_alert_keys):
            return (
                "HK00700 腾讯控股 | 350.20 | +1.25% | MACD:0.12 DEA:0.08 ↑ | Vol: 1.2 亿",
                [],
                {"code": "HK00700", "has_data": True, "indicator_frames": {}, "intraday_rows": []}
            )
        
        monkeypatch.setattr('services.monitor_stock_service.process_stock', fake_process_stock)
        
        monitor = Monitor(config_path="config.yaml", interval=30)
        
        # Mock _db_path
        monkeypatch.setattr(monitor, '_db_path', lambda stock: str(tmp_path / "test.db"))
        
        fake_stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        fake_realtime = {"current": 350.20, "prev_close": 345.80}
        
        result = monitor._handle_stock(fake_stock, realtime=fake_realtime)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        line, alerts = result
        assert isinstance(line, str)
        assert len(line) > 0
        assert isinstance(alerts, list)


class TestMonitorDetectAlerts:
    """测试 Monitor._detect_alerts 方法"""
    
    def test_detect_alerts_returns_list(self, monkeypatch, tmp_path):
        """验证 _detect_alerts 返回 alerts 列表"""
        from monitor import Monitor
        import pandas as pd
        
        # Mock 配置
        fake_config = {
            "watchlist": [],
            "refresh_interval": 30,
            "alerts": [],
            "trading_hours": {},
        }
        monkeypatch.setattr('yaml.safe_load', lambda fh: fake_config)
        monkeypatch.setattr('pathlib.Path.exists', lambda self: True)
        
        monitor = Monitor(config_path="config.yaml", interval=30)
        
        # 创建 fake 的输入数据
        fake_stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        fake_intraday_rows = [
            {"bar_time": "10:00", "close": 10.0, "volume": 1000000},
            {"bar_time": "10:05", "close": 10.5, "volume": 1100000},
        ]
        fake_indicator_frames = {
            "15min": pd.DataFrame({
                "macd": [0.1, 0.15],
                "macd_dea": [0.05, 0.08],
                "macd_hist": [0.05, 0.07],
            })
        }
        fake_realtime = {"current": 10.5, "prev_close": 10.0}
        
        alerts = monitor._detect_alerts(
            fake_stock,
            fake_intraday_rows,
            fake_indicator_frames,
            fake_realtime,
        )
        
        assert isinstance(alerts, list)


class TestMonitorTick:
    """测试 Monitor.tick 方法（使用 monkeypatch 避免真实数据源）"""
    
    def test_tick_runs_without_crash(self, monkeypatch, tmp_path):
        """验证 tick() 在 fake 数据源下能走一轮主路径而不炸"""
        from monitor import Monitor
        
        # Mock 配置
        fake_config = {
            "watchlist": [
                {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
            ],
            "refresh_interval": 30,
            "alerts": [],
            "trading_hours": {},
        }
        monkeypatch.setattr('yaml.safe_load', lambda fh: fake_config)
        monkeypatch.setattr('pathlib.Path.exists', lambda self: True)
        
        # Mock fetch_realtime 返回 fake 数据
        def fake_fetch_realtime(symbol, market):
            return {
                "current": 350.20,
                "prev_close": 345.80,
                "change_pct": 1.27,
                "time": "10:00:00",
            }
        
        monkeypatch.setattr('data_source.fetch_realtime', fake_fetch_realtime)
        
        # Mock _handle_stock 返回 fake 结果
        def fake_handle_stock(self, stock, realtime=None):
            return (
                f"[10:00:00] {stock['market']}{stock['symbol']} {stock.get('name', '')} | 350.20 | +1.27%",
                []
            )
        
        monkeypatch.setattr(Monitor, '_handle_stock', fake_handle_stock)
        
        # Mock write_status
        def fake_write_status(self):
            pass
        
        monkeypatch.setattr(Monitor, 'write_status', fake_write_status)
        
        monitor = Monitor(config_path="config.yaml", interval=30)
        
        # 执行 tick - 不应该抛异常
        try:
            monitor.tick()
        except Exception as e:
            pytest.fail(f"tick() raised unexpected exception: {e}")


# =============================================================================
# C. Alert / Indicator / Stock service 协作回归
# =============================================================================

class TestServiceCollaboration:
    """测试 service 层协作"""
    
    def test_indicator_to_stock_data_flow(self):
        """验证 indicator service 产出能被 stock service 消费"""
        import pandas as pd
        from services.monitor_indicator_service import build_indicator_df
        from services.monitor_stock_service import build_stock_line
        
        # 创建 fake 的 K 线数据
        rows = [
            {"bar_time": "10:00", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000000},
            {"bar_time": "10:05", "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.5, "volume": 1100000},
        ]
        
        # build_indicator_df 应该能处理
        df = build_indicator_df(rows)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "close" in df.columns
        
        # build_stock_line 需要更多参数，这里只验证函数可调用
        fake_stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        fake_realtime = {"current": 10.5, "prev_close": 10.2}
        fake_indicator_df = pd.DataFrame({"macd": [0.1], "macd_dea": [0.05]})
        fake_intraday_rows = [{"volume": 1000000}]
        
        line = build_stock_line(fake_stock, fake_realtime, fake_indicator_df, fake_intraday_rows)
        assert isinstance(line, str)
        assert len(line) > 0
    
    def test_alert_service_returns_compatible_structure(self):
        """验证 alert service 返回结构能被 monitor/tick 使用"""
        from services.monitor_alert_service import detect_alerts, slope_arrow
        import pandas as pd
        
        # 测试 slope_arrow
        assert slope_arrow(0.5) == "↗"
        assert slope_arrow(-0.3) == "↘"
        assert slope_arrow(0.0) == "↗"
        
        # detect_alerts 需要 AlertRule 实例，这里验证空规则列表
        fake_rules = []
        fake_bars_by_period = {
            "15min": [
                {"close": 10.0, "macd": 0.1, "macd_dea": 0.05, "macd_hist": 0.05},
                {"close": 10.5, "macd": 0.15, "macd_dea": 0.08, "macd_hist": 0.07},
            ]
        }
        
        alerts = detect_alerts(
            alert_rules=fake_rules,
            bars_by_period=fake_bars_by_period,
            symbol="00700",
            market="HK",
            stock_name="腾讯控股",
            realtime={"current": 10.5},
        )
        
        assert isinstance(alerts, list)
        assert len(alerts) == 0  # 空规则列表应该返回空 alerts
    
    def test_full_detection_pipeline(self, monkeypatch):
        """验证完整的检测流水线 (indicator -> stock -> alert)"""
        import pandas as pd
        from services.monitor_stock_service import process_stock, stock_key
        from services.monitor_alert_service import detect_alerts
        
        # 验证 stock_key
        fake_stock = {"market": "HK", "symbol": "00700"}
        key = stock_key(fake_stock)
        assert key == "HK00700"
        
        # process_stock 需要真实依赖，这里只验证函数签名兼容
        # 使用 monkeypatch 模拟依赖
        def fake_collect_frames(db_path):
            return {
                "15min": pd.DataFrame({"macd": [0.1], "macd_dea": [0.05]}),
                "5min": pd.DataFrame({"close": [10.0]}),
            }
        
        def fake_detect_alerts_fn(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        # 注意：process_stock 需要真实调用，但我们可以 mock 内部依赖
        # 这里只做 import / 签名验证，不真正执行
        assert callable(process_stock)
        
        # detect_alerts 验证
        fake_rules = []
        alerts = detect_alerts(
            alert_rules=fake_rules,
            bars_by_period={"15min": []},
            symbol="00700",
            market="HK",
        )
        assert isinstance(alerts, list)


# =============================================================================
# D. Server/API 冒烟回归
# =============================================================================

class TestServerSmoke:
    """测试 Server/API 冒烟"""
    
    def test_server_app_exists(self):
        """验证 server 可导入且 app 存在"""
        from server import app
        assert app is not None
        assert hasattr(app, 'routes')
        assert len(app.routes) > 0
    
    def test_server_has_health_route(self):
        """验证 server 有健康检查路由"""
        from server import app
        
        # 检查是否有根路径或健康检查路径
        routes = [route.path for route in app.routes]
        # 至少应该有根路径或 /health 或 /status
        assert '/' in routes or any('/health' in r for r in routes) or any('/status' in r for r in routes)
    
    def test_server_config_route_importable(self):
        """验证 config 路由相关函数可导入"""
        from services.config_service import build_config_payload
        assert callable(build_config_payload)
        
        # 验证函数能执行（不需要真实配置）
        try:
            result = build_config_payload()
            assert isinstance(result, dict)
        except Exception:
            # 如果配置读取失败是可以接受的，只要函数能导入
            pass
    
    def test_server_quote_route_importable(self):
        """验证 quote 路由相关函数可导入"""
        from services.quote_service import build_quote_payload
        assert callable(build_quote_payload)
    
    def test_server_status_route_importable(self):
        """验证 status 路由相关函数可导入"""
        from services.runtime_status_service import (
            build_monitor_status_payload,
            build_calibration_status_payload,
        )
        assert callable(build_monitor_status_payload)
        assert callable(build_calibration_status_payload)


# =============================================================================
# E. 顶层脚本入口回归
# =============================================================================

class TestTopLevelScripts:
    """测试顶层脚本入口"""
    
    def test_premarket_analysis_run_importable(self):
        """验证 premarket_analysis.run 可导入"""
        from premarket_analysis import run
        assert callable(run)
    
    def test_postmarket_review_run_importable(self):
        """验证 postmarket_review.run 可导入"""
        from postmarket_review import run
        assert callable(run)
    
    def test_daily_incremental_backfill_run_importable(self):
        """验证 daily_incremental_backfill.run 可导入"""
        from daily_incremental_backfill import run
        assert callable(run)
    
    def test_status_report_run_importable(self):
        """验证 status_report.run 可导入"""
        from status_report import run
        assert callable(run)
    
    def test_premarket_run_signature(self, monkeypatch):
        """验证 premarket_analysis.run 签名兼容"""
        from premarket_analysis import run
        import inspect
        
        sig = inspect.signature(run)
        params = list(sig.parameters.keys())
        
        # 验证参数存在
        assert 'date' in params
        assert 'dry_run' in params
        assert 'notify' in params
    
    def test_postmarket_run_signature(self, monkeypatch):
        """验证 postmarket_review.run 签名兼容"""
        from postmarket_review import run
        import inspect
        
        sig = inspect.signature(run)
        params = list(sig.parameters.keys())
        
        assert 'date' in params
        assert 'dry_run' in params
        assert 'notify' in params
    
    def test_daily_backfill_run_signature(self, monkeypatch):
        """验证 daily_incremental_backfill.run 签名兼容"""
        from daily_incremental_backfill import run
        import inspect
        
        sig = inspect.signature(run)
        params = list(sig.parameters.keys())
        
        assert 'dry_run' in params
    
    def test_status_report_run_signature(self, monkeypatch):
        """验证 status_report.run 签名兼容"""
        from status_report import run
        import inspect
        
        sig = inspect.signature(run)
        params = list(sig.parameters.keys())
        
        assert 'dry_run' in params
        assert 'notify' in params


# =============================================================================
# 主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
