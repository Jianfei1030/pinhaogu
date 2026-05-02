"""Stock screener package."""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from typing import Any

from .cache import SimpleCache
from .conditions import get_registry
from .engine import ScreenEngine
from .sources.sina_quote import SinaQuoteSource
from .sources.sina_sector import SinaSectorSource

_sector_src = SinaSectorSource()
_quote_src = SinaQuoteSource()
_engine = ScreenEngine(_sector_src, _quote_src)


def screen_stocks(conditions: list[dict]) -> list[dict]:
    """
    选股入口函数。

    conditions: [
        {"type": "sector", "sector_code": "new_blhy"},
        {"type": "change_pct", "min": 2, "max": 10},
        {"type": "volume", "min": 10000000},
        {"type": "or", "conditions": [...]},
    ]

    返回: [
        {"code": "603986", "name": "兆易创新", "price": 273.35, "change_pct": 3.2, ...},
        ...
    ]
    """
    return _engine.screen(conditions)


def _field_to_schema(field_obj) -> dict[str, Any]:
    field_type = getattr(field_obj, "type", Any)
    type_name = getattr(field_type, "__name__", str(field_type))
    schema: dict[str, Any] = {
        "type": type_name,
        "required": field_obj.default is MISSING and field_obj.default_factory is MISSING,
    }

    if field_obj.default_factory is not MISSING:
        schema["default_factory"] = getattr(field_obj.default_factory, "__name__", str(field_obj.default_factory))
    elif field_obj.default is not MISSING:
        schema["default"] = field_obj.default

    return schema


def list_conditions() -> list[dict]:
    """返回可用条件类型 + 参数说明"""
    registry = get_registry()
    results: list[dict] = []
    for name, cls in registry.items():
        params: dict[str, Any] = {}
        if is_dataclass(cls):
            for field_obj in fields(cls):
                params[field_obj.name] = _field_to_schema(field_obj)
        results.append({"type": name, "params": params})
    results.append(
        {
            "type": "or",
            "params": {
                "conditions": {
                    "type": "list[condition]",
                    "required": True,
                    "description": "任一子条件满足即通过",
                }
            },
        }
    )
    results.append(
        {
            "type": "and",
            "params": {
                "conditions": {
                    "type": "list[condition]",
                    "required": True,
                    "description": "全部子条件满足才通过",
                }
            },
        }
    )
    return results


def list_sectors() -> list[dict]:
    """返回板块列表"""
    return _sector_src.get_sectors()


__all__ = [
    "SimpleCache",
    "screen_stocks",
    "list_conditions",
    "list_sectors",
    "ScreenEngine",
    "SinaSectorSource",
    "SinaQuoteSource",
]
