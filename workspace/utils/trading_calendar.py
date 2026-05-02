#!/usr/bin/env python3
"""
A 股交易日判断工具模块 - 兼容层

⚠️ 注意：本模块是兼容 wrapper，核心实现在 services/trading_calendar_service.py

基于本地配置文件判断日期是否为交易日。
逻辑：
1. 周六/周日默认非交易日
2. 命中 holidays_2026.yaml 的日期也非交易日
3. 其它日期默认为交易日

不依赖外部 API，纯本地判断。
"""

# 兼容层：从 service 层重新导出核心函数
from services.trading_calendar_service import is_holiday, is_trading_day

# 保留 CLI 测试能力（直接调用 service 层的测试函数）
from services.trading_calendar_service import _run_tests


if __name__ == "__main__":
    import sys
    from datetime import date
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _run_tests()
    else:
        # 默认行为：判断今天
        today = date.today().strftime("%Y-%m-%d")
        print(f"今天 ({today}):")
        print(f"  is_holiday: {is_holiday()}")
        print(f"  is_trading_day: {is_trading_day()}")
