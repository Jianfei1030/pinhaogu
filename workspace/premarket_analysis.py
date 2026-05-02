#!/usr/bin/env python3
"""
盘前概念板块分析 (v1):
  1. 拉取全部概念板块 → 取 Top 50
  2. LLM（百炼 qwen3.6-plus）+ 当日新闻 → 推荐 1 个板块
  3. 拉取推荐板块成分股
  4. 生成报告 + 推送 Telegram
"""

import json
import os
import re
import ssl
import sys
import argparse
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# === 复用模块 ===
sys.path.insert(0, str(Path(__file__).parent))
from utils.trading_calendar import is_trading_day
from utils.component_index import calc_equal_weight_index


def _write_status(path: str, data: dict):
    """写入状态文件（供 server.py 读取进度）"""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
from concept_board_ths import fetch_board_stocks_by_code
from board_db import save_board_snapshot
from database import get_db_path, list_db_dates, query_kline

# === 白名单配置文件路径 ===
SUPPLEMENTS_FILE = Path(__file__).parent / "data" / "board_supplements.json"

# === 加载白名单配置 ===
def load_supplements() -> dict:
    """加载板块补充白名单配置"""
    if not SUPPLEMENTS_FILE.exists():
        return {}
    try:
        with open(SUPPLEMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [WARN] 加载白名单失败：{e}", file=sys.stderr)
        return {}

# === 从数据库读取成分股的流通市值 ===
def fetch_circ_mv_from_db(stock_codes: list[str]) -> dict:
    """
    从盘后补全数据库读取成分股的流通市值（circ_mv）。
    daily_incremental_backfill.py 每次补全时通过腾讯行情接口写入 circ_mv。
    返回：{code: circ_mv_in_yi_yuan, ...}（单位：亿元），获取不到返回 None
    """
    if not stock_codes:
        return {}

    result = {code: None for code in stock_codes}
    db_root = str(Path(__file__).parent / "data")

    for code in stock_codes:
        try:
            code = str(code).strip()
            if not code:
                continue
            dates = list_db_dates("a", code, db_dir=db_root)
            if not dates:
                continue
            db_path = str(Path(__file__).parent / get_db_path("a", code, dates[-1]))
            rows = query_kline(db_path, "kline_1d")
            if rows:
                latest = rows[-1]
                circ_mv = latest.get("circ_mv")
                if circ_mv is not None and circ_mv > 0:
                    result[code] = circ_mv  # 亿元
        except Exception:
            pass

    count = sum(1 for v in result.values() if v is not None)
    print(f"  流通市值数据：{count}/{len(stock_codes)} 只从数据库获取（单位：亿元）")
    return result


# === 应用白名单补充 ===
def apply_supplements(board_name: str, stocks: list[dict]) -> list[dict]:
    """
    应用白名单补充机制
    在 Step 3 获取成分股后调用，补充缺失的股票或移除伪概念股
    
    Args:
        board_name: 板块名称
        stocks: 原始成分股列表
    
    Returns:
        补充后的成分股列表
    """
    supplements = load_supplements()
    db_root = str(Path(__file__).parent / "data")
    
    if board_name not in supplements:
        return stocks
    
    config = supplements[board_name]
    add_codes = config.get("add", [])
    remove_codes = config.get("remove", [])
    note = config.get("note", "")
    
    if not add_codes and not remove_codes:
        return stocks
    
    print(f"  [白名单] {board_name}: {note}")
    
    # 1. 移除伪概念股
    if remove_codes:
        original_count = len(stocks)
        stocks = [s for s in stocks if s.get("code", "") not in remove_codes]
        if len(stocks) < original_count:
            print(f"    移除 {original_count - len(stocks)} 只股票：{remove_codes}")
    
    # 2. 补充缺失的股票
    if add_codes:
        # 获取补充股票的价格和流通市值
        price_data = {}
        circ_mv_dict = fetch_circ_mv_from_db(add_codes)
        for code in add_codes:
            try:
                code = str(code).strip()
                dates = list_db_dates("a", code, db_dir=db_root)
                if dates:
                    db_path = str(Path(__file__).parent / get_db_path("a", code, dates[-1]))
                    rows = query_kline(db_path, "kline_1d")
                    if rows:
                        latest = rows[-1]
                        price_data[code] = {
                            "code": code,
                            "name": code,
                            "price": latest.get("close", 0),
                            "change_pct": 0,
                            "circulating_mv": latest.get("circ_mv"),
                        }
            except Exception:
                pass
        
        for code in add_codes:
            # 检查是否已存在
            exists = any(s.get("code") == code for s in stocks)
            if exists:
                print(f"    [SKIP] {code} 已在成分股列表中")
                continue
            
            stock_info = price_data.get(code)
            if stock_info:
                stocks.append(stock_info)
                print(f"    [ADD] {code} {stock_info['name']} (价格：{stock_info['price']}, 涨跌幅：{stock_info['change_pct']:+.2f}%)")
            else:
                print(f"    [WARN] {code} 无法获取价格数据，标记为 None")
                stocks.append({
                    "code": code,
                    "name": "未知",
                    "price": None,
                    "change_pct": None,
                    "turnover_rate": None,
                    "volume": None,
                    "amount": None,
                    "pe": None,
                    "pb": None,
                })
    
    return stocks


def auto_add_to_watchlist(stocks):
    """自动添加股票到东方财富自选股"""
    MX_SKILL_DIR = Path(os.path.expanduser("~")) / "projects" / "MyDocs" / "skills" / "mx-zixuan"
    if not MX_SKILL_DIR.exists():
        print("  [WARN] mx_zixuan 技能目录不存在，跳过自动添加")
        return

    apikey = os.environ.get("MX_APIKEY", "")
    if not apikey:
        print("  [WARN] MX_APIKEY 环境变量未设置，跳过自动添加")
        return

    added = 0
    failed = 0
    print(f"\n  📌 自动添加 {len(stocks)} 只股票到自选股...")
    import time
    for s in stocks:
        code = s.get("code", "")
        name = s.get("name", "")
        try:
            result = subprocess.run(
                ["/opt/homebrew/bin/python3.10", "mx_zixuan.py", "add", code],
                cwd=MX_SKILL_DIR,
                env={**os.environ, "MX_APIKEY": apikey},
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and "成功" in result.stdout:
                print(f"    ✅ {code} {name}")
                added += 1
            else:
                print(f"    ❌ {code} {name}: {result.stdout.strip() or result.stderr.strip()}")
                failed += 1
            time.sleep(5)  # 避免请求过快，东方财富 API 限流
        except Exception as e:
            print(f"    ❌ {code} {name}: {e}")
            failed += 1
    print(f"  添加完成：成功 {added} 只，失败 {failed} 只\n")


def _calc_component_index(display_stocks: list[dict], analysis_date: str) -> dict | None:
    """
    计算成分股等权指数。

    从本地数据库读取成分股的 kline_1d 历史数据，调用 calc_equal_weight_index。
    失败时返回 None，不阻塞主流程。
    """
    if not display_stocks:
        return None

    try:
        stocks_data: dict[str, dict] = {}
        for s in display_stocks:
            code = str(s.get("code", "")).strip()
            if not code:
                continue
            try:
                db_root = Path(__file__).parent / "data"
                dates = list_db_dates("A", code, db_dir=str(db_root))
                if not dates:
                    continue

                # 读取所有历史日期的 kline_1d 数据，用 dict 去重（首日 DB 含历史全量，后续文件会重叠）
                date_close: dict[str, float] = {}
                for d in dates:
                    db_path = str(Path(__file__).parent / get_db_path("A", code, d))
                    rows = query_kline(db_path, "kline_1d")
                    for row in rows:
                        bt = str(row.get("bar_time", ""))
                        close = row.get("close")
                        if bt and close is not None:
                            dt_part = bt.split(" ")[0] if " " in bt else bt
                            date_close[dt_part] = float(close)

                if len(date_close) >= 2:
                    sorted_items = sorted(date_close.items())
                    stocks_data[code] = {"dates": [d for d, _ in sorted_items], "closes": [c for _, c in sorted_items]}
            except Exception as e:
                print(f"  [WARN] 读取 {code} 历史 K 线失败：{e}", file=sys.stderr)
                continue

        if not stocks_data:
            print(f"  [WARN] 成分股等权指数：无法获取任何成分股的历史数据", file=sys.stderr)
            return None

        # 基期设为第一个有数据的交易日之前一天，确保所有股票都能纳入
        df = calc_equal_weight_index(stocks_data)
        if df is None or df.empty:
            print(f"  [WARN] 成分股等权指数计算返回空结果", file=sys.stderr)
            return None

        latest = df.iloc[-1]
        idx_value = float(latest["index_value"])
        idx_change = float(latest.get("pct_change", 0))
        result = {
            "index_value": round(idx_value, 2),
            "change_pct": round(idx_change, 4),
            "n_stocks": len(stocks_data),
        }
        print(f"  成分股等权指数：{idx_value:.2f} (日涨跌 {idx_change:+.2f}%, {len(stocks_data)} 只)", file=sys.stderr)
        return result

    except Exception as e:
        print(f"  [WARN] 成分股等权指数计算失败：{e}", file=sys.stderr)
        return None


def load_chip_from_db(stock_code: str, market: str = "A") -> dict | None:
    """从数据库读取最新筹码数据，避免临时计算。"""
    try:
        stock_code = str(stock_code).strip()
        if not stock_code:
            return None

        db_root = Path(__file__).parent / "data"
        dates = list_db_dates(market, stock_code, db_dir=str(db_root))
        if not dates:
            return None

        latest_date = dates[-1]
        db_path = str(Path(__file__).parent / get_db_path(market, stock_code, latest_date))
        rows = query_kline(db_path, "kline_1d")
        if not rows:
            return None

        latest = rows[-1]
        profit_ratio = latest.get("profit_ratio")
        if profit_ratio is None:
            return None

        return {
            "profit_ratio": profit_ratio,
            "avg_cost": latest.get("avg_cost"),
            "concentration_90": latest.get("concentration_90"),
            "cost_90_low": latest.get("cost_90_low"),
            "cost_90_high": latest.get("cost_90_high"),
        }
    except Exception as e:
        print(f"  [WARN] 读取 {stock_code} 筹码数据失败：{e}", file=sys.stderr)
        return None


def enrich_stocks_with_chip_data(stocks: list[dict], market: str = "A") -> list[dict]:
    """把数据库中的筹码数据挂到成分股上。"""
    for stock in stocks:
        code = str(stock.get("code", "")).strip()
        stock["chip"] = load_chip_from_db(code, market=market)
    return stocks


def fetch_all_boards_with_fallback() -> list[dict]:
    """
    获取全部板块列表，使用同花顺数据源
    返回的板块数据包含 change_pct 字段
    """
    try:
        from concept_board_ths import fetch_all_boards as fetch_all_boards_ths
        boards = fetch_all_boards_ths()
        if boards:
            print(f"  数据源：同花顺（{len(boards)} 个板块）")
            return boards
    except Exception as e:
        print(f"  同花顺获取失败：{e}", file=sys.stderr)
    
    return []

from config import config, LLM_BASE_URL, LLM_MODEL, LLM_PROXY, LLM_TIMEOUT, get_config
from services.runtime_state_service import is_dry_run, is_notify_enabled
from utils.push import send_both
from utils.logger import setup_logger

SCRIPT_DIR = Path(__file__).parent
NEWS_DIR = SCRIPT_DIR / "news_data"
REPORT_DIR = SCRIPT_DIR / "reports"

# === LLM Prompt ===
SYSTEM_PROMPT = """你是一位资深的 A 股概念板块分析师。你擅长从板块排名和财经新闻中识别最具投资价值的概念板块，关注政策催化、资金流向和边际变化。你的分析基于事实，不编造数据。"""




# === LLM 调用 (已迁移至 services.llm_service) ===
from services.llm_service import chat_completion


def load_api_key():
    """从环境变量读取阿里百炼 Coding Plan API Key（保留用于兼容性检查）"""
    return config.llm.api_key


def get_watchlist_text() -> str:
    """从配置读取监控标的，返回格式化的文本"""
    watchlist_names = []
    watchlist_codes = []
    for item in config.watchlist:
        if item.get("name"):
            watchlist_names.append(item["name"])
        if item.get("symbol"):
            watchlist_codes.append(item["symbol"])
    watchlist_stocks = list(dict.fromkeys(watchlist_names + watchlist_codes))
    return ", ".join(watchlist_stocks) if watchlist_stocks else "无"


def llm_recommend(boards: list[dict], news_items: list[dict], date: str, api_key: str) -> str:
    """调用 LLM 推荐 1 个概念板块"""
    # 构建板块文本
    boards_lines = []
    for i, b in enumerate(boards, 1):
        boards_lines.append(
            f"{i}. {b['name']} ({b['code']}) "
            f"上涨/下跌: {b['up_count']}/{b['down_count']} "
            f"领涨: {b['leader_stock']}"
        )
    boards_text = "\n".join(boards_lines)

    # 构建新闻文本（包含时间日期）
    news_text = ""
    news_count = 0
    if news_items:
        news_lines = []
        for i, item in enumerate(news_items, 1):
            title = item.get("title", "").strip()
            if len(title) < 5:
                continue
            source = item.get("source", "")
            summary = item.get("summary", "").strip()
            pub_date = item.get("date", "")
            pub_time = item.get("time", "")
            # 构建时间戳：2026-04-08 00:05:05
            timestamp = f"{pub_date} {pub_time}" if pub_date and pub_time else ""
            line = f"{i}. [{source}] {title}"
            if timestamp:
                line = f"{i}. [{pub_date} {pub_time}] [{source}] {title}"
            if summary and summary != title:
                line += f" | {summary[:100]}"
            news_lines.append(line)
        news_text = "\n".join(news_lines)
        news_count = len(news_lines)

    if not news_text:
        news_text = "(无新闻数据，仅基于板块排名分析)"

    # 获取监控标的文本
    watchlist_text = get_watchlist_text()
    
    # 使用 f-string 避免 news/boards 内容中的 {} 冲突 format()
    user_prompt = (
        f"以下是今日 ({date}) 从同花顺获取的 **全部 A 股概念板块列表**（共 {len(boards)} 个）：\n\n"
        f"{boards_text}\n\n"
        f"以下是今日 ({date}) 的财经新闻摘要（已过滤掉地缘政治、外国选举等与 A 股板块无直接关联的宏观新闻，共 {news_count} 条产业相关新闻）：\n"
        f"{news_text}\n\n"
        f"请基于以上板块信息和新闻，推荐 **1 个**最具盘前关注价值的概念板块。\n\n"
        f"要求：\n"
        f"1. 综合板块信息与新闻，识别最具投资机会的板块\n"
        f"2. 新闻必须作为推荐依据的核心支撑\n"
        f"3. 在给出推荐后，必须补充输出与该推荐板块**直接相关**的新闻，最多 10 条；如果不足 10 条，就列出全部\n"
        f"4. 相关新闻必须来自上文提供的新闻，不要编造，不要输出与推荐板块无关的新闻\n"
        f"5. **重要：大宗商品/期货价格类新闻**（如黄金、原油、铜、铁矿石等价格波动）**不作为推荐概念板块的直接依据**，仅用于'宏观形势判断'中分析市场整体偏向【避险/投资】的参考指标。推荐板块必须基于产业政策、公司业绩、技术突破、事件催化等与板块直接相关的新闻。\n\n"
        f"6. **监控股新闻识别**：当前监控的标的包括：{watchlist_text}。请在分析新闻时，特别识别是否与这些监控标的强相关。如果新闻与监控标的强相关，请在输出中增加一个独立章节【监控股新闻】，列出相关新闻并说明其与监控标的的关联。\n\n"
        f"输出格式（严格按此格式，内容要详细）：\n"
        f"宏观形势判断：{{当前市场整体偏向【避险/投资】，理由：...}}\n"
        f"推荐板块：{{板块名}} ({{板块代码}})\n"
        f"推荐理由：{{详细分析，包括为什么这个板块值得关注，结合新闻事件、资金动向、政策催化等}}\n"
        f"关键催化：{{列出 2-3 个具体催化事件，每个事件用一句话说明}}\n"
        f"相关新闻：{{列出与推荐板块直接相关的新闻，按相关性从高到低排序，最多 10 条；不足 10 条则全部列出。每条格式为：1. [YYYY-MM-DD HH:MM:SS] [来源] 标题 | 相关性说明}}\n"
        f"监控股新闻：{{如果新闻与监控标的（{watchlist_text}）强相关，列出相关新闻并说明关联；如无则写'无'}}\n"
        f"风险提示：{{潜在风险因素，如追高风险、政策不确定性等}}\n\n"
        f"注意：不要编造新闻中不存在的事实；如果相关新闻不足 10 条，照实输出，不要为了凑数补充无关新闻。每条新闻必须包含具体时间日期（从输入数据中获取）。"
    )

    # 使用 llm_service 统一调用
    content = chat_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=LLM_MODEL,
        temperature=0.3,
        max_tokens=2048,
        timeout=LLM_TIMEOUT,
        verbose=True,
    )
    return content


# === 解析 LLM 输出 ===
def parse_llm_output(raw: str) -> dict:
    """解析 LLM 返回的结构化文本，支持 {} 包裹和普通格式"""
    parsed = {"raw": raw}
    
    # 清理 { } 包裹（LLM 有时会用花括号包裹内容）
    clean = raw.replace("{", "").replace("}", "")
    
    # 推荐板块: 板块名 (板块代码) 或 {板块名} ({板块代码}) 或 {板块名} (CPO) (309049)
    # 优先匹配纯数字代码（避免 LLM 输出如 "共封装光学 (CPO) (309049)" 时匹配到 CPO）
    # 先尝试匹配带字母+数字的双重括号格式
    m = re.search(r"推荐板块[：:]\s*{?\s*(.+?)\s*}?\s*[(（][A-Za-z]+[)）]\s*[(（](\d+)[)）]", clean)
    if m:
        parsed["board_name"] = m.group(1).strip().rstrip("}").lstrip("{")
        parsed["board_code"] = m.group(2).strip()
    else:
        # 回退到标准格式：板块名 (代码)
        m = re.search(r"推荐板块[：:]\s*{?\s*(.+?)\s*}?\s*[(（]([A-Za-z0-9]+)[)）]", clean)
        if m:
            parsed["board_name"] = m.group(1).strip().rstrip("}").lstrip("{")
            parsed["board_code"] = m.group(2).strip()
    
    # 推荐理由
    m = re.search(r"推荐理由[：:]\s*(.+?)(?:关键催化|$)", clean, re.DOTALL)
    if m:
        parsed["reason"] = m.group(1).strip()
    
    # 关键催化
    m = re.search(r"关键催化[：:]\s*(.+?)(?:风险提示|$)", clean, re.DOTALL)
    if m:
        parsed["catalyst"] = m.group(1).strip()
    
    return parsed
# === QQ 推送配置 ===
OPENCLAW_MESSAGE_API = "http://127.0.0.1:18789/message"




# === Telegram 发送 ===
def split_telegram(text, max_len=4000):
    if len(text) <= max_len:
        return [text]
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


# === 盘前新闻加载 ===
def load_premarket_news(date: str) -> tuple[list[dict], list[dict]]:
    """
    加载盘前新闻并按宏观/产业分类：
    - 周二~周五：前一天 16:10 ~ 当天全天
    - 周六：周五 16:10 ~ 周六全天
    - 周日：周五 16:10 ~ 周日全天
    - 周一：周五 16:10 ~ 周一全天
    返回: (macro_news, industry_news)
    """
    from datetime import timedelta
    
    target_date = datetime.strptime(date, "%Y-%m-%d")
    weekday = target_date.weekday()  # 0=周一, 6=周日
    
    # 确定要加载的日期范围
    if weekday == 0:  # 周一：周五 ~ 周一
        base_date = (target_date - timedelta(days=3)).strftime("%Y-%m-%d")  # 周五
        dates_to_load = [
            base_date,  # 周五
            (target_date - timedelta(days=2)).strftime("%Y-%m-%d"),  # 周六
            (target_date - timedelta(days=1)).strftime("%Y-%m-%d"),  # 周日
            date,  # 周一
        ]
    elif weekday == 5:  # 周六：周五 ~ 周六
        base_date = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")  # 周五
        dates_to_load = [
            base_date,  # 周五
            date,  # 周六
        ]
    elif weekday == 6:  # 周日：周五 ~ 周日
        base_date = (target_date - timedelta(days=2)).strftime("%Y-%m-%d")  # 周五
        dates_to_load = [
            base_date,  # 周五
            (target_date - timedelta(days=1)).strftime("%Y-%m-%d"),  # 周六
            date,  # 周日
        ]
    else:  # 周二~周五：前一天 16:10 ~ 当天
        base_date = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_load = [
            base_date,  # 前一天
            date,  # 当天
        ]
    
    all_news = []
    seen_titles = set()
    
    for d in dates_to_load:
        news_file = NEWS_DIR / f"financial_news_{d}.json"
        if not news_file.exists():
            continue
        with open(news_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for item in data:
            title = item.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            
            news_date = item.get("date", d)
            news_time = item.get("time", "23:59:59")
            
            # 基准日（周五或前一天）：只取 16:10 之后；其余日期：全取
            if news_date == base_date:
                try:
                    h, m, s = map(int, news_time.split(":"))
                    if h * 60 + m < 16 * 60 + 10:
                        continue
                except:
                    pass
            
            all_news.append(item)
            seen_titles.add(title)
    
    print(f"  盘前新闻: {len(all_news)} 条 (范围: {base_date} 16:10 ~ {date} 全天)")

    # 新闻分类：宏观 vs 产业
    try:
        from news_filter import classify_news
        macro_news, industry_news = classify_news(all_news)
        print(f"  分类结果: 宏观 {len(macro_news)} 条, 产业 {len(industry_news)} 条")
        return macro_news, industry_news
    except Exception as e:
        print(f"  ⚠️ 新闻分类失败 ({e})，fallback 返回全部新闻作为产业新闻")
        return [], all_news





def load_news(date: str) -> list[dict]:
    news_file = NEWS_DIR / f"financial_news_{date}.json"
    if not news_file.exists():
        print(f"  新闻文件不存在: {news_file}（将仅基于板块排名分析）")
        return []
    with open(news_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  新闻文件: {news_file.name} | 共 {len(data)} 条")
    return data


# === Job Runner 入口 ===
def run(date: str | None = None, dry_run: bool | None = None, notify: bool | None = None, status_file: str = "", auto_add: bool = False) -> dict | str | int:
    """
    盘前概念板块分析 Job Runner 入口
    
    Args:
        date: 分析日期 YYYY-MM-DD，默认今天
        dry_run: 干跑模式（不保存不推送），CLI > env > yaml > default
        notify: 是否推送，CLI > env > yaml > default
    
    Returns:
        dict: 报告数据（成功）
        str: 错误信息（失败）
        int: 退出码（0=成功，1=失败）
    """
    # 默认值处理
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # 开关优先级：CLI 显式参数 > 全局配置 > 代码默认值
    # 已迁移至 runtime_state_service：底层读取 config.runtime.*
    if dry_run is None:
        dry_run = is_dry_run()
    if notify is None:
        notify = is_notify_enabled()
    
    date_compact = date.replace("-", "")
    
    # 非交易日降级提示：使用上一交易日数据继续分析
    if not is_trading_day(date):
        print(f"⚠️ {date} 为非交易日，将使用上一交易日数据进行分析")
    
    print(f"=== {date} 盘前概念板块分析 ===\n")
    
    # 写入初始状态
    _write_status(status_file, {"status": "loading", "progress": 0, "date": date})
    
    api_key = load_api_key()
    if not api_key:
        msg = "ERROR: BAILIAN_API_KEY 未设置（阿里百炼 Coding Plan API）"
        print(msg, file=sys.stderr)
        return msg

    # ── Step 1: 拉取全部板块 ──
    print("[1/4] 拉取概念板块...")
    boards = fetch_all_boards_with_fallback()
    if not boards:
        msg = "ERROR: 未获取到板块数据"
        print(msg, file=sys.stderr)
        _write_status(status_file, {"status": "error", "current_step": "未获取到板块数据", "date": date})
        return msg
    print(f"  共 {len(boards)} 个板块")
    
    # Step 1 完成
    _write_status(status_file, {"status": "loading", "progress": 25, "current_step": "板块数据获取完成", "date": date})

    # 全部板块用于报告展示（不排序、不过滤）
    sorted_boards = sorted(boards, key=lambda x: x.get("change_pct", 0), reverse=True)
    print(f"  全部 {len(boards)} 个板块已就绪，最高涨幅：{sorted_boards[0]['name']} ({sorted_boards[0]['change_pct']:.2f}%)")

    # ── Step 2: LLM 推荐 1 个板块 ──
    print(f"\n[2/4] LLM 分析 ({LLM_MODEL})...")
    macro_news, industry_news = load_premarket_news(date)
    llm_raw = llm_recommend(boards, industry_news, date, api_key)
    print(f"\n  LLM 原始输出:\n{'─'*40}\n{llm_raw}\n{'─'*40}\n")

    # Step 2 完成
    _write_status(status_file, {"status": "analyzing", "progress": 50, "current_step": "LLM 分析完成", "news_count": len(industry_news), "macro_news_count": len(macro_news), "date": date})

    # 解析 LLM 输出
    parsed = parse_llm_output(llm_raw)
    board_name = parsed.get("board_name", "")
    board_code = parsed.get("board_code", "")
    llm_change_pct = parsed.get("change_pct", 0)
    llm_reason = parsed.get("reason", "")
    llm_catalyst = parsed.get("catalyst", "")

    if not board_name:
        msg = "ERROR: LLM 未能解析出推荐板块"
        print(msg, file=sys.stderr)
        print(f"原始输出:\n{llm_raw}", file=sys.stderr)
        _write_status(status_file, {"status": "error", "current_step": "LLM 未能解析出推荐板块", "date": date})
        return msg

    print(f"  推荐板块：{board_name} ({board_code})")

    # ── Step 3: 拉取推荐板块成分股 ──
    print(f"\n[3/4] 拉取 [{board_name}] 成分股...")
    
    # 默认使用同花顺代码获取成分股
    # 如需回退到东财，取消注释下面两行
    # stocks = fetch_board_stocks(board_name)
    # if not stocks:
    stocks = fetch_board_stocks_by_code(board_code) if board_code else []
    
    # 应用白名单补充机制
    stocks = apply_supplements(board_name, stocks)
    
    if stocks:
        # 从数据库读取流通市值（盘后补全时已写入 kline_1d.circ_mv，单位：亿元）
        stock_codes = [s['code'] for s in stocks]
        circ_mv_dict = fetch_circ_mv_from_db(stock_codes)
        for s in stocks:
            code = s.get('code')
            mv = circ_mv_dict.get(code)
            if mv is not None:
                s['circulating_mv'] = mv  # 亿元
        
        stocks_sorted = sorted(stocks, key=lambda x: x["change_pct"] if x["change_pct"] is not None else 0, reverse=True)
        leader_chg = stocks_sorted[0]['change_pct'] if stocks_sorted[0]['change_pct'] is not None else 0
        print(f"  共 {len(stocks_sorted)} 只成分股，领涨：{stocks_sorted[0]['name']} ({leader_chg:+.2f}%)")
        
        # 全量成分股（用于报告展示）
        all_stocks_count = len(stocks_sorted)
        
        # 基础筛选：换手率 > 3% 且成交额 > 3 亿 且涨幅 < 11% 且流通市值 < 300 亿
        def pass_base_filter(s):
            tr = (s.get("turnover_rate") or 0) > 3
            am = (s.get("amount") or 0) > 300000000
            cp = (s.get("change_pct") or 0) < 11
            mv = s.get("circulating_mv")  # 亿元
            mv_ok = (mv is None) or (mv < 300)
            return tr and am and cp and mv_ok
        filtered_stocks = [s for s in stocks_sorted if pass_base_filter(s)]
        if filtered_stocks:
            print(f"  全量成分股 {len(stocks_sorted)} 只，基础筛选后（换手率>3% 且成交额>3亿 且涨幅<10% 且流通市值<300亿）：{len(filtered_stocks)} 只")

            print(f"\n[3.5/4] 读取数据库筹码分布...")
            enriched_stocks = enrich_stocks_with_chip_data(filtered_stocks, market="A")
            chip_ready_count = sum(1 for s in enriched_stocks if (s.get("chip") or {}).get("profit_ratio") is not None)
            print(f"  数据库筹码数据可用：{chip_ready_count}/{len(enriched_stocks)} 只")
            
            # Step 3 完成
            _write_status(status_file, {"status": "analyzing", "progress": 75, "current_step": "成分股分析完成", "date": date})

            chip_results = []
            for stock in enriched_stocks:
                chip = stock.get("chip")
                if not chip:
                    continue
                chip_results.append({
                    "code": stock["code"],
                    "name": stock["name"],
                    "profit_ratio": chip.get("profit_ratio", 0),
                    "avg_cost": chip.get("avg_cost", 0),
                    "concentration_90": chip.get("concentration_90", 0),
                })

            # 仅保留数据库中已满足筹码条件的成分股；没有就真的为空
            display_stocks = [s for s in enriched_stocks if (s.get("chip") or {}).get("profit_ratio", 0) > 0.5]
            print(f"  获利比例 > 50% 过滤后：{len(display_stocks)} 只")
        else:
            print(f"  [INFO] 暂无同时满足 换手率 > 3% 且成交额 > 3 亿 的成分股")
            enriched_stocks = []
            chip_ready_count = 0
            display_stocks = []
            chip_results = []
    else:
        stocks_sorted = []
        filtered_stocks = []
        enriched_stocks = []
        chip_ready_count = 0
        display_stocks = []
        chip_results = []
        print(f"  未获取到成分股数据（板块名可能不匹配）")

    # ── 自动添加自选股 ──
    if auto_add and display_stocks:
        auto_add_to_watchlist(display_stocks)

    # ── 计算成分股等权指数 ──
    component_index = _calc_component_index(display_stocks, date)

    # ── Step 4: 生成报告 + 推送 ──
    print(f"\n[4/4] 生成报告...")
    
    # Step 4 开始
    _write_status(status_file, {"status": "saving", "progress": 90, "current_step": "保存报告中", "date": date})

    # 板块涨跌幅只用等权指数，移除简单平均
    if component_index:
        print(f"  板块等权指数：{component_index['index_value']:.2f} (日涨跌 {component_index['change_pct']:+.2f}%)")
    else:
        print(f"  [WARN] 等权指数计算失败，报告将不包含指数数据")

    # 构建报告数据（符合 schema_premarket.json）
    report_data = {
        "date": date,
        "type": "premarket",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "top_sectors": [
            {
                "rank": i + 1,
                "name": b["name"],
                "code": b["code"],
                "change_pct": b["change_pct"],
                "up_count": b["up_count"],
                "down_count": b["down_count"],
                "leader": b["leader_stock"],
                "leader_change": b["leader_change_pct"],
            }
            for i, b in enumerate(boards)
        ],
        "recommended_sector": {
            "name": board_name,
            "code": board_code,
            "logic": llm_reason,
            "catalyst": llm_catalyst,
        },
        # 三层结构：全量成分股 -> 基础筛选 -> 最终筛选
        "all_stocks_count": len(stocks_sorted) if stocks else 0,  # 全量成分股
        "candidate_stocks_count": len(filtered_stocks),  # 基础筛选后（换手率>3% 且成交额>3亿 且涨幅<10%）
        "chip_ready_count": chip_ready_count,
        "final_stocks_count": len(display_stocks),  # 最终筛选后（满足筹码条件 profit_ratio>50%）
        "all_stocks": [  # 全量成分股列表
            {
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "change_pct": s["change_pct"],
                "turnover_rate": s.get("turnover_rate", 0.0),
                "volume": s.get("volume", 0),
                "amount": s.get("amount", 0.0),
                "pe": s.get("pe", 0.0),
                "pb": s.get("pb", 0.0),
            }
            for s in (stocks_sorted if stocks else [])
        ],
        "candidate_stocks": [  # 基础筛选后：满足换手率>3% 且成交额>3亿 且涨幅<10%
            {
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "change_pct": s["change_pct"],
                "turnover_rate": s.get("turnover_rate", 0.0),
                "volume": s.get("volume", 0),
                "amount": s.get("amount", 0.0),
                "pe": s.get("pe", 0.0),
                "pb": s.get("pb", 0.0),
            }
            for s in filtered_stocks
        ],
        "final_stocks": [  # 最终筛选后：满足筹码条件 profit_ratio>50%
            {
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "change_pct": s["change_pct"],
                "turnover_rate": s.get("turnover_rate", 0.0),
                "volume": s.get("volume", 0),
                "amount": s.get("amount", 0.0),
                "pe": s.get("pe", 0.0),
                "pb": s.get("pb", 0.0),
                "chip_profit_ratio": (s.get("chip") or {}).get("profit_ratio", 0.0),
                "chip_avg_cost": (s.get("chip") or {}).get("avg_cost", 0.0),
                "chip_concentration_90": (s.get("chip") or {}).get("concentration_90", 0.0),
            }
            for s in display_stocks
        ],
        # 保留旧字段名以兼容旧版本
        "display_stocks_count": len(display_stocks),
        "recommended_stocks": [  # 兼容旧字段
            {
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "change_pct": s["change_pct"],
                "turnover_rate": s.get("turnover_rate", 0.0),
                "volume": s.get("volume", 0),
                "amount": s.get("amount", 0.0),
                "pe": s.get("pe", 0.0),
                "pb": s.get("pb", 0.0),
                "chip_profit_ratio": (s.get("chip") or {}).get("profit_ratio", 0.0),
                "chip_avg_cost": (s.get("chip") or {}).get("avg_cost", 0.0),
                "chip_concentration_90": (s.get("chip") or {}).get("concentration_90", 0.0),
            }
            for s in display_stocks
        ],
        "chip_analysis": chip_results if 'chip_results' in locals() else [],
        "component_index": component_index,
        "llm_analysis": llm_raw,
    }

    # 构建 Telegram 消息 - 全量成分股列表
    all_stocks_count = len(stocks_sorted) if stocks else 0
    all_stocks_text = ""
    if stocks_sorted:
        for i, s in enumerate(stocks_sorted[:20], 1):  # 只展示前20只，避免消息过长
            amount = s.get('amount', 0.0)
            amount_str = f"{amount / 100000000:.2f}亿" if amount >= 100000000 else f"{amount / 10000:.2f}万" if amount > 0 else "N/A"
            turnover_str = f"{s.get('turnover_rate', 0.0):.2f}%" if s.get('turnover_rate') else "N/A"
            all_stocks_text += (
                f"{i}. {s['code']} {s['name']} {(s['change_pct'] or 0):+.2f}% "
                f"换手:{turnover_str} 成交额:{amount_str}\n"
            )
        if len(stocks_sorted) > 20:
            all_stocks_text += f"... 共 {len(stocks_sorted)} 只，此处展示前20只\n"
    else:
        all_stocks_text = "暂无成分股数据\n"

    # 构建 Telegram 消息 - 基础筛选后股票列表（换手率>3% 且成交额>3亿 且涨幅<10%）
    candidate_stocks_text = ""
    if filtered_stocks:
        for i, s in enumerate(filtered_stocks, 1):
            amount = s.get('amount', 0.0)
            amount_str = f"{amount / 100000000:.2f}亿" if amount >= 100000000 else f"{amount / 10000:.2f}万"
            candidate_stocks_text += (
                f"{i}. {s['code']} {s['name']} {(s['change_pct'] or 0):+.2f}% "
                f"换手:{s.get('turnover_rate', 0.0):.2f}% 成交额:{amount_str}\n"
            )
    else:
        candidate_stocks_text = "暂无\n"

    # 构建 Telegram 消息 - 最终筛选后股票列表（满足筹码条件 profit_ratio>50%）
    final_stocks_text = ""
    if display_stocks:
        for i, s in enumerate(display_stocks, 1):
            amount = s.get('amount', 0.0)
            amount_str = f"{amount / 100000000:.2f}亿" if amount >= 100000000 else f"{amount / 10000:.2f}万"
            chip_info = ""
            chip = s.get("chip")
            if chip:
                chip_info = f" 获利{chip['profit_ratio']*100:.1f}% 集中度{chip['concentration_90']:.2f}"
            final_stocks_text += (
                f"{i}. {s['code']} {s['name']} {(s['change_pct'] or 0):+.2f}% "
                f"换手:{s.get('turnover_rate', 0.0):.2f}% 成交额:{amount_str}{chip_info}\n"
            )
    else:
        final_stocks_text = "暂无\n"

    # Top 5 概念板块概览（从全部板块中取涨幅最高的有涨跌幅的 5 个）
    top5_text = ""
    boards_with_change = [b for b in sorted_boards if b.get("change_pct", 0) != 0][:5]
    if not boards_with_change:
        boards_with_change = sorted_boards[:5]  # fallback: 直接取前 5
    for b in boards_with_change:
        top5_text += f"  • {b['name']} {b['change_pct']:+.2f}%\n"

    # 过滤思考过程（<thinking>标签或类似内容）
    import re as re_mod
    llm_clean = re_mod.sub(r'<thinking>.*?</thinking>\s*', '', llm_raw, flags=re.DOTALL)
    llm_clean = llm_clean.strip()

    # 构建 Telegram 消息：LLM 完整输出 + 最终筛选完整列表

    # 成分股等权指数行
    if component_index:
        ci_line = (
            f"📈 **成分股等权指数**：{component_index['index_value']:.2f}"
            f"（日涨跌 {component_index['change_pct']:+.2f}%）\n\n"
        )
    else:
        ci_line = "📈 **成分股等权指数**：暂无数据\n\n"

    tg_msg = (
        f"📊 **盘前分析** {date}\n"
        f"{'━' * 26}\n\n"
        f"🎯 **推荐板块：{board_name}**\n"
        f"全量成分股：{all_stocks_count} 只\n"
        f"基础筛选后：{len(filtered_stocks)} 只\n"
        f"最终筛选后：{len(display_stocks)} 只\n\n"
        f"🔍 **筛选条件**\n"
        f"① 换手率 > 3%\n"
        f"② 成交额 > 3 亿\n"
        f"③ 涨幅 < 11%\n"
        f"④ 流通市值 < 300 亿\n"
        f"⑤ 筹码获利比例 > 50%\n\n"
        f"{'─' * 26}\n"
        f"{llm_clean}\n"
        f"{'─' * 26}\n\n"
        f"{ci_line}"
        f"📋 **最终筛选成分股**（获利比例>50%，共 {len(display_stocks)} 只）\n"
        f"{final_stocks_text}"
    )

    # Dry-run: 只打印
    if dry_run:
        print("\n[DRY-RUN] Telegram 消息预览:")
        print("─" * 40)
        print(tg_msg)
        print("─" * 40)
        print(f"\n[DRY-RUN] 报告 JSON:")
        print(json.dumps(report_data, ensure_ascii=False, indent=2))
        print("\n✅ Dry-run 完成，未保存未推送")
        return report_data

    # 发送 Telegram
    telegram_ok = True
    qq_ok = True
    if not notify:
        print("  跳过 Telegram (notify_enabled=False)")
    else:
        print("  发送 Telegram...")
        telegram_ok, qq_ok = send_both(tg_msg)

    # 保存报告
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"premarket_{date_compact}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"  报告已保存：{report_path}")
    
    # 最终完成状态
    _write_status(status_file, {
        "status": "done",
        "progress": 100,
        "current_step": "✅ 分析完成",
        "date": date,
        "board_name": board_name,
        "board_code": board_code,
        "all_stocks_count": len(stocks_sorted) if stocks else 0,
        "candidate_stocks_count": len(filtered_stocks),
        "final_stocks_count": len(display_stocks),
        "report_path": str(report_path)
    })

    # 保存板块数据库快照
    try:
        snapshot_id = save_board_snapshot(
            date=date_compact,
            period="premarket",
            board={"code": board_code, "name": board_name, "component_index": component_index},
            stocks=stocks_sorted,
            reason=llm_reason,
            catalyst=llm_catalyst,
            recommended=True,
            news_count=len(industry_news),
        )
        print(f"  数据库写入成功：snapshot_id={snapshot_id}")
    except Exception as e:
        print(f"  数据库写入失败：{e}", file=sys.stderr)

    print(f"\n{'='*40}")
    if telegram_ok and qq_ok:
        print("✅ 完成 (Telegram + QQ)")
    elif telegram_ok:
        print("✅ 完成 (Telegram OK, QQ 可能失败)")
    elif qq_ok:
        print("✅ 完成 (QQ OK, Telegram 可能失败)")
    else:
        print("⚠️ 完成（推送可能都失败了）")
    
    return report_data


# === CLI 入口 ===
def main():
    parser = argparse.ArgumentParser(description="盘前概念板块分析")
    parser.add_argument("--date", default="", help="分析日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--no-notify", action="store_true", help="不发送 Telegram")
    parser.add_argument("--dry-run", action="store_true", help="不保存不推送，只打印结果")
    parser.add_argument("--status-file", default="", help="状态文件路径")
    parser.add_argument("--auto-add", action="store_true", help="分析完成后自动添加推荐成分股到东方财富自选股")
    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y-%m-%d")
    
    # CLI 参数转 run() 参数
    # dry_run: CLI 显式 > 全局配置
    dry_run = args.dry_run or (not args.dry_run and is_dry_run())
    # notify: --no-notify 显式禁用 > 全局配置
    notify = not args.no_notify and is_notify_enabled()
    
    result = run(date=date, dry_run=dry_run, notify=notify, status_file=args.status_file, auto_add=args.auto_add)
    
    # 处理返回值
    if isinstance(result, int):
        sys.exit(result)
    elif isinstance(result, str):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
