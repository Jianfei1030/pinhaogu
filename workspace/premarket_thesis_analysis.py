#!/usr/bin/env python3
"""
盘前题材分析 (v1):
  1. 拉取全部 thesis 题材 → 取 Top N
  2. LLM（百炼 qwen3.5-plus）+ 当日新闻 → 推荐 1 个题材
  3. 拉取推荐题材成分股 → 从本地 DB（kline_1d）获取行情
  4. 生成报告 + 推送 Telegram

与 premarket_analysis.py 并存，不动现有文件。
数据源变更：行情数据从本地 DB（kline_1d）获取，而非 akshare。
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
from datetime import datetime, timedelta
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

from database import get_db_path, list_db_dates, query_kline
from config import config, LLM_BASE_URL, LLM_MODEL, LLM_PROXY, LLM_TIMEOUT, get_config
from services.runtime_state_service import is_dry_run, is_notify_enabled
from utils.push import send_both
from utils.logger import setup_logger
from news_filter import classify_news

# === thesis API 路径 ===
THESIS_ROOT = Path(__file__).parent.parent / "thesis-ingest"
sys.path.insert(0, str(THESIS_ROOT / "scripts"))
from thesis_api import list_all_thesis, get_all_thesis_stocks, get_thesis_tree_structure, get_stocks_by_nodes

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

# === 获取补充股票的价格数据 ===
def fetch_supplement_prices(stock_codes: list[str]) -> dict:
    """
    获取补充股票的实时价格数据
    使用 akshare stock_zh_a_spot_em 获取 A 股行情
    返回：{code: {name, price, change_pct, turnover_rate, volume, amount, pe, pb}, ...}
    """
    if not stock_codes:
        return {}

    result = {}

    try:
        import akshare as ak
        # 获取全部 A 股实时行情
        df = ak.stock_zh_a_spot_em()

        # 遍历需要的股票代码
        for code in stock_codes:
            # 匹配股票代码（df 中的代码是纯数字字符串）
            mask = df["代码"] == code
            if not mask.any():
                print(f"  [WARN] 未找到股票 {code} 的行情数据", file=sys.stderr)
                result[code] = None
                continue

            row = df[mask].iloc[0]
            result[code] = {
                "code": code,
                "name": row.get("名称", "未知"),
                "price": float(row.get("最新价", 0)) if row.get("最新价") else None,
                "change_pct": float(row.get("涨跌幅", 0)) if row.get("涨跌幅") else None,
                "turnover_rate": float(row.get("换手率", 0)) if row.get("换手率") else None,
                "volume": int(row.get("成交量", 0)) if row.get("成交量") else None,
                "amount": float(row.get("成交额", 0)) if row.get("成交额") else None,
                "pe": float(row.get("市盈率 - 动态", 0)) if row.get("市盈率 - 动态") else None,
                "pb": float(row.get("市净率", 0)) if row.get("市净率") else None,
            }
    except Exception as e:
        print(f"  [WARN] 获取补充股票行情失败：{e}", file=sys.stderr)
        # 失败时为所有股票返回 None 占位
        for code in stock_codes:
            result[code] = None

    return result


# === 应用白名单补充 ===
def apply_supplements(thesis_name: str, stocks: list[dict]) -> list[dict]:
    """
    应用白名单补充机制
    在 Step 3 获取成分股后调用，补充缺失的股票或移除伪概念股

    Args:
        thesis_name: 题材名称
        stocks: 原始成分股列表

    Returns:
        补充后的成分股列表
    """
    supplements = load_supplements()

    if thesis_name not in supplements:
        return stocks

    config = supplements[thesis_name]
    add_codes = config.get("add", [])
    remove_codes = config.get("remove", [])
    note = config.get("note", "")

    if not add_codes and not remove_codes:
        return stocks

    print(f"  [白名单] {thesis_name}: {note}")

    # 1. 移除伪概念股
    if remove_codes:
        original_count = len(stocks)
        stocks = [s for s in stocks if s.get("code", "") not in remove_codes]
        if len(stocks) < original_count:
            print(f"    移除 {original_count - len(stocks)} 只股票：{remove_codes}")

    # 2. 补充缺失的股票
    if add_codes:
        # 获取补充股票的价格数据
        price_data = fetch_supplement_prices(add_codes)

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


# ============================================================
# 从本地 DB 获取 A 股前一交易日行情
# ============================================================

def _is_bj_stock(code: str) -> bool:
    """判断是否为北交所股票（代码以 8 或 4 开头，6 位数字）"""
    code = str(code).strip()
    return len(code) == 6 and (code[0] in ('8', '4'))


def _get_last_available_date(market: str = "A") -> str | None:
    """
    获取本地 DB 中最近一个可用日期。
    扫描全部 A 股 DB 目录，取最大的日期。
    """
    import glob as _glob
    db_root = Path(__file__).parent / "data"
    pattern = os.path.join(db_root, market.upper(), "A*", "*.db")
    files = _glob.glob(pattern)
    if not files:
        return None
    dates = []
    for f in files:
        basename = os.path.splitext(os.path.basename(f))[0]
        dates.append(basename)
    if not dates:
        return None
    return sorted(dates)[-1]


def _fetch_stock_from_db(stock_code: str) -> dict | None:
    """
    从本地 DB（kline_1d）获取某只股票最近一个交易日的行情。
    返回 {code, name, price, change_pct, turnover_rate, volume, amount, pe, pb}
    """
    try:
        stock_code = str(stock_code).strip()
        if not stock_code:
            return None

        # 北交所股票本地 DB 无数据
        if _is_bj_stock(stock_code):
            print(f"    [INFO] {stock_code} 为北交所股票，本地 DB 无数据，跳过")
            return None

        db_root = Path(__file__).parent / "data"
        dates = list_db_dates("A", stock_code, db_dir=str(db_root))
        if not dates:
            return None

        latest_date = dates[-1]
        db_path = get_db_path("A", stock_code, latest_date)
        rows = query_kline(db_path, "kline_1d")
        if not rows:
            return None

        latest = rows[-1]
        close = latest.get("close")
        if close is None or close <= 0:
            return None

        # 计算涨跌幅（需要前一日收盘价）
        change_pct = None
        if len(rows) >= 2:
            prev_close = rows[-2].get("close")
            if prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 2)

        return {
            "code": stock_code,
            "name": stock_code,  # 名称需后续补充
            "price": round(close, 2),
            "change_pct": change_pct,
            "turnover_rate": latest.get("turnover"),
            "volume": latest.get("volume", 0),
            "amount": latest.get("amount", 0),
            "pe": None,
            "pb": None,
        }
    except Exception as e:
        print(f"  [WARN] 读取 {stock_code} DB 行情失败：{e}", file=sys.stderr)
        return None


def _fetch_bj_stock_from_sina(stock_code: str) -> dict | None:
    """
    使用新浪接口获取北交所股票行情（东财接口不可用时的 fallback）。
    使用 stock_zh_a_minute(symbol='bj{code}') 获取分钟数据，
    取最新 bar 作为当前行情。
    """
    try:
        import akshare as ak
        symbol = f"bj{stock_code}"
        df = ak.stock_zh_a_minute(symbol=symbol, period="1", adjust="")
        if df is None or df.empty:
            return None

        latest = df.iloc[-1]
        return {
            "code": stock_code,
            "name": stock_code,
            "price": float(latest.get("close", 0)),
            "change_pct": None,  # 分钟线无法计算日涨跌幅
            "turnover_rate": None,
            "volume": int(latest.get("volume", 0)),
            "amount": None,
            "pe": None,
            "pb": None,
        }
    except Exception as e:
        print(f"  [WARN] 新浪获取 {stock_code} 北交所行情失败：{e}", file=sys.stderr)
        return None


def enrich_thesis_stocks_with_market_data(thesis_name: str, stocks: list[dict]) -> list[dict]:
    """
    为题材成分股补全行情数据（从本地 DB）。

    Args:
        thesis_name: 题材名称
        stocks: [{"stock_code": "600118", "stock_name": "中国卫星"}, ...]

    Returns:
        补全后的成分股列表，每只包含 price/change_pct/turnover_rate/volume/amount
    """
    enriched = []
    total = len(stocks)
    bj_count = 0
    db_ok = 0
    db_fail = 0

    for i, s in enumerate(stocks):
        code = s.get("stock_code", "")
        name = s.get("stock_name", code)

        if not code:
            continue

        # 北交所股票：尝试新浪接口
        if _is_bj_stock(code):
            bj_count += 1
            market_data = _fetch_bj_stock_from_sina(code)
        else:
            market_data = _fetch_stock_from_db(code)

        if market_data:
            market_data["name"] = name
            enriched.append(market_data)
            db_ok += 1
        else:
            db_fail += 1

        # 进度打印（每 100 只）
        if (i + 1) % 100 == 0:
            print(f"    行情补全进度：{i+1}/{total}（成功 {db_ok}，失败 {db_fail}，北交所跳过 {bj_count}）")

    print(f"  行情补全完成：{db_ok}/{total} 只可用，{db_fail} 只无数据，{bj_count} 只北交所")
    return enriched


# ============================================================
# 筹码读取（复用现有逻辑）
# ============================================================

def load_chip_from_db(stock_code: str, market: str = "A") -> dict | None:
    """从数据库读取最新筹码数据，避免临时计算。"""
    try:
        stock_code = str(stock_code).strip()
        if not stock_code:
            return None

        # 北交所无筹码数据
        if _is_bj_stock(stock_code):
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


# ============================================================
# LLM 相关
# ============================================================

SYSTEM_PROMPT = """你是一位资深的 A 股题材分析师。你擅长从题材描述、成分股构成和财经新闻中识别最具投资价值的题材，关注政策催化、资金流向和边际变化。你的分析基于事实，不编造数据。"""


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


def llm_recommend_thesis(theses: list[dict], news_items: list[dict], date: str, api_key: str, macro_judgment: str = "", macro_summary: str = "") -> str:
    """调用 LLM 推荐 1 个题材"""
    # 构建题材文本（无涨跌幅，用描述+成分股数替代）
    theses_lines = []
    for i, t in enumerate(theses, 1):
        desc = t.get("description", "") or "无描述"
        stock_count = t.get("total_stock_count", 0) or 0
        theses_lines.append(
            f"{i}. {t['image_name']} (成分股: {stock_count}只) 描述: {desc}"
        )
    theses_text = "\n".join(theses_lines)

    # 构建新闻文本
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
        news_text = "(无新闻数据，仅基于题材排名分析)"

    # 获取监控标的文本
    watchlist_text = get_watchlist_text()

    # 宏观背景参考（仅当 macro_judgment 非空时注入）
    macro_section = ""
    if macro_judgment:
        macro_section = (
            f"宏观背景参考（仅供参考，不影响题材选择）：\n"
            f"形势判断：{macro_judgment}\n"
            f"摘要：{macro_summary}\n\n"
        )

    user_prompt = (
        f"以下是今日 ({date}) 的 **全部 A 股题材列表**（共 {len(theses)} 个）：\n\n"
        f"{theses_text}\n\n"
        f"以下是今日 ({date}) 的财经新闻摘要（共 {news_count} 条）：\n"
        f"{news_text}\n\n"
        f"{macro_section}"
        f"请基于以上题材信息和新闻，推荐 **1 个**最具盘前关注价值的题材。\n\n"
        f"要求：\n"
        f"1. 综合题材信息与新闻，识别最具投资机会的题材\n"
        f"2. 新闻必须作为推荐依据的核心支撑\n"
        f"3. 在给出推荐后，必须补充输出与该推荐题材**直接相关**的新闻，最多 10 条；如果不足 10 条，就列出全部\n"
        f"4. 相关新闻必须来自上文提供的新闻，不要编造，不要输出与推荐题材无关的新闻\n"
        f"5. **重要：大宗商品/期货价格类新闻**（如黄金、原油、铜、铁矿石等价格波动）**不作为推荐题材的直接依据**，仅用于'宏观形势判断'中分析市场整体偏向【避险/投资】的参考指标。推荐题材必须基于产业政策、公司业绩、技术突破、事件催化等与题材直接相关的新闻。\n\n"
        f"6. **监控股新闻识别**：当前监控的标的包括：{watchlist_text}。请在分析新闻时，特别识别是否与这些监控标的强相关。如果新闻与监控标的强相关，请在输出中增加一个独立章节【监控股新闻】，列出相关新闻并说明其与监控标的的关联。\n\n"
        f"输出格式（严格按此格式，内容要详细）：\n"
        f"宏观形势判断：{{当前市场整体偏向【避险/投资】，理由：...}}\n"
        f"推荐题材：{{题材名}}\n"
        f"推荐理由：{{详细分析，包括为什么这个题材值得关注，结合新闻事件、资金动向、政策催化等}}\n"
        f"关键催化：{{列出 2-3 个具体催化事件，每个事件用一句话说明}}\n"
        f"相关新闻：{{列出与推荐题材直接相关的新闻，按相关性从高到低排序，最多 10 条；不足 10 条则全部列出。每条格式为：1. [YYYY-MM-DD HH:MM:SS] [来源] 标题 | 相关性说明}}\n"
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
def parse_thesis_llm_output(raw: str) -> dict:
    """解析 LLM 返回的结构化文本（题材场景）"""
    parsed = {"raw": raw}

    # 清理 { } 包裹（LLM 有时会用花括号包裹内容）
    clean = raw.replace("{", "").replace("}", "")

    # 推荐题材
    m = re.search(r"推荐题材[：:]\s*{?\s*(.+?)\s*}?\s*$", clean, re.MULTILINE)
    if m:
        parsed["thesis_name"] = m.group(1).strip()

    # 推荐理由
    m = re.search(r"推荐理由[：:]\s*(.+?)(?:关键催化|$)", clean, re.DOTALL)
    if m:
        parsed["reason"] = m.group(1).strip()

    # 关键催化
    m = re.search(r"关键催化[：:]\s*(.+?)(?:风险提示|$)", clean, re.DOTALL)
    if m:
        parsed["catalyst"] = m.group(1).strip()

    return parsed


def parse_sub_theme_selection(llm_output: str) -> list[dict]:
    """解析 LLM 第二轮输出，返回选中的子题材列表。

    支持格式：
      1. 题材名 — 理由
      2. 题材名：理由
      2. 题材名: 理由

    最多返回 5 个，解析失败返回空列表。
    """
    results = []
    # 清理 markdown 代码块标记
    clean = re.sub(r'```[a-zA-Z]*\n?', '', llm_output)
    clean = re.sub(r'```', '', clean)

    # 匹配 "推荐子题材：" 到 "未选子题材" 之间的内容
    section_match = re.search(
        r'推荐子题材[：:]\s*\n(.*?)(?:\n\s*未选子题材|\Z)',
        clean, re.DOTALL
    )
    if not section_match:
        # fallback: 尝试匹配任意编号列表（LLM 可能不严格遵守格式）
        section_text = clean
    else:
        section_text = section_match.group(1)

    # 匹配每一行：数字. 题材名 — 理由 / 题材名: 理由 / 题材名——理由
    pattern = re.compile(
        r'\d+\.\s*'
        r'([^—\-:\n]{2,30})'       # 题材名
        r'\s*[—\-:]{1,2}\s*'        # 分隔符（支持 — / -- / : / ：）
        r'(.+?)$',                   # 理由
        re.MULTILINE
    )

    for m in pattern.finditer(section_text):
        name = m.group(1).strip()
        reason = m.group(2).strip()
        # 去除可能的 markdown 标记
        name = re.sub(r'[*_`]', '', name).strip()
        reason = re.sub(r'[*_`]', '', reason).strip()
        if name and reason:
            results.append({"node_name": name, "reason": reason})
        if len(results) >= 5:
            break

    return results


# ============================================================
# 宏观形势分析
# ============================================================

MACRO_ANALYST_PROMPT = (
    "你是一位资深的 A 股宏观策略分析师。你擅长从地缘政治、央行政策、大宗商品、"
    "宏观经济数据中判断市场整体风险偏好。你的分析基于事实，不编造数据。"
    "重点关注：地缘冲突升级/缓和、央行利率决议、原油/黄金价格异动、重要经济数据发布。"
)


def llm_macro_analysis(macro_news: list[dict], date: str, api_key: str) -> str:
    """用宏观新闻做形势分析，返回 LLM 原始输出。

    Args:
        macro_news: 宏观新闻列表，每项含 title/source/summary/date/time 等字段
        date: 分析日期 YYYY-MM-DD
        api_key: API Key（保留参数，实际由 chat_completion 内部读取配置）

    Returns:
        LLM 原始输出文本
    """
    # 格式化新闻，最多 50 条
    news_lines = []
    for i, item in enumerate(macro_news[:50], 1):
        pub_date = item.get("date", "")
        pub_time = item.get("time", "")
        timestamp = f"{pub_date} {pub_time}" if pub_date and pub_time else ""
        source = item.get("source", "")
        title = item.get("title", "").strip()
        summary = item.get("summary", "").strip()
        detail = f" | {summary[:80]}" if summary else ""
        if timestamp:
            line = f"{i}. [{timestamp}] [{source}] {title}{detail}"
        else:
            line = f"{i}. [{source}] {title}{detail}"
        news_lines.append(line)
    news_text = "\n".join(news_lines) if news_lines else "(无宏观新闻)"

    user_prompt = (
        f"以下是 {date} 的宏观新闻摘要（共 {len(macro_news[:50])} 条）：\n\n"
        f"{news_text}\n\n"
        f"请基于以上宏观新闻，对 A 股市场整体风险偏好做出形势判断。\n\n"
        f"要求输出以下 4 个部分：\n"
        f"1. 形势判断：偏乐观/偏谨慎/中性（三选一）\n"
        f"2. 一句话摘要：用一句话概括当前宏观形势的核心要点\n"
        f"3. 关键信号：列出 2-5 个支撑判断的关键信号，每行一条\n"
        f"4. 关注风险：列出 1-3 个需要重点关注的风险因素，每行一条\n\n"
        f"输出格式（严格按此格式）：\n"
        f"形势判断：{{偏乐观/偏谨慎/中性}}\n"
        f"一句话摘要：{{摘要内容}}\n"
        f"关键信号：\n"
        f"- {{信号1}}\n"
        f"- {{信号2}}\n"
        f"...\n"
        f"关注风险：\n"
        f"- {{风险1}}\n"
        f"- {{风险2}}\n"
        f"..."
    )

    content = chat_completion(
        system_prompt=MACRO_ANALYST_PROMPT,
        user_prompt=user_prompt,
        model=LLM_MODEL,
        temperature=0.3,
        max_tokens=512,
        timeout=LLM_TIMEOUT,
        verbose=True,
    )
    return content


def parse_macro_analysis(llm_output: str) -> dict:
    """解析宏观形势分析 LLM 输出，提取 4 个字段。

    Args:
        llm_output: llm_macro_analysis 的原始返回值

    Returns:
        {"judgment": str, "summary": str, "signals": list, "risks": list}
    """
    result = {
        "judgment": "",
        "summary": "",
        "signals": [],
        "risks": [],
    }

    # 清理 markdown 代码块和花括号
    clean = re.sub(r'```[a-zA-Z]*\n?', '', llm_output)
    clean = re.sub(r'```', '', clean)
    clean = clean.replace('{', '').replace('}', '')

    # 1. 形势判断
    m = re.search(r'形势判断[：:]\s*([^\n]+)', clean)
    if m:
        result["judgment"] = m.group(1).strip()

    # 2. 一句话摘要
    m = re.search(r'(?:一句话摘要|摘要)[：:]\s*([^\n]+)', clean)
    if m:
        result["summary"] = m.group(1).strip()

    # 3. 关键信号
    signals_section = re.search(r'关键信号[：:]\s*\n(.*?)(?:关注风险|\Z)', clean, re.DOTALL)
    if signals_section:
        signals_text = signals_section.group(1)
        for line in signals_text.split('\n'):
            line = line.strip().lstrip('-*• ').strip()
            if line:
                result["signals"].append(line)

    # 4. 关注风险
    risks_section = re.search(r'(?:关注)?风险[：:]\s*\n(.*?)(?:\Z)', clean, re.DOTALL)
    if risks_section:
        risks_text = risks_section.group(1)
        for line in risks_text.split('\n'):
            line = line.strip().lstrip('-*• ').strip()
            if line:
                result["risks"].append(line)

    return result


def llm_select_sub_themes(tree: dict, news: list, root_theme: str, date: str, macro_parsed: dict = None) -> str:
    """调用 LLM 从子题材树中选出最多 5 个核心子题材。

    Args:
        tree: get_thesis_tree_structure() 的返回值
        news: 当日新闻列表
        root_theme: 根题材名
        date: 分析日期 YYYY-MM-DD
        macro_parsed: parse_macro_analysis() 返回值（可选），用于注入宏观形势摘要

    Returns:
        LLM 原始输出文本
    """
    # 构建子题材结构文本
    first_levels = tree.get("first_levels", [])
    tree_lines = []
    for fl in first_levels:
        name = fl.get("name", "")
        desc = (fl.get("description") or "").strip()
        stock_count = fl.get("stock_count", 0)
        second_names = [sl.get("name", "") for sl in fl.get("second_levels", [])]
        second_str = "、".join(second_names) if second_names else "无"
        line = f"- {name}（成分股: {stock_count}只）"
        if desc:
            line += f" 描述: {desc}"
        line += f" 二级题材: {second_str}"
        tree_lines.append(line)
    tree_text = "\n".join(tree_lines) if tree_lines else "(无子题材数据)"

    # 取最近 30 条新闻标题
    news_lines = []
    # 加入宏观形势摘要
    if macro_parsed and macro_parsed.get("judgment"):
        macro_summary = f"宏观形势: {macro_parsed['judgment']}"
        if macro_parsed.get("summary"):
            macro_summary += f" — {macro_parsed['summary']}"
        news_lines.append(f"- [宏观] {macro_summary}")
    for item in news[:30]:
        title = item.get("title", "").strip()
        if title:
            source = item.get("source", "")
            news_lines.append(f"- [{source}] {title}")
    news_text = "\n".join(news_lines) if news_lines else "(无相关新闻)"

    user_prompt = (
        f"你是一位资深A股题材分析师。今天是{date}，请从「{root_theme}」题材的子题材中选出最多5个今日最具爆发力的核心子题材。\n\n"
        f"## {root_theme} 子题材结构\n"
        f"{tree_text}\n\n"
        f"## 近期新闻（供判断催化用）\n"
        f"{news_text}\n\n"
        f"请基于以下维度选出子题材：\n"
        f"1. 新闻催化：近期是否有明确的政策、业绩、事件催化\n"
        f"2. 产业趋势：是否处于产业上升周期\n"
        f"3. 资金关注：是否为当前市场热点\n\n"
        f"输出格式：\n"
        f"推荐子题材：\n"
        f"1. 题材名 — 推荐理由（一句话）\n"
        f"2. 题材名 — 推荐理由\n\n"
        f"未选子题材：未选的理由简述（一句话）"
    )

    content = chat_completion(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=LLM_MODEL,
        temperature=0.3,
        max_tokens=1024,
        timeout=LLM_TIMEOUT,
        verbose=True,
    )
    return content


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
    加载盘前新闻：
    - 周二~周五：前一天 16:10 ~ 当天全天
    - 周六：周五 16:10 ~ 周六全天
    - 周日：周五 16:10 ~ 周日全天
    - 周一：周五 16:10 ~ 周一全天
    """
    SCRIPT_DIR = Path(__file__).parent
    NEWS_DIR = SCRIPT_DIR / "news_data"

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
    print(f"  正在用 embedding 分类宏观/产业...")
    macro_news, industry_news = classify_news(all_news)
    print(f"  分类结果: 宏观 {len(macro_news)} 条, 产业 {len(industry_news)} 条")
    return macro_news, industry_news


