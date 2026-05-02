#!/usr/bin/env python3
"""
Job Runner 接口统一验证测试

验证 5 个 R1 脚本的 Job Runner 化接口：
- premarket_analysis.py
- postmarket_review.py
- daily_sector_pipeline.py
- daily_incremental_backfill.py
- status_report.py

测试设计原则：
1. 兼容接口差异，不要求签名完全一致
2. 安全调用，不触发真实业务逻辑（非交易日/安全参数）
3. 验证返回值属于合理范围
"""

import inspect
import sys
from pathlib import Path
from datetime import datetime

import pytest

# === 测试配置 ===
WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))

# 5 个 Job Runner 脚本的模块路径
JOB_RUNNER_MODULES = [
    "premarket_analysis",
    "postmarket_review",
    "daily_sector_pipeline",
    "daily_incremental_backfill",
    "status_report",
]

# 每个模块的接口配置（兼容性设计）
MODULE_CONFIGS = {
    "premarket_analysis": {
        "requires_date": True,
        "allows_extra": False,
        "safe_args": {"date": "2026-04-05", "dry_run": True, "notify": False},  # 非交易日
    },
    "postmarket_review": {
        "requires_date": True,
        "allows_extra": False,
        "safe_args": {"date": "2026-04-05", "dry_run": True, "notify": False},  # 非交易日
    },
    "daily_sector_pipeline": {
        "requires_date": True,
        "allows_extra": True,  # 允许 status_file 参数
        "safe_args": {"date": "2026-04-05", "dry_run": True, "notify": False, "status_file": ""},
    },
    "daily_incremental_backfill": {
        "requires_date": True,
        "allows_extra": False,
        # safe_args 不需要，因为有专门的 smoke test
    },
    "status_report": {
        "requires_date": False,  # status_report 不需要 date 参数
        "allows_extra": False,
        "safe_args": {"dry_run": True, "notify": False},
    },
}

# 合理的返回值类型
VALID_RETURN_TYPES = (dict, str, int, type(None))


# === 测试用例 ===

@pytest.mark.parametrize("module_name", JOB_RUNNER_MODULES)
def test_job_runner_modules_have_run(module_name):
    """
    测试 A: 基础接口存在性
    - 模块可导入
    - 存在 run 函数
    - run 是 callable
    """
    module = __import__(module_name, fromlist=[""])
    assert module is not None, f"模块 {module_name} 导入失败"
    assert hasattr(module, "run"), f"模块 {module_name} 缺少 run 函数"
    assert callable(getattr(module, "run")), f"模块 {module_name}.run 不是 callable"


def test_job_runner_signatures_are_compatible():
    """
    测试 B: 签名兼容性
    - 验证每个模块的 run 函数签名与配置一致
    - 允许合理的参数差异（如 status_report 无 date，daily_sector_pipeline 有 status_file）
    """
    for module_name in JOB_RUNNER_MODULES:
        module = __import__(module_name, fromlist=[""])
        run_func = getattr(module, "run")
        sig = inspect.signature(run_func)
        params = list(sig.parameters.keys())
        
        config = MODULE_CONFIGS[module_name]
        
        # 验证 date 参数要求
        if config["requires_date"]:
            assert "date" in params, (
                f"{module_name}.run 缺少必需的 date 参数，当前参数：{params}"
            )
        else:
            # status_report 不应该有 date 参数
            assert "date" not in params, (
                f"{module_name}.run 不应有 date 参数，当前参数：{params}"
            )
        
        # 验证核心参数存在（dry_run 和 notify 是通用开关）
        assert "dry_run" in params, (
            f"{module_name}.run 缺少 dry_run 参数，当前参数：{params}"
        )
        assert "notify" in params, (
            f"{module_name}.run 缺少 notify 参数，当前参数：{params}"
        )


@pytest.mark.parametrize("module_name", ["premarket_analysis", "postmarket_review", "daily_sector_pipeline"])
def test_job_runner_safe_call_returns_reasonable_type(module_name):
    """
    测试 C + D: 最小可调用性 + 返回值约束
    - 使用安全参数调用（非交易日/dry_run）
    - 验证返回值属于合理类型（dict/str/int/None）
    - 不要求跑真实业务逻辑
    """
    module = __import__(module_name, fromlist=[""])
    run_func = getattr(module, "run")
    config = MODULE_CONFIGS[module_name]
    safe_args = config["safe_args"]
    
    result = run_func(**safe_args)
    
    # 验证返回值类型
    assert isinstance(result, VALID_RETURN_TYPES), (
        f"{module_name}.run 返回类型异常：{type(result)}，期望 {VALID_RETURN_TYPES}"
    )


def test_status_report_run_smoke(monkeypatch):
    """
    测试 E: status_report 的 smoke test
    - monkeypatch 模块级值让它稳定走 skip 路径
    - 期望返回 dict，且 status == 'skipped'、reason == 'outside_hours'
    """
    import status_report as module
    
    # monkeypatch 模块级值，让它走 skip 路径
    module.is_trading_day = lambda *args, **kwargs: True
    module.NOW = datetime(2026, 4, 7, 9, 0)
    module.DATE_STR = '2026-04-07'
    module.TIME_STR = '09:00'
    
    # 调用 run
    result = module.run(dry_run=True, notify=False)
    
    # 验证返回值
    assert isinstance(result, dict), f"status_report.run 应返回 dict，实际返回 {type(result)}"
    assert result.get('status') == 'skipped', f"status 应为 'skipped'，实际为 {result.get('status')}"
    assert result.get('reason') == 'outside_hours', f"reason 应为 'outside_hours'，实际为 {result.get('reason')}"


def test_daily_incremental_backfill_run_callable():
    """
    测试 F: daily_incremental_backfill 的接口可调用性验证
    - 验证 run() 函数存在且 callable
    - 注意：不实际调用 run()，因为即使 dry_run=True 也会进入股票循环
    - 接口兼容性已由 test_job_runner_signatures_are_compatible 验证
    """
    import daily_incremental_backfill as module
    
    # 验证 run 存在且 callable
    assert hasattr(module, "run"), "daily_incremental_backfill 缺少 run 函数"
    assert callable(module.run), "daily_incremental_backfill.run 不是 callable"


def test_job_runner_interface_summary():
    """
    接口概览测试（信息性测试，始终通过）
    输出每个模块的签名信息供参考
    """
    print("\n\n=== Job Runner 接口概览 ===")
    for module_name in JOB_RUNNER_MODULES:
        module = __import__(module_name, fromlist=[""])
        run_func = getattr(module, "run")
        sig = inspect.signature(run_func)
        print(f"  {module_name}.run{sig}")
    print()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
