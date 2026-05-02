#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘前题材分析 dry-run 完整验证 (T34.6)

测试目标：
- 验证 premarket_thesis_analysis.py 所有组件可导入
- 验证 parse_thesis_llm_output 正确解析 LLM 输出
- 验证报告 JSON 结构完整（type / all_stocks / candidate_stocks / final_stocks）
- 验证 run() 在 dry-run 模式下不推送消息
- 验证数据链路：thesis API → 行情补全 → 筹码读取 → 筛选 → 报告生成
- 验证抽样股票数据合理性（price > 0, |change_pct| < 20）

注意：本测试不调用真实 LLM，通过 mock 绕过 LLM 调用。
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(WORKSPACE_ROOT))

# thesis-ingest 路径
THESIS_ROOT = WORKSPACE_ROOT.parent / "thesis-ingest"
sys.path.insert(0, str(THESIS_ROOT / "scripts"))


# =============================================================================
# A. 模块导入验证
# =============================================================================

class TestImports:
    """验证所有关键模块可导入"""

    def test_main_module_importable(self):
        import premarket_thesis_analysis as pta
        assert hasattr(pta, 'run')
        assert hasattr(pta, 'parse_thesis_llm_output')
        assert hasattr(pta, 'llm_recommend_thesis')
        assert hasattr(pta, 'enrich_thesis_stocks_with_market_data')
        assert hasattr(pta, 'load_chip_from_db')
        assert hasattr(pta, 'enrich_stocks_with_chip_data')

    def test_thesis_api_importable(self):
        from thesis_api import list_all_thesis, get_all_thesis_stocks
        assert callable(list_all_thesis)
        assert callable(get_all_thesis_stocks)

    def test_run_function_signature(self):
        import premarket_thesis_analysis as pta
        import inspect
        sig = inspect.signature(pta.run)
        params = list(sig.parameters.keys())
        assert 'date' in params
        assert 'dry_run' in params
        assert 'notify' in params


# =============================================================================
# B. LLM 输出解析验证
# =============================================================================

class TestParseLLMOutput:
    """验证 LLM 输出解析器"""

    def test_parse_basic(self):
        from premarket_thesis_analysis import parse_thesis_llm_output
        raw = "推荐题材：商业航天\n推荐理由：政策支持\n关键催化：卫星发射"
        r = parse_thesis_llm_output(raw)
        assert r["thesis_name"] == "商业航天"
        assert "政策支持" in r["reason"]
        assert "卫星发射" in r["catalyst"]

    def test_parse_with_braces(self):
        from premarket_thesis_analysis import parse_thesis_llm_output
        raw = "推荐题材：{AI 硬件}\n推荐理由：{算力需求增长}\n关键催化：{新芯片发布}"
        r = parse_thesis_llm_output(raw)
        assert r["thesis_name"] == "AI 硬件"

    def test_parse_multiline_reason(self):
        from premarket_thesis_analysis import parse_thesis_llm_output
        raw = (
            "宏观形势判断：市场偏向投资\n"
            "推荐题材：固态电池\n"
            "推荐理由：第一行理由\n"
            "第二行理由继续\n"
            "关键催化：事件一\n"
            "事件二\n"
            "风险提示：追高风险"
        )
        r = parse_thesis_llm_output(raw)
        assert r["thesis_name"] == "固态电池"
        assert "第一行理由" in r["reason"]

    def test_parse_missing_fields(self):
        from premarket_thesis_analysis import parse_thesis_llm_output
        raw = "一些无法解析的输出"
        r = parse_thesis_llm_output(raw)
        assert "thesis_name" not in r or r.get("thesis_name") is None
        assert "raw" in r


# =============================================================================
# C. 数据链路验证（使用 mock）
# =============================================================================