def load_news(date: str) -> list[dict]:
    SCRIPT_DIR = Path(__file__).parent
    NEWS_DIR = SCRIPT_DIR / "news_data"
    news_file = NEWS_DIR / f"financial_news_{date}.json"
    if not news_file.exists():
        print(f"  新闻文件不存在: {news_file}（将仅基于题材排名分析）")
        return []
    with open(news_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  新闻文件: {news_file.name} | 共 {len(data)} 条")
    return data


# ============================================================
# 成分股等权指数计算
# ============================================================

def _calc_thesis_component_index(display_stocks: list[dict], analysis_date: str) -> dict | None:
    """
    计算题材成分股等权指数。

    参数:
        display_stocks: 最终筛选的成分股列表（含 code, price/close 字段）
        analysis_date: 分析日期 YYYY-MM-DD

    返回:
        {index_value, change_pct, n_stocks} 或 None（失败时不阻塞主流程）
    """
    try:
        import sqlite3

        db_root = str(Path(__file__).parent / "data")
        stocks_data = {}

        for s in display_stocks:
            code = str(s.get("code", "")).strip()
            if not code:
                continue
            if _is_bj_stock(code):
                continue

            try:
                dates = list_db_dates("A", code, db_dir=db_root)
                if not dates:
                    continue

                # Use dict to deduplicate by date (later files may overlap with earlier ones)
                date_close: dict[str, float] = {}
                for d in dates:
                    db_path = get_db_path("A", code, d)
                    if not Path(db_path).exists():
                        continue
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT bar_time, close FROM kline_1d WHERE close IS NOT NULL")
                    rows = cursor.fetchall()
                    conn.close()
                    for row in rows:
                        bt = str(row[0])
                        close = row[1]
                        if bt and close is not None:
                            date_close[bt] = float(close)

                if len(date_close) < 2:
                    continue

                sorted_items = sorted(date_close.items())
                stocks_data[code] = {"dates": [d for d, _ in sorted_items], "closes": [c for _, c in sorted_items]}
            except Exception:
                continue

        if len(stocks_data) < 2:
            return None

        df = calc_equal_weight_index(stocks_data, base_date="2024-01-01", base_value=1000.0)

        if df is None or df.empty:
            return None

        latest = df.iloc[-1]
        return {
            "index_value": round(float(latest["index_value"]), 2),
            "change_pct": round(float(latest["pct_change"]) * 100, 2),
            "n_stocks": len(stocks_data),
        }
    except Exception as e:
        print(f"  [WARN] 成分股等权指数计算失败：{e}", file=sys.stderr)
        return None


# ============================================================
# Job Runner 入口
# ============================================================

def run(date: str | None = None, dry_run: bool | None = None, notify: bool | None = None, status_file: str = "", auto_add: bool = False) -> dict | str | int:
    """
    盘前题材分析 Job Runner 入口

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
    if dry_run is None:
        dry_run = is_dry_run()
    if notify is None:
        notify = is_notify_enabled()

    date_compact = date.replace("-", "")

    # 非交易日降级提示：使用上一交易日数据继续分析
    if not is_trading_day(date):
        print(f"⚠️ {date} 为非交易日，将使用上一交易日数据进行分析")

    print(f"=== {date} 盘前题材分析 ===\n")

    # 写入初始状态
    _write_status(status_file, {"status": "loading", "progress": 0, "date": date})

    api_key = load_api_key()
    if not api_key:
        msg = "ERROR: BAILIAN_API_KEY 未设置（阿里百炼 Coding Plan API）"
        print(msg, file=sys.stderr)
        return msg

    SCRIPT_DIR = Path(__file__).parent
    REPORT_DIR = SCRIPT_DIR / "reports"

    # ── Step 1: 拉取全部题材 ──
    print("[1/5] 拉取题材列表...")
    theses = list_all_thesis()
    if not theses:
        msg = "ERROR: 未获取到题材数据（thesis.db）"
        print(msg, file=sys.stderr)
        _write_status(status_file, {"status": "error", "current_step": "未获取到题材数据", "date": date})
        return msg
    print(f"  共 {len(theses)} 个题材")

    # Step 1 完成
    _write_status(status_file, {"status": "loading", "progress": 20, "current_step": "题材数据获取完成", "date": date})

    # 全部题材用于报告展示（按成分股数降序）
    sorted_theses = sorted(theses, key=lambda x: x.get("total_stock_count", 0) or 0, reverse=True)
    top_name = sorted_theses[0].get("image_name", "N/A")
    top_count = sorted_theses[0].get("total_stock_count", 0)
    print(f"  全部 {len(theses)} 个题材已就绪，最大题材：{top_name} ({top_count}只成分股)")

    # ── Step 2: 新闻过滤 + 宏观分析 ──
    print(f"\n[2/5] 新闻过滤 + 宏观分析...")
    macro_news, industry_news = load_premarket_news(date)

    # 宏观形势分析
    macro_raw = llm_macro_analysis(macro_news, date, api_key)
    print(f"\n  宏观分析原始输出:\n{'─'*40}\n{macro_raw}\n{'─'*40}\n")
    macro_parsed = parse_macro_analysis(macro_raw)
    print(f"  形势判断: {macro_parsed.get('judgment', '')}")
    print(f"  摘要: {macro_parsed.get('summary', '')}")
    if macro_parsed.get('signals'):
        print(f"  关键信号: {', '.join(macro_parsed['signals'])}")
    if macro_parsed.get('risks'):
        print(f"  关注风险: {', '.join(macro_parsed['risks'])}")

    # Step 2 完成
    _write_status(status_file, {"status": "loading", "progress": 40, "current_step": "宏观分析完成", "macro_news": len(macro_news), "industry_news": len(industry_news), "date": date})

    # ── Step 3: LLM 推荐 1 个题材 ──
    print(f"\n[3/5] LLM 题材推荐 ({LLM_MODEL})...")
    llm_raw = llm_recommend_thesis(theses, industry_news, date, api_key)
    print(f"\n  LLM 原始输出:\n{'─'*40}\n{llm_raw}\n{'─'*40}\n")

    # Step 3 完成
    _write_status(status_file, {"status": "analyzing", "progress": 60, "current_step": "LLM 题材推荐完成", "news_count": len(industry_news), "date": date})

    # 解析 LLM 输出
    parsed = parse_thesis_llm_output(llm_raw)
    thesis_name = parsed.get("thesis_name", "")
    llm_reason = parsed.get("reason", "")
    llm_catalyst = parsed.get("catalyst", "")

    if not thesis_name:
        msg = "ERROR: LLM 未能解析出推荐题材"
        print(msg, file=sys.stderr)
        print(f"原始输出:\n{llm_raw}", file=sys.stderr)
        _write_status(status_file, {"status": "error", "current_step": "LLM 未能解析出推荐题材", "date": date})
        return msg

    print(f"  推荐题材：{thesis_name}")

    # ── Step 3.5: LLM 子题材精筛 ──
    print(f"\n[3.5/5] LLM 子题材精筛...")
    selected_sub_themes = []
    raw_stocks = []

    try:
        # 1. 获取子题材树
        tree = get_thesis_tree_structure(thesis_name)
        print(f"  子题材树: {tree['total_first']} 个一级, {tree['total_second']} 个二级")

        # 2. LLM 选子题材
        llm_sub_output = llm_select_sub_themes(tree, industry_news, thesis_name, date, macro_parsed)
        print(f"  LLM 原始输出: {llm_sub_output[:200]}...")
        selected_sub_themes = parse_sub_theme_selection(llm_sub_output)
        print(f"  选中 {len(selected_sub_themes)} 个子题材:")
        for s in selected_sub_themes:
            print(f"    - {s['node_name']}: {s['reason'][:40]}")

        # 3. 根据选中的子题材名找到对应的 node_id
        selected_node_ids = []
        for sel in selected_sub_themes:
            for fl in tree["first_levels"]:
                if fl["name"] == sel["node_name"]:
                    selected_node_ids.append(fl["node_id"])
                    break
                for sl in fl["second_levels"]:
                    if sl["name"] == sel["node_name"]:
                        selected_node_ids.append(sl["node_id"])
                        break

        if not selected_node_ids:
            print("  ⚠ 未匹配到选中子题材的 node_id，使用全部一级题材")
            selected_node_ids = [fl["node_id"] for fl in tree["first_levels"]]
        else:
            print(f"  选中 node_ids: {selected_node_ids}")

        # 4. 获取精选成分股
        raw_stocks = get_stocks_by_nodes(thesis_name, selected_node_ids)
        print(f"  核心子题材成分股: {len(raw_stocks)} 只（去重后）")

    except Exception as e:
        print(f"  ⚠ 子题材精筛失败（{e}），fallback 到全部成分股")
        raw_stocks = get_all_thesis_stocks(thesis_name)
        if not raw_stocks:
            msg = f"ERROR: 未获取到 [{thesis_name}] 成分股数据"
            print(msg, file=sys.stderr)
            _write_status(status_file, {"status": "error", "current_step": "未获取到成分股数据", "date": date})
            return msg
        print(f"  Fallback: 全部成分股 {len(raw_stocks)} 只")

    if not raw_stocks:
        msg = f"ERROR: 未获取到 [{thesis_name}] 成分股数据"
        print(msg, file=sys.stderr)
        _write_status(status_file, {"status": "error", "current_step": "未获取到成分股数据", "date": date})
        return msg

    # ── Step 4: 行情补全 ──
    print(f"\n[4/5] 拉取 [{thesis_name}] 成分股行情...")

    # 应用白名单补充
    raw_stocks_dict = [{"stock_code": s["stock_code"], "stock_name": s["stock_name"]} for s in raw_stocks]
    stocks_supplemented = apply_supplements(thesis_name, [])  # 白名单机制预留，默认不补充
    if stocks_supplemented:
        # 如果白名单有补充，合并
        existing_codes = {s["stock_code"] for s in raw_stocks_dict}
        for s in stocks_supplemented:
            if s.get("code") and s["code"] not in existing_codes:
                raw_stocks_dict.append({"stock_code": s["code"], "stock_name": s.get("name", s["code"])})

    # 补全行情数据（从本地 DB）
    print(f"\n[4.5/5] 从本地 DB 补全行情...")
    enriched_stocks = enrich_thesis_stocks_with_market_data(thesis_name, raw_stocks_dict)

    if enriched_stocks:
        stocks_sorted = sorted(enriched_stocks, key=lambda x: x.get("change_pct") or 0, reverse=True)
        leader_chg = stocks_sorted[0].get("change_pct") or 0
        print(f"  有行情 {len(stocks_sorted)} 只，领涨：{stocks_sorted[0]['name']} ({leader_chg:+.2f}%)")

        # 基础筛选：换手率 > 3% 且成交额 > 3 亿 且涨幅 < 10%
        filtered_stocks = [s for s in stocks_sorted
                          if (s.get("turnover_rate") or 0) > 3
                          and (s.get("amount") or 0) > 300000000
                          and (s.get("change_pct") or 0) < 10]
        if filtered_stocks:
            pre_filter_count = len([s for s in stocks_sorted
                                   if (s.get("turnover_rate") or 0) > 3
                                   and (s.get("amount") or 0) > 300000000])
            print(f"  全量 {len(stocks_sorted)} 只，基础筛选后（换手率>3% 且成交额>3亿 且涨幅<10%）：{len(filtered_stocks)} 只")

            print(f"\n[4.6/5] 读取数据库筹码分布...")
            enriched_stocks_chip = enrich_stocks_with_chip_data(filtered_stocks, market="A")
            chip_ready_count = sum(1 for s in enriched_stocks_chip if (s.get("chip") or {}).get("profit_ratio") is not None)
            print(f"  数据库筹码数据可用：{chip_ready_count}/{len(enriched_stocks_chip)} 只")

            # Step 4 完成
            _write_status(status_file, {"status": "analyzing", "progress": 80, "current_step": "成分股分析完成", "date": date})

            chip_results = []
            for stock in enriched_stocks_chip:
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

            # 仅保留数据库中已满足筹码条件的成分股
            display_stocks = [s for s in enriched_stocks_chip if (s.get("chip") or {}).get("profit_ratio", 0) > 0.5]
            print(f"  获利比例 > 50% 过滤后：{len(display_stocks)} 只")
        else:
            print(f"  [INFO] 暂无同时满足 换手率 > 3% 且成交额 > 3 亿 的成分股")
            enriched_stocks_chip = []
            chip_ready_count = 0
            display_stocks = []
            chip_results = []
    else:
        stocks_sorted = []
        filtered_stocks = []
        enriched_stocks_chip = []
        chip_ready_count = 0
        display_stocks = []
        chip_results = []
        print(f"  未获取到有行情的成分股数据（本地 DB 可能缺少该题材成分股数据）")

    # ── 自动添加自选股 ──
    if auto_add and display_stocks:
        auto_add_to_watchlist(display_stocks)

    # ── 成分股等权指数 ──
    component_index = _calc_thesis_component_index(display_stocks, date)
    if component_index:
        print(f"  📈 成分股等权指数: {component_index['index_value']:.2f}（日涨跌 {component_index['change_pct']:+.2f}%，{component_index['n_stocks']} 只）")
    else:
        print(f"  📈 成分股等权指数: 暂无数据")

    # ── Step 5: 生成报告 + 推送 ──
    print(f"\n[5/5] 生成报告...")

    # Step 5 开始
    _write_status(status_file, {"status": "saving", "progress": 90, "current_step": "保存报告中", "date": date})

    # 构建报告数据
    report_data = {
        "date": date,
        "type": "premarket_thesis",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "top_theses": [
            {
                "rank": i + 1,
                "name": t["image_name"],
                "description": t.get("description", ""),
                "total_stock_count": t.get("total_stock_count", 0),
                "node_count": t.get("node_count", 0),
            }
            for i, t in enumerate(theses)
        ],
        "recommended_thesis": {
            "name": thesis_name,
            "root_theme": thesis_name,
            "selected_sub_themes": [
                {
                    "node_name": s["node_name"],
                    "reason": s["reason"],
                }
                for s in selected_sub_themes
            ],
            "logic": llm_reason,
            "catalyst": llm_catalyst,
            "total_stock_count": len(raw_stocks),
            "enriched_count": len(enriched_stocks) if 'enriched_stocks' in dir() else 0,
        },
        # 三层结构（报告只保留最终筛选结果，全量/基础筛选仅保留 count）
        "all_stocks_count": len(stocks_sorted) if stocks_sorted else 0,
        "candidate_stocks_count": len(filtered_stocks) if filtered_stocks else 0,
        "chip_ready_count": chip_ready_count,
        "final_stocks_count": len(display_stocks) if display_stocks else 0,
        "all_stocks": [],
        "candidate_stocks": [],
        "final_stocks": [
            {
                "code": s["code"],
                "name": s["name"],
                "price": s["price"],
                "change_pct": s["change_pct"],
                "turnover_rate": s.get("turnover_rate", 0.0),
                "volume": s.get("volume", 0),
                "amount": s.get("amount", 0.0),
                "chip_profit_ratio": (s.get("chip") or {}).get("profit_ratio", 0.0),
                "chip_avg_cost": (s.get("chip") or {}).get("avg_cost", 0.0),
                "chip_concentration_90": (s.get("chip") or {}).get("concentration_90", 0.0),
            }
            for s in (display_stocks if display_stocks else [])
        ],
        "chip_analysis": chip_results if 'chip_results' in dir() else [],
        "llm_analysis": llm_raw,
        "macro_analysis": macro_parsed if 'macro_parsed' in dir() else None,
        "component_index": component_index,
    }

    # 构建 Telegram 消息 - 最终筛选后股票列表（唯一输出）
    final_stocks_text = ""
    if display_stocks:
        for i, s in enumerate(display_stocks, 1):
            amount = s.get('amount', 0.0)
            amount_str = f"{amount / 100000000:.2f}亿" if amount >= 100000000 else f"{amount / 10000:.2f}万"
            chg = s.get('change_pct')
            chg_str = f"{chg:+.2f}%" if chg is not None else "N/A"
            chip_info = ""
            chip = s.get("chip")
            if chip:
                chip_info = f" 获利{chip['profit_ratio']*100:.1f}% 集中度{chip['concentration_90']:.2f}"
            final_stocks_text += (
                f"{i}. {s['code']} {s['name']} {chg_str} "
                f"换手:{s.get('turnover_rate', 0.0):.2f}% 成交额:{amount_str}{chip_info}\n"
            )
    else:
        final_stocks_text = "暂无\n"

    # 过滤思考过程
    llm_clean = re.sub(r'<thinking>.*?</thinking>\s*', '', llm_raw, flags=re.DOTALL)
    llm_clean = llm_clean.strip()

    # 构建 Telegram 消息（仅输出最终筛选结果）
    # 子题材层级展示
    sub_theme_text = ""
    if selected_sub_themes:
        sub_lines = []
        for i, s in enumerate(selected_sub_themes, 1):
            sub_lines.append(f"  {i}. {s['node_name']} — {s['reason'][:50]}")
        sub_theme_text = "\n".join(sub_lines) + "\n"
    else:
        sub_theme_text = "  （未精筛，使用全部子题材）\n"

    # 宏观形势行
    macro_line = ""
    if macro_parsed and macro_parsed.get("judgment"):
        macro_j = macro_parsed["judgment"]
        macro_s = macro_parsed.get("summary", "")
        macro_line = f"🌍 宏观形势: {macro_j} — {macro_s}\n\n"

    # 成分股等权指数行
    if component_index:
        ci = component_index
        component_index_line = f"📈 成分股等权指数：{ci['index_value']:.2f}（日涨跌 {ci['change_pct']:+.2f}%，{ci['n_stocks']} 只）\n\n"
    else:
        component_index_line = "📈 成分股等权指数：暂无数据\n\n"

    tg_msg = (
        f"📊 **盘前题材分析** {date}\n"
        f"{'━' * 26}\n\n"
        f"{macro_line}"
        f"🎯 **推荐题材：{thesis_name}**\n"
        f"{'─' * 26}\n"
        f"🔍 **核心子题材**（{len(selected_sub_themes)} 个）\n"
        f"{sub_theme_text}\n"
        f"成分股总数：{len(raw_stocks)} 只 | 有行情：{len(stocks_sorted)} 只 | 基础筛选后：{len(filtered_stocks)} 只 | 最终筛选后：{len(display_stocks)} 只\n\n"
        f"{'─' * 26}\n"
        f"{llm_clean}\n"
        f"{'─' * 26}\n\n"
        f"{component_index_line}"
        f"📋 **最终筛选结果**（获利比例>50%，共 {len(display_stocks)} 只）\n"
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
    report_path = REPORT_DIR / f"premarket_thesis_{date_compact}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"  报告已保存：{report_path}")

    # 最终完成状态
    _write_status(status_file, {
        "status": "done",
        "progress": 100,
        "current_step": "✅ 分析完成",
        "date": date,
        "thesis_name": thesis_name,
        "all_stocks_count": len(stocks_sorted) if stocks_sorted else 0,
        "candidate_stocks_count": len(filtered_stocks) if filtered_stocks else 0,
        "final_stocks_count": len(display_stocks) if display_stocks else 0,
        "report_path": str(report_path)
    })

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
    parser = argparse.ArgumentParser(description="盘前题材分析")
    parser.add_argument("--date", default="", help="分析日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--no-notify", action="store_true", help="不发送 Telegram")
    parser.add_argument("--dry-run", action="store_true", help="不保存不推送，只打印结果")
    parser.add_argument("--status-file", default="", help="状态文件路径")
    parser.add_argument("--auto-add", action="store_true", help="分析完成后自动添加推荐成分股到东方财富自选股")
    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    # CLI 参数转 run() 参数
    dry_run = args.dry_run or (not args.dry_run and is_dry_run())
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
