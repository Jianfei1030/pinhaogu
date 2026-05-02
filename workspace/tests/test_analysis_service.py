# -*- coding: utf-8 -*-
"""
Analysis Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实子进程，不依赖真实分析报告文件。
使用 monkeypatch + tmp_path + fake popen。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services.analysis_service import (
    AnalysisServiceError,
    AnalysisConflictError,
    AnalysisNotFoundError,
    AnalysisPayloadError,
    read_analysis_status,
    analysis_is_running,
    resolve_analysis_report_path,
    normalize_date,
    parse_notify_flag,
    start_daily_analysis,
    get_daily_analysis_status,
    get_daily_analysis_report_text,
    check_analysis_conflict,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert AnalysisServiceError is not None
    assert AnalysisConflictError is not None
    assert AnalysisNotFoundError is not None
    assert AnalysisPayloadError is not None


def test_exception_hierarchy():
    """所有异常都继承自 AnalysisServiceError"""
    assert issubclass(AnalysisConflictError, AnalysisServiceError)
    assert issubclass(AnalysisNotFoundError, AnalysisServiceError)
    assert issubclass(AnalysisPayloadError, AnalysisServiceError)


# =============================================================================
# B. Helper 函数测试
# =============================================================================

class TestNormalizeDate:
    """normalize_date 测试"""

    def test_normalize_none(self):
        """None 返回今天"""
        result = normalize_date(None)
        expected = datetime.now().strftime("%Y-%m-%d")
        assert result == expected

    def test_normalize_valid_string(self):
        """有效字符串返回标准化格式"""
        assert normalize_date("2026-04-07") == "2026-04-07"
        assert normalize_date("2026-4-7") == "2026-04-07"


class TestParseNotifyFlag:
    """parse_notify_flag 测试"""

    def test_parse_true(self):
        assert parse_notify_flag(True) is True
        assert parse_notify_flag("true") is True
        assert parse_notify_flag("yes") is True
        assert parse_notify_flag("1") is True

    def test_parse_false(self):
        assert parse_notify_flag(False) is False
        assert parse_notify_flag("false") is False
        assert parse_notify_flag("no") is False
        assert parse_notify_flag("off") is False
        assert parse_notify_flag("0") is False
        assert parse_notify_flag("") is False

    def test_parse_other_string(self):
        """其他字符串视为 True"""
        assert parse_notify_flag("random") is True
        assert parse_notify_flag("TRUE") is True


class TestReadAnalysisStatus:
    """read_analysis_status 测试"""

    def test_file_not_exists(self, tmp_path):
        """文件不存在返回 None"""
        status_path = tmp_path / "status.json"
        assert read_analysis_status(status_path) is None

    def test_file_exists_valid_json(self, tmp_path):
        """文件存在且有效 JSON 返回 dict"""
        status_path = tmp_path / "status.json"
        expected_data = {"status": "running", "date": "2026-04-07"}
        status_path.write_text(json.dumps(expected_data), encoding="utf-8")
        assert read_analysis_status(status_path) == expected_data

    def test_file_exists_invalid_json(self, tmp_path):
        """文件损坏返回 None"""
        status_path = tmp_path / "status.json"
        status_path.write_text("not valid json {", encoding="utf-8")
        assert read_analysis_status(status_path) is None


class TestAnalysisIsRunning:
    """analysis_is_running 测试"""

    def test_running_status(self):
        """running 状态返回 True"""
        assert analysis_is_running({"status": "loading"}) is True
        assert analysis_is_running({"status": "analyzing"}) is True
        assert analysis_is_running({"status": "sending"}) is True
        assert analysis_is_running({"status": "saving"}) is True

    def test_idle_status(self):
        """idle 状态返回 False"""
        assert analysis_is_running({"status": "idle"}) is False
        assert analysis_is_running({"status": "completed"}) is False
        assert analysis_is_running({"status": "failed"}) is False

    def test_empty_or_none(self):
        """empty/None 返回 False"""
        assert analysis_is_running(None) is False
        assert analysis_is_running({}) is False


class TestResolveAnalysisReportPath:
    """resolve_analysis_report_path 测试"""

    def test_with_target_date_exists(self, tmp_path):
        """指定日期有文件返回 Path"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        report_file = report_dir / "daily_analysis_20260407.md"
        report_file.write_text("# Report", encoding="utf-8")
        
        result = resolve_analysis_report_path(report_dir, "2026-04-07")
        assert result == report_file

    def test_with_target_date_returns_path(self, tmp_path):
        """指定日期返回路径（不检查文件是否存在，由调用方检查）"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        
        result = resolve_analysis_report_path(report_dir, "2026-04-07")
        assert result.name == "daily_analysis_20260407.md"
        assert result.parent == report_dir

    def test_without_target_date_latest(self, tmp_path):
        """不传日期时取最新一份"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        (report_dir / "daily_analysis_20260405.md").write_text("# Old", encoding="utf-8")
        (report_dir / "daily_analysis_20260407.md").write_text("# New", encoding="utf-8")
        
        result = resolve_analysis_report_path(report_dir, None)
        assert result.name == "daily_analysis_20260407.md"

    def test_dir_not_exists(self, tmp_path):
        """目录不存在返回 None"""
        report_dir = tmp_path / "nonexistent"
        result = resolve_analysis_report_path(report_dir, None)
        assert result is None


