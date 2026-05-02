# -*- coding: utf-8 -*-
"""
Runtime Status Service

提供 monitor 和 calibration 状态查询的核心逻辑。
不包含 FastAPI / JSONResponse，仅作为轻量函数接口。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

# =============================================================================
# A. 业务异常（轻量）
# =============================================================================


class RuntimeStatusServiceError(Exception):
    """Runtime status service 业务异常基类"""
    pass


class FileReadError(RuntimeStatusServiceError):
    """文件读取失败"""
    pass


class ProcessScanError(RuntimeStatusServiceError):
    """进程扫描失败"""
    pass


# =============================================================================
# B. 低层 helper
# =============================================================================


def read_json_file(path: Path) -> dict[str, Any] | None:
    """
    读取 JSON 文件，返回解析后的字典。
    文件不存在或解析失败时返回 None。
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def pid_running(pid: int) -> bool:
    """
    检查指定 PID 的进程是否正在运行。
    使用 os.kill(pid, 0) 方式检测。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_monitor_pid_file(primary_path: Path, legacy_path: Path) -> dict[str, Any] | None:
    """
    读取 monitor PID 文件（支持主路径和遗留路径）。
    
    返回格式：
    {
        "pid": int,
        "start_time": str | None
    }
    """
    pid_path = primary_path if primary_path.exists() else legacy_path
    if not pid_path.exists():
        return None
    
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    
    if not raw:
        return None
    
    # 尝试 JSON 格式
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    
    # 回退到旧格式：第一行 PID，第二行 start_time
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    
    try:
        pid = int(lines[0])
    except Exception:
        return None
    
    result: dict[str, Any] = {"pid": pid}
    if len(lines) >= 2:
        result["start_time"] = lines[1]
    return result


def find_monitor_process() -> dict[str, Any] | None:
    """
    通过系统命令扫描 monitor.py 进程。
    
    返回格式：
    {
        "pid": int,
        "start_time": str | None,
        "command_line": str | None
    }
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", 
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'monitor\\.py' } | Select-Object ProcessId, CreationDate, CommandLine | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return None
    
    if result.returncode != 0 or not (result.stdout or "").strip():
        return None
    
    try:
        payload = json.loads(result.stdout)
    except Exception:
        return None
    
    items = payload if isinstance(payload, list) else [payload]
    if not items:
        return None
    
    item = items[0] or {}
    created = str(item.get("CreationDate") or "")
    start_time = None
    
    if len(created) >= 14 and created[:14].isdigit():
        try:
            start_time = datetime.strptime(created[:14], "%Y%m%d%H%M%S").isoformat()
        except Exception:
            start_time = None
    
    return {
        "pid": int(item.get("ProcessId") or 0),
        "start_time": start_time,
        "command_line": item.get("CommandLine"),
    }


def get_market_status(trading_hours: dict[str, dict[str, str]]) -> dict[str, Any]:
    """
    检查当前是否在交易时段内，返回各市场状态。
    
    Args:
        trading_hours: 配置中的交易时间配置，格式如：
            {
                "HK": {"start": "09:30", "end": "16:00", "break_start": "12:00", "break_end": "13:00"},
                ...
            }
    
    Returns:
        {
            "any_open": bool,
            "markets": {market: {"open": bool, "start": str, "end": str}},
            "current_time": str,
            "next_open": str
        }
    """
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    markets_status: dict[str, dict[str, Any]] = {}
    any_open = False
    
    for market, cfg in trading_hours.items():
        start = cfg.get("start", "")
        end = cfg.get("end", "")
        break_start = cfg.get("break_start", "")
        break_end = cfg.get("break_end", "")
        
        is_open = False
        if start <= current_time <= end:
            is_open = True
            if break_start and break_end and break_start <= current_time <= break_end:
                is_open = False  # 午间休市
        
        if is_open:
            any_open = True
        
        markets_status[market] = {
            "open": is_open,
            "start": start,
            "end": end,
        }
    
    # 计算下次开盘时间
    next_open = ""
    if not any_open:
        first_start = min(
            (cfg.get("start", "99:99") for cfg in trading_hours.values()),
            default="09:00"
        )
        # 简化处理：无论当前时间，next_open 都设为下一个交易日的开盘时间
        next_open = first_start
    
    return {
        "any_open": any_open,
        "markets": markets_status,
        "current_time": current_time,
        "next_open": next_open,
    }