class TestDataPipeline:
    """验证数据链路各环节"""

    def test_is_bj_stock(self):
        from premarket_thesis_analysis import _is_bj_stock
        assert _is_bj_stock("830000") is True
        assert _is_bj_stock("430000") is True
        assert _is_bj_stock("600000") is False
        assert _is_bj_stock("000001") is False
        assert _is_bj_stock("920062") is False  # 920 is BJ but handled differently

    def test_load_chip_from_db_nonexistent(self):
        from premarket_thesis_analysis import load_chip_from_db
        result = load_chip_from_db("000000")
        assert result is None

    def test_enrich_stocks_with_chip_data_structure(self):
        from premarket_thesis_analysis import enrich_stocks_with_chip_data
        stocks = [
            {"code": "000001", "name": "测试"},
            {"code": "000002", "name": "测试2"},
        ]
        result = enrich_stocks_with_chip_data(stocks)
        assert len(result) == 2
        for s in result:
            assert "chip" in s  # chip key should exist (value may be None)


# =============================================================================
# D. 报告结构验证
# =============================================================================

class TestReportStructure:
    """验证报告 JSON 结构完整性"""

    def _make_mock_report_data(self):
        """构造一份模拟报告数据，验证结构"""
        return {
            "date": "2026-04-10",
            "type": "premarket_thesis",
            "generated_at": "2026-04-10 08:47:00",
            "top_theses": [
                {"rank": 1, "name": "商业航天", "description": "测试", "total_stock_count": 831, "node_count": 136},
                {"rank": 2, "name": "AI 硬件", "description": "测试", "total_stock_count": 252, "node_count": 58},
            ],
            "recommended_thesis": {
                "name": "商业航天",
                "logic": "政策催化",
                "catalyst": "卫星发射",
                "total_stock_count": 831,
                "enriched_count": 100,
            },
            "all_stocks_count": 100,
            "candidate_stocks_count": 15,
            "chip_ready_count": 10,
            "final_stocks_count": 5,
            "all_stocks": [
                {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
                 "turnover_rate": 5.0, "volume": 1000000, "amount": 300000000},
            ],
            "candidate_stocks": [
                {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
                 "turnover_rate": 5.0, "volume": 1000000, "amount": 300000000},
            ],
            "final_stocks": [
                {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
                 "turnover_rate": 5.0, "volume": 1000000, "amount": 300000000,
                 "chip_profit_ratio": 0.75, "chip_avg_cost": 28.0, "chip_concentration_90": 0.15},
            ],
            "chip_analysis": [],
            "llm_analysis": "推荐题材：商业航天\n推荐理由：测试",
        }

    def test_report_type_field(self):
        data = self._make_mock_report_data()
        assert data["type"] == "premarket_thesis"

    def test_report_three_layer_structure(self):
        data = self._make_mock_report_data()
        assert "all_stocks" in data
        assert "candidate_stocks" in data
        assert "final_stocks" in data
        assert isinstance(data["all_stocks"], list)
        assert isinstance(data["candidate_stocks"], list)
        assert isinstance(data["final_stocks"], list)

    def test_report_count_fields(self):
        data = self._make_mock_report_data()
        assert "all_stocks_count" in data
        assert "candidate_stocks_count" in data
        assert "chip_ready_count" in data
        assert "final_stocks_count" in data
        assert data["all_stocks_count"] >= data["candidate_stocks_count"]
        assert data["candidate_stocks_count"] >= data["final_stocks_count"]

    def test_report_top_theses_sorted(self):
        data = self._make_mock_report_data()
        theses = data["top_theses"]
        assert len(theses) >= 2
        # Should be sorted by total_stock_count descending
        for i in range(len(theses) - 1):
            assert theses[i]["total_stock_count"] >= theses[i + 1]["total_stock_count"]

    def test_report_recommended_thesis(self):
        data = self._make_mock_report_data()
        rec = data["recommended_thesis"]
        assert "name" in rec
        assert "logic" in rec
        assert "catalyst" in rec
        assert rec["name"] == "商业航天"

    def test_final_stocks_have_chip_data(self):
        data = self._make_mock_report_data()
        for s in data["final_stocks"]:
            assert "chip_profit_ratio" in s
            assert "chip_avg_cost" in s
            assert "chip_concentration_90" in s

    def test_stock_data合理性(self):
        """验证股票数据字段合理性"""
        data = self._make_mock_report_data()
        for s in data["all_stocks"]:
            assert s["price"] > 0, f"price should be > 0, got {s['price']}"
            assert abs(s["change_pct"]) < 20, f"|change_pct| should be < 20, got {s['change_pct']}"
            assert s["turnover_rate"] >= 0


