# -*- coding: utf-8 -*-
"""
Monitor Indicator Service 独立测试

测试 monitor_indicator_service.py 中的核心函数及 monitor.py 中的 wrapper 接线
"""
from __future__ import annotations

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock


# =============================================================================
# A. 基础接口与异常
# =============================================================================

class TestModuleImport:
    """测试模块可导入性及基本异常类"""
    
    def test_module_importable(self):
        """模块可正常导入"""
        from services.monitor_indicator_service import (
            build_indicator_df,
            calc_macd_from_rows,
            calc_macd_from_db,
            calc_macd_with_history,
            collect_indicator_frames,
            MonitorIndicatorServiceError,
        )
        # 所有函数都可调用
        assert callable(build_indicator_df)
        assert callable(calc_macd_from_rows)
        assert callable(calc_macd_from_db)
        assert callable(calc_macd_with_history)
        assert callable(collect_indicator_frames)
    
    def test_error_class_exists(self):
        """MonitorIndicatorServiceError 异常类存在"""
        from services.monitor_indicator_service import MonitorIndicatorServiceError
        assert issubclass(MonitorIndicatorServiceError, Exception)
        
    def test_error_can_be_raised(self):
        """异常可被抛出和捕获"""
        from services.monitor_indicator_service import MonitorIndicatorServiceError
        with pytest.raises(MonitorIndicatorServiceError) as exc_info:
            raise MonitorIndicatorServiceError("test error")
        assert "test error" in str(exc_info.value)


# =============================================================================
# B. build_indicator_df 测试
# =============================================================================

class TestBuildIndicatorDf:
    """测试 build_indicator_df 函数"""
    
    def test_empty_rows_returns_empty_df(self):
        """空数据返回空 DataFrame"""
        from services.monitor_indicator_service import build_indicator_df
        df = build_indicator_df([])
        assert df.empty
        assert isinstance(df, pd.DataFrame)
    
    def test_normal_rows_converts_to_df(self):
        """正常 rows 转换为 DataFrame"""
        from services.monitor_indicator_service import build_indicator_df
        rows = [
            {"bar_time": "09:30", "open": "100.5", "close": "101.2"},
            {"bar_time": "09:35", "open": "101.2", "close": "100.8"},
        ]
        df = build_indicator_df(rows)
        assert not df.empty
        assert len(df) == 2
        assert list(df.columns) == ["bar_time", "open", "close"]
    
    def test_numeric_columns_converted(self):
        """数值列自动转换为 numeric 类型"""
        from services.monitor_indicator_service import build_indicator_df
        rows = [
            {"bar_time": "09:30", "open": "100.5", "high": "102.0", "low": "99.5", 
             "close": "101.2", "volume": "10000", "amount": "1012000"},
        ]
        df = build_indicator_df(rows)
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            assert col in df.columns
            assert pd.api.types.is_numeric_dtype(df[col])
    
    def test_invalid_numeric_becomes_nan(self):
        """无效数值转为 NaN（宽松行为）"""
        from services.monitor_indicator_service import build_indicator_df
        rows = [
            {"bar_time": "09:30", "open": "invalid", "close": "101.2"},
        ]
        df = build_indicator_df(rows)
        assert pd.isna(df["open"].iloc[0])
        assert df["close"].iloc[0] == 101.2
    
    def test_missing_fields_handled_gracefully(self):
        """缺失字段时宽松处理"""
        from services.monitor_indicator_service import build_indicator_df
        rows = [
            {"bar_time": "09:30", "open": "100.5"},  # 缺少 close 等其他字段
            {"bar_time": "09:35", "close": "101.2"},  # 缺少 open
        ]
        df = build_indicator_df(rows)
        assert not df.empty
        assert "open" in df.columns
        assert "close" in df.columns
        # 缺失值应为 NaN
        assert pd.isna(df["open"].iloc[1])
        assert pd.isna(df["close"].iloc[0])


# =============================================================================
# C. calc_macd_from_rows 测试
# =============================================================================

