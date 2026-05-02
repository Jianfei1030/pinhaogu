# workspace/services package
# Service layer for pinhaogu workspace

from .runtime_state_service import is_dry_run, is_notify_enabled, get_runtime_flags
from .news_service import (
    get_news_status,
    get_recent_news,
    resolve_news_file,
    normalize_news_date,
    is_news_collector_running,
    load_news_items,
    NewsServiceError,
    NewsFileError,
)
from .monitor_service import (
    build_monitor_runtime_config,
    load_monitor_alert_rules,
    load_monitor_trading_hours,
    load_monitor_config,
    resolve_monitor_path,
    MonitorServiceError,
)
from .stock_lookup_service import (
    lookup_a_stock_code_by_name,
    lookup_multiple_stocks,
    get_cache_stats,
    clear_cache,
    preload_cache,
    StockLookupError,
    DataFileNotFoundError,
)

__all__ = [
    # Runtime state
    "is_dry_run",
    "is_notify_enabled",
    "get_runtime_flags",
    # News service
    "get_news_status",
    "get_recent_news",
    "resolve_news_file",
    "normalize_news_date",
    "is_news_collector_running",
    "load_news_items",
    "NewsServiceError",
    "NewsFileError",
    # Monitor service
    "build_monitor_runtime_config",
    "load_monitor_alert_rules",
    "load_monitor_trading_hours",
    "load_monitor_config",
    "resolve_monitor_path",
    "MonitorServiceError",
    # Stock lookup service
    "lookup_a_stock_code_by_name",
    "lookup_multiple_stocks",
    "get_cache_stats",
    "clear_cache",
    "preload_cache",
    "StockLookupError",
    "DataFileNotFoundError",
]
