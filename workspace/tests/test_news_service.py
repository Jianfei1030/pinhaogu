# -*- coding: utf-8 -*-
"""
News Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实新闻采集器进程。
使用 tmp_path 创建临时测试文件，使用 monkeypatch 注入依赖。
"""
import os
import sys
import json
from datetime import datetime

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services import news_service
from services.news_service import (
    NewsServiceError,
    NewsFileError,
    resolve_news_file,
    normalize_news_date,
    is_news_collector_running,
    load_news_items,
    get_news_status,
    get_recent_news,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert news_service is not None
    assert NewsServiceError is not None
    assert NewsFileError is not None


def test_exception_hierarchy():
    """NewsFileError 继承自 NewsServiceError"""
    assert issubclass(NewsFileError, NewsServiceError)


# =============================================================================
# B. resolve_news_file 测试
# =============================================================================

def test_resolve_news_file_path(tmp_path):
    """目标日期路径拼接正确"""
    result = resolve_news_file(tmp_path, "2026-04-07")
    assert result == tmp_path / "financial_news_2026-04-07.json"
    assert isinstance(result, type(tmp_path))


# =============================================================================
# C. normalize_news_date 测试
# =============================================================================

def test_normalize_news_date_none(tmp_path, monkeypatch):
    """None -> today"""
    fake_today = datetime(2026, 4, 7)
    monkeypatch.setattr(news_service, 'datetime', type('FakeDatetime', (), {
        'now': lambda: fake_today,
        'strptime': datetime.strptime,
    }))
    result = normalize_news_date(None)
    assert result == "2026-04-07"


def test_normalize_news_date_today(tmp_path, monkeypatch):
    """'today' -> today"""
    fake_today = datetime(2026, 4, 7)
    monkeypatch.setattr(news_service, 'datetime', type('FakeDatetime', (), {
        'now': lambda: fake_today,
        'strptime': datetime.strptime,
    }))
    result = normalize_news_date("today")
    assert result == "2026-04-07"


def test_normalize_news_date_custom_fn(tmp_path):
    """自定义 normalize_date_fn 被调用"""
    def custom_fn(value):
        return "custom-" + value
    
    result = normalize_news_date("2026-04-07", normalize_date_fn=custom_fn)
    assert result == "custom-2026-04-07"


def test_normalize_news_date_valid_date(tmp_path):
    """具体日期字符串 -> 规范化返回"""
    result = normalize_news_date("2026-04-07")
    assert result == "2026-04-07"


def test_normalize_news_date_invalid_date_fallback(tmp_path, monkeypatch):
    """非法日期格式 -> fallback 到 today"""
    fake_today = datetime(2026, 4, 7)
    monkeypatch.setattr(news_service, 'datetime', type('FakeDatetime', (), {
        'now': lambda: fake_today,
        'strptime': lambda v, fmt: (_ for _ in ()).throw(ValueError("invalid")),
    }))
    result = normalize_news_date("invalid-date")
    assert result == "2026-04-07"


# =============================================================================
# D. is_news_collector_running 测试
# =============================================================================

def test_collector_running_fake_psutil(tmp_path, monkeypatch):
    """fake psutil 检测到 collector -> True"""
    fake_psutil = type('FakePsutil', (), {
        'NoSuchProcess': Exception,
        'AccessDenied': Exception,
        'process_iter': lambda self, attrs: [
            type('FakeProc', (), {'info': {'cmdline': ['python', 'daily_news_collector.py']}})()
        ],
    })()
    
    result = is_news_collector_running(psutil_module=fake_psutil)
    assert result is True


def test_collector_not_running_fake_psutil(tmp_path, monkeypatch):
    """fake psutil 未检测到 -> False"""
    fake_psutil = type('FakePsutil', (), {
        'NoSuchProcess': Exception,
        'AccessDenied': Exception,
        'process_iter': lambda self, attrs: [
            type('FakeProc', (), {'info': {'cmdline': ['python', 'other_script.py']}})()
        ],
    })()
    
    result = is_news_collector_running(psutil_module=fake_psutil)
    assert result is False


def test_collector_fallback_subprocess(tmp_path, monkeypatch):
    """无 psutil 时 fallback subprocess 路径 -> 可正常返回"""
    fake_run = type('FakeRun', (), {
        '__call__': lambda self, *args, **kwargs: type('FakeResult', (), {
            'stdout': 'python.exe,1234,other_task\npython.exe,5678,daily_news_collector\n',
        })(),
    })()
    
    result = is_news_collector_running(psutil_module=None, subprocess_run=fake_run)
    assert result is True


def test_collector_fallback_subprocess_not_found(tmp_path, monkeypatch):
    """fallback subprocess 未检测到 -> False"""
    fake_run = type('FakeRun', (), {
        '__call__': lambda self, *args, **kwargs: type('FakeResult', (), {
            'stdout': 'python.exe,1234,other_task\n',
        })(),
    })()
    
    result = is_news_collector_running(psutil_module=None, subprocess_run=fake_run)
    assert result is False


# =============================================================================
# E. load_news_items 测试
# =============================================================================

def test_load_news_items_file_not_exists(tmp_path):
    """文件不存在 -> []"""
    non_existent = tmp_path / "not_exists.json"
    result = load_news_items(non_existent)
    assert result == []


def test_load_news_items_valid_json_list(tmp_path):
    """有效 JSON list -> 返回 list"""
    news_file = tmp_path / "news.json"
    expected = [{"title": "News 1", "detail": "Detail 1"}]
    with news_file.open('w') as f:
        json.dump(expected, f)
    
    result = load_news_items(news_file)
    assert result == expected


def test_load_news_items_invalid_json(tmp_path):
    """损坏 JSON -> []"""
    news_file = tmp_path / "news.json"
    news_file.write_text("{ invalid json }")
    
    result = load_news_items(news_file)
    assert result == []


def test_load_news_items_non_list_json(tmp_path):
    """非 list JSON -> []"""
    news_file = tmp_path / "news.json"
    news_file.write_text('{"key": "value"}')
    
    result = load_news_items(news_file)
    assert result == []


# =============================================================================
# F. get_news_status 测试
# =============================================================================

def test_get_news_status_file_not_exists(tmp_path, monkeypatch):
    """文件不存在 + collector false"""
    fake_psutil = type('FakePsutil', (), {
        'NoSuchProcess': Exception,
        'AccessDenied': Exception,
        'process_iter': lambda self, attrs: [],
    })()
    
    result = get_news_status(tmp_path, "2026-04-07", psutil_module=fake_psutil)
    
    assert result == {
        "date": "2026-04-07",
        "has_news": False,
        "news_count": 0,
        "collector_running": False,
        "file_exists": False,
    }


def test_get_news_status_file_exists_with_news(tmp_path, monkeypatch):
    """文件存在且有新闻 + collector true"""
    # 创建新闻文件
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_items = [
        {"title": "News 1", "detail": "Detail 1"},
        {"title": "News 2", "detail": "Detail 2"},
    ]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    # fake psutil 检测到 collector
    fake_psutil = type('FakePsutil', (), {
        'NoSuchProcess': Exception,
        'AccessDenied': Exception,
        'process_iter': lambda self, attrs: [
            type('FakeProc', (), {'info': {'cmdline': ['daily_news_collector']}})()
        ],
    })()
    
    result = get_news_status(tmp_path, "2026-04-07", psutil_module=fake_psutil)
    
    assert result["date"] == "2026-04-07"
    assert result["has_news"] is True
    assert result["news_count"] == 2
    assert result["collector_running"] is True
    assert result["file_exists"] is True


def test_get_news_status_file_exists_empty(tmp_path, monkeypatch):
    """文件存在但为空 list"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_file.write_text('[]')
    
    fake_psutil = type('FakePsutil', (), {
        'NoSuchProcess': Exception,
        'AccessDenied': Exception,
        'process_iter': lambda self, attrs: [],
    })()
    
    result = get_news_status(tmp_path, "2026-04-07", psutil_module=fake_psutil)
    
    assert result["file_exists"] is True
    assert result["has_news"] is False
    assert result["news_count"] == 0


# =============================================================================
# G. get_recent_news 测试
# =============================================================================

def test_get_recent_news_file_not_exists(tmp_path):
    """文件不存在 -> 空结构"""
    result = get_recent_news(tmp_path, "2026-04-07")
    
    assert result == {
        "news": [],
        "has_new": False,
        "last_time": None,
        "total": 0,
    }


def test_get_recent_news_sorting_by_time(tmp_path):
    """正常排序（按 time 倒序）"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_items = [
        {"time": "2026-04-07 10:00", "title": "News 1", "detail": "Detail 1"},
        {"time": "2026-04-07 14:00", "title": "News 2", "detail": "Detail 2"},
        {"time": "2026-04-07 12:00", "title": "News 3", "detail": "Detail 3"},
    ]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    result = get_recent_news(tmp_path, "2026-04-07")
    
    # 应该是倒序：14:00, 12:00, 10:00
    assert result["news"][0]["time"] == "2026-04-07 14:00"
    assert result["news"][1]["time"] == "2026-04-07 12:00"
    assert result["news"][2]["time"] == "2026-04-07 10:00"
    assert result["last_time"] == "2026-04-07 14:00"


