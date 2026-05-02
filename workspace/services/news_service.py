# -*- coding: utf-8 -*-
"""
News Service - Financial News Collection Business Logic

This module provides pure business logic for news status and recent news operations.
No FastAPI dependencies. No HTTPException. Lightweight exceptions only.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# =============================================================================
# A. 业务异常 (Business Exceptions)
# =============================================================================

class NewsServiceError(Exception):
    """Base exception for news service errors."""
    pass


class NewsFileError(NewsServiceError):
    """Raised when news file exists but cannot be read or parsed."""
    pass


# =============================================================================
# B. 常量 (Constants)
# =============================================================================

DATE_FMT = "%Y-%m-%d"


# =============================================================================
# C. Helper 函数 (Helpers)
# =============================================================================

def resolve_news_file(news_dir: Path, target_date: str) -> Path:
    """
    Resolve the path to a news file for a given date.
    
    Args:
        news_dir: Directory containing news JSON files.
        target_date: Target date in YYYY-MM-DD format.
    
    Returns:
        Path to the news file (may not exist).
    """
    return news_dir / f"financial_news_{target_date}.json"


def normalize_news_date(
    value: str | None,
    normalize_date_fn: Callable[[str | None], str] | None = None
) -> str:
    """
    Normalize a date string to YYYY-MM-DD format.
    
    Args:
        value: Date string in YYYY-MM-DD format, "today", or None.
        normalize_date_fn: Optional custom normalization function.
                          If not provided, uses built-in normalization.
    
    Returns:
        Normalized date string, or today's date if value is None or "today".
    """
    if value is None:
        return datetime.now().strftime(DATE_FMT)
    
    value = str(value).strip().lower()
    
    if value == "today":
        return datetime.now().strftime(DATE_FMT)
    
    if normalize_date_fn is not None:
        return normalize_date_fn(value)
    
    # Built-in normalization
    try:
        return datetime.strptime(value, DATE_FMT).strftime(DATE_FMT)
    except ValueError:
        # Fallback to today if parsing fails
        return datetime.now().strftime(DATE_FMT)


def is_news_collector_running(
    psutil_module: Any = None,
    subprocess_run: Callable | None = None
) -> bool:
    """
    Check if the news collector process is currently running.
    
    Args:
        psutil_module: psutil module, or None if not available.
        subprocess_run: subprocess.run function, or None for default.
    
    Returns:
        True if collector is running, False otherwise.
    """
    if psutil_module is not None:
        try:
            for proc in psutil_module.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and 'daily_news_collector' in ' '.join(cmdline).lower():
                        return True
                except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
                    pass
                except Exception:
                    pass
        except Exception:
            pass
    
    # Fallback: use platform-specific process detection
    if subprocess_run is None:
        subprocess_run = subprocess.run
    
    import platform
    system = platform.system()
    
    try:
        if system == 'Windows':
            # Windows: use tasklist
            result = subprocess_run(
                ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if 'daily_news_collector' in line.lower():
                    return True
        else:
            # macOS/Linux: use pgrep or ps
            # Try pgrep first (more reliable)
            try:
                result = subprocess_run(
                    ['pgrep', '-f', 'daily_news_collector'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except Exception:
                pass
            
            # Fallback to ps command
            try:
                result = subprocess_run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    if 'daily_news_collector' in line.lower() and 'grep' not in line.lower():
                        return True
            except Exception:
                pass
    except Exception:
        pass
    
    return False


def load_news_items(news_file: Path) -> list[dict]:
    """
    Load news items from a JSON file.
    
    Args:
        news_file: Path to the news JSON file.
    
    Returns:
        List of news items, or empty list if file doesn't exist or is invalid.
    
    Raises:
        NewsFileError: If file exists but cannot be parsed (optional, currently returns empty list).
    """
    if not news_file.exists():
        return []
    
    try:
        with news_file.open('r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            return data
        return []
    except Exception:
        # Keep lenient behavior: return empty list instead of raising
        return []


# =============================================================================
# D. 面向 Route 的入口 (Route-facing Entry Points)
# =============================================================================

def get_news_status(
    news_dir: Path,
    target_date: str,
    psutil_module: Any = None,
    subprocess_run: Callable | None = None
) -> dict[str, Any]:
    """
    Get news collection status for a given date.
    
    Args:
        news_dir: Directory containing news JSON files.
        target_date: Target date in YYYY-MM-DD format.
        psutil_module: Optional psutil module for process detection.
        subprocess_run: Optional subprocess.run function for fallback detection.
    
    Returns:
        Status dict with fields:
        - date: Target date in YYYY-MM-DD format
        - has_news: True if news file exists and contains items
        - news_count: Number of news items
        - collector_running: True if collector process is running
        - file_exists: True if news file exists
    """
    news_file = resolve_news_file(news_dir, target_date)
    
    # Check if collector is running
    collector_running = is_news_collector_running(psutil_module, subprocess_run)
    
    # Check file and count news
    news_count = 0
    has_news = False
    file_exists = news_file.exists()
    
    if file_exists:
        news_items = load_news_items(news_file)
        news_count = len(news_items)
        has_news = news_count > 0
    
    return {
        "date": target_date,
        "has_news": has_news,
        "news_count": news_count,
        "collector_running": collector_running,
        "file_exists": file_exists,
    }


def get_recent_news(
    news_dir: Path,
    target_date: str,
    limit: int = 5000,
    after: str | None = None
) -> dict[str, Any]:
    """
    Get recent news items for a given date.
    
    Args:
        news_dir: Directory containing news JSON files.
        target_date: Target date in YYYY-MM-DD format, or "today".
        limit: Maximum number of news items to return (default 5000 for full-day view, max 5000).
        after: Optional timestamp filter: only return items with time > after.
    
    Returns:
        Status dict with fields:
        - news: List of news items (time, title, source, summary)
        - has_new: True if any news items were returned
        - last_time: Timestamp of the most recent news item, or None
        - total: Number of news items returned
    """
    news_file = resolve_news_file(news_dir, target_date)
    
    # File doesn't exist: return empty structure
    if not news_file.exists():
        return {
            "news": [],
            "has_new": False,
            "last_time": None,
            "total": 0,
        }
    
    # Load news items
    news_items = load_news_items(news_file)
    
    if not news_items:
        return {
            "news": [],
            "has_new": False,
            "last_time": None,
            "total": 0,
        }
    
    # Sort by time descending (newest first)
    sorted_news = sorted(news_items, key=lambda x: x.get('time', ''), reverse=True)
    
    # Apply after filter if provided
    if after:
        sorted_news = [item for item in sorted_news if item.get('time', '') > after]
    
    # Apply limit
    limited_news = sorted_news[:limit]
    
    # Build response structure
    news_list = [
        {
            "time": item.get('time', ''),
            "title": item.get('title', ''),
            "source": item.get('source', ''),
            "summary": (item.get('detail', '') or '')[:80],
        }
        for item in limited_news
    ]
    
    last_time = limited_news[0].get('time') if limited_news else None
    
    return {
        "news": news_list,
        "has_new": len(news_list) > 0,
        "last_time": last_time,
        "total": len(news_list),
    }
