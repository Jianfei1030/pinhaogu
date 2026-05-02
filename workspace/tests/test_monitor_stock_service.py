# -*- coding: utf-8 -*-
"""
Monitor Stock Service 独立单元测试

纯 fake stock / fake realtime / fake callback / 纯内存测试。
不启动主循环，不依赖真实行情/真实推送/真实 DB。
测试稳定、快速。

覆盖范围：
- A. 基础接口与异常
- B. helper 函数 (stock_key, format_volume, build_stock_line)
- C. process_stock 主流程
- D. _handle_stock wrapper 接线验证 (通过 process_stock 语义验证)
"""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.monitor_stock_service import (
    MonitorStockServiceError,
    stock_key,
    format_volume,
    build_stock_line,
    process_stock,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

class TestModuleImport:
    """模块导入测试"""

    def test_module_importable(self):
        """模块可正常导入"""
        from services import monitor_stock_service
        assert monitor_stock_service is not None

    def test_exception_class_exists(self):
        """MonitorStockServiceError 异常类存在"""
        assert MonitorStockServiceError is not None
        assert issubclass(MonitorStockServiceError, Exception)

    def test_functions_exist(self):
        """核心函数都存在"""
        assert callable(stock_key)
        assert callable(format_volume)
        assert callable(build_stock_line)
        assert callable(process_stock)


# =============================================================================
# B. Helper 函数测试
# =============================================================================

class TestStockKey:
    """stock_key 函数测试"""

    def test_hk_stock(self):
        """港股：HK + symbol 拼接"""
        stock = {"market": "HK", "symbol": "00700"}
        assert stock_key(stock) == "HK00700"

    def test_a_stock(self):
        """A 股：A + symbol 拼接"""
        stock = {"market": "A", "symbol": "600519"}
        assert stock_key(stock) == "A600519"

    def test_market_uppercase(self):
        """market 自动转大写"""
        stock = {"market": "hk", "symbol": "00700"}
        assert stock_key(stock) == "HK00700"

    def test_missing_market(self):
        """缺失 market 时为空字符串"""
        stock = {"symbol": "00700"}
        assert stock_key(stock) == "00700"

    def test_missing_symbol(self):
        """缺失 symbol 时为空字符串"""
        stock = {"market": "HK"}
        assert stock_key(stock) == "HK"

    def test_with_extra_fields(self):
        """包含额外字段不影响"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股", "extra": "data"}
        assert stock_key(stock) == "HK00700"


class TestFormatVolume:
    """format_volume 函数测试"""

    def test_small_volume(self):
        """小成交量：直接显示"""
        assert format_volume(1000) == "1000"
        assert format_volume(500) == "500"

    def test_volume_in_wan(self):
        """成交量过万：显示为 X.X 万"""
        assert format_volume(10000) == "1.0万"
        assert format_volume(3456000) == "345.6万"
        assert format_volume(100000) == "10.0万"

    def test_volume_in_yi(self):
        """成交量过亿：显示为 X.XX 亿"""
        assert format_volume(100000000) == "1.00亿"
        assert format_volume(120000000) == "1.20亿"
        assert format_volume(1234567890) == "12.35亿"

    def test_zero_volume(self):
        """零成交量"""
        assert format_volume(0) == "0"

    def test_none_volume(self):
        """None 成交量"""
        assert format_volume(None) == "0"

    def test_float_input(self):
        """浮点数输入"""
        assert format_volume(12345.67) == "1.2万"


class TestBuildStockLine:
    """build_stock_line 函数测试"""

    def test_normal_case(self):
        """正常场景：有 realtime + indicator_df"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        
        # 创建 fake indicator DataFrame
        indicator_df = pd.DataFrame({
            "macd": [0.1, 0.12],
            "macd_dea": [0.05, 0.06],
        })
        
        intraday_rows = [{"volume": 120000000}]
        
        line = build_stock_line(stock, realtime, indicator_df, intraday_rows)
        
        assert "HK00700" in line
        assert "腾讯控股" in line
        assert "350.20" in line
        assert "+" in line  # 涨跌幅
        assert "%" in line
        assert "MACD:" in line
        assert "DEA:" in line
        assert "↑" in line or "↓" in line  # DEA 箭头
        assert "Vol:" in line
        assert "1.20亿" in line

    def test_empty_indicator_df(self):
        """无指标数据场景"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        indicator_df = pd.DataFrame()  # 空 DataFrame
        intraday_rows = [{"volume": 1000000}]
        
        line = build_stock_line(stock, realtime, indicator_df, intraday_rows)
        
        assert "HK00700" in line
        assert "MACD:--" in line
        assert "DEA:--" in line

    def test_no_intraday_rows(self):
        """无 intraday 数据场景"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        indicator_df = pd.DataFrame({"macd": [0.1], "macd_dea": [0.05]})
        intraday_rows = []
        
        line = build_stock_line(stock, realtime, indicator_df, intraday_rows)
        
        assert "HK00700" in line
        assert "Vol:" in line

    def test_dea_arrow_direction(self):
        """DEA 箭头方向：上升↑ / 下降↓"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        
        # DEA 上升
        indicator_df_up = pd.DataFrame({"macd": [0.1, 0.12], "macd_dea": [0.05, 0.06]})
        intraday_rows = [{"volume": 10000}]
        line_up = build_stock_line(stock, realtime, indicator_df_up, intraday_rows)
        assert "↑" in line_up
        
        # DEA 下降
        indicator_df_down = pd.DataFrame({"macd": [0.12, 0.1], "macd_dea": [0.06, 0.05]})
        line_down = build_stock_line(stock, realtime, indicator_df_down, intraday_rows)
        assert "↓" in line_down

    def test_missing_prev_close(self):
        """缺失 prev_close 时使用 change_pct"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "change_pct": 1.5}
        indicator_df = pd.DataFrame()
        intraday_rows = []
        
        line = build_stock_line(stock, realtime, indicator_df, intraday_rows)
        
        assert "HK00700" in line
        assert "350.20" in line


# =============================================================================
# C. process_stock 主流程测试
# =============================================================================

class TestProcessStock:
    """process_stock 函数测试"""

    def test_normal_case(self, tmp_path):
        """正常场景：返回 (line, alerts, meta)"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        db_path = str(tmp_path / "test.db")
        
        # Fake collect_indicator_frames_fn
        def fake_collect(db_path):
            return {
                "5min": pd.DataFrame([{"bar_time": "10:00", "volume": 10000}]),
                "15min": pd.DataFrame({"macd": [0.1, 0.12], "macd_dea": [0.05, 0.06]}),
            }
        
        # Fake detect_alerts_fn
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return [{"type": "test", "key": "test:1", "message": "测试告警"}]
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # 验证 line
        assert isinstance(line, str)
        assert "HK00700" in line
        
        # 验证 alerts
        assert isinstance(alerts, list)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "test"
        assert alerts[0]["key"] == "test:1"
        
        # 验证 meta
        assert isinstance(meta, dict)
        assert meta["code"] == "HK00700"
        assert meta["has_data"] is True
        assert "indicator_frames" in meta
        assert "intraday_rows" in meta
        assert len(meta["intraday_rows"]) == 1

    def test_no_data_scenario(self, tmp_path):
        """无数据场景：返回空 line 和空 alerts"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        db_path = str(tmp_path / "test.db")
        
        # Fake collect_indicator_frames_fn 返回空数据
        def fake_collect(db_path):
            return {"5min": pd.DataFrame(), "15min": pd.DataFrame()}
        
        # Fake detect_alerts_fn（不会被调用，但还是要提供）
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # 验证 line 包含无数据标识
        assert isinstance(line, str)
        assert "无数据" in line
        
        # 验证 alerts 为空
        assert alerts == []
        
        # 验证 meta
        assert meta["code"] == "HK00700"
        assert meta["has_data"] is False

    def test_collect_indicator_frames_called(self, tmp_path):
        """验证 collect_indicator_frames_fn 被调用"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        collect_called = False
        collect_db_path = None
        
        def fake_collect(db_path):
            nonlocal collect_called, collect_db_path
            collect_called = True
            collect_db_path = db_path
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert collect_called is True
        assert collect_db_path == db_path

    def test_detect_alerts_fn_called(self, tmp_path):
        """验证 detect_alerts_fn 被调用"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        detect_called = False
        detect_args = None
        
        def fake_collect(db_path):
            return {
                "5min": pd.DataFrame([{"volume": 10000, "bar_time": "10:00"}]),
                "15min": pd.DataFrame(),
            }
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            nonlocal detect_called, detect_args
            detect_called = True
            detect_args = (stock, intraday_rows, indicator_frames, realtime)
            return []
        
        process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert detect_called is True
        assert detect_args is not None
        assert detect_args[0]["symbol"] == "00700"

    def test_alerts_structure(self, tmp_path):
        """alerts 列表结构兼容"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return [
                {"type": "change_pct", "key": "HK00700:change:1", "message": "涨 5%"},
                {"type": "macd_cross", "key": "HK00700:macd:1", "message": "金叉"},
            ]
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert len(alerts) == 2
        for alert in alerts:
            assert "type" in alert
            assert "key" in alert
            assert "message" in alert

    def test_meta_has_required_fields(self, tmp_path):
        """meta 包含 wrapper 使用到的语义字段"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # wrapper 使用到的字段
        assert "has_data" in meta
        assert "code" in meta
        
        # service 返回的字段
        assert "indicator_frames" in meta
        assert "intraday_rows" in meta

    def test_missing_stock_symbol_raises_error(self, tmp_path):
        """缺失股票代码抛出异常"""
        stock = {"market": "HK"}  # 缺失 symbol
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        with pytest.raises(MonitorStockServiceError) as exc_info:
            process_stock(
                stock=stock,
                realtime=realtime,
                db_path=db_path,
                collect_indicator_frames_fn=fake_collect,
                detect_alerts_fn=fake_detect,
            )
        
        assert "股票代码缺失" in str(exc_info.value)

    def test_collect_indicator_frames_error(self, tmp_path):
        """collect_indicator_frames 抛出异常时抛出 MonitorStockServiceError"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            raise RuntimeError("数据库读取失败")
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        with pytest.raises(MonitorStockServiceError) as exc_info:
            process_stock(
                stock=stock,
                realtime=realtime,
                db_path=db_path,
                collect_indicator_frames_fn=fake_collect,
                detect_alerts_fn=fake_detect,
            )
        
        assert "收集指标帧失败" in str(exc_info.value)

    def test_detect_alerts_error(self, tmp_path):
        """detect_alerts 抛出异常时抛出 MonitorStockServiceError"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            raise RuntimeError("告警检测失败")
        
        with pytest.raises(MonitorStockServiceError) as exc_info:
            process_stock(
                stock=stock,
                realtime=realtime,
                db_path=db_path,
                collect_indicator_frames_fn=fake_collect,
                detect_alerts_fn=fake_detect,
            )
        
        assert "告警检测失败" in str(exc_info.value)


# =============================================================================
# D. _handle_stock wrapper 接线验证 (通过 process_stock 语义验证)
# =============================================================================

class TestHandleStockWrapper:
    """
    _handle_stock wrapper 接线验证。
    
    注意：不直接实例化 Monitor（有较多外部依赖），
    而是验证 process_stock 返回的 meta 语义，确保 wrapper 可以正确接线。
    
    Monitor._handle_stock 的接线逻辑：
    1. 调用 process_stock(stock, realtime, db_path, ...)
    2. 如果 meta["has_data"] and realtime: 更新 last_prices
    3. 返回 (line, alerts) 保持与原调用方兼容
    """

    def test_process_stock_returns_compatible_structure(self, tmp_path):
        """process_stock 返回 (line, alerts, meta) 与 wrapper 兼容"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return [{"type": "test", "key": "test:1", "message": "测试"}]
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # 验证 line 是字符串
        assert isinstance(line, str)
        
        # 验证 alerts 是列表，结构兼容
        assert isinstance(alerts, list)
        assert len(alerts) == 1
        assert "type" in alerts[0]
        assert "key" in alerts[0]
        assert "message" in alerts[0]
        
        # 验证 meta 包含 wrapper 需要的字段
        assert isinstance(meta, dict)
        assert "has_data" in meta
        assert "code" in meta

    def test_meta_has_data_true_when_data_exists(self, tmp_path):
        """meta["has_data"] = True: wrapper 会更新 last_prices"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20, "prev_close": 345.80}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # wrapper 逻辑：if meta.get("has_data") and realtime: update last_prices
        assert meta["has_data"] is True

    def test_meta_has_data_false_when_no_data(self, tmp_path):
        """meta["has_data"] = False: wrapper 不会更新 last_prices"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame(), "15min": pd.DataFrame()}  # 空数据
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        # wrapper 逻辑：has_data=False 时不更新 last_prices
        assert meta["has_data"] is False
        assert "无数据" in line

    def test_wrapper_compatible_with_empty_realtime(self, tmp_path):
        """realtime 缺失/空时 wrapper 可以安全处理"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {}  # 空 realtime
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        # 不应该抛出异常
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert isinstance(line, str)
        assert isinstance(alerts, list)
        assert isinstance(meta, dict)

    def test_process_stock_signature_compatible(self, tmp_path):
        """process_stock 函数签名与 wrapper 调用兼容"""
        # 验证 process_stock 可以接收 wrapper 传递的所有参数
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        last_keys = {"HK00700:alert:1"}
        
        # 验证可以传递 last_alert_keys 参数
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
            last_alert_keys=last_keys,
        )
        
        assert isinstance(line, str)
        assert isinstance(alerts, list)
        assert isinstance(meta, dict)


# =============================================================================
# E. 边缘场景测试
# =============================================================================

class TestEdgeCases:
    """边缘场景测试"""

    def test_realtime_missing_fields(self, tmp_path):
        """realtime 缺失字段时行为宽松"""
        stock = {"market": "HK", "symbol": "00700", "name": "腾讯控股"}
        realtime = {}  # 空 realtime
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        # 不应该抛出异常
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert isinstance(line, str)
        assert isinstance(alerts, list)
        assert isinstance(meta, dict)

    def test_stock_missing_name(self, tmp_path):
        """stock 缺失 name 字段"""
        stock = {"market": "HK", "symbol": "00700"}  # 无 name
        realtime = {"current": 350.20}
        db_path = str(tmp_path / "test.db")
        
        def fake_collect(db_path):
            return {"5min": pd.DataFrame([{"volume": 10000}]), "15min": pd.DataFrame()}
        
        def fake_detect(stock, intraday_rows, indicator_frames, realtime):
            return []
        
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime,
            db_path=db_path,
            collect_indicator_frames_fn=fake_collect,
            detect_alerts_fn=fake_detect,
        )
        
        assert "HK00700" in line
        assert meta["code"] == "HK00700"