def test_get_recent_news_limit(tmp_path):
    """limit 生效"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_items = [
        {"time": f"2026-04-07 {i:02d}:00", "title": f"News {i}", "detail": f"Detail {i}"}
        for i in range(100)
    ]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    # 默认 limit=1000，返回全部 100 条
    result_default = get_recent_news(tmp_path, "2026-04-07")
    assert result_default["total"] == 100
    
    # 指定 limit=3，返回 3 条
    result_limited = get_recent_news(tmp_path, "2026-04-07", limit=3)
    assert result_limited["total"] == 3
    assert len(result_limited["news"]) == 3


def test_get_recent_news_after_filter(tmp_path):
    """after 过滤生效"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_items = [
        {"time": "2026-04-07 10:00", "title": "News 1", "detail": "Detail 1"},
        {"time": "2026-04-07 12:00", "title": "News 2", "detail": "Detail 2"},
        {"time": "2026-04-07 14:00", "title": "News 3", "detail": "Detail 3"},
    ]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    # 只看 12:00 之后的
    result = get_recent_news(tmp_path, "2026-04-07", after="2026-04-07 11:00")
    
    assert result["total"] == 2
    assert result["news"][0]["time"] == "2026-04-07 14:00"
    assert result["news"][1]["time"] == "2026-04-07 12:00"