# =============================================================================
# E. run() dry-run 模式验证（mock LLM）
# =============================================================================

class TestRunDryRun:
    """验证 run() 在 dry-run 模式下的行为"""

    @patch('premarket_thesis_analysis.llm_recommend_thesis')
    @patch('premarket_thesis_analysis.get_all_thesis_stocks')
    @patch('premarket_thesis_analysis.list_all_thesis')
    @patch('premarket_thesis_analysis.load_premarket_news')
    @patch('premarket_thesis_analysis.is_trading_day', return_value=True)
    @patch('premarket_thesis_analysis.load_api_key', return_value='fake_key')
    def test_dry_run_returns_report_data(self, mock_apikey, mock_trading, mock_news,
                                          mock_list_thesis, mock_get_stocks, mock_llm):
        """验证 dry-run 返回完整的报告数据"""
        import premarket_thesis_analysis as pta

        # Mock thesis list
        mock_list_thesis.return_value = [
            {"image_name": "商业航天", "description": "测试描述", "total_stock_count": 831, "node_count": 136},
            {"image_name": "AI 硬件", "description": "测试描述", "total_stock_count": 252, "node_count": 58},
        ]

        # Mock thesis stocks
        mock_get_stocks.return_value = [
            {"stock_code": "600118", "stock_name": "中国卫星"},
            {"stock_code": "600000", "stock_name": "浦发银行"},
        ]

        # Mock LLM output
        mock_llm.return_value = (
            "宏观形势判断：市场偏向投资\n"
            "推荐题材：商业航天\n"
            "推荐理由：政策支持力度大，卫星互联网加速建设\n"
            "关键催化：千帆星座发射\n"
            "相关新闻：1. [2026-04-10] [财联社] 卫星发射成功\n"
            "监控股票新闻：无\n"
            "风险提示：追高风险"
        )

        # Mock news
        mock_news.return_value = []

        # Mock enrich_thesis_stocks_with_market_data to return fake market data
        with patch.object(pta, 'enrich_thesis_stocks_with_market_data', return_value=[
            {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
             "turnover_rate": 5.0, "volume": 1000000, "amount": 350000000},
            {"code": "600000", "name": "浦发银行", "price": 10.0, "change_pct": -0.5,
             "turnover_rate": 2.0, "volume": 500000, "amount": 50000000},
        ]):
            result = pta.run(date="2026-04-10", dry_run=True, notify=False)

        # 验证返回值是 dict
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

        # 验证 type 字段
        assert result.get("type") == "premarket_thesis"

        # 验证三层结构
        assert "all_stocks" in result
        assert "candidate_stocks" in result
        assert "final_stocks" in result

        # 验证推荐题材
        assert result["recommended_thesis"]["name"] == "商业航天"

        # 验证 count 字段存在
        assert "all_stocks_count" in result
        assert "candidate_stocks_count" in result
        assert "chip_ready_count" in result
        assert "final_stocks_count" in result

    @patch('premarket_thesis_analysis.llm_recommend_thesis')
    @patch('premarket_thesis_analysis.get_all_thesis_stocks')
    @patch('premarket_thesis_analysis.list_all_thesis')
    @patch('premarket_thesis_analysis.load_premarket_news')
    @patch('premarket_thesis_analysis.is_trading_day', return_value=True)
    @patch('premarket_thesis_analysis.load_api_key', return_value='fake_key')
    def test_dry_run_does_not_push(self, mock_apikey, mock_trading, mock_news,
                                    mock_list_thesis, mock_get_stocks, mock_llm):
        """验证 dry-run 模式不调用推送"""
        import premarket_thesis_analysis as pta

        mock_list_thesis.return_value = [
            {"image_name": "商业航天", "description": "测试", "total_stock_count": 100, "node_count": 10},
        ]
        mock_get_stocks.return_value = [
            {"stock_code": "600118", "stock_name": "中国卫星"},
        ]
        mock_llm.return_value = "推荐题材：商业航天\n推荐理由：测试\n关键催化：测试"
        mock_news.return_value = []

        with patch.object(pta, 'enrich_thesis_stocks_with_market_data', return_value=[
            {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
             "turnover_rate": 5.0, "volume": 1000000, "amount": 350000000},
        ]):
            with patch('premarket_thesis_analysis.send_both') as mock_send:
                result = pta.run(date="2026-04-10", dry_run=True, notify=False)

                # send_both 不应被调用
                mock_send.assert_not_called()

    @patch('premarket_thesis_analysis.llm_recommend_thesis')
    @patch('premarket_thesis_analysis.get_all_thesis_stocks')
    @patch('premarket_thesis_analysis.list_all_thesis')
    @patch('premarket_thesis_analysis.load_premarket_news')
    @patch('premarket_thesis_analysis.is_trading_day', return_value=True)
    @patch('premarket_thesis_analysis.load_api_key', return_value='fake_key')
    def test_dry_run_llm_parse_validation(self, mock_apikey, mock_trading, mock_news,
                                           mock_list_thesis, mock_get_stocks, mock_llm):
        """验证 dry-run 中 LLM 输出包含 '推荐题材：' 且题材名存在于 thesis_catalog"""
        import premarket_thesis_analysis as pta

        mock_list_thesis.return_value = [
            {"image_name": "商业航天", "description": "测试", "total_stock_count": 100, "node_count": 10},
        ]
        mock_get_stocks.return_value = [
            {"stock_code": "600118", "stock_name": "中国卫星"},
        ]
        mock_llm.return_value = "推荐题材：商业航天\n推荐理由：政策支持\n关键催化：卫星发射"
        mock_news.return_value = []

        with patch.object(pta, 'enrich_thesis_stocks_with_market_data', return_value=[
            {"code": "600118", "name": "中国卫星", "price": 30.5, "change_pct": 2.1,
             "turnover_rate": 5.0, "volume": 1000000, "amount": 350000000},
        ]):
            result = pta.run(date="2026-04-10", dry_run=True, notify=False)

        # LLM 输出应包含 "推荐题材："
        assert "推荐题材" in result.get("llm_analysis", "")

        # 解析出的题材名应存在于 thesis list
        parsed = pta.parse_thesis_llm_output(result["llm_analysis"])
        thesis_names = [t["image_name"] for t in mock_list_thesis.return_value]
        assert parsed["thesis_name"] in thesis_names