# =============================================================================
# C. start_daily_analysis 测试
# =============================================================================

class TestStartDailyAnalysis:
    """start_daily_analysis 测试"""

    def test_payload_not_dict_raises(self, tmp_path):
        """payload 非 dict 抛出 AnalysisPayloadError"""
        status_path = tmp_path / "status.json"
        script_path = tmp_path / "script.py"
        base_dir = tmp_path
        
        with pytest.raises(AnalysisPayloadError, match="must be a JSON object"):
            start_daily_analysis(
                payload="not a dict",
                status_path=status_path,
                script_path=script_path,
                base_dir=base_dir,
            )
        
        with pytest.raises(AnalysisPayloadError):
            start_daily_analysis(
                payload=None,
                status_path=status_path,
                script_path=script_path,
                base_dir=base_dir,
            )

    def test_conflict_raises(self, tmp_path, monkeypatch):
        """conflict 路径抛出 AnalysisConflictError"""
        status_path = tmp_path / "status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps({"status": "loading", "date": "2026-04-07"}),
            encoding="utf-8"
        )
        
        script_path = tmp_path / "script.py"
        base_dir = tmp_path
        
        # Fake popen (不应该被调用)
        fake_popen_called = []
        def fake_popen(*args, **kwargs):
            fake_popen_called.append(True)
            return type("FakeProc", (), {"pid": 12345})()
        
        with pytest.raises(AnalysisConflictError, match="already running"):
            start_daily_analysis(
                payload={"date": "2026-04-07"},
                status_path=status_path,
                script_path=script_path,
                base_dir=base_dir,
                popen=fake_popen,
            )
        
        assert len(fake_popen_called) == 0, "popen 不应该被调用"

    def test_happy_path(self, tmp_path, monkeypatch):
        """happy path 返回 started 状态"""
        status_path = tmp_path / "status.json"
        script_path = tmp_path / "script.py"
        base_dir = tmp_path
        
        # Fake popen
        def fake_popen(*args, **kwargs):
            return type("FakeProc", (), {"pid": 99999})()
        
        result = start_daily_analysis(
            payload={"date": "2026-04-07", "notify": True},
            status_path=status_path,
            script_path=script_path,
            base_dir=base_dir,
            popen=fake_popen,
        )
        
        assert result["status"] == "started"
        assert result["pid"] == 99999
        assert result["date"] == "2026-04-07"
        assert result["notify"] is True


# =============================================================================
# D. get_daily_analysis_status 测试
# =============================================================================

