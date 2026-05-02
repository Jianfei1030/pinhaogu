#!/usr/bin/env python3
"""测试节假日判断是否正常工作"""
import sys
sys.path.insert(0, '.')

from utils.trading_calendar import is_trading_day

# 测试清明节 (2026-04-06)
date_holiday = "2026-04-06"
# 测试普通工作日 (2026-04-07)
date_workday = "2026-04-07"

print(f"{date_holiday} 是交易日：{is_trading_day(date_holiday)} (期望：False)")
print(f"{date_workday} 是交易日：{is_trading_day(date_workday)} (期望：True)")

if not is_trading_day(date_holiday) and is_trading_day(date_workday):
    print("\n✅ 节假日判断测试通过")
    sys.exit(0)
else:
    print("\n❌ 节假日判断测试失败")
    sys.exit(1)