class TestCalcMacdFromRows:
    """测试 calc_macd_from_rows 函数"""
    
    def test_empty_rows_returns_empty_df(self):
        """空 rows 返回空 DataFrame"""
        from services.monitor_indicator_service import calc_macd_from_rows
        df = calc_macd_from_rows([])
        assert df.empty
        assert isinstance(df, pd.DataFrame)
    
    def test_minimal_rows_returns_df_with_macd_columns(self):
        """最小 rows 场景返回包含 MACD 列的 DataFrame"""
        from services.monitor_indicator_service import calc_macd_from_rows
        # 提供足够的历史数据以计算 MACD
        rows = []
        for i in range(50):
            rows.append({
                "calc_time": f"09:{30 + i // 5:02d}",
                "bar_time": f"09:{30 + i // 5:02d}",
                "open": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.0 + i * 0.1,
                "close": 100.5 + i * 0.1,
                "volume": 10000,
                "amount": 1005000,
                "date": "2026-04-07",
            })
        
        df = calc_macd_from_rows(rows)
        assert not df.empty
        # 验证 MACD 相关列存在
        assert "macd" in df.columns
        assert "macd_dea" in df.columns
        assert "macd_hist" in df.columns
    
    def test_returns_sorted_by_calc_time(self):
        """结果按 calc_time 排序"""
        from services.monitor_indicator_service import calc_macd_from_rows
        rows = []
        for i in reversed(range(50)):  # 倒序插入
            rows.append({
                "calc_time": f"09:{30 + i // 5:02d}",
                "bar_time": f"09:{30 + i // 5:02d}",
                "open": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.0 + i * 0.1,
                "close": 100.5 + i * 0.1,
                "volume": 10000,
                "amount": 1005000,
                "date": "2026-04-07",
            })
        
        df = calc_macd_from_rows(rows)
        if not df.empty and "calc_time" in df.columns:
            assert df["calc_time"].is_monotonic_increasing


# =============================================================================
# D. calc_macd_from_db / calc_macd_with_history 测试
# =============================================================================

class TestCalcMacdFromDb:
    """测试 calc_macd_from_db 函数（使用 monkeypatch）"""
    
    def test_query_kline_returns_empty(self, monkeypatch, tmp_path):
        """query_kline 返回空数据时返回空 DataFrame"""
        from services.monitor_indicator_service import calc_macd_from_db
        import database as db_module
        
        # Mock database.query_kline
        monkeypatch.setattr(db_module, "query_kline", lambda db_path, table: [])
        
        db_path = str(tmp_path / "test.db")
        df = calc_macd_from_db(db_path, table="kline_15min")
        assert df.empty
    
    def test_query_kline_returns_data(self, monkeypatch, tmp_path):
        """query_kline 返回数据时正常计算 MACD"""
        from services.monitor_indicator_service import calc_macd_from_db
        import database as db_module
        
        # Mock database.query_kline 返回足够的数据
        def fake_query_kline(db_path, table):
            rows = []
            for i in range(50):
                rows.append({
                    "bar_time": f"09:{30 + i // 5:02d}",
                    "open": 100.0 + i * 0.1,
                    "high": 101.0 + i * 0.1,
                    "low": 99.0 + i * 0.1,
                    "close": 100.5 + i * 0.1,
                    "volume": 10000,
                    "amount": 1005000,
                })
            return rows
        
        monkeypatch.setattr(db_module, "query_kline", fake_query_kline)
        
        # 创建假 db 文件路径
        db_dir = tmp_path / "data" / "HK" / "HK00700"
        db_dir.mkdir(parents=True)
        db_path = str(db_dir / "2026-04-07.db")
        
        df = calc_macd_from_db(db_path, table="kline_15min")
        assert not df.empty
        assert "macd" in df.columns


class TestCalcMacdWithHistory:
    """测试 calc_macd_with_history 函数（使用 monkeypatch）"""
    
    def test_empty_history_returns_empty_df(self, monkeypatch, tmp_path):
        """历史数据加载为空时返回空 DataFrame"""
        from services.monitor_indicator_service import calc_macd_with_history
        
        # Mock _load_multi_day_rows_for_macd
        def fake_load(*args, **kwargs):
            return []
        
        monkeypatch.setattr(
            "services.monitor_indicator_service._load_multi_day_rows_for_macd",
            fake_load
        )
        
        # Mock _extract_db_path_info
        def fake_extract(db_path):
            return {"market": "HK", "symbol": "00700", "date": "2026-04-07"}
        
        monkeypatch.setattr(
            "services.monitor_indicator_service._extract_db_path_info",
            fake_extract
        )
        
        db_dir = tmp_path / "data" / "HK" / "HK00700"
        db_dir.mkdir(parents=True)
        db_path = str(db_dir / "2026-04-07.db")
        
        df = calc_macd_with_history(db_path, table="kline_15min")
        assert df.empty
    
    def test_history_data_returns_macd_df(self, monkeypatch, tmp_path):
        """有历史数据时返回包含 MACD 的 DataFrame"""
        from services.monitor_indicator_service import calc_macd_with_history
        
        # Mock _load_multi_day_rows_for_macd 返回足够数据
        def fake_load(*args, **kwargs):
            rows = []
            for i in range(100):
                rows.append({
                    "calc_time": f"09:{30 + i // 5:02d}",
                    "bar_time": f"09:{30 + i // 5:02d}",
                    "open": 100.0 + i * 0.1,
                    "high": 101.0 + i * 0.1,
                    "low": 99.0 + i * 0.1,
                    "close": 100.5 + i * 0.1,
                    "volume": 10000,
                    "amount": 1005000,
                    "date": "2026-04-07",
                })
            return rows
        
        monkeypatch.setattr(
            "services.monitor_indicator_service._load_multi_day_rows_for_macd",
            fake_load
        )
        
        # Mock _extract_db_path_info
        def fake_extract(db_path):
            return {"market": "HK", "symbol": "00700", "date": "2026-04-07"}
        
        monkeypatch.setattr(
            "services.monitor_indicator_service._extract_db_path_info",
            fake_extract
        )
        
        db_dir = tmp_path / "data" / "HK" / "HK00700"
        db_dir.mkdir(parents=True)
        db_path = str(db_dir / "2026-04-07.db")
        
        df = calc_macd_with_history(db_path, table="kline_15min")
        assert not df.empty
        assert "macd" in df.columns


