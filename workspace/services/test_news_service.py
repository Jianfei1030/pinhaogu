# -*- coding: utf-8 -*-
"""
Lightweight smoke test for news_service.py
No FastAPI dependency. No real collector process.
"""
import json
import tempfile
from pathlib import Path
from datetime import datetime

# Import the service module
from services.news_service import (
    get_news_status,
    get_recent_news,
    resolve_news_file,
    normalize_news_date,
    is_news_collector_running,
    load_news_items,
    NewsServiceError,
    NewsFileError,
)


def test_resolve_news_file():
    """Test news file path resolution."""
    news_dir = Path("/tmp/news")
    path = resolve_news_file(news_dir, "2026-04-07")
    assert str(path) == "/tmp/news/financial_news_2026-04-07.json"
    print("✓ test_resolve_news_file PASSED")


def test_normalize_news_date():
    """Test date normalization."""
    # Today
    today = datetime.now().strftime("%Y-%m-%d")
    assert normalize_news_date(None) == today
    assert normalize_news_date("today") == today
    assert normalize_news_date("Today") == today
    
    # Specific date
    assert normalize_news_date("2026-04-07") == "2026-04-07"
    
    print("✓ test_normalize_news_date PASSED")


def test_is_news_collector_running_with_fake():
    """Test collector detection with fake psutil."""
    # Fake psutil that says collector is running
    class FakeProc:
        def __init__(self, has_collector):
            self.info = {
                'pid': 123,
                'cmdline': ['python', 'daily_news_collector.py'] if has_collector else ['python', 'other.py']
            }
    
    class FakePsutil:
        NoSuchProcess = Exception
        AccessDenied = Exception
        
        @staticmethod
        def process_iter(attrs):
            return [FakeProc(True)]  # Has collector
    
    result = is_news_collector_running(psutil_module=FakePsutil)
    assert result is True
    
    # Fake psutil that says collector is NOT running
    class FakePsutil2:
        NoSuchProcess = Exception
        AccessDenied = Exception
        
        @staticmethod
        def process_iter(attrs):
            return [FakeProc(False)]  # No collector
    
    result = is_news_collector_running(psutil_module=FakePsutil2)
    assert result is False
    
    print("✓ test_is_news_collector_running_with_fake PASSED")


def test_load_news_items():
    """Test loading news from file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        news_file = Path(tmpdir) / "financial_news_2026-04-07.json"
        
        # Non-existent file
        items = load_news_items(news_file)
        assert items == []
        
        # Valid file
        test_data = [
            {"time": "2026-04-07 10:00", "title": "Test 1", "source": "Test", "detail": "Detail 1"},
            {"time": "2026-04-07 09:00", "title": "Test 2", "source": "Test", "detail": "Detail 2"},
        ]
        with news_file.open('w') as f:
            json.dump(test_data, f)
        
        items = load_news_items(news_file)
        assert len(items) == 2
        assert items[0]["title"] == "Test 1"
        
        # Invalid JSON (should return empty list, not raise)
        with news_file.open('w') as f:
            f.write("not valid json")
        
        items = load_news_items(news_file)
        assert items == []
    
    print("✓ test_load_news_items PASSED")


def test_get_news_status():
    """Test get_news_status function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        news_dir = Path(tmpdir)
        
        # No file exists
        status = get_news_status(news_dir, "2026-04-07")
        assert status["date"] == "2026-04-07"
        assert status["has_news"] is False
        assert status["news_count"] == 0
        assert status["file_exists"] is False
        assert status["collector_running"] is False  # No fake psutil
        
        # File exists with news
        news_file = news_dir / "financial_news_2026-04-07.json"
        test_data = [
            {"time": "2026-04-07 10:00", "title": "Test 1", "source": "Test", "detail": "Detail 1"},
            {"time": "2026-04-07 09:00", "title": "Test 2", "source": "Test", "detail": "Detail 2"},
        ]
        with news_file.open('w') as f:
            json.dump(test_data, f)
        
        status = get_news_status(news_dir, "2026-04-07")
        assert status["has_news"] is True
        assert status["news_count"] == 2
        assert status["file_exists"] is True
    
    print("✓ test_get_news_status PASSED")


def test_get_recent_news():
    """Test get_recent_news function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        news_dir = Path(tmpdir)
        news_file = news_dir / "financial_news_2026-04-07.json"
        
        # No file
        recent = get_recent_news(news_dir, "2026-04-07")
        assert recent["news"] == []
        assert recent["has_new"] is False
        assert recent["last_time"] is None
        assert recent["total"] == 0
        
        # File with news
        test_data = [
            {"time": "2026-04-07 10:00", "title": "Test 1", "source": "Source1", "detail": "This is a detailed description for test 1"},
            {"time": "2026-04-07 09:00", "title": "Test 2", "source": "Source2", "detail": "Detail 2"},
            {"time": "2026-04-07 08:00", "title": "Test 3", "source": "Source3", "detail": "Detail 3"},
        ]
        with news_file.open('w') as f:
            json.dump(test_data, f)
        
        # Get all (limit default 20)
        recent = get_recent_news(news_dir, "2026-04-07")
        assert recent["total"] == 3
        assert recent["has_new"] is True
        assert recent["last_time"] == "2026-04-07 10:00"
        assert recent["news"][0]["title"] == "Test 1"  # Sorted by time desc
        assert recent["news"][0]["summary"] == "This is a detailed description for test 1"  # detail[:80]
        
        # With limit
        recent = get_recent_news(news_dir, "2026-04-07", limit=2)
        assert recent["total"] == 2
        
        # With after filter
        recent = get_recent_news(news_dir, "2026-04-07", after="2026-04-07 09:00")
        assert recent["total"] == 1
        assert recent["news"][0]["time"] == "2026-04-07 10:00"
    
    print("✓ test_get_recent_news PASSED")


def test_exceptions():
    """Test exception classes exist."""
    assert issubclass(NewsServiceError, Exception)
    assert issubclass(NewsFileError, NewsServiceError)
    print("✓ test_exceptions PASSED")


if __name__ == "__main__":
    test_resolve_news_file()
    test_normalize_news_date()
    test_is_news_collector_running_with_fake()
    test_load_news_items()
    test_get_news_status()
    test_get_recent_news()
    test_exceptions()
    
    print("\n✅ All smoke tests PASSED!")
