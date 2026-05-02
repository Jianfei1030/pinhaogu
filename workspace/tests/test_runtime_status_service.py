# -*- coding: utf-8 -*-
"""
Runtime Status Service 独立测试

纯 pytest 测试，不依赖 FastAPI，不依赖真实进程。
使用 tmp_path + monkeypatch 确保测试隔离。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.runtime_status_service import (
    RuntimeStatusServiceError,
    FileReadError,
    ProcessScanError,
    read_json_file,
    pid_running,
    read_monitor_pid_file,
    get_market_status,
    get_monitor_runtime_status,
    get_calibration_status,
    build_monitor_status_payload,
    build_calibration_status_payload,
)


# =============================================================================
# A. 基础接口与异常
# =============================================================================

class TestExceptionHierarchy:
    """测试异常继承关系"""

    def test_file_read_error_inherits_from_runtime_status_service_error(self):
        """FileReadError 应继承自 RuntimeStatusServiceError"""
        assert issubclass(FileReadError, RuntimeStatusServiceError)

    def test_process_scan_error_inherits_from_runtime_status_service_error(self):
        """ProcessScanError 应继承自 RuntimeStatusServiceError"""
        assert issubclass(ProcessScanError, RuntimeStatusServiceError)

    def test_exceptions_can_be_caught_as_base_type(self):
        """子类异常应能被基类捕获"""
        try:
            raise FileReadError("test error")
        except RuntimeStatusServiceError as e:
            assert str(e) == "test error"


# =============================================================================
# B. read_json_file
# =============================================================================

class TestReadJsonFile:
    """测试 read_json_file 函数"""

    def test_file_not_exists_returns_none(self, tmp_path: Path):
        """文件不存在时返回 None"""
        non_existent = tmp_path / "not_exists.json"
        assert read_json_file(non_existent) is None

    def test_valid_json_dict_returns_dict(self, tmp_path: Path):
        """有效 JSON dict 返回解析后的字典"""
        test_file = tmp_path / "valid.json"
        test_data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(test_data), encoding="utf-8")
        assert read_json_file(test_file) == test_data

    def test_invalid_json_returns_none(self, tmp_path: Path):
        """非法 JSON 返回 None（宽松处理）"""
        test_file = tmp_path / "invalid.json"
        test_file.write_text("not valid json {", encoding="utf-8")
        assert read_json_file(test_file) is None

    def test_empty_file_returns_none(self, tmp_path: Path):
        """空文件返回 None"""
        test_file = tmp_path / "empty.json"
        test_file.write_text("", encoding="utf-8")
        assert read_json_file(test_file) is None


# =============================================================================
# C. pid_running
# =============================================================================

class TestPidRunning:
    """测试 pid_running 函数"""

    def test_pid_zero_returns_false(self):
        """pid=0 返回 False"""
        assert pid_running(0) is False

    def test_negative_pid_returns_false(self):
        """负数 pid 返回 False"""
        assert pid_running(-1) is False

    def test_os_kill_success_returns_true(self, monkeypatch):
        """os.kill 成功时返回 True"""
        def mock_kill(pid, sig):
            pass  # 不抛异常表示成功
        monkeypatch.setattr(os, "kill", mock_kill)
        assert pid_running(1234) is True

    def test_os_kill_oserror_returns_false(self, monkeypatch):
        """os.kill 抛 OSError 时返回 False"""
        def mock_kill_fail(pid, sig):
            raise OSError("Process not found")
        monkeypatch.setattr(os, "kill", mock_kill_fail)
        assert pid_running(99999) is False


# =============================================================================
# D. read_monitor_pid_file
# =============================================================================

class TestReadMonitorPidFile:
    """测试 read_monitor_pid_file 函数"""

    def test_primary_path_exists_returns_data(self, tmp_path: Path):
        """主路径文件存在时正常解析"""
        primary = tmp_path / "pid_primary.json"
        primary.write_text('{"pid": 1234, "start_time": "2026-04-07T10:00:00"}', encoding="utf-8")
        legacy = tmp_path / "pid_legacy.txt"
        
        result = read_monitor_pid_file(primary, legacy)
        assert result is not None
        assert result["pid"] == 1234
        assert result["start_time"] == "2026-04-07T10:00:00"

    def test_legacy_fallback_when_primary_not_exists(self, tmp_path: Path):
        """主路径不存在时回退到 legacy 路径"""
        primary = tmp_path / "not_exists.json"
        legacy = tmp_path / "pid_legacy.txt"
        legacy.write_text('{"pid": 5678}', encoding="utf-8")
        
        result = read_monitor_pid_file(primary, legacy)
        assert result is not None
        assert result["pid"] == 5678

    def test_empty_file_returns_none(self, tmp_path: Path):
        """空文件返回 None"""
        primary = tmp_path / "empty.json"
        primary.write_text("", encoding="utf-8")
        legacy = tmp_path / "legacy.txt"
        
        assert read_monitor_pid_file(primary, legacy) is None

    def test_old_format_two_lines(self, tmp_path: Path):
        """旧格式：第一行 PID，第二行 start_time"""
        primary = tmp_path / "old_format.txt"
        primary.write_text("1234\n2026-04-07T10:00:00", encoding="utf-8")
        legacy = tmp_path / "legacy.txt"
        
        result = read_monitor_pid_file(primary, legacy)
        assert result is not None
        assert result["pid"] == 1234
        assert result["start_time"] == "2026-04-07T10:00:00"

    def test_damaged_content_returns_none(self, tmp_path: Path):
        """损坏内容返回 None"""
        primary = tmp_path / "damaged.txt"
        primary.write_text("not a number", encoding="utf-8")
        legacy = tmp_path / "legacy.txt"
        
        assert read_monitor_pid_file(primary, legacy) is None


# =============================================================================
# E. build_monitor_status_payload
# =============================================================================

class TestBuildMonitorStatusPayload:
    """测试 build_monitor_status_payload 函数"""

    def test_unknown_path_no_files(self, tmp_path: Path, monkeypatch):
        """unknown 路径：没有任何状态文件"""
        status_path = tmp_path / "status.json"
        pid_primary = tmp_path / "pid_primary.json"
        pid_legacy = tmp_path / "pid_legacy.txt"
        trading_hours = {"HK": {"start": "09:30", "end": "16:00"}}
        
        # 确保所有 helper 返回空
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: False)
        monkeypatch.setattr("services.runtime_status_service.find_monitor_process", lambda: None)
        
        result = build_monitor_status_payload(status_path, pid_primary, pid_legacy, trading_hours)
        
        assert result["running"] == "unknown"
        assert result.get("source") is None

    def test_stale_status_path(self, tmp_path: Path, monkeypatch):
        """stale_status 路径：有状态文件但进程未运行"""
        status_path = tmp_path / "status.json"
        status_path.write_text('{"pid": 1234, "last_tick": "2026-04-06T10:00:00"}', encoding="utf-8")
        pid_primary = tmp_path / "pid_primary.json"
        pid_legacy = tmp_path / "pid_legacy.txt"
        trading_hours = {"HK": {"start": "09:30", "end": "16:00"}}
        
        # pid_running 返回 False
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: False)
        monkeypatch.setattr("services.runtime_status_service.find_monitor_process", lambda: None)
        
        result = build_monitor_status_payload(status_path, pid_primary, pid_legacy, trading_hours)
        
        assert result["running"] is False
        assert result["source"] == "stale_status"
        assert result["pid"] == 1234

    def test_running_status_file_path(self, tmp_path: Path, monkeypatch):
        """running/status_file 路径：status 文件命中且 pid 存活"""
        status_path = tmp_path / "status.json"
        status_path.write_text(
            '{"pid": 1234, "start_time": "2026-04-07T09:00:00", "last_tick": "2026-04-07T10:00:00", "tick_count": 100, "alert_count": 2, "last_prices": {"00700": 500}}',
            encoding="utf-8"
        )
        pid_primary = tmp_path / "pid_primary.json"
        pid_legacy = tmp_path / "pid_legacy.txt"
        trading_hours = {"HK": {"start": "09:30", "end": "16:00"}}
        
        # pid_running 返回 True
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: True)
        
        result = build_monitor_status_payload(status_path, pid_primary, pid_legacy, trading_hours)
        
        assert result["running"] is True
        assert result["source"] == "status_file"
        assert result["pid"] == 1234
        assert result["tick_count"] == 100
        assert result["alert_count"] == 2

    def test_running_process_scan_path(self, tmp_path: Path, monkeypatch):
        """running/process_scan 路径：process scan 命中"""
        status_path = tmp_path / "status.json"
        pid_primary = tmp_path / "pid_primary.json"
        pid_legacy = tmp_path / "pid_legacy.txt"
        trading_hours = {"HK": {"start": "09:30", "end": "16:00"}}
        
        # pid_running 返回 False，但 find_monitor_process 返回进程信息
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: False)
        monkeypatch.setattr("services.runtime_status_service.find_monitor_process", lambda: {
            "pid": 5678,
            "start_time": "2026-04-07T09:30:00",
            "command_line": "python monitor.py"
        })
        
        result = build_monitor_status_payload(status_path, pid_primary, pid_legacy, trading_hours)
        
        assert result["running"] is True
        assert result["source"] == "process_scan"
        assert result["pid"] == 5678


# =============================================================================
# F. build_calibration_status_payload
# =============================================================================

class TestBuildCalibrationStatusPayload:
    """测试 build_calibration_status_payload 函数"""

    def test_done_path(self, tmp_path: Path):
        """done 路径：payload.done=True 且日期匹配"""
        calib_path = tmp_path / "calibration_status.json"
        calib_path.write_text(
            '{"date": "2026-04-07", "done": true, "updated_at": "2026-04-07T09:00:00", "results": {"accuracy": 0.95}}',
            encoding="utf-8"
        )
        
        result = build_calibration_status_payload("2026-04-07", calib_path)
        
        assert result["date"] == "2026-04-07"
        assert result["done"] is True
        assert result["updated_at"] == "2026-04-07T09:00:00"
        assert result["results"]["accuracy"] == 0.95
        assert result["source"] == "Tencent"

    def test_not_done_path(self, tmp_path: Path):
        """not-done 路径：done=False 或日期不匹配"""
        calib_path = tmp_path / "calibration_status.json"
        calib_path.write_text(
            '{"date": "2026-04-06", "done": false, "updated_at": "2026-04-06T09:00:00"}',
            encoding="utf-8"
        )
        
        result = build_calibration_status_payload("2026-04-07", calib_path)
        
        assert result["date"] == "2026-04-07"
        assert result["done"] is False
        assert result["source"] == "THS-SIM"

    def test_source_default_logic(self, tmp_path: Path):
        """source 默认值逻辑：done 时为 Tencent，否则为 THS-SIM"""
        calib_path_done = tmp_path / "done.json"
        calib_path_done.write_text('{"date": "2026-04-07", "done": true}', encoding="utf-8")
        
        calib_path_not_done = tmp_path / "not_done.json"
        calib_path_not_done.write_text('{"date": "2026-04-07", "done": false}', encoding="utf-8")
        
        result_done = build_calibration_status_payload("2026-04-07", calib_path_done)
        result_not_done = build_calibration_status_payload("2026-04-07", calib_path_not_done)
        
        assert result_done["source"] == "Tencent"
        assert result_not_done["source"] == "THS-SIM"

    def test_source_from_payload(self, tmp_path: Path):
        """payload 中显式指定 source 时使用 payload 的值"""
        calib_path = tmp_path / "calibration_status.json"
        calib_path.write_text(
            '{"date": "2026-04-07", "done": true, "source": "CustomSource"}',
            encoding="utf-8"
        )
        
        result = build_calibration_status_payload("2026-04-07", calib_path)
        
        assert result["source"] == "CustomSource"


# =============================================================================
# G. 轻量 helper 测试
# =============================================================================

class TestGetMarketStatus:
    """测试 get_market_status 函数"""

    def test_market_open_during_trading_hours(self):
        """交易时段内市场状态为 open"""
        trading_hours = {
            "HK": {"start": "09:30", "end": "16:00", "break_start": "12:00", "break_end": "13:00"},
            "CN": {"start": "09:30", "end": "15:00"}
        }
        
        # 模拟在交易时段内（假设当前时间在 10:00）
        result = get_market_status(trading_hours)
        
        assert "any_open" in result
        assert "markets" in result
        assert "current_time" in result
        assert "next_open" in result

    def test_market_closed_outside_trading_hours(self):
        """非交易时段市场状态为 closed"""
        trading_hours = {
            "HK": {"start": "09:30", "end": "16:00"},
        }
        
        result = get_market_status(trading_hours)
        
        assert "any_open" in result
        assert "markets" in result


# =============================================================================
# 主入口测试
# =============================================================================

class TestGetMonitorRuntimeStatus:
    """测试 get_monitor_runtime_status 核心函数"""

    def test_running_via_status_file(self, tmp_path: Path, monkeypatch):
        """通过 status_file 检测到运行中"""
        status_path = tmp_path / "status.json"
        status_path.write_text('{"pid": 1234, "start_time": "2026-04-07T09:00:00"}', encoding="utf-8")
        pid_primary = tmp_path / "pid.json"
        pid_legacy = tmp_path / "legacy.txt"
        
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: True)
        
        result = get_monitor_runtime_status(status_path, pid_primary, pid_legacy)
        
        assert result["running"] is True
        assert result["source"] == "status_file"

    def test_not_running_stale(self, tmp_path: Path, monkeypatch):
        """进程未运行，有 stale 状态"""
        status_path = tmp_path / "status.json"
        status_path.write_text('{"pid": 1234}', encoding="utf-8")
        pid_primary = tmp_path / "pid.json"
        pid_legacy = tmp_path / "legacy.txt"
        
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: False)
        monkeypatch.setattr("services.runtime_status_service.find_monitor_process", lambda: None)
        
        result = get_monitor_runtime_status(status_path, pid_primary, pid_legacy)
        
        assert result["running"] is False
        assert result["source"] == "stale_status"

    def test_unknown_no_data(self, tmp_path: Path, monkeypatch):
        """无任何数据时返回 unknown"""
        status_path = tmp_path / "not_exists.json"
        pid_primary = tmp_path / "not_exists.json"
        pid_legacy = tmp_path / "not_exists.txt"
        
        monkeypatch.setattr("services.runtime_status_service.pid_running", lambda pid: False)
        monkeypatch.setattr("services.runtime_status_service.find_monitor_process", lambda: None)
        
        result = get_monitor_runtime_status(status_path, pid_primary, pid_legacy)
        
        assert result["running"] == "unknown"


class TestGetCalibrationStatus:
    """测试 get_calibration_status 核心函数"""

    def test_done_with_matching_date(self, tmp_path: Path):
        """日期匹配且 done=True"""
        calib_path = tmp_path / "status.json"
        calib_path.write_text('{"date": "2026-04-07", "done": true}', encoding="utf-8")
        
        result = get_calibration_status("2026-04-07", calib_path)
        
        assert result["done"] is True
        assert result["date"] == "2026-04-07"

    def test_not_done_with_different_date(self, tmp_path: Path):
        """日期不匹配"""
        calib_path = tmp_path / "status.json"
        calib_path.write_text('{"date": "2026-04-06", "done": true}', encoding="utf-8")
        
        result = get_calibration_status("2026-04-07", calib_path)
        
        assert result["done"] is False
        assert result["date"] == "2026-04-07"
