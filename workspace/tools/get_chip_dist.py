#!/usr/bin/env python3
"""直接调用 calc_chip_dist.py 获取 300548 筹码分布"""

import sys
import os

# 确保 workspace 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入筹码分布计算函数
from calc_chip_dist import calc_chip_distribution
import json

if __name__ == "__main__":
    print("计算 300548.SZ 筹码分布...")

    # 计算筹码分布（回溯 120 天）
    result = calc_chip_distribution("300548.SZ", days=120, daily_turnover=0.02)

    if result:
        print("\n=== 筹码分布 ===")
        print(f"当前价格：{result['current_price']:.2f}")
        print(f"平均成本：{result['avg_cost']:.2f}")
        print(f"获利比例：{result['profit_ratio']*100:.2f}%")
        print(f"90% 成本区间：{result['cost_90_low']:.2f} - {result['cost_90_high']:.2f}")
        print(f"90% 集中度：{result['concentration_90']:.4f}")
        print(f"70% 成本区间：{result['cost_70_low']:.2f} - {result['cost_70_high']:.2f}")
        print(f"70% 集中度：{result['concentration_70']:.4f}")

        print("\n=== JSON 输出 ===")
        print(json.dumps(result, indent=2, default=str))
    else:
        print("计算失败")
