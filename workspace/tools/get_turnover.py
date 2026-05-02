#!/usr/bin/env python3
"""获取 300548 换手率 - 使用东方财富接口"""

import sys
import os
import time

# 确保 workspace 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import akshare as ak
import pandas as pd

def get_turnover_rate():
    """获取 300548 的换手率"""
    print("从东方财富获取 300548 换手率...")
    
    try:
        # 方法 1: 获取个股实时行情
        print("\n方法 1: stock_zh_a_spot_em")
        df = ak.stock_zh_a_spot_em()
        stock_data = df[df['代码'] == '300548']
        
        if not stock_data.empty:
            print(stock_data[['代码', '名称', '最新价', '涨跌幅', '成交量', '换手率']].to_string())
            turnover = stock_data['换手率'].values[0]
            print(f"换手率：{turnover}%")
            return turnover
    except Exception as e:
        print(f"方法 1 失败：{e}")
    
    # 方法 2: 获取个股历史行情（包含换手率）
    try:
        print("\n方法 2: stock_zh_a_hist")
        time.sleep(3)  # 限流
        df = ak.stock_zh_a_hist(symbol="300548", period="daily", start_date="20260325", end_date="20260404")
        
        if not df.empty:
            print(df[['日期', '收盘', '成交量', '换手率']].tail(3).to_string())
            last_turnover = df['换手率'].iloc[-1]
            print(f"最新换手率：{last_turnover}%")
            return last_turnover
    except Exception as e:
        print(f"方法 2 失败：{e}")
    
    return None

if __name__ == "__main__":
    get_turnover_rate()