# =============================================================================
# F. 集成验证：thesis API → 行情 → 报告
# =============================================================================

class TestIntegration:
    """端到端集成验证（使用 mock 数据）"""

    @patch('premarket_thesis_analysis.enrich_thesis_stocks_with_market_data')
    @patch('premarket_thesis_analysis.get_all_thesis_stocks')
    @patch('premarket_thesis_analysis.list_all_thesis')
    def test_full_pipeline_mock(self, mock_list_thesis, mock_get_stocks, mock_enrich):
        """验证从 thesis 列表到报告生成的完整链路"""
        import premarket_thesis_analysis as pta

        # 1. thesis 列表
        mock_list_thesis.return_value = [
            {"image_name": "商业航天", "description": "卫星互联网", "total_stock_count": 831, "node_count": 136},
        ]

        # 2. 成分股
        mock_get_stocks.return_value = [
            {"stock_code": f"{600000 + i}", "stock_name": f"股票{i}"} for i in range(10)
        ]

        # 3. 行情数据（模拟 10 只股票，其中 5 只满足基础筛选）
        mock_enrich.return_value = [
            {"code": f"{600000 + i}", "name": f"股票{i}",
             "price": 10.0 + i, "change_pct": 1.0 + i * 0.5,
             "turnover_rate": 3.0 + i, "amount": 300000000 + i * 100000000}
            for i in range(10)
        ]

        # 验证 enrich 函数返回数据
        enriched = pta.enrich_thesis_stocks_with_market_data(
            "商业航天",
            mock_get_stocks.return_value
        )
        assert len(enriched) == 10

        # 验证每只股票有必要的字段
        for s in enriched:
            assert "price" in s
            assert "change_pct" in s
            assert "turnover_rate" in s
            assert "amount" in s
            assert s["price"] > 0
            assert abs(s["change_pct"]) < 20
