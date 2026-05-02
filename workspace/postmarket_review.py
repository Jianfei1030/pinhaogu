#!/usr/bin/env python3
"""
盘后复盘主脚本 (v1):
  1. 读取当日盘前报告
  2. 拉取推荐板块收盘数据
  3. LLM 复盘分析
  4. 生成报告 + 推送 Telegram
"""

import json
import os
import re
import ssl
import sys
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# === 复用模块 ===
sys.path.insert(0, str(Path(__file__).parent))
from concept_board_em import fetch_all_boards as fetch_all_boards_em
from concept_board import fetch_board_stocks
from board_db import save_board_snapshot
from database import get_db_path, list_db_dates, query_kline


def _calc_review_component_index(
    display_stocks: list[dict],
    review_date: str,
    premarket_index_value: float,
) -> dict | None:
    """
    计算复盘成分股等权指数。

    从本地数据库读取 display_stocks 中各股票在 review_date 及前一交易日的收盘价，
    调用 calc_equal_weight_index 计算复盘等权指数，并与盘前基线对比。

    失败时返回 None，不阻塞主流程。
    """
    if not display_stocks:
        return None

    try:
        stocks_data: dict[str, dict] = {}
        db_root = Path(__file__).parent / "data"

        for s in display_stocks:
            code = str(s.get("code", "")).strip()
            if not code:
                continue
            try:
                dates = list_db_dates("A", code, db_dir=str(db_root))
                if not dates:
                    continue

                # 读取所有历史日期的 kline_1d 数据，用 dict 去重（首日 DB 含历史全量，后续文件会重叠）
                date_close: dict[str, float] = {}
                for d in dates:
                    db_path = get_db_path("A", code, d)
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
            print(f"  [WARN] 复盘等权指数：无法获取任何成分股的历史数据", file=sys.stderr)
            return None

        df = calc_equal_weight_index(stocks_data)
        if df is None or df.empty:
            print(f"  [WARN] 复盘等权指数计算返回空结果", file=sys.stderr)
            return None

        latest = df.iloc[-1]
        review_index_value = float(latest["index_value"])
        review_daily_change = float(latest.get("pct_change", 0))

        # 相对于盘前基线的变化
        index_change_pct = (review_index_value - premarket_index_value) / premarket_index_value * 100

        # 找出最佳/最差个股（从数据库中读取 review_date 当天的涨跌幅）
        best_stock = None
        worst_stock = None
        best_chg = -999
        worst_chg = 999
        for s in display_stocks:
            code = str(s.get("code", "")).strip()
            if code not in stocks_data:
                continue
            sd = stocks_data[code]
            # 找 review_date 对应的索引
            for i, d in enumerate(sd["dates"]):
                if d == review_date or d.startswith(review_date):
                    if i > 0:
                        prev_close = sd["closes"][i - 1]
                        curr_close = sd["closes"][i]
                        chg = (curr_close - prev_close) / prev_close * 100
                        if chg > best_chg:
                            best_chg = chg
                            best_stock = {"code": code, "name": s.get("name", ""), "change_pct": round(chg, 2)}
                        if chg < worst_chg:
                            worst_chg = chg
                            worst_stock = {"code": code, "name": s.get("name", ""), "change_pct": round(chg, 2)}
                    break

        print(f"  📊 复盘成分股等权指数:{review_index_value:.2f}(相对盘前 {index_change_pct:+.2f}%,{len(stocks_data)} 只)")

        return {
            "index_value": round(review_index_value, 2),
            "change_pct": round(index_change_pct, 2),
            "daily_change_pct": round(review_daily_change, 4),
            "n_stocks": len(stocks_data),
            "best_stock": best_stock or {"code": "", "name": "N/A", "change_pct": 0},
            "worst_stock": worst_stock or {"code": "", "name": "N/A", "change_pct": 0},
        }

    except Exception as e:
        print(f"  [WARN] 复盘等权指数计算失败：{e}", file=sys.stderr)
        return None


def fetch_all_boards_with_fallback() -> list[dict]:
    """
    获取全部板块列表,东财失败时 fallback 到同花顺
    返回的板块数据包含 change_pct 字段
    """
    # 先尝试东财
    boards = fetch_all_boards_em()
    if boards:
        print(f"  数据源:东方财富({len(boards)} 个板块)")
        return boards

    # 东财失败,fallback 到同花顺
    print("  东财板块列表获取失败,使用同花顺数据源")
    try:
        from concept_board_ths import fetch_all_boards as fetch_all_boards_ths
        boards = fetch_all_boards_ths()
        if boards:
            print(f"  数据源:同花顺({len(boards)} 个板块)")
            return boards
    except Exception as e:
        print(f"  同花顺 fallback 也失败:{e}", file=sys.stderr)

    return []

