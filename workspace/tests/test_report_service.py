# -*- coding: utf-8 -*-
"""
Report Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实报告目录。
使用 tmp_path 创建临时测试文件。
"""
import os
import sys
import json
from datetime import datetime

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services import report_service
from services.report_service import (
    ReportServiceError,
    ReportNotFoundError,
    ReportUnreadableError,
    ReportInvalidTypeError,
    resolve_report_path,
    resolve_latest_report_path,
    read_report_json,
    build_report_status,
    get_report,
    get_latest_report,
    get_report_status,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert report_service is not None
    assert ReportServiceError is not None
    assert ReportNotFoundError is not None
    assert ReportUnreadableError is not None
    assert ReportInvalidTypeError is not None


def test_exception_hierarchy():
    """所有异常都继承自 ReportServiceError"""
    assert issubclass(ReportNotFoundError, ReportServiceError)
    assert issubclass(ReportUnreadableError, ReportServiceError)
    assert issubclass(ReportInvalidTypeError, ReportServiceError)


# =============================================================================
# B. resolve_report_path 测试
# =============================================================================

def test_resolve_report_path_premarket(tmp_path):
    """premarket + 指定日期"""
    result = resolve_report_path(tmp_path, "premarket", "2026-04-07")
    assert result == tmp_path / "premarket_20260407.json"
    assert isinstance(result, type(tmp_path))


def test_resolve_report_path_review(tmp_path):
    """review + 指定日期"""
    result = resolve_report_path(tmp_path, "review", "2026-04-07")
    assert result == tmp_path / "review_20260407.json"


def test_resolve_report_path_none_date(tmp_path):
    """target_date=None 时默认今天，返回 Path 结构合理"""
    result = resolve_report_path(tmp_path, "premarket", None)
    today = datetime.now().strftime("%Y%m%d")
    assert result == tmp_path / f"premarket_{today}.json"
    assert hasattr(result, "exists")  # Path 对象


def test_resolve_report_path_invalid_type(tmp_path):
    """非法 report_type -> ReportInvalidTypeError"""
    with pytest.raises(ReportInvalidTypeError):
        resolve_report_path(tmp_path, "invalid_type", "2026-04-07")


# =============================================================================
# C. resolve_latest_report_path 测试
# =============================================================================

def test_resolve_latest_report_path_dir_not_exists(tmp_path):
    """目录不存在 -> None"""
    non_existent = tmp_path / "non_existent"
    result = resolve_latest_report_path(non_existent, "premarket")
    assert result is None


def test_resolve_latest_report_path_no_files(tmp_path):
    """目录存在但无匹配文件 -> None"""
    result = resolve_latest_report_path(tmp_path, "premarket")
    assert result is None


def test_resolve_latest_report_path_multiple_files(tmp_path):
    """有多个文件时返回最新一个"""
    # 创建多个文件（按时间倒序）
    (tmp_path / "premarket_20260405.json").touch()
    (tmp_path / "premarket_20260407.json").touch()
    (tmp_path / "premarket_20260406.json").touch()
    
    result = resolve_latest_report_path(tmp_path, "premarket")
    assert result == tmp_path / "premarket_20260407.json"


def test_resolve_latest_report_path_review_type(tmp_path):
    """review 类型也能正确识别"""
    (tmp_path / "review_20260405.json").touch()
    (tmp_path / "review_20260408.json").touch()
    
    result = resolve_latest_report_path(tmp_path, "review")
    assert result == tmp_path / "review_20260408.json"


# =============================================================================
# D. read_report_json 测试
# =============================================================================

def test_read_report_json_not_found(tmp_path):
    """文件不存在 -> ReportNotFoundError"""
    non_existent = tmp_path / "non_existent.json"
    with pytest.raises(ReportNotFoundError):
        read_report_json(non_existent)


def test_read_report_json_valid(tmp_path):
    """有效 JSON dict -> 返回 dict"""
    test_file = tmp_path / "valid.json"
    test_data = {"status": "ok", "value": 123}
    test_file.write_text(json.dumps(test_data), encoding="utf-8")
    
    result = read_report_json(test_file)
    assert result == test_data
    assert isinstance(result, dict)


def test_read_report_json_non_dict(tmp_path):
    """非 dict JSON（如 list） -> ReportUnreadableError"""
    test_file = tmp_path / "list.json"
    test_file.write_text("[1, 2, 3]", encoding="utf-8")
    
    with pytest.raises(ReportUnreadableError):
        read_report_json(test_file)


def test_read_report_json_invalid(tmp_path):
    """非法 JSON -> ReportUnreadableError"""
    test_file = tmp_path / "invalid.json"
    test_file.write_text("not valid json {", encoding="utf-8")
    
    with pytest.raises(ReportUnreadableError):
        read_report_json(test_file)


# =============================================================================
# E. build_report_status 测试
# =============================================================================

def test_build_report_status_exists(tmp_path):
    """文件存在 -> exists=True, path 非空"""
    test_file = tmp_path / "premarket_20260407.json"
    test_file.touch()
    
    result = build_report_status(tmp_path, "premarket", "2026-04-07")
    assert result["date"] == "2026-04-07"
    assert result["exists"] is True
    assert result["path"] is not None
    assert "premarket_20260407.json" in result["path"]


def test_build_report_status_not_exists(tmp_path):
    """文件不存在 -> exists=False, path=None"""
    result = build_report_status(tmp_path, "premarket", "2026-04-07")
    assert result["date"] == "2026-04-07"
    assert result["exists"] is False
    assert result["path"] is None


def test_build_report_status_structure(tmp_path):
    """返回结构兼容当前 API"""
    test_file = tmp_path / "review_20260407.json"
    test_file.touch()
    
    result = build_report_status(tmp_path, "review", "2026-04-07")
    assert "date" in result
    assert "exists" in result
    assert "path" in result


# =============================================================================
# F. get_report 测试
# =============================================================================

def test_get_report_success(tmp_path):
    """正常读取指定日期报告"""
    test_file = tmp_path / "premarket_20260407.json"
    test_data = {"report": "test", "data": [1, 2, 3]}
    test_file.write_text(json.dumps(test_data), encoding="utf-8")
    
    result = get_report(tmp_path, "premarket", "2026-04-07")
    assert result == test_data


def test_get_report_not_found(tmp_path):
    """not found 路径"""
    with pytest.raises(ReportNotFoundError):
        get_report(tmp_path, "premarket", "2026-04-07")


def test_get_report_unreadable(tmp_path):
    """unreadable 路径"""
    test_file = tmp_path / "premarket_20260407.json"
    test_file.write_text("invalid json {", encoding="utf-8")
    
    with pytest.raises(ReportUnreadableError):
        get_report(tmp_path, "premarket", "2026-04-07")


# =============================================================================
# G. get_latest_report 测试
# =============================================================================

def test_get_latest_report_success(tmp_path):
    """正常读取最新报告"""
    (tmp_path / "premarket_20260405.json").write_text(
        json.dumps({"version": "old"}), encoding="utf-8"
    )
    (tmp_path / "premarket_20260407.json").write_text(
        json.dumps({"version": "new"}), encoding="utf-8"
    )
    
    result = get_latest_report(tmp_path, "premarket")
    assert result == {"version": "new"}


def test_get_latest_report_no_files(tmp_path):
    """无文件 -> ReportNotFoundError"""
    with pytest.raises(ReportNotFoundError):
        get_latest_report(tmp_path, "premarket")


# =============================================================================
# H. get_report_status 测试
# =============================================================================

def test_get_report_status_premarket(tmp_path):
    """premarket 路径"""
    test_file = tmp_path / "premarket_20260407.json"
    test_file.touch()
    
    result = get_report_status(tmp_path, "premarket", "2026-04-07")
    assert result["exists"] is True
    assert result["date"] == "2026-04-07"


def test_get_report_status_review(tmp_path):
    """review 路径"""
    test_file = tmp_path / "review_20260407.json"
    test_file.touch()
    
    result = get_report_status(tmp_path, "review", "2026-04-07")
    assert result["exists"] is True
    assert result["date"] == "2026-04-07"


def test_get_report_status_not_exists(tmp_path):
    """状态查询返回不存在的报告"""
    result = get_report_status(tmp_path, "premarket", "2026-04-07")
    assert result["exists"] is False
    assert result["path"] is None
