# -*- coding: utf-8 -*-
"""
Report Service - Premarket & Review Report Business Logic

This module provides pure business logic for premarket and review report operations.
No FastAPI dependencies. No HTTPException. Lightweight exceptions only.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


# =============================================================================
# A. 业务异常 (Business Exceptions)
# =============================================================================

class ReportServiceError(Exception):
    """Base exception for report service errors."""
    pass


class ReportNotFoundError(ReportServiceError):
    """Raised when a report file is not found."""
    pass


class ReportUnreadableError(ReportServiceError):
    """Raised when a report file exists but cannot be read/parsed."""
    pass


class ReportInvalidTypeError(ReportServiceError):
    """Raised when an invalid report type is provided."""
    pass


# =============================================================================
# B. 常量 (Constants)
# =============================================================================

DATE_FMT = "%Y-%m-%d"
VALID_REPORT_TYPES = {"premarket", "review", "premarket_thesis"}


# =============================================================================
# C. 低层 Helper (Low-level Helpers)
# =============================================================================

def _get_report_prefix(report_type: str) -> str:
    """
    Get the file prefix for a given report type.
    
    Args:
        report_type: One of 'premarket', 'review'.
    
    Returns:
        File prefix string (e.g., 'premarket', 'review').
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
    """
    if report_type not in VALID_REPORT_TYPES:
        raise ReportInvalidTypeError(
            f"Invalid report type: {report_type}. Must be one of {VALID_REPORT_TYPES}"
        )
    return report_type


def resolve_report_path(
    report_dir: Path,
    report_type: str,
    target_date: str | None
) -> Path:
    """
    Resolve the path to a specific report file.
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
        target_date: Target date in YYYY-MM-DD format, or None for today.
    
    Returns:
        Path to the report file (may not exist).
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
    """
    prefix = _get_report_prefix(report_type)
    
    if target_date:
        date_str = target_date.replace("-", "")
    else:
        date_str = datetime.now().strftime("%Y%m%d")
    
    return report_dir / f"{prefix}_{date_str}.json"


def resolve_latest_report_path(
    report_dir: Path,
    report_type: str
) -> Path | None:
    """
    Resolve the path to the latest report file of a given type.
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
    
    Returns:
        Path to the latest report file, or None if no files found.
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
    """
    prefix = _get_report_prefix(report_type)
    
    if not report_dir.exists():
        return None
    
    pattern = f"{prefix}_*.json"
    candidates = sorted(report_dir.glob(pattern), reverse=True)
    
    return candidates[0] if candidates else None


def read_report_json(path: Path) -> dict[str, Any]:
    """
    Read and parse a JSON report file.
    
    Args:
        path: Path to the JSON file.
    
    Returns:
        Parsed JSON content as a dict.
    
    Raises:
        ReportNotFoundError: If the file does not exist.
        ReportUnreadableError: If the file cannot be read or parsed.
    """
    if not path.exists():
        raise ReportNotFoundError(f"Report file not found: {path}")
    
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        
        if not isinstance(data, dict):
            raise ReportUnreadableError(
                f"Report file is not a valid JSON object: {path}"
            )
        
        return data
    
    except json.JSONDecodeError as e:
        raise ReportUnreadableError(
            f"Failed to parse JSON report: {path}. Error: {e}"
        )
    except Exception as e:
        raise ReportUnreadableError(
            f"Failed to read report file: {path}. Error: {e}"
        )


def build_report_status(
    report_dir: Path,
    report_type: str,
    target_date: str
) -> dict[str, Any]:
    """
    Build a status dict for a report.
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
        target_date: Target date in YYYY-MM-DD format.
    
    Returns:
        Status dict with 'date', 'exists', and 'path' fields.
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
    """
    path = resolve_report_path(report_dir, report_type, target_date)
    
    return {
        "date": target_date,
        "exists": path.exists(),
        "path": str(path) if path.exists() else None,
    }


# =============================================================================
# D. 面向 Route 的入口 (Route-facing Entry Points)
# =============================================================================

def get_report(
    report_dir: Path,
    report_type: str,
    target_date: str
) -> dict[str, Any]:
    """
    Get a specific report by date.
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
        target_date: Target date in YYYY-MM-DD format.
    
    Returns:
        Report content as a dict.
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
        ReportNotFoundError: If the report file does not exist.
        ReportUnreadableError: If the report file cannot be read or parsed.
    """
    path = resolve_report_path(report_dir, report_type, target_date)
    return read_report_json(path)


def get_latest_report(
    report_dir: Path,
    report_type: str
) -> dict[str, Any]:
    """
    Get the latest report of a given type.
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
    
    Returns:
        Latest report content as a dict.
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
        ReportNotFoundError: If no report files are found.
        ReportUnreadableError: If the latest report cannot be read or parsed.
    """
    path = resolve_latest_report_path(report_dir, report_type)
    
    if path is None:
        raise ReportNotFoundError(f"No {report_type} reports found in {report_dir}")
    
    return read_report_json(path)


def get_report_status(
    report_dir: Path,
    report_type: str,
    target_date: str
) -> dict[str, Any]:
    """
    Get the status of a report (whether it exists).
    
    Args:
        report_dir: Directory containing report files.
        report_type: One of 'premarket', 'review'.
        target_date: Target date in YYYY-MM-DD format.
    
    Returns:
        Status dict with 'date', 'exists', and 'path' fields.
    
    Raises:
        ReportInvalidTypeError: If report_type is not valid.
    """
    return build_report_status(report_dir, report_type, target_date)