from config import config, LLM_BASE_URL, LLM_MODEL, LLM_PROXY, LLM_TIMEOUT, get_config
from services.runtime_state_service import is_dry_run, is_notify_enabled
from utils.push import send_both
from utils.logger import setup_logger
from utils.component_index import calc_equal_weight_index


def _write_status(path: str, data: dict):
    """写入状态文件(供 server.py 读取进度)"""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


SCRIPT_DIR = Path(__file__).parent
NEWS_DIR = SCRIPT_DIR / "news_data"
REPORT_DIR = Path(__file__).parent / "reports"

# === LLM Prompt ===
SYSTEM_PROMPT = """你是一位资深的 A 股市场复盘分析师。你擅长从盘前预测与盘后数据的对比中总结经验教训,结合当日新闻事件分析市场实际走势。你的分析基于事实,不编造数据。"""


def load_api_key():
    """从环境变量读取阿里百炼 Coding Plan API Key"""
    return config.llm.api_key


# === Step 1: 读取盘前报告 ===
def find_latest_premarket_report(from_date: str, max_lookback: int = 7) -> tuple[dict | None, str | None]:
    """
    从 from_date 开始往前找最近的盘前报告(兼容概念版/题材版)。
    最多往前看 max_lookback 天。
    返回 (报告数据, 报告日期 YYYY-MM-DD),找不到返回 (None, None)。
    """
    from_date_dt = datetime.strptime(from_date, "%Y-%m-%d")
    for i in range(max_lookback):
        check_dt = from_date_dt - timedelta(days=i)
        check_date = check_dt.strftime("%Y-%m-%d")
        check_compact = check_date.replace("-", "")

        # 先找题材版,再找概念版
        for prefix in ["premarket_thesis", "premarket"]:
            candidate = REPORT_DIR / f"{prefix}_{check_compact}.json"
            if candidate.exists():
                with open(candidate, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"  盘前报告: {candidate.name}({check_date},{'题材' if prefix == 'premarket_thesis' else '概念'})")
                return data, check_date

    return None, None


# === Step 2: 拉取推荐板块收盘数据 ===
def fetch_closing_board(board_name: str, board_code: str = "") -> tuple[list[dict], None]:
    """拉取指定板块成分股,返回 (stocks, None)

    Args:
        board_name: 板块名称
        board_code: 板块代码(可选,如果提供则直接用代码查询,避免名称匹配问题)
    """
    # 如果提供了板块代码,直接用代码查询(避免名称匹配问题)
    if board_code:
        try:
            from concept_board import fetch_board_stocks_by_code
            stocks = fetch_board_stocks_by_code(board_code)
            if stocks:
                print(f"  成分股查询:使用板块代码 {board_code},获取 {len(stocks)} 只股票")
                return stocks, None
        except Exception as e:
            print(f"  [WARNING] 用代码查询失败:{e},回退到名称查询")

    # 没有代码或代码查询失败,用名称查询
    stocks = fetch_board_stocks(board_name)
    return stocks, None


def find_ths_code_by_name(board_name: str) -> str:
    """
    通过板块名称查找同花顺板块代码
    用于解决东财和同花顺板块名称不一致的问题
    """
    try:
        from concept_board_ths import fetch_all_boards
        boards = fetch_all_boards()

        # 精确匹配
        for board in boards:
            if board["name"] == board_name:
                return board["code"]

        # 模糊匹配:检查是否包含关键词
        # 例如:东财"油气资源" -> 同花顺"油气开采及服务"
        keywords = board_name.replace("资源", "").replace("板块", "").replace("概念", "").strip()
        for board in boards:
            if keywords in board["name"] or board["name"] in keywords:
                print(f"  名称匹配:{board_name} -> {board['name']} ({board['code']})")
                return board["code"]

        return ""
    except Exception as e:
        print(f"  [WARNING] 查找同花顺代码失败:{e}")
        return ""