# =============================================================================
# E. collect_indicator_frames 测试
# =============================================================================

class TestCollectIndicatorFrames:
    """测试 collect_indicator_frames 函数"""
    
    def test_empty_db_returns_dict_with_empty_dfs(self, monkeypatch, tmp_path):
        """空/不存在 db 场景返回空 DataFrame 字典"""
        from services.monitor_indicator_service import collect_indicator_frames
        
        # Mock calc_macd_from_db 返回空 DataFrame
        def fake_calc_macd_from_db(db_path, table, engine=None):
            return pd.DataFrame()
        
        monkeypatch.setattr(
            "services.monitor_indicator_service.calc_macd_from_db",
            fake_calc_macd_from_db
        )
        
        db_path = str(tmp_path / "nonexistent.db")
        frames = collect_indicator_frames(
            db_path,
            base_period="15min",
            ref_periods=["5min", "30min"]
        )
        
        assert isinstance(frames, dict)
        assert "15min" in frames
        assert frames["15min"].empty
    
    def test_base_period_normal_scenario(self, monkeypatch, tmp_path):
        """base period 正常场景"""
        from services.monitor_indicator_service import collect_indicator_frames
        
        # Mock calc_macd_from_db 返回带 MACD 列的 DataFrame
        def fake_calc_macd_from_db(db_path, table, engine=None):
            df = pd.DataFrame({
                "bar_time": [f"09:{30 + i:02d}" for i in range(10)],
                "macd": [i * 0.1 for i in range(10)],
                "macd_dea": [i * 0.05 for i in range(10)],
                "macd_hist": [i * 0.02 for i in range(10)],
            })
            return df
        
        monkeypatch.setattr(
            "services.monitor_indicator_service.calc_macd_from_db",
            fake_calc_macd_from_db
        )
        
        db_path = str(tmp_path / "test.db")
        frames = collect_indicator_frames(
            db_path,
            base_period="15min",
            ref_periods=[]
        )
        
        assert isinstance(frames, dict)
        assert "15min" in frames
        assert not frames["15min"].empty
        assert "macd" in frames["15min"].columns
    
    def test_ref_periods_merged_scenario(self, monkeypatch, tmp_path):
        """ref periods 合并场景"""
        from services.monitor_indicator_service import collect_indicator_frames
        
        # Mock calc_macd_from_db 返回带 MACD 列的 DataFrame
        def fake_calc_macd_from_db(db_path, table, engine=None):
            df = pd.DataFrame({
                "bar_time": [f"09:{30 + i:02d}" for i in range(10)],
                "macd": [i * 0.1 for i in range(10)],
                "macd_dea": [i * 0.05 for i in range(10)],
                "macd_hist": [i * 0.02 for i in range(10)],
            })
            return df
        
        monkeypatch.setattr(
            "services.monitor_indicator_service.calc_macd_from_db",
            fake_calc_macd_from_db
        )
        
        db_path = str(tmp_path / "test.db")
        frames = collect_indicator_frames(
            db_path,
            base_period="15min",
            ref_periods=["5min", "30min"]
        )
        
        assert isinstance(frames, dict)
        # 应该包含所有周期
        assert "15min" in frames
        assert "5min" in frames
        assert "30min" in frames
        # base period 的 DataFrame 应包含合并后的引用周期列
        base_df = frames["15min"]
        # 验证有引用周期的列（如 5min_macd, 30min_macd 等）
        has_ref_cols = any(col.startswith("5min_") or col.startswith("30min_") 
                          for col in base_df.columns)
        assert has_ref_cols
    
    def test_returns_dict_of_dataframes(self, monkeypatch, tmp_path):
        """返回结构是 dict[str, DataFrame]"""
        from services.monitor_indicator_service import collect_indicator_frames
        
        def fake_calc_macd_from_db(db_path, table, engine=None):
            return pd.DataFrame({
                "bar_time": ["09:30"],
                "macd": [0.1],
            })
        
        monkeypatch.setattr(
            "services.monitor_indicator_service.calc_macd_from_db",
            fake_calc_macd_from_db
        )
        
        db_path = str(tmp_path / "test.db")
        frames = collect_indicator_frames(
            db_path,
            base_period="15min",
            ref_periods=["5min"]
        )
        
        assert isinstance(frames, dict)
        for period, df in frames.items():
            assert isinstance(period, str)
            assert isinstance(df, pd.DataFrame)


