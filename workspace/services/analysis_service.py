# -*- coding: utf-8 -*-
"""
Analysis Service - Daily Analysis Business Logic

This module provides pure business logic for daily analysis operations.
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

class AnalysisServiceError(Exception):
    """Base exception for analysis service errors."""
    pass


class AnalysisConflictError(AnalysisServiceError):
    """Raised when daily analysis is already running."""
    pass


class AnalysisNotFoundError(AnalysisServiceError):
    """Raised when analysis report is not found."""
    pass


class AnalysisPayloadError(AnalysisServiceError):
    """Raised when request payload is invalid."""
    pass


# =============================================================================
# B. 状态 / 路径 Helper (Status / Path Helpers)
# =============================================================================

DATE_FMT = "%Y-%m-%d"


def read_analysis_status(status_path: Path) -> dict[str, Any] | None:
    """
    Read analysis status from JSON file.
    
    Args:
        status_path: Path to the status JSON file.
    
    Returns:
        Parsed status dict, or None if file doesn't exist or is invalid.
    """
    if not status_path.exists():
        return None
    try:
        with status_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def analysis_is_running(
    status_data: dict[str, Any] | None,
    running_statuses: set[str] | None = None
) -> bool:
    """
    Check if daily analysis is currently running.
    
    Args:
        status_data: Status dict from read_analysis_status().
        running_statuses: Set of status strings that indicate "running".
                         Defaults to ANALYSIS_RUNNING_STATUSES.
    
    Returns:
        True if analysis is running, False otherwise.
    """
    if running_statuses is None:
        running_statuses = {"loading", "analyzing", "sending", "saving"}
    
    if not status_data:
        return False
    
    status = str(status_data.get("status") or "").strip().lower()
    return status in running_statuses


def resolve_analysis_report_path(
    report_dir: Path,
    target_date: str | None
) -> Path | None:
    """
    Resolve the path to a daily analysis report.
    
    Args:
        report_dir: Directory containing report files.
        target_date: Target date in YYYY-MM-DD format, or None for latest.
    
    Returns:
        Path to the report file, or None if not found.
    """
    if target_date:
        return report_dir / f"daily_analysis_{target_date.replace('-', '')}.md"
    
    if not report_dir.exists():
        return None
    
    candidates = sorted(report_dir.glob("daily_analysis_*.md"), reverse=True)
    return candidates[0] if candidates else None


def normalize_date(value: str | None) -> str:
    """
    Normalize a date string to YYYY-MM-DD format.
    
    Args:
        value: Date string in YYYY-MM-DD format, or None.
    
    Returns:
        Normalized date string, or today's date if value is None.
    """
    if value:
        return datetime.strptime(str(value).strip(), DATE_FMT).strftime(DATE_FMT)
    return datetime.now().strftime(DATE_FMT)


def parse_notify_flag(notify_value: Any) -> bool:
    """
    Parse notify flag from request payload.
    
    Args:
        notify_value: Boolean or string value from payload.
    
    Returns:
        True if notify is enabled, False otherwise.
    """
    if isinstance(notify_value, bool):
        return notify_value
    
    notify_str = str(notify_value).strip().lower()
    return notify_str not in {"0", "false", "no", "off", ""}


# =============================================================================
# C. 业务入口函数 (Business Entry Points)
# =============================================================================

def start_daily_analysis(
    payload: dict[str, Any],
    status_path: Path,
    script_path: Path,
    base_dir: Path,
    normalize_date_fn: Callable[[str | None], str] = normalize_date,
    running_statuses: set[str] | None = None,
    popen: Callable = subprocess.Popen
) -> dict[str, Any]:
    """
    Start a daily analysis task.
    
    Args:
        payload: Request body dict containing 'date' and 'notify' fields.
        status_path: Path to the status JSON file.
        script_path: Path to daily_sector_pipeline.py.
        base_dir: Base directory for running the script.
        normalize_date_fn: Date normalization function.
        running_statuses: Set of statuses indicating "running".
        popen: subprocess.Popen or mock for testing.
    
    Returns:
        Dict with 'status' ('started' or 'conflict') and metadata.
    
    Raises:
        AnalysisPayloadError: If payload is not a dict.
        AnalysisConflictError: If analysis is already running.
    """
    # Validate payload
    if not isinstance(payload, dict):
        raise AnalysisPayloadError("Request body must be a JSON object")
    
    # Parse parameters
    target_date = normalize_date_fn(payload.get("date"))
    notify_flag = parse_notify_flag(payload.get("notify", True))
    
    # Check for conflict
    status_data = read_analysis_status(status_path)
    if analysis_is_running(status_data, running_statuses):
        raise AnalysisConflictError(
            f"Daily analysis is already running (date: {status_data.get('date')})"
        )
    
    # Ensure status directory exists
    status_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build command (cross-platform: use 'python3' on macOS/Linux, 'py -3' on Windows)
    import platform
    if platform.system() == "Windows":
        python_cmd = ["py", "-3"]
    else:
        python_cmd = ["python3"]
    
    command = [
        *python_cmd,
        str(script_path),
        "--status-file",
        str(status_path),
        "--date",
        target_date,
    ]
    if not notify_flag:
        command.append("--no-notify")
    
    # Start process
    proc = popen(
        command,
        cwd=str(base_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    return {
        "status": "started",
        "pid": proc.pid,
        "date": target_date,
        "notify": notify_flag,
    }


def get_daily_analysis_status(
    target_date: str | None,
    status_path: Path,
    normalize_date_fn: Callable[[str | None], str] = normalize_date,
    today_str: str | None = None
) -> dict[str, Any]:
    """
    Get daily analysis status.
    
    Args:
        target_date: Target date in YYYY-MM-DD format, or None for today.
        status_path: Path to the status JSON file.
        normalize_date_fn: Date normalization function.
        today_str: Pre-computed today's date string (for testing).
    
    Returns:
        Status dict. Returns idle structure if no status or date mismatch.
    """
    if today_str is None:
        today_str = datetime.now().strftime(DATE_FMT)
    
    if target_date is None:
        target_date = today_str
    else:
        target_date = normalize_date_fn(target_date)
    
    status_data = read_analysis_status(status_path)
    
    # No status file -> idle
    if not status_data:
        return {"status": "idle", "progress": 0, "current_step": "未开始"}
    
    # Date mismatch -> idle (avoid returning stale status)
    if status_data.get("date") != target_date:
        return {"status": "idle", "progress": 0, "current_step": "未开始"}
    
    # Return status data as-is
    return status_data


def get_daily_analysis_report_text(
    target_date: str | None,
    report_dir: Path,
    normalize_date_fn: Callable[[str | None], str] = normalize_date
) -> str:
    """
    Get daily analysis report text.
    
    Args:
        target_date: Target date in YYYY-MM-DD format, or None for latest.
        report_dir: Directory containing report files.
        normalize_date_fn: Date normalization function.
    
    Returns:
        Report markdown text.
    
    Raises:
        AnalysisNotFoundError: If report file is not found.
    """
    if target_date is not None:
        target_date = normalize_date_fn(target_date)
    
    report_path = resolve_analysis_report_path(report_dir, target_date)
    
    if not report_path or not report_path.exists():
        if target_date:
            raise AnalysisNotFoundError(
                f"Analysis report not found for {target_date}"
            )
        raise AnalysisNotFoundError("Analysis report not found")
    
    return report_path.read_text(encoding="utf-8")


# =============================================================================
# D. 批量状态检查 (Batch Status Check - Optional Utility)
# =============================================================================

def check_analysis_conflict(
    status_path: Path,
    running_statuses: set[str] | None = None
) -> tuple[bool, dict[str, Any] | None]:
    """
    Check if analysis is running without throwing exceptions.
    
    Args:
        status_path: Path to the status JSON file.
        running_statuses: Set of statuses indicating "running".
    
    Returns:
        Tuple of (is_running, status_data).
    """
    status_data = read_analysis_status(status_path)
    is_running = analysis_is_running(status_data, running_statuses)
    return is_running, status_data
