# -*- coding: utf-8 -*-
"""
Monitor Service - 监控器配置/初始化服务层

将 monitor.py 中的配置加载、路径解析、告警规则构建等初始化逻辑下沉到 service 层。
为 R5 顶层脚本软迁移做准备。

Usage:
    from workspace.services.monitor_service import (
        build_monitor_runtime_config,
        load_monitor_alert_rules,
        load_monitor_trading_hours,
        MonitorServiceError,
    )
    
    runtime_config = build_monitor_runtime_config(
        workspace=Path("/path/to/workspace"),
        config_path="config.yaml",
        interval=30
    )
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class MonitorServiceError(Exception):
    """Monitor Service 业务异常"""
    pass


def resolve_monitor_path(workspace: Path, path: str) -> Path:
    """
    解析监控配置文件路径
    
    Args:
        workspace: 工作目录路径
        path: 配置路径（可以是相对路径或绝对路径）
    
    Returns:
        解析后的绝对路径
    
    Examples:
        >>> resolve_monitor_path(Path("/workspace"), "config.yaml")
        PosixPath('/workspace/config.yaml')
        >>> resolve_monitor_path(Path("/workspace"), "/absolute/config.yaml")
        PosixPath('/absolute/config.yaml')
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return workspace / candidate


def load_monitor_config(path: Path) -> dict[str, Any]:
    """
    加载监控配置文件
    
    Args:
        path: 配置文件路径
    
    Returns:
        配置字典
    
    Raises:
        MonitorServiceError: 文件不存在或解析失败时抛出
    
    Examples:
        >>> config = load_monitor_config(Path("config.yaml"))
        >>> config.get("watchlist", [])
        []
    """
    if not path.exists():
        raise MonitorServiceError(f"配置文件不存在：{path}")
    
    try:
        with path.open("r", encoding="utf-8") as fh:
            content = yaml.safe_load(fh)
            return content if content is not None else {}
    except yaml.YAMLError as e:
        raise MonitorServiceError(f"配置文件解析失败：{e}")
    except Exception as e:
        raise MonitorServiceError(f"读取配置文件失败：{e}")


def load_monitor_alert_rules(config: dict[str, Any]) -> list[Any]:
    """
    从配置中加载告警规则列表
    
    Args:
        config: 配置字典
    
    Returns:
        AlertRule 对象列表（需要 monitor.py 中的 AlertRule 类）
    
    Notes:
        - 延迟导入 AlertRule 避免循环依赖
        - alerts 为空或非法时返回空列表，与当前 Monitor.__init__ 行为一致
    
    Examples:
        >>> rules = load_monitor_alert_rules({"alerts": [...]})
        >>> len(rules)
        3
    """
    # 延迟导入 AlertRule，避免在 service 层初始化时依赖 monitor.py
    from monitor import AlertRule
    
    raw_alerts = config.get("alerts", [])
    
    # 兼容旧版：如果 alerts 是字典而非列表，返回空列表
    if isinstance(raw_alerts, dict):
        return []
    
    # 过滤并构建 AlertRule 对象
    return [
        AlertRule(item) 
        for item in raw_alerts 
        if isinstance(item, dict)
    ]


def load_monitor_trading_hours(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """
    从配置中加载交易时间配置
    
    Args:
        config: 配置字典
    
    Returns:
        交易时间字典，格式：{market: {start, end, break_start, break_end}}
    
    Notes:
        - 默认返回空字典，与当前 Monitor.__init__ 行为一致
        - 自动将市场代码转为大写
    
    Examples:
        >>> hours = load_monitor_trading_hours({"trading_hours": {"SH": {...}}})
        >>> "SH" in hours
        False  # 已转为大写
        >>> "SSE" in hours  # 假设配置中是 SH -> SSE
        True
    """
    trading_hours = config.get("trading_hours", {})
    
    # 兼容旧版：如果 trading_hours 不是字典，返回空字典
    if not isinstance(trading_hours, dict):
        return {}
    
    # 标准化：市场代码转大写，值必须是字典
    return {
        str(market).upper(): value 
        for market, value in trading_hours.items() 
        if isinstance(value, dict)
    }


def build_monitor_runtime_config(
    workspace: Path,
    config_path: str,
    interval: int | None = None,
) -> dict[str, Any]:
    """
    构建监控器运行时配置（结构化入口）
    
    整合 Monitor.__init__ 中的配置加载逻辑，返回一个完整的运行时配置字典。
    
    Args:
        workspace: 工作目录路径
        config_path: 配置文件路径（相对或绝对）
        interval: 刷新间隔（可选，优先于配置文件的 refresh_interval）
    
    Returns:
        运行时配置字典，包含：
        - workspace: Path - 工作目录
        - config_path: Path - 解析后的配置文件路径
        - config: dict - 完整配置字典
        - watchlist: list - 监控股票列表
        - interval: int - 刷新间隔（秒）
        - alert_rules: list[AlertRule] - 告警规则列表
        - trading_hours: dict - 交易时间配置
    
    Raises:
        MonitorServiceError: 配置加载失败时抛出
    
    Notes:
        - refresh_interval 的回退逻辑与当前 Monitor.__init__ 保持一致：
          interval 参数 > config.refresh_interval > 默认值 30
        - alerts 为空或非法时，alert_rules 为空列表
        - trading_hours 默认值为空字典
    
    Examples:
        >>> runtime_config = build_monitor_runtime_config(
        ...     workspace=Path("/workspace"),
        ...     config_path="config.yaml",
        ...     interval=60
        ... )
        >>> runtime_config["workspace"]
        PosixPath('/workspace')
        >>> runtime_config["interval"]
        60
    """
    # 1. 解析配置文件路径
    resolved_config_path = resolve_monitor_path(workspace, config_path)
    
    # 2. 加载配置
    config = load_monitor_config(resolved_config_path)
    
    # 3. 提取 watchlist
    watchlist = config.get("watchlist", [])
    if not isinstance(watchlist, list):
        watchlist = []
    
    # 4. 计算刷新间隔（保持与 Monitor.__init__ 一致的回退逻辑）
    # interval 参数 > config.refresh_interval > 默认值 30
    config_interval = config.get("refresh_interval", 30)
    if config_interval is None:
        config_interval = 30
    final_interval = int(interval or config_interval or 30)
    
    # 5. 加载告警规则
    alert_rules = load_monitor_alert_rules(config)
    
    # 6. 加载交易时间
    trading_hours = load_monitor_trading_hours(config)
    
    return {
        "workspace": workspace,
        "config_path": resolved_config_path,
        "config": config,
        "watchlist": watchlist,
        "interval": final_interval,
        "alert_rules": alert_rules,
        "trading_hours": trading_hours,
    }