# =============================================================================
# F. 轻量 wrapper 接线验证
# =============================================================================

class TestMonitorWrapperIntegration:
    """测试 monitor.py 中 wrapper 函数正确调用 service"""
    
    def test_build_indicator_df_wrapper_calls_service(self, monkeypatch):
        """_build_indicator_df wrapper 调用 service 函数"""
        from monitor import Monitor
        import monitor as monitor_module
        
        # Mock service 函数
        called_with = []
        
        def fake_build_indicator_df(rows):
            called_with.append(rows)
            return pd.DataFrame()
        
        monkeypatch.setattr(
            "monitor.build_indicator_df",
            fake_build_indicator_df
        )
        
        # 创建 Monitor 实例（需要 mock config 加载）
        with patch.object(monitor_module, 'build_monitor_runtime_config') as mock_cfg:
            mock_cfg.return_value = {
                "workspace": Path("/tmp"),
                "config_path": "/tmp/config.yaml",
                "config": {},
                "watchlist": [],
                "interval": 30,
                "alert_rules": [],
                "trading_hours": {},
            }
            
            monitor = Monitor()
            test_rows = [{"bar_time": "09:30", "close": 100}]
            monitor._build_indicator_df(test_rows)
        
        assert len(called_with) == 1
        assert called_with[0] == test_rows
    
    def test_calc_macd_wrapper_calls_service(self, monkeypatch):
        """_calc_macd wrapper 调用 service 函数"""
        from monitor import Monitor
        import monitor as monitor_module
        
        called_with = []
        
        def fake_calc_macd_with_history(db_path, table, engine=None):
            called_with.append((db_path, table, engine))
            return pd.DataFrame()
        
        monkeypatch.setattr(
            "monitor.calc_macd_with_history",
            fake_calc_macd_with_history
        )
        
        with patch.object(monitor_module, 'build_monitor_runtime_config') as mock_cfg:
            mock_cfg.return_value = {
                "workspace": Path("/tmp"),
                "config_path": "/tmp/config.yaml",
                "config": {},
                "watchlist": [],
                "interval": 30,
                "alert_rules": [],
                "trading_hours": {},
            }
            
            monitor = Monitor()
            test_db = "/tmp/test.db"
            monitor._calc_macd(test_db, table="kline_15min")
        
        assert len(called_with) == 1
        assert called_with[0][0] == test_db
        assert called_with[0][1] == "kline_15min"
    
    def test_collect_indicator_frames_wrapper_calls_service(self, monkeypatch):
        """_collect_indicator_frames wrapper 调用 service 函数"""
        from monitor import Monitor
        import monitor as monitor_module
        
        called_with = []
        
        def fake_collect_indicator_frames(db_path, base_period, ref_periods, alert_rules, engine=None):
            called_with.append((db_path, base_period, ref_periods, alert_rules, engine))
            return {}
        
        monkeypatch.setattr(
            "monitor.collect_indicator_frames",
            fake_collect_indicator_frames
        )
        
        with patch.object(monitor_module, 'build_monitor_runtime_config') as mock_cfg:
            mock_cfg.return_value = {
                "workspace": Path("/tmp"),
                "config_path": "/tmp/config.yaml",
                "config": {},
                "watchlist": [],
                "interval": 30,
                "alert_rules": [],
                "trading_hours": {},
            }
            
            monitor = Monitor()
            test_db = "/tmp/test.db"
            monitor._collect_indicator_frames(test_db)
        
        assert len(called_with) == 1
        assert called_with[0][0] == test_db
        assert called_with[0][1] == "15min"
        assert called_with[0][3] == []  # alert_rules