def test_get_recent_news_summary_truncated(tmp_path):
    """summary 取 detail[:80]"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    long_detail = "A" * 200  # 200 字符
    news_items = [
        {"time": "2026-04-07 10:00", "title": "News 1", "detail": long_detail},
    ]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    result = get_recent_news(tmp_path, "2026-04-07")
    
    assert len(result["news"][0]["summary"]) == 80
    assert result["news"][0]["summary"] == "A" * 80


def test_get_recent_news_empty_file(tmp_path):
    """文件存在但为空 -> 空结构"""
    news_file = tmp_path / "financial_news_2026-04-07.json"
    news_file.write_text('[]')
    
    result = get_recent_news(tmp_path, "2026-04-07")
    
    assert result["news"] == []
    assert result["has_new"] is False
    assert result["total"] == 0


# =============================================================================
# H. 集成场景测试
# =============================================================================

def test_get_recent_news_today_semantic(tmp_path, monkeypatch):
    """target_date='today' 语义可通过上层 helper 体现"""
    # 模拟今天的新闻文件
    fake_today = datetime(2026, 4, 7)
    today_str = "2026-04-07"
    
    monkeypatch.setattr(news_service, 'datetime', type('FakeDatetime', (), {
        'now': lambda: fake_today,
        'strptime': datetime.strptime,
    }))
    
    # 使用 normalize_news_date 处理 'today'
    normalized_date = normalize_news_date("today")
    assert normalized_date == today_str
    
    # 创建今天的新闻文件
    news_file = tmp_path / f"financial_news_{today_str}.json"
    news_items = [{"time": "2026-04-07 10:00", "title": "Today News", "detail": "Detail"}]
    with news_file.open('w') as f:
        json.dump(news_items, f)
    
    # 使用规范化后的日期查询
    result = get_recent_news(tmp_path, normalized_date)
    
    assert result["has_new"] is True
    assert result["news"][0]["title"] == "Today News"
