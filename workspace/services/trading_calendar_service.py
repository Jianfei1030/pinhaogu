#!/usr/bin/env python3
"""
A 股交易日判断服务

基于本地配置文件判断日期是否为交易日。
逻辑：
1. 周六/周日默认非交易日
2. 命中 holidays_2026.yaml 的日期也非交易日
3. 其它日期默认为交易日

不依赖外部 API，纯本地判断。
"""

import os
import sys
import yaml
from datetime import datetime, date
from pathlib import Path
from typing import Optional


# 服务模块所在目录
_SERVICE_DIR = Path(__file__).parent.resolve()
# 节假日配置文件路径 (相对于服务目录的父级 workspace 目录)
_HOLIDAYS_FILE = _SERVICE_DIR.parent / "holidays_2026.yaml"


def _load_holidays() -> set[str]:
    """
    加载节假日配置文件，返回日期字符串集合 (YYYY-MM-DD 格式)
    """
    if not _HOLIDAYS_FILE.exists():
        return set()
    
    with open(_HOLIDAYS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    if not data or "holidays" not in data:
        return set()
    
    return set(data["holidays"])


def is_holiday(date_str: Optional[str] = None) -> bool:
    """
    判断指定日期是否为节假日 (非交易日)
    
    Args:
        date_str: 日期字符串，格式 YYYY-MM-DD。None 表示今天。
    
    Returns:
        bool: True 表示是节假日 (非交易日)，False 表示是交易日
    """
    if date_str is None:
        target_date = date.today()
    else:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    
    # 1. 检查是否为周末 (周六=5, 周日=6)
    if target_date.weekday() >= 5:
        return True
    
    # 2. 检查是否在节假日配置中
    holidays = _load_holidays()
    if target_date.strftime("%Y-%m-%d") in holidays:
        return True
    
    # 3. 其它日期默认为交易日
    return False


def is_trading_day(date_str: Optional[str] = None) -> bool:
    """
    判断指定日期是否为交易日
    
    Args:
        date_str: 日期字符串，格式 YYYY-MM-DD。None 表示今天。
    
    Returns:
        bool: True 表示是交易日，False 表示非交易日
    """
    return not is_holiday(date_str)


def _run_tests():
    """
    内置测试 CLI：python3 trading_calendar_service.py --test
    """
    print("=" * 60)
    print("交易日判断服务 - 测试")
    print("=" * 60)
    print(f"配置文件路径：{_HOLIDAYS_FILE}")
    print(f"配置文件存在：{_HOLIDAYS_FILE.exists()}")
    print()
    
    # 加载节假日列表
    holidays = _load_holidays()
    print(f"已加载 {len(holidays)} 个节假日")
    print()
    
    # 测试用例
    test_dates = [
        "2026-04-06",  # 清明节调休 - 应该是节假日
        "2026-04-07",  # 普通周二 - 应该是交易日
        "2026-04-04",  # 周六 - 应该是节假日
        "2026-04-05",  # 清明节 - 应该是节假日
        "2026-05-01",  # 劳动节 - 应该是节假日
        "2026-05-06",  # 普通周三 - 应该是交易日
        "2026-10-01",  # 国庆节 - 应该是节假日
        "2026-10-09",  # 国庆后第一个工作日 - 应该是交易日
    ]
    
    print("测试结果:")
    print("-" * 60)
    print(f"{'日期':<12} {'星期':<8} {'is_holiday':<12} {'is_trading_day':<15} {'备注'}")
    print("-" * 60)
    
    for date_str in test_dates:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_map[target_date.weekday()]
        
        holiday = is_holiday(date_str)
        trading = is_trading_day(date_str)
        
        # 简单备注
        note = ""
        if date_str == "2026-04-06":
            note = "← 清明调休"
        elif date_str == "2026-04-07":
            note = "← 普通工作日"
        elif target_date.weekday() >= 5:
            note = "← 周末"
        elif holiday:
            note = "← 法定节假日"
        
        print(f"{date_str:<12} {weekday:<8} {str(holiday):<12} {str(trading):<15} {note}")
    
    print("-" * 60)
    print()
    
    # 验收断言
    print("验收检查:")
    print("-" * 60)
    
    # 2026-04-06 应该是节假日 (非交易日)
    april_6_holiday = is_holiday("2026-04-06")
    april_6_not_trading = not is_trading_day("2026-04-06")
    print(f"2026-04-06 是节假日：{april_6_holiday} ✓" if april_6_holiday else f"2026-04-06 是节假日：{april_6_holiday} ✗")
    print(f"2026-04-06 非交易日：{april_6_not_trading} ✓" if april_6_not_trading else f"2026-04-06 非交易日：{april_6_not_trading} ✗")
    
    # 2026-04-07 应该是交易日
    april_7_trading = is_trading_day("2026-04-07")
    april_7_not_holiday = not is_holiday("2026-04-07")
    print(f"2026-04-07 是交易日：{april_7_trading} ✓" if april_7_trading else f"2026-04-07 是交易日：{april_7_trading} ✗")
    print(f"2026-04-07 非节假日：{april_7_not_holiday} ✓" if april_7_not_holiday else f"2026-04-07 非节假日：{april_7_not_holiday} ✗")
    
    print("=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _run_tests()
    else:
        # 默认行为：判断今天
        today = date.today().strftime("%Y-%m-%d")
        print(f"今天 ({today}):")
        print(f"  is_holiday: {is_holiday()}")
        print(f"  is_trading_day: {is_trading_day()}")
