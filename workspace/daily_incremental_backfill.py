#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股每日增量数据补全脚本（Phase 30 优化版 - 并行处理）
- 历史 K 线从本地 DB 读取
- 每只股票只从数据源获取当日 1 条 K 线
- 本地拼接历史 + 今日后计算 MACD 和筹码分布
- 推送 Telegram + QQ
- Phase 30: 使用进程池并行处理，默认 4 workers

Job Runner 形态：
- run() 为可复用入口，支持 API/测试调用
- main() 为薄入口，仅负责 CLI 参数解析
"""

import json
import sys
import time
import logging
import argparse
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

from data_source import fetch_a_daily
from database import get_db_path, query_kline, upsert_kline, init_db, list_db_dates
from config import config, get_config
from utils.logger import setup_logger
from utils.push import send_telegram, send_qq, send_both

# ===== 配置 =====
A_STOCK_LIST = config.data.a_stock_list_path
WORKSPACE = config.data.workspace

# ===== 限流配置（Phase 30 优化） =====
# 优先级：env > config.yaml > 代码默认值
BACKFILL_SLEEP_PER_STOCK = get_config('backfill.sleep_per_stock', 2.0)  # 每只股票后延迟（秒），默认 2s
BACKFILL_SLEEP_PER_100 = get_config('backfill.sleep_per_100', 60.0)    # 每 100 只后延迟（秒），默认 60s
BACKFILL_ENABLED = get_config('backfill.enabled', True)                 # 是否启用 backfill
BACKFILL_WORKERS = get_config('backfill.workers', 4)                    # 并行 workers 数量，默认 4

# ===== 日志 =====
logger = setup_logger("daily_backfill")


def collect_market_cap_stats(today: str) -> dict:
    """从当日 DB 文件中收集市值统计数据。"""
    import glob
    import sqlite3
    
    pattern = f"{WORKSPACE}/data/A/A*/{today}.db"
    if '-' in today:
        pattern = f"{WORKSPACE}/data/A/A*/{today}.db"
    else:
        pattern = f"{WORKSPACE}/data/A/A*/{today}.db"
    
    dbs = glob.glob(pattern)
    if not dbs:
        # 尝试日期格式变体
        if '-' in today:
            alt = today.replace('-', '')
        else:
            alt = f"{today[:4]}-{today[4:6]}-{today[6:]}"
        pattern = f"{WORKSPACE}/data/A/A*/{alt}.db"
        dbs = glob.glob(pattern)
    
    total_mv_list = []
    circ_mv_list = []
    
    for db_path in dbs:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT total_mv, circ_mv FROM kline_1d ORDER BY bar_time DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                if row[0]:
                    total_mv_list.append(row[0])
                if row[1]:
                    circ_mv_list.append(row[1])
        except Exception:
            pass
    
    stats = {
        'total_count': len(total_mv_list),
        'circ_count': len(circ_mv_list),
    }
    
    if total_mv_list:
        # 总市值分段统计
        mega = sum(1 for v in total_mv_list if v >= 1000)    # >= 1000 亿
        large = sum(1 for v in total_mv_list if 200 <= v < 1000)   # 200-1000 亿
        mid = sum(1 for v in total_mv_list if 50 <= v < 200)       # 50-200 亿
        small = sum(1 for v in total_mv_list if v < 50)            # < 50 亿
        stats['total_segments'] = {'≥1000亿': mega, '200-1000亿': large, '50-200亿': mid, '<50亿': small}
        stats['total_mv_avg'] = sum(total_mv_list) / len(total_mv_list)
        stats['total_mv_median'] = sorted(total_mv_list)[len(total_mv_list) // 2]
    
    if circ_mv_list:
        stats['circ_mv_avg'] = sum(circ_mv_list) / len(circ_mv_list)
    
    return stats


def generate_report(today: str, start_time: datetime, end_time: datetime,
                    processed: int, skipped: int, failed: int,
                    failed_symbols: list, pass_stats: list | None = None,
                    market_cap_stats: dict | None = None) -> str:
    """生成推送报告"""
    total = processed + skipped + failed
    success_count = processed + skipped  # 已处理 + 已跳过 = 写入成功
    success_rate = (success_count / total * 100) if total > 0 else 0
    
    report = f"📊 A 股每日数据补全完成\n\n"
    report += f"执行时间：{start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')}\n"
    report += f"处理股票：{total:,} 只\n"
    
    # 如果有 pass_stats，显示重试过程
    if pass_stats:
        report += "\n🔄 重试过程：\n"
        for ps in pass_stats:
            p_num = ps['pass']
            p_ok = ps['processed'] + ps['skipped']
            p_fail = ps['failed']
            if p_num == 1:
                report += f"  第1轮：成功 {p_ok:,} / 失败 {p_fail:,}\n"
            elif p_num == 2:
                report += f"  第2轮：成功 {p_ok:,} / 剩余 {p_fail:,}\n"
            elif p_num == 3:
                report += f"  第3轮：成功 {p_ok:,} / 最终失败 {p_fail:,}\n"
            else:
                report += f"  第{p_num}轮：成功 {p_ok:,} / 失败 {p_fail:,}\n"
    
    report += f"\n✅ 成功：{success_count:,} 只 ({success_rate:.1f}%)\n"
    report += f"❌ 失败：{failed:,} 只\n"
    
    if failed_symbols:
        report += "\n失败列表：\n"
        for symbol, reason in failed_symbols[:20]:  # 最多显示 20 个
            report += f"- {symbol} ({reason})\n"
        if len(failed_symbols) > 20:
            report += f"... 还有 {len(failed_symbols) - 20} 个失败\n"
    
    # 市值分布统计
    if market_cap_stats and market_cap_stats.get('total_segments'):
        seg = market_cap_stats['total_segments']
        total_count = market_cap_stats['total_count']
        avg_mv = market_cap_stats.get('total_mv_avg', 0)
        report += f"\n💰 市值分布（{total_count:,} 只）：\n"
        report += f"  ≥1000 亿：{seg.get('≥1000亿', 0)} 只\n"
        report += f"  200-1000 亿：{seg.get('200-1000亿', 0)} 只\n"
        report += f"  50-200 亿：{seg.get('50-200亿', 0)} 只\n"
        report += f"  <50 亿：{seg.get('<50亿', 0)} 只\n"
        if avg_mv:
            report += f"  平均总市值：{avg_mv:.0f} 亿\n"
    
    report += f"\n数据库路径：{WORKSPACE}/data/A/\n"
    report += "\n✅ 所有数据包含：\n"
    report += "- 当日 K 线（1 条）\n"
    report += "- MACD 指标（DIF/DEA/MACD 柱）\n"
    report += "- 筹码分布（获利比例/平均成本/集中度）\n"
    report += "- 总市值 / 流通市值（亿元）\n"
    
    return report


def send_push(message: str):
    """推送到 Telegram 和 QQ"""
    logger.info("开始推送报告...")
    tg_ok, qq_ok = send_both(message)
    if tg_ok:
        logger.info("Telegram 推送成功")
    else:
        logger.error("Telegram 推送失败")
    if qq_ok:
        logger.info("QQ 推送成功")
    else:
        logger.error("QQ 推送失败")
    return tg_ok, qq_ok


def fetch_today_kline(symbol: str, today: str) -> dict | None:
    """
    仅从数据源获取当日 1 条最新 K 线数据（不含指标）
    
    Args:
        symbol: 股票代码
        today: 日期字符串 YYYY-MM-DD
        
    Returns:
        当日 K 线数据字典，或 None 如果获取失败
    """
    try:
        # 获取最近几条数据，然后筛选出当日的
        records = fetch_a_daily(symbol, count=5, with_indicators=False)
        if not records:
            return None
        
        # 找到当日的数据
        for record in records:
            if record.get('bar_time') == today:
                return record
        
        # 如果没有找到当日数据，返回最新一条（可能是当日）
        latest = records[-1]
        if latest.get('bar_time') == today:
            return latest
        
        return None
    except Exception as e:
        logger.warning(f"获取 {symbol} 当日数据失败：{e}")
        return None


def load_historical_klines_from_db(symbol: str, today: str, min_days: int = 120) -> list[dict]:
    """
    从本地 DB 加载历史 K 线数据（不含今日）
    
    Args:
        symbol: 股票代码
        today: 今日日期 YYYY-MM-DD（排除）
        min_days: 最少需要的历史天数
        
    Returns:
        历史 K 线数据列表
    """
    try:
        dates = list_db_dates("A", symbol)
        if not dates:
            return []
        
        # 排除今日，获取历史日期
        historical_dates = [d for d in dates if d != today]
        
        if not historical_dates:
            return []
        
        # 从多个日期的数据库读取历史数据
        all_history = []
        for date in historical_dates:
            db_path = get_db_path("A", symbol, date)
            if Path(db_path).exists():
                try:
                    rows = query_kline(db_path, "kline_1d")
                    all_history.extend(rows)
                except Exception as e:
                    logger.debug(f"读取 {symbol} {date} 历史数据失败：{e}")
                    continue
        
        # 按时间排序并去重
        all_history.sort(key=lambda x: x.get('bar_time', ''))
        
        # 去重（同一时间点只保留一条）
        seen_times = set()
        unique_history = []
        for row in all_history:
            bar_time = row.get('bar_time')
            if bar_time and bar_time not in seen_times:
                seen_times.add(bar_time)
                unique_history.append(row)
        
        return unique_history
        
    except Exception as e:
        logger.warning(f"从 DB 加载 {symbol} 历史数据失败：{e}")
        return []


def calculate_macd_and_chip(historical_klines: list[dict], today_kline: dict) -> dict:
    """
    拼接历史 + 今日数据，计算 MACD 和筹码分布
    
    Args:
        historical_klines: 历史 K 线数据列表
        today_kline: 当日 K 线数据
        
    Returns:
        包含 MACD 和筹码指标的当日数据
    """
    import pandas as pd
    from indicators.macd import MACD
    from calc_chip_dist import calc_chip_distribution
    
    # 拼接历史 + 今日
    all_klines = historical_klines + [today_kline]
    
    # 确保数据足够计算 MACD
    if len(all_klines) < 26:
        # 数据不足，返回原始数据（不计算指标）
        return today_kline
    
    # 转换为 DataFrame 计算 MACD
    df = pd.DataFrame(all_klines)
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 计算 MACD
    macd = MACD()
    macd_result = macd.calc(df)
    
    # 获取最后一条（今日）的 MACD 值
    today_idx = len(all_klines) - 1
    if today_idx < len(macd_result):
        macd_row = macd_result.iloc[today_idx]
        today_kline['dif'] = round(float(macd_row.get('macd', 0)), 4)
        today_kline['dea'] = round(float(macd_row.get('macd_dea', 0)), 4)
        today_kline['macd_hist'] = round(float(macd_row.get('macd_hist', 0)), 4)
    
    # 计算筹码分布（基于全部历史 + 今日数据）
    chip_result = calc_chip_distribution(kline_data=all_klines, use_real_turnover=True)
    if chip_result:
        today_kline['profit_ratio'] = round(chip_result.get('profit_ratio', 0), 4)
        today_kline['avg_cost'] = round(chip_result.get('avg_cost', 0), 2)
        today_kline['concentration_90'] = round(chip_result.get('concentration_90', 0), 4)
        today_kline['cost_90_low'] = round(chip_result.get('cost_90_low', 0), 2)
        today_kline['cost_90_high'] = round(chip_result.get('cost_90_high', 0), 2)
    
    return today_kline


def _is_bse_stock(symbol: str) -> bool:
    """判断是否为北交所股票（920xxx / 8xxxxx / 4xxxxx）。"""
    # 去掉交易所前缀 sh/sz/bj（大小写不敏感），再去掉前导 0
    pure = symbol.lstrip('shszbjSHSZBJ').lstrip('0')
    return pure.startswith('920') or pure.startswith('8') or pure.startswith('4')


def _fetch_market_cap_from_tencent(symbol: str) -> tuple[float | None, float | None]:
    """从腾讯实时行情接口获取总市值和流通市值（单位：亿元）。
    
    Args:
        symbol: 股票代码（如 '000001', 'sz000001'）
    
    Returns:
        (total_mv, circ_mv) 单位亿元，获取失败返回 (None, None)
    """
    try:
        # 规范化 symbol
        pure = symbol.lstrip('shszbjSHSZBJ')
        if pure.startswith(('6', '9')):
            tx_symbol = f'sh{pure}'
        else:
            tx_symbol = f'sz{pure}'
        
        url = f'https://qt.gtimg.cn/q={tx_symbol}'
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None, None
        
        fields = resp.text.split('~')
        if len(fields) < 46:
            return None, None
        
        # [44] = 总市值（亿元），[45] = 流通市值（亿元）
        total_mv = float(fields[44]) if fields[44] else None
        circ_mv = float(fields[45]) if fields[45] else None
        return total_mv, circ_mv
    except Exception:
        return None, None


def _fetch_today_with_fallback(symbol: str, date: str, count: int = 5) -> list | None:
    """获取当日 K 线数据，带 fallback 重试。

    逻辑：
    1st: fetch_a_daily(symbol, count) — 新浪源
         ├─ 成功 → 返回结果
         └─ 失败 →
              ├─ 北交所（920xxx/8xxxxx/4xxxxx）→ 再试新浪
              └─ A股（sh/sz）→ 试腾讯 _fetch_a_kline_tencent
                   ├─ 成功 → 返回结果
                   └─ 失败 → 返回 None
    """
    from data_source import fetch_a_daily
    from data_sources.tencent import _fetch_a_kline_tencent

    # 1st: 新浪源
    records = fetch_a_daily(symbol, count=count, with_indicators=False)
    if records:
        return records

    # 失败后 fallback
    if _is_bse_stock(symbol):
        # 北交所：再试一次新浪（有时网络波动）
        records = fetch_a_daily(symbol, count=count, with_indicators=False)
        return records if records else None

    # A股：尝试腾讯源
    try:
        records = _fetch_a_kline_tencent(symbol, date, date, count)
        if records:
            return records
    except Exception:
        pass

    return None


# ===== Phase 30: 并行处理辅助函数 =====
def _process_single_symbol(args: tuple) -> dict:
    """
    处理单只股票的顶层函数（用于进程池）
    
    必须在模块顶层定义，确保可以被 pickle 序列化。
    返回结果字典，包含处理状态和结果。
    
    Args:
        args: (symbol, date, sleep_per_stock)
        
    Returns:
        dict: {
            'symbol': str,
            'status': 'processed' | 'skipped' | 'failed',
            'error': str or None,
            'data': dict or None  # 处理成功时的 K 线数据
        }
    """
    symbol, date, sleep_per_stock = args
    
    # 延迟导入，避免序列化问题
    from pathlib import Path
    from data_source import fetch_a_daily
    from database import get_db_path, query_kline, upsert_kline, list_db_dates
    import pandas as pd
    from indicators.macd import MACD
    from calc_chip_dist import calc_chip_distribution
    
    # 简单的进程内日志（打印到 stderr）
    def log(msg: str):
        print(f"[{symbol}] {msg}", file=sys.stderr, flush=True)
    
    db_path = get_db_path("A", symbol, date)
    
    # 检查当日数据是否已存在（幂等性）
    if Path(db_path).exists():
        try:
            existing = query_kline(db_path, "kline_1d", start=date, end=date)
            if existing:
                return {'symbol': symbol, 'status': 'skipped', 'error': None, 'data': None}
        except Exception:
            pass  # 继续尝试获取数据
    
    try:
        # 1. 从本地 DB 加载历史 K 线
        dates = list_db_dates("A", symbol)
        historical_dates = [d for d in dates if d != date] if dates else []
        
        all_history = []
        for hist_date in historical_dates:
            hist_db_path = get_db_path("A", symbol, hist_date)
            if Path(hist_db_path).exists():
                try:
                    rows = query_kline(hist_db_path, "kline_1d")
                    all_history.extend(rows)
                except Exception:
                    continue
        
        # 排序并去重
        all_history.sort(key=lambda x: x.get('bar_time', ''))
        seen_times = set()
        historical = []
        for row in all_history:
            bar_time = row.get('bar_time')
            if bar_time and bar_time not in seen_times:
                seen_times.add(bar_time)
                historical.append(row)
        
        # 2. 仅从数据源获取当日 1 条 K 线（带 fallback）
        records = _fetch_today_with_fallback(symbol, date, count=5)
        if not records:
            return {'symbol': symbol, 'status': 'failed', 'error': '数据源返回空数据', 'data': None}
        
        today_kline = None
        for record in records:
            if record.get('bar_time') == date:
                today_kline = record
                break
        
        if not today_kline:
            latest = records[-1]
            if latest.get('bar_time') == date:
                today_kline = latest
        
        if not today_kline:
            return {'symbol': symbol, 'status': 'failed', 'error': '当日数据不存在', 'data': None}
        
        # 3. 拼接历史 + 今日，计算 MACD 和筹码
        if len(historical) >= 120:
            all_klines = historical + [today_kline]
            
            if len(all_klines) >= 26:
                df = pd.DataFrame(all_klines)
                for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                macd = MACD()
                macd_result = macd.calc(df)
                today_idx = len(all_klines) - 1
                if today_idx < len(macd_result):
                    macd_row = macd_result.iloc[today_idx]
                    today_kline['dif'] = round(float(macd_row.get('macd', 0)), 4)
                    today_kline['dea'] = round(float(macd_row.get('macd_dea', 0)), 4)
                    today_kline['macd_hist'] = round(float(macd_row.get('macd_hist', 0)), 4)
                
                chip_result = calc_chip_distribution(kline_data=all_klines, use_real_turnover=True)
                if chip_result:
                    today_kline['profit_ratio'] = round(chip_result.get('profit_ratio', 0), 4)
                    today_kline['avg_cost'] = round(chip_result.get('avg_cost', 0), 2)
                    today_kline['concentration_90'] = round(chip_result.get('concentration_90', 0), 4)
                    today_kline['cost_90_low'] = round(chip_result.get('cost_90_low', 0), 2)
                    today_kline['cost_90_high'] = round(chip_result.get('cost_90_high', 0), 2)
        
        # 4. 获取总市值和流通市值（腾讯实时行情接口）
        try:
            total_mv, circ_mv = _fetch_market_cap_from_tencent(symbol)
            if total_mv is not None:
                today_kline['total_mv'] = total_mv
            if circ_mv is not None:
                today_kline['circ_mv'] = circ_mv
        except Exception:
            pass  # 市值获取失败不影响主流程
        
        # 5. 写入数据库
        upsert_kline(db_path, "kline_1d", [today_kline])
        
        # 限流延迟
        if sleep_per_stock > 0:
            time.sleep(sleep_per_stock)
        
        return {'symbol': symbol, 'status': 'processed', 'error': None, 'data': today_kline}
        
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 100:
            error_msg = error_msg[:100] + "..."
        return {'symbol': symbol, 'status': 'failed', 'error': error_msg, 'data': None}


def _run_parallel(symbols: list[str], date: str, workers: int, sleep_per_stock: float) -> tuple:
    """
    使用进程池并行处理股票列表
    
    Returns:
        (processed, skipped, failed, failed_symbols)
    """
    processed = 0
    skipped = 0
    failed = 0
    failed_symbols = []
    
    # 准备任务参数
    task_args = [(symbol, date, sleep_per_stock) for symbol in symbols]
    
    logger.info(f"启动并行处理：{len(symbols)} 只股票，{workers} 个 workers")
    
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # 提交所有任务
        future_to_symbol = {executor.submit(_process_single_symbol, args): args[0] 
                           for args in task_args}
        
        # 收集结果
        for i, future in enumerate(as_completed(future_to_symbol)):
            symbol = future_to_symbol[future]
            try:
                result = future.result()
                status = result['status']
                
                if status == 'processed':
                    processed += 1
                    if processed % 10 == 0:
                        logger.info(f"已处理 {processed} 只 (最新: {symbol})")
                elif status == 'skipped':
                    skipped += 1
                else:  # failed
                    failed += 1
                    failed_symbols.append((symbol, result.get('error', '未知错误')))
                    logger.warning(f"{symbol} 处理失败：{result.get('error')}")
                
                # 每 500 只输出进度
                if (i + 1) % 500 == 0:
                    progress = (i + 1) / len(symbols) * 100
                    logger.info(f"进度：{i+1}/{len(symbols)} ({progress:.1f}%)")
                    
            except Exception as e:
                failed += 1
                failed_symbols.append((symbol, str(e)))
                logger.error(f"{symbol} 任务异常：{e}")
    
    return processed, skipped, failed, failed_symbols


def _run_sequential(symbols: list[str], date: str, sleep_per_stock: float, 
                    sleep_per_100: float) -> tuple:
    """
    顺序处理股票列表（备用方案）
    
    Returns:
        (processed, skipped, failed, failed_symbols)
    """
    processed = 0
    skipped = 0
    failed = 0
    failed_symbols = []
    
    logger.info(f"使用顺序处理模式：{len(symbols)} 只股票")
    
    for i, symbol in enumerate(symbols):
        db_path = get_db_path("A", symbol, date)
        
        # 检查当日数据是否已存在
        if Path(db_path).exists():
            try:
                existing = query_kline(db_path, "kline_1d", start=date, end=date)
                if existing:
                    skipped += 1
                    continue
            except Exception as e:
                logger.warning(f"{symbol} 数据库检查失败：{e}")
        
        try:
            # Phase 30 优化：本地 DB 历史 + 今日最新 1 条模式
            
            # 1. 从本地 DB 加载历史 K 线
            historical = load_historical_klines_from_db(symbol, date)
            
            # 2. 仅从数据源获取当日 1 条 K 线（不含指标）
            today_kline = fetch_today_kline(symbol, date)
            
            if not today_kline:
                raise Exception("数据源返回空数据或当日数据不存在")
            
            # 3. 拼接历史 + 今日，计算 MACD 和筹码
            if len(historical) >= 120:  # 有足够历史数据才计算指标
                today_kline = calculate_macd_and_chip(historical, today_kline)
            else:
                logger.debug(f"{symbol} 历史数据不足 ({len(historical)} 天)，跳过指标计算")
            
            # 4. 写入数据库（幂等：当日数据已存在则更新）
            upsert_kline(db_path, "kline_1d", [today_kline])
            processed += 1
            
            if processed % 10 == 0:
                logger.info(f"{symbol} 处理成功 (累计 {processed} 只)")
            
        except Exception as e:
            failed += 1
            error_msg = str(e)
            if len(error_msg) > 50:
                error_msg = error_msg[:50] + "..."
            failed_symbols.append((symbol, error_msg))
            logger.error(f"{symbol} 处理失败：{e}")
            continue  # 失败的不延迟
        
        # 限流：只对真正抓到数据的股票延迟（跳过的不触发限流）
        if BACKFILL_ENABLED:
            time.sleep(sleep_per_stock)
            
            # 每 100 只长延迟（只计真正抓到的）
            if processed % 100 == 0:
                logger.info(f"完成 {processed} 只，休息 {sleep_per_100} 秒...")
                time.sleep(sleep_per_100)
        
        # 每 500 只输出进度
        if (i + 1) % 500 == 0:
            progress = (i + 1) / len(symbols) * 100
            logger.info(f"进度：{i+1}/{len(symbols)} ({progress:.1f}%)")
    
    return processed, skipped, failed, failed_symbols


def _run_with_multi_pass(symbols: list[str], date: str, workers: int,
                         sleep_per_stock: float) -> tuple:
    """三轮循环处理股票列表。

    第1轮：处理全部 symbols
    第2轮：只处理第1轮失败的
    第3轮：只处理第2轮剩余的

    每轮之间延迟 10 秒（让网络恢复）。

    Returns:
        (processed, skipped, failed, failed_symbols, pass_stats)
        pass_stats = [
            {"pass": 1, "processed": N, "skipped": M, "failed": K},
            {"pass": 2, ...},
            {"pass": 3, ...},
        ]
    """
    total_processed = 0
    total_skipped = 0
    total_failed = 0
    total_failed_symbols: list = []
    pass_stats = []

    current_symbols = list(symbols)

    for pass_num in range(1, 4):
        if pass_num > 1:
            # 第 2、3 轮只处理上一轮失败的 symbol
            if not total_failed_symbols:
                pass_stats.append({
                    "pass": pass_num,
                    "processed": 0,
                    "skipped": 0,
                    "failed": 0,
                })
                continue
            current_symbols = [sym for sym, _ in total_failed_symbols]
            logger.info(f"===== 第 {pass_num} 轮：重试 {len(current_symbols)} 只失败股票 =====")
            # 每轮之间延迟 10 秒
            time.sleep(10)
        else:
            logger.info(f"===== 第 1 轮：处理全部 {len(current_symbols)} 只股票 =====")

        # 复用现有函数
        if workers > 1:
            p, s, f, fs = _run_parallel(current_symbols, date, workers, sleep_per_stock)
        else:
            p, s, f, fs = _run_sequential(
                current_symbols, date, sleep_per_stock, BACKFILL_SLEEP_PER_100
            )

        pass_stats.append({
            "pass": pass_num,
            "processed": p,
            "skipped": s,
            "failed": f,
        })

        # 累计统计
        total_processed += p
        total_skipped += s

        # 最后一轮用实际结果，中间轮次只用于重试
        if pass_num == 3 or not fs:
            total_failed = f
            total_failed_symbols = fs
        else:
            total_failed = f
            total_failed_symbols = fs

    logger.info(f"===== 三轮循环完成：成功 {total_processed + total_skipped} / 最终失败 {total_failed} =====")
    return total_processed, total_skipped, total_failed, total_failed_symbols, pass_stats


def _run_dry_run(symbols: list[str], date: str,
                 sleep_per_stock: float, sleep_per_100: float) -> tuple:
    """Dry-run 模式：执行完整三轮流程但不写入数据库、不发送推送。

    复用 _fetch_today_with_fallback 获取数据，验证数据链路完整性，
    只统计不写盘。

    Returns:
        (processed, skipped, failed, failed_symbols, pass_stats)
    """
    from pathlib import Path

    total_processed = 0
    total_skipped = 0
    total_failed = 0
    total_failed_symbols = []
    pass_stats = []
    current_symbols = symbols

    for pass_num in range(1, 4):
        if pass_num > 1:
            if not total_failed_symbols:
                pass_stats.append({"pass": pass_num, "processed": 0, "skipped": 0, "failed": 0})
                continue
            current_symbols = [sym for sym, _ in total_failed_symbols]
            logger.info(f"[dry-run] 第 {pass_num} 轮：重试 {len(current_symbols)} 只失败股票")
            time.sleep(3)
        else:
            logger.info(f"[dry-run] 第 1 轮：验证 {len(current_symbols)} 只股票数据链路")

        p, s, f, fs = 0, 0, 0, []
        for i, symbol in enumerate(current_symbols):
            # 幂等检查
            db_path = get_db_path("A", symbol, date)
            if Path(db_path).exists():
                try:
                    existing = query_kline(db_path, "kline_1d", start=date, end=date)
                    if existing:
                        s += 1
                        continue
                except Exception:
                    pass

            try:
                records = _fetch_today_with_fallback(symbol, date, count=5)
                if not records:
                    f += 1
                    fs.append((symbol, "数据源返回空"))
                    continue

                today_kline = None
                for r in records:
                    if r.get("bar_time") == date:
                        today_kline = r
                        break
                if not today_kline:
                    latest = records[-1]
                    if latest.get("bar_time") == date:
                        today_kline = latest

                if not today_kline:
                    f += 1
                    fs.append((symbol, "当日数据不存在"))
                    continue

                # 加载历史 + 指标计算（仅验证，不写盘）
                dates = list_db_dates("A", symbol)
                hist_dates = [d for d in dates if d != date] if dates else []
                hist = []
                for hd in hist_dates:
                    hp = get_db_path("A", symbol, hd)
                    if Path(hp).exists():
                        try:
                            hist.extend(query_kline(hp, "kline_1d"))
                        except Exception:
                            continue
                hist.sort(key=lambda x: x.get("bar_time", ""))
                seen = set()
                hist = [r for r in hist if r.get("bar_time") not in seen and not seen.add(r.get("bar_time"))]

                # 指标计算验证
                if len(hist) >= 25:
                    try:
                        calculate_macd_and_chip(hist, today_kline)
                    except Exception as e:
                        logger.debug(f"[dry-run] {symbol} 指标计算跳过: {e}")

                # ⚠️ dry-run: 不写入数据库
                p += 1

            except Exception as e:
                f += 1
                err = str(e)[:80]
                fs.append((symbol, err))

            if sleep_per_stock > 0:
                time.sleep(sleep_per_stock)
            if BACKFILL_ENABLED and (i + 1) % 100 == 0:
                time.sleep(sleep_per_100)

        pass_stats.append({"pass": pass_num, "processed": p, "skipped": s, "failed": f})
        total_processed += p
        total_skipped += s
        if pass_num == 3 or not fs:
            total_failed = f
            total_failed_symbols = fs
        else:
            total_failed = f
            total_failed_symbols = fs

    logger.info(f"[dry-run] 完成：成功 {total_processed + total_skipped} / 失败 {total_failed}")
    return total_processed, total_skipped, total_failed, total_failed_symbols, pass_stats


# === Job Runner 入口 ===
def run(
    date: str | None = None,
    dry_run: bool | None = None,
    notify: bool | None = None,
    workers: int | None = None,
) -> dict | str | int:
    """
    A 股每日增量数据补全 Job Runner 入口
    
    Args:
        date: 分析日期 YYYY-MM-DD，默认今天
        dry_run: 干跑模式（不保存不推送），当前未完整实现，保留接口
        notify: 是否推送，CLI > env > yaml > default
        workers: 并行 workers 数量，None 表示使用配置默认值
    
    Returns:
        dict: 报告数据（成功）
        str: 错误信息（失败）
        int: 退出码（0=成功，1=失败）
    """
    # 默认值处理
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # 开关优先级：CLI 显式参数 > 全局配置 > 代码默认值
    if dry_run is None:
        dry_run = False  # 默认不启用 dry_run
    if notify is None:
        notify = config.runtime.notify_enabled if hasattr(config, 'runtime') else True
    if workers is None:
        workers = BACKFILL_WORKERS
    
    # 确保 workers 是合理的值
    if workers < 1:
        workers = 1
    max_workers = min(cpu_count(), 8)  # 最多 8 个 workers
    if workers > max_workers:
        workers = max_workers
    
    start_time = datetime.now()
    
    logger.info(f"===== 开始 A 股每日增量数据补全 ({date}) =====")
    logger.info(f"并行 workers: {workers}")
    
    # 加载 A 股列表
    stock_list_path = WORKSPACE / A_STOCK_LIST
    if not stock_list_path.exists():
        msg = f"A 股列表文件不存在：{stock_list_path}"
        logger.error(msg)
        return msg
    
    with open(stock_list_path) as f:
        stock_data = json.load(f)
    
    # 支持三种格式：dict / list[str] / list[dict]
    symbols = []
    if isinstance(stock_data, dict):
        # dict: key 是股票代码
        symbols = list(stock_data.keys())
    elif isinstance(stock_data, list):
        if len(stock_data) > 0:
            if isinstance(stock_data[0], dict):
                # list[dict]: 从 symbol 字段提取
                symbols = [item.get("symbol", "") for item in stock_data]
            else:
                # list[str]: 直接使用
                symbols = stock_data
    
    # 清洗：只保留非空字符串，去掉首尾空白
    symbols = [str(s).strip() for s in symbols if s and str(s).strip()]
    
    # 最小验证：确认前几个 symbol 是字符串而不是 dict
    if symbols:
        sample = symbols[:3]
        assert all(isinstance(s, str) for s in sample), \
            f"symbol 类型错误：前 3 个为 {sample}"
    
    logger.info(f"加载 {len(symbols)} 只有效 A 股代码")

    try:
        # 使用三轮循环处理（dry-run 模式不写 DB 不推送）
        if dry_run:
            processed, skipped, failed, failed_symbols, pass_stats = _run_dry_run(
                symbols, date, BACKFILL_SLEEP_PER_STOCK, BACKFILL_SLEEP_PER_100
            )
        else:
            processed, skipped, failed, failed_symbols, pass_stats = _run_with_multi_pass(
                symbols, date, workers, BACKFILL_SLEEP_PER_STOCK
            )
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info(f"===== 数据处理完成 =====")
        logger.info(f"总耗时：{duration}")
        logger.info(f"成功：{processed} 只，跳过：{skipped} 只，失败：{failed} 只")
        
        # 收集市值统计
        market_cap_stats = collect_market_cap_stats(date)
        logger.info(f"市值统计：{market_cap_stats.get('total_count', 0)} 只含总市值数据")
        
        # 生成报告
        report = generate_report(date, start_time, end_time, processed, skipped, failed, failed_symbols, pass_stats, market_cap_stats)
        
        # 推送
        if notify and not dry_run:
            logger.info("开始推送报告...")
            send_push(report)
            logger.info("执行完成，报告已推送")
        else:
            logger.info("跳过推送（dry_run 或 notify=False）")
            print(report)
        
        # 返回报告数据
        return {
            "date": date,
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "duration_seconds": duration.total_seconds(),
            "pass_stats": pass_stats,
            "report": report,
        }
    except Exception as e:
        # 顶层异常：脚本崩溃时也必须推送失败报告
        end_time = datetime.now()
        error_msg = str(e)
        if len(error_msg) > 500:
            error_msg = error_msg[:500] + "..."
        
        fail_report = f"❌ A 股数据补全异常\n\n"
        fail_report += f"执行时间：{start_time.strftime('%Y-%m-%d %H:%M')}\n"
        fail_report += f"日期：{date}\n"
        fail_report += f"错误信息：{error_msg}\n"
        fail_report += f"\n涉及股票数：{len(symbols)} 只\n"
        fail_report += f"\n请检查日志文件：logs/daily_backfill_{date.replace('-', '')}.log"
        
        logger.error(f"补全任务异常：{e}")
        
        if notify and not dry_run:
            try:
                send_both(fail_report)
                logger.info("失败报告已推送")
            except Exception as push_err:
                logger.error(f"失败报告推送也失败：{push_err}")
        else:
            print(fail_report)
        
        return str(e)


# === CLI 入口 ===
def main():
    parser = argparse.ArgumentParser(description="A 股每日增量数据补全")
    parser.add_argument("--date", default="", help="分析日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="不保存不推送，只打印结果")
    parser.add_argument("--no-notify", action="store_true", help="不发送推送")
    parser.add_argument("--workers", type=int, default=None, 
                       help="并行 workers 数量（默认从配置读取，通常为 4）")
    args = parser.parse_args()
    
    # CLI 参数转 run() 参数
    date = args.date or None
    dry_run = args.dry_run or None
    notify = False if args.no_notify else None
    workers = args.workers
    
    result = run(date=date, dry_run=dry_run, notify=notify, workers=workers)
    
    # 处理返回值
    if isinstance(result, int):
        sys.exit(result)
    elif isinstance(result, str):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
