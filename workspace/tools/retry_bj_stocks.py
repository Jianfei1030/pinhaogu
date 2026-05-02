#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北交所股票数据重试脚本

重新获取之前失败的 303 只北交所（920 开头）股票数据。
"""
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加工作区到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_source import fetch_a_daily
from database import get_db_path, upsert_kline

# ===== 日志配置 =====
def setup_logging() -> logging.Logger:
    """配置日志系统"""
    LOGS_DIR = Path(__file__).resolve().parent / "logs"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    log_file = LOGS_DIR / f"retry_bj_{datetime.now().strftime('%Y-%m-%d')}.log"
    
    logger = logging.getLogger("retry_bj")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    # 文件 handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    
    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


def load_failed_symbols() -> list[str]:
    """从日志文件中提取失败的北交所股票代码"""
    failed_file = Path("/tmp/failed_bj_stocks.txt")
    if not failed_file.exists():
        raise FileNotFoundError("未找到失败股票列表：/tmp/failed_bj_stocks.txt")
    
    with open(failed_file, "r", encoding="utf-8") as f:
        symbols = [line.strip() for line in f if line.strip()]
    
    return symbols


def process_symbol(symbol: str, logger: logging.Logger) -> bool:
    """处理单只股票"""
    try:
        # 获取数据（含 MACD+ 筹码指标）
        daily = fetch_a_daily(symbol, count=120, with_indicators=True)
        
        if not daily:
            raise ValueError("获取数据为空")
        
        # 写入数据库
        db_path = get_db_path("A", symbol, daily[-1]['bar_time'])
        upsert_kline(db_path, "kline_1d", daily)
        
        return True
    except Exception as e:
        logger.error(f"{symbol} 失败：{e}")
        return False


def main():
    logger = setup_logging()
    
    # 加载失败股票列表
    symbols = load_failed_symbols()
    total = len(symbols)
    
    logger.info("=" * 60)
    logger.info(f"北交所股票数据重试 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"失败股票总数：{total}")
    logger.info("=" * 60)
    
    # 处理循环
    completed = 0
    failed = 0
    failed_symbols = []
    start_time = datetime.now()
    
    for i, symbol in enumerate(symbols):
        try:
            success = process_symbol(symbol, logger)
            
            if success:
                completed += 1
                status = "✅"
            else:
                failed += 1
                failed_symbols.append(symbol)
                status = "❌"
            
            # 输出进度
            elapsed = (datetime.now() - start_time).total_seconds()
            avg_time = elapsed / (i + 1) if i > 0 else 0
            remaining = (total - i - 1) * avg_time
            
            logger.info(f"[{i+1:03d}/{total}] {status} {symbol} | 耗时：{avg_time:.1f}s | 预计剩余：{remaining/60:.1f}m")
            
            # 限流延迟（3 秒）
            time.sleep(3)
            
            # 每 50 只长延迟
            if (i + 1) % 50 == 0:
                logger.info("完成 50 只，休息 30 秒...")
                time.sleep(30)
                
        except Exception as e:
            logger.error(f"{symbol} 异常：{e}")
            failed += 1
            failed_symbols.append(symbol)
            continue
    
    # 完成报告
    total_elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(f"完成报告 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"处理总数：{total}")
    logger.info(f"成功：{completed} ({completed/total*100:.1f}%)")
    logger.info(f"失败：{failed} ({failed/total*100:.1f}%)")
    logger.info(f"总耗时：{total_elapsed/60:.1f} 分钟")
    logger.info(f"平均速度：{total_elapsed/total:.1f} 秒/只")
    logger.info("=" * 60)
    
    if failed_symbols:
        logger.info(f"失败股票 ({len(failed_symbols)}):")
        for sym in failed_symbols[:20]:
            logger.info(f"  - {sym}")
        if len(failed_symbols) > 20:
            logger.info(f"  ... 及另外 {len(failed_symbols) - 20} 只")
    
    # 保存失败列表
    if failed_symbols:
        failed_file = Path(__file__).resolve().parent / "data" / "bj_retry_failed.json"
        failed_file.parent.mkdir(parents=True, exist_ok=True)
        with open(failed_file, "w", encoding="utf-8") as f:
            json.dump({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total": total,
                "completed": completed,
                "failed": failed,
                "failed_symbols": failed_symbols
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"失败列表已保存：{failed_file}")


if __name__ == "__main__":
    main()