# === Step 3: 加载新闻 ===
def load_news(date: str) -> list[dict]:
    """加载当日新闻 JSON"""
    news_file = NEWS_DIR / f"financial_news_{date}.json"
    if not news_file.exists():
        print(f"  新闻文件不存在: {news_file}(将仅基于板块数据复盘)")
        return []
    with open(news_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  新闻文件: {news_file.name} | 共 {len(data)} 条")
    return data


# === Step 3: LLM 复盘 (已迁移至 services.llm_service) ===
from services.llm_service import chat_completion


def llm_review(
    sector_name: str,
    sector_code: str,
    logic: str,
    premarket_index: float | None,
    review_component_index: dict | None,
    best_stock: dict,
    worst_stock: dict,
    news_items: list[dict],
    date: str,
    api_key: str,
) -> str:
    """调用 LLM 进行复盘分析"""

    # 构建新闻摘要
    news_text = ""
    if news_items:
        news_lines = []
        for i, item in enumerate(news_items, 1):
            title = item.get("title", "").strip()
            if len(title) < 5:
                continue
            source = item.get("source", "")
            summary = item.get("summary", "").strip()
            line = f"{i}. [{source}] {title}"
            if summary and summary != title:
                line += f" | {summary[:100]}"
            news_lines.append(line)
        news_text = "\n".join(news_lines[:80])
    if not news_text:
        news_text = "(无新闻数据)"

    # 等权指数对比
    if premarket_index is not None and review_component_index is not None:
        review_idx = review_component_index["index_value"]
        idx_change = review_component_index["change_pct"]
        index_line = f"盘前等权指数: {premarket_index:.2f} → 复盘等权指数: {review_idx:.2f}（{idx_change:+.2f}%）\n"
        if idx_change > 0.5:
            verdict_str = "指数走高 (赚钱)"
        elif idx_change < -0.5:
            verdict_str = "指数回落 (亏钱)"
        else:
            verdict_str = "指数持平 (不赚不亏)"
        post_line = f"指数变化: {idx_change:+.2f}% ({verdict_str})"
    else:
        index_line = ""
        post_line = "收盘等权指数: 无记录"

    user_prompt = (
        f"盘前推荐板块: {sector_name} ({sector_code})\n"
        f"盘前推荐理由: {logic}\n"
        f"{index_line}"
        f"{post_line}\n\n"
        f"成分股最佳: {best_stock['name']} ({best_stock['change_pct']:+.2f}%)\n"
        f"成分股最差: {worst_stock['name']} ({worst_stock['change_pct']:+.2f}%)\n\n"
        f"今日相关新闻摘要:\n{news_text}\n\n"
        f"请从真实交易视角进行复盘分析:\n"
        f"1. 推荐方向评价（等权指数变化，方向是否正确）\n"
        f"2. 实际走势原因分析（结合新闻，分析为何走强/走弱）\n"
        f"3. 经验教训\n\n"
        f"要求：\n"
        f"- 适合 Telegram 阅读，简洁有力\n"
        f"- 用 emoji 但不要过度\n"
        f"- 每个要点 2-3 句话\n"
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


# === Telegram 发送 ===
def split_telegram(text: str, max_len: int = 4000) -> list[str]:
    """按段落分片,避免超 Telegram 4096 字符限制"""
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


# === Job Runner 入口 ===
def run(date: str | None = None, dry_run: bool | None = None, notify: bool | None = None, status_file: str = "") -> dict | str | int:
    """
    盘后复盘分析 Job Runner 入口

    Args:
        date: 复盘日期 YYYY-MM-DD,默认今天
        dry_run: 干跑模式(不保存不推送),CLI > env > yaml > default
        notify: 是否推送,CLI > env > yaml > default

    Returns:
        dict: 报告数据(成功)
        str: 错误信息(失败)
        int: 退出码(0=成功,1=失败)
    """
    # 默认值处理
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # 开关优先级:CLI 显式参数 > 全局配置 > 代码默认值
    # 已迁移至 runtime_state_service:底层读取 config.runtime.*
    if dry_run is None:
        dry_run = is_dry_run()
    if notify is None:
        notify = is_notify_enabled()

    date_compact = date.replace("-", "")

    # 盘后复盘可在任何日期执行(非交易日仍可基于最近的盘前报告复盘)

    print(f"=== {date} 盘后复盘分析 ===\n")

    # 写入初始状态
    _write_status(status_file, {"status": "loading", "progress": 0, "date": date})

    api_key = load_api_key()
    if not api_key:
        msg = "ERROR: BAILIAN_API_KEY 未设置(阿里百炼 Coding Plan API)"
        print(msg, file=sys.stderr)
        return msg

    # ── Step 1: 读取盘前报告(往前找最近的) ──
    print("[1/4] 读取盘前报告...")
    premarket, premarket_date = find_latest_premarket_report(date)
    if not premarket:
        msg = f"ERROR: {date} 及最近 7 天内无盘前报告"
        print(msg, file=sys.stderr)
        return msg

    # Step 1 完成
    _write_status(status_file, {"status": "loading", "progress": 25, "current_step": "盘前报告读取完成", "date": date, "premarket_date": premarket_date})

    # 兼容题材版(recommended_thesis)和概念版(recommended_sector)
    rec_sector = premarket.get("recommended_sector", {})
    rec_thesis = premarket.get("recommended_thesis", {})
    if rec_thesis and not rec_sector:
        rec_sector = {"name": rec_thesis.get("name", ""), "code": "", "logic": rec_thesis.get("logic", "")}
    sector_name = rec_sector.get("name", "")
    sector_code = rec_sector.get("code", "")
    logic = rec_sector.get("logic", "")

    if not sector_name:
        msg = "ERROR: 盘前报告中无推荐板块信息"
        print(msg, file=sys.stderr)
        return msg

    report_type = premarket.get("type", "")
    print(f"  推荐板块: {sector_name} ({sector_code}) [{'题材' if report_type == 'premarket_thesis' else '概念'}]")

    # 读取盘前等权指数作为基线
    premarket_ci = premarket.get("component_index")
    premarket_index_value = None
    if premarket_ci and premarket_ci.get("index_value"):
        premarket_index_value = float(premarket_ci["index_value"])
        print(f"  盘前等权指数: {premarket_index_value:.2f}")
    else:
        print(f"  盘前等权指数: 无记录(盘前报告未保存 component_index)")

    # ── Step 2: 拉取推荐板块收盘数据 ──
    print(f"\n[2/4] 拉取 [{sector_name}] 收盘数据...")

    # Step 2 完成
    _write_status(status_file, {"status": "loading", "progress": 50, "current_step": "收盘数据拉取完成", "date": date})

    # 尝试用代码直接查询
    stocks, board_info = fetch_closing_board(sector_name, sector_code)

    # 如果没获取到成分股,可能是代码不匹配(东财 vs 同花顺),尝试用同花顺代码
    if not stocks and sector_code.startswith("BK"):
        print(f"  [INFO] 东财代码 {sector_code} 未获取到成分股,尝试查找同花顺代码...")
        ths_code = find_ths_code_by_name(sector_name)
        if ths_code:
            print(f"  找到同花顺代码:{ths_code},重新查询成分股...")
            stocks, board_info = fetch_closing_board(sector_name, ths_code)

    # 获取最佳/最差个股（用于展示）
    if stocks:
        best = max(stocks, key=lambda x: x["change_pct"])
        worst = min(stocks, key=lambda x: x["change_pct"])
        print(f"  成分股最佳: {best['name']} ({best['change_pct']:+.2f}%)")
        print(f"  成分股最差: {worst['name']} ({worst['change_pct']:+.2f}%)")
    else:
        best = {"name": "N/A", "change_pct": 0}
        worst = {"name": "N/A", "change_pct": 0}
        print("  [WARNING] 未获取到成分股数据")

    # ── 计算复盘成分股等权指数 ──
    # 使用盘前报告中的 display_stocks 或 final_stocks 作为成分股列表
    display_stocks = premarket.get("display_stocks") or premarket.get("final_stocks") or []
    review_component_index = None
    if premarket_index_value is not None and display_stocks:
        try:
            review_component_index = _calc_review_component_index(display_stocks, date, premarket_index_value)
        except Exception as e:
            print(f"  [WARN] 复盘等权指数计算失败:{e}")
    elif premarket_index_value is None:
        print(f"  [WARN] 盘前等权指数缺失，无法计算复盘指数")

    # ── Step 3: LLM 复盘 ──
    print(f"\n[3/4] LLM 复盘分析 ({LLM_MODEL})...")

    # Step 3 完成
    _write_status(status_file, {"status": "analyzing", "progress": 75, "current_step": "LLM 复盘完成", "date": date})
    news = load_news(date)
    llm_text = llm_review(
        sector_name=sector_name,
        sector_code=sector_code,
        logic=logic,
        premarket_index=premarket_index_value,
        review_component_index=review_component_index,
        best_stock=best,
        worst_stock=worst,
        news_items=news,
        date=date,
        api_key=api_key,
    )
    print(f"\n  LLM 原始输出:\n{'─'*40}\n{llm_text}\n{'─'*40}\n")

    # ── Step 4: 评估 + 报告 + 推送 ──
    print(f"[4/4] 生成报告...")

    # Step 4 开始
    _write_status(status_file, {"status": "saving", "progress": 90, "current_step": "保存报告中", "date": date})

    # 等权指数评估
    evaluation: dict = {
        "verdict": "",
    }
    if review_component_index:
        idx_change = review_component_index["change_pct"]
        if idx_change > 0:
            evaluation["verdict"] = "✅ 复盘指数走高"
        elif idx_change < 0:
            evaluation["verdict"] = "❌ 复盘指数回落"
        else:
            evaluation["verdict"] = "⏸️ 复盘指数持平"
        evaluation["index_change_pct"] = idx_change
    else:
        evaluation["verdict"] = "⏸️ 指数数据不足"

    # 构建报告数据(符合 schema_review.json)
    report_data = {
        "date": date,
        "type": "review",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "premarket_date": premarket_date,
        "recommendation_snapshot": {
            "sector_name": sector_name,
            "sector_code": sector_code,
            "component_index": premarket_index_value,
            "logic": logic,
        },
        "actual": {
            "review_component_index": review_component_index,
            "stocks": [
                {"code": s["code"], "name": s["name"], "change_pct": s["change_pct"]}
                for s in (stocks[:10] if stocks else [])
            ],
            "best_stock": {"name": best["name"], "change_pct": best["change_pct"]},
            "worst_stock": {"name": worst["name"], "change_pct": worst["change_pct"]},
        },
        "evaluation": evaluation,
        "llm_review": llm_text,
    }

    # Telegram 消息
    if review_component_index:
        review_idx = review_component_index["index_value"]
        idx_change = review_component_index["change_pct"]
        if premarket_index_value is not None:
            component_index_line = f"📊 成分股等权指数:盘前 {premarket_index_value:.2f} → 复盘 {review_idx:.2f}（{idx_change:+.2f}%）\n"
        else:
            component_index_line = f"📊 复盘等权指数: {review_idx:.2f}\n"
    else:
        component_index_line = "📊 成分股等权指数:数据不足\n"

    # 复盘基准日标注(如果复盘日和盘前报告日不同则显示)
    premarket_date_label = ""
    if premarket_date != date:
        premarket_date_label = f"📌 基于 {premarket_date} 盘前分析\n"

    tg_msg = (
        f"📊 盘后复盘 {date}\n\n"
        f"{premarket_date_label}"
        f"🎯 盘前推荐:{sector_name}\n\n"
        f"{component_index_line}"
        f"🏆 成分股表现:\n"
        f"最佳:{best['name']} ({best['change_pct']:+.2f}%)\n"
        f"最差:{worst['name']} ({worst['change_pct']:+.2f}%)\n\n"
        f"📝 复盘分析:\n{llm_text}"
    )

    # Dry-run: 只打印
    if dry_run:
        print("\n[DRY-RUN] Telegram 消息预览:")
        print("─" * 40)
        print(tg_msg)
        print("─" * 40)
        print(f"\n[DRY-RUN] 报告 JSON:")
        print(json.dumps(report_data, ensure_ascii=False, indent=2))
        print("\n✅ Dry-run 完成,未保存未推送")
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
    report_path = REPORT_DIR / f"review_{date_compact}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"  报告已保存: {report_path}")

    # 保存板块数据库快照
    try:
        snapshot_id = save_board_snapshot(
            date=date_compact,
            period="review",
            board={"code": sector_code, "name": sector_name, "component_index": review_component_index},
            stocks=stocks if stocks else [],
            reason=llm_text[:200] if llm_text else "",
            catalyst="",
            recommended=True,
        )
        print(f"  数据库写入成功: snapshot_id={snapshot_id}")
    except Exception as e:
        print(f"  数据库写入失败: {e}", file=sys.stderr)

    # 最终完成状态
    _write_status(status_file, {
        "status": "done",
        "progress": 100,
        "current_step": "✅ 复盘完成",
        "date": date,
        "sector_name": sector_name,
        "sector_code": sector_code,
        "review_component_index": review_component_index,
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
        print("⚠️ 完成(推送可能都失败了)")

    return report_data


# === CLI 入口 ===
def main():
    parser = argparse.ArgumentParser(description="盘后复盘分析")
    parser.add_argument("--date", default="", help="复盘日期 YYYY-MM-DD,默认今天")
    parser.add_argument("--no-notify", action="store_true", help="不发送 Telegram")
    parser.add_argument("--dry-run", action="store_true", help="不保存不推送,只打印结果")
    parser.add_argument("--status-file", default="", help="状态文件路径")
    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    # CLI 参数转 run() 参数
    # dry_run: CLI 显式 > 全局配置
    dry_run = args.dry_run or (not args.dry_run and is_dry_run())
    # notify: --no-notify 显式禁用 > 全局配置
    notify = not args.no_notify and is_notify_enabled()

    result = run(date=date, dry_run=dry_run, notify=notify, status_file=args.status_file)

    # 处理返回值
    if isinstance(result, int):
        sys.exit(result)
    elif isinstance(result, str):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