class TestGetDailyAnalysisStatus:
    """get_daily_analysis_status 测试"""

    def test_no_status_file(self, tmp_path):
        """无状态文件返回 idle 结构"""
        status_path = tmp_path / "status.json"
        
        result = get_daily_analysis_status(
            target_date="2026-04-07",
            status_path=status_path,
        )
        
        assert result == {"status": "idle", "progress": 0, "current_step": "未开始"}

    def test_date_mismatch(self, tmp_path):
        """状态文件日期不匹配返回 idle 结构"""
        status_path = tmp_path / "status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps({"status": "completed", "date": "2026-04-06"}),
            encoding="utf-8"
        )
        
        result = get_daily_analysis_status(
            target_date="2026-04-07",
            status_path=status_path,
        )
        
        assert result == {"status": "idle", "progress": 0, "current_step": "未开始"}

    def test_date_match(self, tmp_path):
        """状态文件日期匹配返回原状态内容"""
        status_path = tmp_path / "status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        expected_status = {
            "status": "analyzing",
            "date": "2026-04-07",
            "progress": 50,
            "current_step": "分析中"
        }
        status_path.write_text(json.dumps(expected_status), encoding="utf-8")
        
        result = get_daily_analysis_status(
            target_date="2026-04-07",
            status_path=status_path,
        )
        
        assert result == expected_status


# =============================================================================
# E. get_daily_analysis_report_text 测试
# =============================================================================

class TestGetDailyAnalysisReportText:
    """get_daily_analysis_report_text 测试"""

    def test_report_exists(self, tmp_path):
        """有报告返回 markdown 文本"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        report_file = report_dir / "daily_analysis_20260407.md"
        expected_text = "# Daily Analysis Report\n\nContent here..."
        report_file.write_text(expected_text, encoding="utf-8")
        
        result = get_daily_analysis_report_text(
            target_date="2026-04-07",
            report_dir=report_dir,
        )
        
        assert result == expected_text

    def test_report_not_found(self, tmp_path):
        """无报告抛出 AnalysisNotFoundError"""
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        
        with pytest.raises(AnalysisNotFoundError, match="not found"):
            get_daily_analysis_report_text(
                target_date="2026-04-07",
                report_dir=report_dir,
            )


# =============================================================================
# F. check_analysis_conflict 测试
# =============================================================================

class TestCheckAnalysisConflict:
    """check_analysis_conflict 测试"""

    def test_running(self, tmp_path):
        """running 返回 (True, status_data)"""
        status_path = tmp_path / "status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_data = {"status": "loading", "date": "2026-04-07"}
        status_path.write_text(json.dumps(status_data), encoding="utf-8")
        
        is_running, data = check_analysis_conflict(status_path)
        
        assert is_running is True
        assert data == status_data

    def test_not_running(self, tmp_path):
        """not running 返回 (False, status_data)"""
        status_path = tmp_path / "status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_data = {"status": "idle", "date": "2026-04-07"}
        status_path.write_text(json.dumps(status_data), encoding="utf-8")
        
        is_running, data = check_analysis_conflict(status_path)
        
        assert is_running is False
        assert data == status_data

    def test_no_status_file(self, tmp_path):
        """无状态文件返回 (False, None)"""
        status_path = tmp_path / "status.json"
        
        is_running, data = check_analysis_conflict(status_path)
        
        assert is_running is False
        assert data is None


# =============================================================================
# 测试汇总
# =============================================================================
# 共 20 个测试，覆盖：
# - 模块导入与异常层次结构 (2)
# - normalize_date (2)
# - parse_notify_flag (3)
# - read_analysis_status (3)
# - analysis_is_running (3)
# - resolve_analysis_report_path (4)
# - start_daily_analysis (3)
# - get_daily_analysis_status (3)
# - get_daily_analysis_report_text (2)
# - check_analysis_conflict (3)
# 
# 所有测试均为纯内存操作，无外部副作用。
