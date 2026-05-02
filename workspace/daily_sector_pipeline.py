#!/usr/bin/env python3
# ⚠️ DEPRECATED - 本脚本已被 premarket_analysis.py + postmarket_review.py 替代
# 保留仅供参考，不再 cron 调度
"""
每日财经分析全流程 (v2):
  1. 读取当日新闻 JSON（直接喂 LLM，跳过 sector_analyzer）
  2. LLM (百炼 qwen3.5-plus) 分析当日 A/港股投资机会
  3. 发送 Telegram 消息（自动分片）
  4. 保存本地报告
"""

import json
import os
import re
import sys
import ssl
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# === 配置 ===
USE_RESPONSES_API = False    # 百炼走标准 Chat Completions
MAX_CHARS = 100000           # 全量喂入

from config import config, LLM_BASE_URL, LLM_MODEL, LLM_PROXY, LLM_TIMEOUT, get_config
from utils.push import send_both
from utils.logger import setup_logger
from utils.trading_calendar import is_trading_day

SCRIPT_DIR = Path(__file__).parent
NEWS_DIR = SCRIPT_DIR / "news_data"
REPORT_DIR = SCRIPT_DIR / "reports"

# === LLM Prompt ===
SYSTEM_PROMPT = """你是一位资深的 A 股和港股市场分析师。你擅长从大量新闻中提炼出关键的投资信号，关注政策变化、行业趋势、资金流向和边际变化。你的分析基于事实，不编造数据。"""

USER_PROMPT_TEMPLATE = """以下是今日 ({date}) 收集到的财经新闻（共 {count} 条），来源包括同花顺、新浪、东方财富、富途、财联社。

请阅读全部新闻后，完成以下分析：

1. **今日市场概览**（2-3 句话总结大盘走势和核心驱动因素）
2. **今日 TOP 5 值得关注的板块/概念**（按投资价值排序）
   - 板块名
   - 投资价值评级：⭐~⭐⭐⭐⭐⭐
   - 核心逻辑：为什么值得关注（1-2 句话）
   - 关键个股或事件
3. **风险提示**：需要警惕的板块或信号（如有）
4. **一句话总结**：今日最核心的一条投资信号

输出格式要求：
- 适合 Telegram 阅读，简洁有力
- 用 emoji 但不要过度
- 每个板块 2-3 句话，不要长篇大论

---
以下是原始新闻：

{news_text}
"""