def get_monitor_runtime_status(
    monitor_status_path: Path,
    monitor_pid_primary_path: Path,
    monitor_pid_legacy_path: Path,
) -> dict[str, Any]:
    """
    获取 monitor 运行时状态（底层逻辑，不包含 market_status）。
    
    返回格式（4 种路径）：
    1. running=True, source=status_file|pid_file (status/pid 文件命中且 pid 存活)
    2. running=True, source=process_scan (process scan 命中)
    3. running=False, source=stale_status (有 stale 状态但未运行)
    4. running="unknown" (什么都没有)
    """
    status_data = read_json_file(monitor_status_path) or {}
    pid_data = read_monitor_pid_file(monitor_pid_primary_path, monitor_pid_legacy_path) or {}
    
    pid = int(status_data.get("pid") or pid_data.get("pid") or 0)
    
    # 路径 1: status/pid 文件命中且 pid 存活
    if pid and pid_running(pid):
        return {
            "running": True,
            "pid": pid,
            "start_time": status_data.get("start_time") or pid_data.get("start_time"),
            "last_tick": status_data.get("last_tick"),
            "tick_count": int(status_data.get("tick_count") or 0),
            "alert_count": int(status_data.get("alert_count") or 0),
            "last_prices": status_data.get("last_prices", {}),
            "source": "status_file" if status_data else "pid_file",
        }
    
    # 路径 2: process scan 命中
    process_info = find_monitor_process()
    if process_info and process_info.get("pid"):
        return {
            "running": True,
            "pid": process_info.get("pid"),
            "start_time": status_data.get("start_time") or pid_data.get("start_time") or process_info.get("start_time"),
            "last_tick": status_data.get("last_tick"),
            "tick_count": int(status_data.get("tick_count") or 0),
            "alert_count": int(status_data.get("alert_count") or 0),
            "last_prices": status_data.get("last_prices", {}),
            "source": "process_scan",
        }
    
    # 路径 3: 有 stale 状态但未运行
    if pid or status_data or pid_data:
        return {
            "running": False,
            "pid": pid or None,
            "start_time": status_data.get("start_time") or pid_data.get("start_time"),
            "last_tick": status_data.get("last_tick"),
            "tick_count": int(status_data.get("tick_count") or 0),
            "alert_count": int(status_data.get("alert_count") or 0),
            "source": "stale_status",
        }
    
    # 路径 4: 什么都没有
    return {"running": "unknown"}


def get_calibration_status(
    target_date: str,
    calibration_status_path: Path,
) -> dict[str, Any]:
    """
    获取 calibration 状态。
    
    Returns:
        {
            "date": str,
            "done": bool,
            "updated_at": str | None,
            "results": dict,
            "source": str
        }
    """
    payload = read_json_file(calibration_status_path) or {}
    
    # done 的判定：payload.done=True 且 payload.date == target_date
    done = bool(payload.get("done")) and str(payload.get("date") or "") == target_date
    
    # source 优先级：payload.source > (done ? "Tencent" : "THS-SIM")
    source = payload.get("source") or ("Tencent" if done else "THS-SIM")
    
    return {
        "date": target_date,
        "done": done,
        "updated_at": payload.get("updated_at"),
        "results": payload.get("results", {}),
        "source": source,
    }


# =============================================================================
# C. 面向 route 的主入口
# =============================================================================


def build_monitor_status_payload(
    monitor_status_path: Path,
    monitor_pid_primary_path: Path,
    monitor_pid_legacy_path: Path,
    trading_hours: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """
    构建 /api/monitor/status 的完整响应 payload。
    
    保持与当前 API 完全兼容，包含 market_status 信息。
    
    Returns:
        {
            "running": bool | str,
            "pid": int | None,
            "start_time": str | None,
            "last_tick": str | None,
            "tick_count": int,
            "alert_count": int,
            "last_prices": dict,
            "source": str,
            "market_open": bool,
            "market_status": dict
        }
    """
    # 获取底层 runtime status
    runtime_status = get_monitor_runtime_status(
        monitor_status_path,
        monitor_pid_primary_path,
        monitor_pid_legacy_path,
    )
    
    # 获取市场状态
    market_status = get_market_status(trading_hours)
    
    # 合并返回
    return {
        **runtime_status,
        "market_open": market_status["any_open"],
        "market_status": market_status,
    }


def build_calibration_status_payload(
    target_date: str,
    calibration_status_path: Path,
) -> dict[str, Any]:
    """
    构建 /api/calibration/status 的完整响应 payload。
    
    保持与当前 API 完全兼容。
    
    Returns:
        {
            "date": str,
            "done": bool,
            "updated_at": str | None,
            "results": dict,
            "source": str
        }
    """
    return get_calibration_status(target_date, calibration_status_path)
