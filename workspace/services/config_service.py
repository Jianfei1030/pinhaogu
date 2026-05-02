# -*- coding: utf-8 -*-
"""
Config Service for Stock Monitor

This module provides configuration loading and enrichment functionality
for the /api/config endpoint.

Style: Lightweight functional module (not class-based).
"""
from __future__ import annotations

from typing import Any, Callable


# =============================================================================
# Business Exceptions
# =============================================================================


class ConfigServiceError(Exception):
    """Base exception for config operations."""
    pass


# =============================================================================
# Helper Functions
# =============================================================================


def get_analysis_model(default: str = "unknown") -> str:
    """
    Get the LLM analysis model from daily_sector_pipeline.
    
    Attempts to import LLM_MODEL from daily_sector_pipeline module.
    Returns the default value if import fails for any reason.
    
    Args:
        default: Default model string to return if import fails
        
    Returns:
        LLM_MODEL string if import succeeds, otherwise default value
    """
    try:
        from daily_sector_pipeline import LLM_MODEL
        return str(LLM_MODEL)
    except ImportError:
        return default
    except Exception:
        # Catch any other unexpected errors (e.g., module exists but LLM_MODEL doesn't)
        return default


# =============================================================================
# Main Entry Points
# =============================================================================


def build_config_payload(config_loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """
    Build the complete config payload for /api/config endpoint.
    
    This function encapsulates the core logic of the /api/config route:
    1. Load base config via the provided loader
    2. Enrich with analysisModel from daily_sector_pipeline
    3. Return the complete config dict
    
    Args:
        config_loader: Callable that returns the base config dict.
                       Typically load_config() from config.py.
                       
    Returns:
        Complete config dict with analysisModel field populated.
        
    Note:
        This function does not raise exceptions. If config loading fails,
        the error will propagate from config_loader. If analysisModel
        enrichment fails, it defaults to "unknown".
    """
    # Load base configuration
    cfg = config_loader()
    
    # Enrich with analysis model
    cfg["analysisModel"] = get_analysis_model(default="unknown")
    
    return cfg