def load_news(date=None):
    """加载当日新闻 JSON"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    news_file = NEWS_DIR / f"financial_news_{date}.json"
    if not news_file.exists():
        print(f"新闻文件不存在: {news_file}", file=sys.stderr)
        return []

    with open(news_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  新闻文件: {news_file.name} | 共 {len(data)} 条")
    return data


def format_news_text(news_items, max_chars=MAX_CHARS):
    """格式化新闻为文本，控制总字符数"""
    items = news_items
    lines = []
    total_chars = 0
    for i, item in enumerate(items, 1):
        title = item.get("title", "").strip()
        source = item.get("source", "")
        summary = item.get("summary", "").strip()
        # 跳过无意义的短标题
        if len(title) < 5:
            continue
        line = f"{i}. [{source}] {title}"
        if summary and summary != title:
            line += f" | {summary[:100]}"
        lines.append(line)
        total_chars += len(line)
        if total_chars > max_chars:
            break

    result = "\n".join(lines)
    print(f"  格式化: {len(lines)} 条 | {len(result)} 字符")
    return result


def llm_analyze(news_text: str, date: str, api_key: str = "") -> str:
    """调用 LLM API 进行分析（支持 Chat Completions + Responses API）"""
    key = api_key or load_api_key()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        date=date,
        count=len(news_text.split("\n")),
        news_text=news_text,
    )

    if USE_RESPONSES_API:
        # Responses API（gpt-5.4 等新模型专用）
        url = f"{LLM_BASE_URL}/responses"
        payload = json.dumps({
            "model": LLM_MODEL,
            "input": SYSTEM_PROMPT + "\n\n" + user_prompt,
            "max_output_tokens": 4096,
        }).encode("utf-8")
    else:
        # Chat Completions API（gpt-4.1, gpt-5-mini 等）
        url = f"{LLM_BASE_URL}/chat/completions"
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }).encode("utf-8")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    proxy_handler = urllib.request.ProxyHandler(LLM_PROXY)
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(proxy_handler, https_handler)

    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })

    print(f"  调用 {LLM_MODEL} ({USE_RESPONSES_API and 'Responses' or 'Chat Completions'}) ...")
    resp = opener.open(req, timeout=LLM_TIMEOUT)
    result = json.loads(resp.read())

    if USE_RESPONSES_API:
        # Responses API 返回格式
        output = result.get("output", [])
        content = ""
        for item in output:
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    content += part.get("text", "")
        usage = result.get("usage", {})
        tokens_in = usage.get("input_tokens", usage.get("total_tokens", "?"))
        tokens_out = usage.get("output_tokens", "?")
    else:
        # Chat Completions 返回格式
        content = result["choices"][0]["message"]["content"].strip()
        usage = result.get("usage", {})
        tokens_in = usage.get("prompt_tokens", usage.get("total_tokens", "?"))
        tokens_out = usage.get("completion_tokens", "?")

    print(f"  Token: {tokens_in} in / {tokens_out} out")
    return content.strip()


def split_telegram(text, max_len=4000):
    """按段落分片，避免超 Telegram 4096 字符限制"""
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

# === QQ 推送配置 ===



def _write_status(path: str, data: dict):
    """写入状态文件（供 server.py 读取进度）"""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def run(
    date: str | None = None,
    dry_run: bool | None = None,
    notify: bool | None = None,
    status_file: str = "",
) -> int:
    """
    Job Runner 入口：执行每日财经分析全流程
    
    Args:
        date: 分析日期 YYYY-MM-DD，默认今天
        dry_run: 仅模拟不执行（当前未实现完整 dry-run，保留接口）
        notify: 是否发送 Telegram，默认读取全局配置
        status_file: 状态文件路径
    
    Returns:
        0 表示成功，非 0 表示失败
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    sf = status_file
    
    # 开关优先级：显式参数 > 全局配置 > 代码默认值
    notify_enabled = notify if notify is not None else config.runtime.notify_enabled
    
    # 节假日保护：非交易日直接退出
    if not is_trading_day(date):
        print(f"今天 {date} 为休市日，跳过每日财经分析")
        return 0
    
    print(f"=== {date} 每日财经分析 (v2 直喂模式) ===\n")

    api_key = load_api_key()
    if not api_key:
        print("ERROR: BAILIAN_API_KEY 未设置（阿里百炼 Coding Plan API）", file=sys.stderr)
        _write_status(sf, {"status": "error", "error": "BAILIAN_API_KEY not found", "date": date})
        return 1

    # Step 1: 读取新闻
    print("[1/4] 加载新闻...")
    _write_status(sf, {"status": "loading", "progress": 10, "current_step": "加载新闻中...", "date": date})
    news = load_news(date)
    if not news or len(news) == 0:
        error_msg = f"没有找到 {date} 的新闻数据（文件不存在或为空）"
        _write_status(sf, {
            "status": "error",
            "progress": 0,
            "current_step": error_msg,
            "date": date,
            "news_count": 0,
            "suggestion": "请先运行新闻收集器：daily_news_collector.py",
        })
        print(error_msg, file=sys.stderr)
        return 1
    news_text = format_news_text(news)
    _write_status(sf, {"status": "loading", "progress": 30, "current_step": f"新闻加载完成：{len(news)} 条",
                       "news_count": len(news), "char_count": len(news_text), "date": date})

    # Step 2: LLM 分析
    print(f"\n[2/4] LLM 分析 ({LLM_MODEL})...")
    _write_status(sf, {"status": "analyzing", "progress": 40, "current_step": f"{LLM_MODEL} 分析中...",
                       "news_count": len(news), "date": date, "model": LLM_MODEL})
    analysis = llm_analyze(news_text, date, api_key=api_key)
    print(f"  结果：{len(analysis)} 字符\n")
    _write_status(sf, {"status": "analyzing", "progress": 70, "current_step": f"分析完成：{len(analysis)} 字符",
                       "news_count": len(news), "analysis_length": len(analysis), "date": date, "model": LLM_MODEL})

    # Step 3: 发送 Telegram
    telegram_ok = True
    if not notify_enabled:
        print("[3/4] 跳过 Telegram (notify_enabled=False)")
    else:
        print("[3/4] 发送 Telegram...")
        _write_status(sf, {"status": "sending", "progress": 80, "current_step": "发送 Telegram 中...",
                           "news_count": len(news), "date": date, "model": LLM_MODEL})
        header = f"📰 *{date} 每日财经分析*\n\n"
        success = send_both(header + analysis)
        telegram_ok = success

    # Step 4: 保存本地报告
    print("\n[4/4] 保存报告...")
    _write_status(sf, {"status": "saving", "progress": 90, "current_step": "保存本地报告中...",
                       "news_count": len(news), "date": date, "model": LLM_MODEL})
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"daily_analysis_{date.replace('-', '')}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# {date} 每日财经分析\n\n")
        f.write(f"**模型:** {LLM_MODEL} | **新闻:** {len(news)} 条 | **分析:** {len(analysis)} 字符\n\n")
        f.write("## 分析结果\n\n")
        f.write(analysis + "\n")
        f.write("\n## 新闻源（前 100 条标题）\n\n")
        for i, item in enumerate(news[:100], 1):
            f.write(f"{i}. [{item.get('source','')}] {item.get('title','')}\n")
    print(f"  报告：{report_path}")

    # 完成
    _write_status(sf, {
        "status": "done", "progress": 100, "current_step": "✅ 分析完成",
        "news_count": len(news), "analysis_length": len(analysis),
        "report_path": str(report_path), "telegram_ok": telegram_ok,
        "model": LLM_MODEL, "date": date,
    })
    print(f"\n{'='*40}")
    print(f"{'完成' if telegram_ok else '部分完成（Telegram 可能失败）'}")
    return 0 if telegram_ok else 1


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default="", help="状态文件路径")
    parser.add_argument("--date", default="", help="分析日期 YYYY-MM-DD")
    parser.add_argument("--no-notify", action="store_true", help="不发送 Telegram")
    args = parser.parse_args()

    # CLI 参数转换：--no-notify 取反为 notify=False
    notify = False if args.no_notify else None
    
    exit_code = run(
        date=args.date or None,
        notify=notify,
        status_file=args.status_file,
    )
    sys.exit(exit_code)

def load_api_key():
    """从环境变量读取阿里百炼 Coding Plan API Key"""
    return config.llm.api_key


if __name__ == "__main__":
    main()
