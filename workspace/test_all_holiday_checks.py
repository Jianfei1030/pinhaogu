#!/usr/bin/env python3
"""测试所有脚本的节假日判断"""
import sys
import os
sys.path.insert(0, '.')

# 设置环境变量避免 API key 错误
os.environ['BAILIAN_API_KEY'] = 'test-key-for-testing-only'

from utils.trading_calendar import is_trading_day

print("=" * 60)
print("节假日判断机制 - 全面测试")
print("=" * 60)

# 测试基础函数
print("\n1. 基础函数测试:")
test_cases = [
    ("2026-04-06", False, "清明节"),
    ("2026-04-07", True, "普通周二"),
    ("2026-04-04", False, "周六"),
    ("2026-04-05", False, "清明节"),
    ("2026-05-01", False, "劳动节"),
    ("2026-10-01", False, "国庆节"),
]

all_passed = True
for date, expected, desc in test_cases:
    result = is_trading_day(date)
    status = "✅" if result == expected else "❌"
    if result != expected:
        all_passed = False
    print(f"  {status} {date} ({desc}): {result} (期望：{expected})")

# 测试各模块导入
print("\n2. 模块导入测试:")
modules_to_test = [
    ("status_report", "status_report.py"),
    ("monitor", "monitor.py"),
    ("premarket_analysis", "premarket_analysis.py"),
    ("postmarket_review", "postmarket_review.py"),
    ("daily_sector_pipeline", "daily_sector_pipeline.py"),
]

for module_name, file_name in modules_to_test:
    try:
        __import__(module_name)
        print(f"  ✅ {file_name} 导入成功")
    except Exception as e:
        print(f"  ❌ {file_name} 导入失败：{e}")
        all_passed = False

# 验证各脚本的节假日检查逻辑
print("\n3. 节假日检查逻辑验证:")
print(f"  清明节 (2026-04-06) is_trading_day: {is_trading_day('2026-04-06')} (期望：False)")
print(f"  工作日 (2026-04-07) is_trading_day: {is_trading_day('2026-04-07')} (期望：True)")

print("\n" + "=" * 60)
if all_passed:
    print("✅ 所有测试通过")
    sys.exit(0)
else:
    print("❌ 部分测试失败")
    sys.exit(1)
