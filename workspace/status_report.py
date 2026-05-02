"""每小时后台任务状态汇报脚本 + 自动重启"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORKSPACE = SCRIPT_DIR
STOCK_DIR = SCRIPT_DIR
LOGS_DIR = WORKSPACE / "logs"

from config import config, get_config
from services.runtime_state_service import is_notify_enabled
from utils.push import send_both
from utils.logger import setup_logger
from utils.trading_calendar import is_trading_day

def get_backfill_status(date_str: str) -> str:
    """扫描补全日志提取状态，支持两种路径：
    1. 独立脚本: logs/daily_backfill_{date}.log
    2. monitor.py 触发: logs/monitor_{date}.log
    """
    # 优先检查独立脚本日志
    log_file = LOGS_DIR / f"daily_backfill_{date_str}.log"
    monitor_log = LOGS_DIR / f"monitor_{date_str}.log"

    # ── 路径 1: 独立脚本日志 ──
    if log_file.exists():
        try:
            content = log_file.read_text("utf-8", errors="replace")
        except Exception:
            return "❌ A股补全: 日志读取失败"

        stats_match = re.search(r"成功：(\d+)\s*只.*跳过：(\d+)\s*只.*失败：(\d+)\s*只", content)
        time_match = re.search(r"总耗时：(\d+):(\d+):(\d+)", content)

        if stats_match:
            return _format_backfill_result(stats_match, time_match)
        # 日志存在但无统计行 → 可能正在执行，继续检查 monitor 日志

    # ── 路径 2: monitor.py 触发的补全 ──
    if monitor_log.exists():
        try:
            content = monitor_log.read_text("utf-8", errors="replace")
        except Exception:
            return "❌ A股补全: 日志读取失败"

        # 检查是否完成
        done_match = re.search(r"\[BACKFILL\].*补全完成.*\((\d+):(\d+)\)", content)
        if done_match:
            h, m = int(done_match.group(1)), int(done_match.group(2))
            elapsed = f"{h}h{m}m" if h > 0 else f"{m}m"
            return f"✅ A股补全: 已完成 (耗时约{elapsed})"

        # 检查是否开始（可能还在跑）
        start_match = re.search(r"\[BACKFILL\].*开始每日数据补全", content)
        if start_match:
            # 统计已处理的股票数
            db_count = _count_today_db_files()
            if db_count > 0:
                return f"🔄 A股补全: 进行中 (已写入 {db_count} 只)"
            return "🔄 A股补全: 进行中"

        # 检查是否失败
        fail_match = re.search(r"\[BACKFILL\].*数据补全失败.*(.*)", content)
        if fail_match:
            return f"❌ A股补全: 失败 ({fail_match.group(1).strip()[:100]})"

    return "❌ A股补全: 今日未执行"


def _format_backfill_result(stats_match, time_match) -> str:
    success = stats_match.group(1)
    skip = stats_match.group(2)
    fail = stats_match.group(3)

    if time_match:
        h, m, s = int(time_match.group(1)), int(time_match.group(2)), int(time_match.group(3))
        elapsed = f"{h}h{m}m" if h > 0 else f"{m}m{s}s"
    else:
        elapsed = "?"

    if int(fail) > 0:
        return f"⚠️ A股补全: 已完成 ({success}成功, {skip}跳过, {fail}失败, 耗时{elapsed})"
    return f"✅ A股补全: 已完成 ({success}成功, {skip}跳过, 耗时{elapsed})"


def _count_today_db_files() -> int:
    """统计今天日期写入的 DB 文件数量"""
    data_dir = WORKSPACE / "data" / "A"
    if not data_dir.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        for stock_dir in data_dir.iterdir():
            if stock_dir.is_dir():
                if (stock_dir / f"{today}.db").exists():
                    count += 1
    except Exception:
        pass
    return count


NOW = datetime.now()
DATE_STR = NOW.strftime("%Y-%m-%d")
TIME_STR = NOW.strftime("%H:%M")

# 使用全局 python3（要求版本为 3.10）
PYTHON_BIN = "python3"

# 从配置读取 web 端口，默认 18805
WEB_PORT = get_config('web.port', 18805)


def find_process_by_port(port: int) -> int | None:
    """通过端口查找进程 PID (macOS)"""
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-i", f":{port}", "-t"], capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def _is_market_open() -> str:
    h, m = NOW.hour, NOW.minute
    minutes = h * 60 + m
    hk_open, hk_close = 9 * 60, 16 * 60 + 10
    a_am_start, a_am_end = 9 * 60 + 15, 11 * 60 + 30
    a_pm_start, a_pm_end = 13 * 60, 15 * 60
    hk_now = hk_open <= minutes < hk_close
    a_now = a_am_start <= minutes < a_am_end or a_pm_start <= minutes < a_pm_end
    if hk_now or a_now:
        return "🟢 交易中"
    elif minutes < hk_open:
        return "🟡 盘前"
    else:
        return "🔘 已收盘"


# ── 自动重启函数 ──

def restart_server() -> bool:
    """重启 server.py"""
    pid = find_process_by_port(WEB_PORT)
    if pid:
        return True  # 已在运行
    try:
        subprocess.Popen(
            [PYTHON_BIN, "server.py"],
            cwd=str(WORKSPACE),
            stdout=open(WORKSPACE / "logs" / f"server_{DATE_STR}.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(3)
        new_pid = find_process_by_port(WEB_PORT)
        if new_pid:
            print(f"✅ server.py 已重启 (pid {new_pid})")
            return True
        print("❌ server.py 重启失败")
        return False
    except Exception as e:
        print(f"❌ server.py 重启异常：{e}")
        return False


def restart_news_collector() -> bool:
    """重启 daily_news_collector.py"""
    result = subprocess.run(
        ["pgrep", "-f", "daily_news_collector"], capture_output=True, text=True, timeout=5
    )
    if result.stdout.strip():
        return True  # 已在运行
    try:
        subprocess.Popen(
            [PYTHON_BIN, "daily_news_collector.py", "--interval", "600"],
            cwd=str(WORKSPACE),
            stdout=open(WORKSPACE / "logs" / f"news_{DATE_STR}.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(2)
        result2 = subprocess.run(
            ["pgrep", "-f", "daily_news_collector"], capture_output=True, text=True, timeout=5
        )
        if result2.stdout.strip():
            print(f"✅ news collector 已重启 (pid {result2.stdout.strip()})")
            return True
        print("❌ news collector 重启失败")
        return False
    except Exception as e:
        print(f"❌ news collector 重启异常：{e}")
        return False


def restart_ollama() -> bool:
    """重启 Ollama"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        json.loads(resp.read())
        return True  # 已在运行
    except Exception:
        pass
    try:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True, timeout=5)
        time.sleep(2)
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=open("/dev/null", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(8)
        resp = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5)
        json.loads(resp.read())
        print("✅ Ollama 已重启")
        return True
    except Exception as e:
        print(f"❌ Ollama 重启失败：{e}")
        return False


# ── 检查函数 ──

def check_monitor() -> str:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{WEB_PORT}/api/monitor/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        pid = data.get("pid", "?")
        tick = data.get("tick_count", 0)
        alert_count = data.get("alert_count", 0)
        market_status = _is_market_open()
        log_file = WORKSPACE / "logs" / f"monitor_{DATE_STR}.log"
        last_line = ""
        if log_file.exists():
            lines = log_file.read_text("utf-8", errors="replace").strip().splitlines()
            for line in reversed(lines[-50:]):
                if "]" in line and ("HK0" in line or "A60" in line):
                    last_line = line.strip()
                    break
        status = "🟢 运行中" if pid else "🔴 未运行"
        return (
            f"{status} (pid {pid}) | {market_status}\n"
            f"  Tick: {tick} | 今日告警：{alert_count} 次\n"
            f"  最后轮询：{last_line[:80] if last_line else '-'}"
        )
    except Exception as e:
        return f"🔴 无法连接 ({e})"


def check_news_collector() -> tuple[str, bool]:
    """检查新闻采集状态，返回 (状态文本，是否需要重启)"""
    pid = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "daily_news_collector"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            pid = int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass

    news_file = STOCK_DIR / "news_data" / f"financial_news_{DATE_STR}.json"
    news_count = 0
    last_update = "-"
    if news_file.exists():
        try:
            with open(news_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            news_count = len(data)
            mtime = news_file.stat().st_mtime
            last_update = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
        except Exception:
            pass

    if pid:
        status = f"🟢 运行中 (pid {pid})"
        return f"{status}\n  今日新闻：{news_count} 条\n  最后更新：{last_update}", False
    else:
        # 自动重启
        restarted = restart_news_collector()
        if restarted:
            status = "🟡 刚重启"
        else:
            status = "🔴 未运行（重启失败）"
        return f"{status}\n  今日新闻：{news_count} 条\n  最后更新：{last_update}", restarted


def restart_monitor() -> bool:
    """重启 monitor.py"""
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/api/monitor/status", timeout=5)
        data = json.loads(resp.read())
        if data.get("running"):
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(
            [PYTHON_BIN, "monitor.py", "--config", "config.yaml", "--interval", "60"],
            cwd=str(WORKSPACE),
            stdout=open(WORKSPACE / "logs" / f"monitor_{DATE_STR}.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(5)
        resp = urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/api/monitor/status", timeout=5)
        data = json.loads(resp.read())
        if data.get("running"):
            print(f"✅ monitor 已重启")
            return True
        print("❌ monitor 重启失败")
        return False
    except Exception as e:
        print(f"❌ monitor 重启异常：{e}")
        return False


def check_server() -> tuple[str, bool]:
    """检查 server.py 状态，返回 (状态文本，是否需要重启)"""
    pid = find_process_by_port(WEB_PORT)
    if pid:
        return f"🟢 运行中 (pid {pid})", False
    else:
        restarted = restart_server()
        if restarted:
            return f"🟡 刚重启 (pid {find_process_by_port(WEB_PORT)})", True
        return "🔴 未运行（重启失败）", False


def check_ollama() -> tuple[str, bool]:
    """检查 Ollama 状态，返回 (状态文本，是否重启)"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if "qwen3-embedding:4b" in models or "bge-m3:latest" in models:
            return f"🟢 运行中 ({', '.join(models[:3])})", False
        elif models:
            return f"🟡 运行中但缺 bge-m3 (有：{models})", False
        else:
            return "🟡 运行中但无模型", False
    except Exception:
        restarted = restart_ollama()
        if restarted:
            return "🟡 刚重启", True
        return "🔴 未运行（重启失败）", False


def check_duplicate_processes() -> str:
    alerts = []
    # 检查重复进程：精确匹配 Python 解释器直接执行的脚本
    # 使用 ps + grep 排除 grep/find 自身，且只匹配 Python 进程
    for name in ["server.py", "daily_news_collector"]:
        try:
            result = subprocess.run(
                ["sh", "-c", f"ps aux | grep '[p]ython.*{name}' | grep -v grep"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
            # 提取 PID（ps aux 第 2 列）
            pids = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    pids.append(parts[1])
            if len(pids) > 1:
                alerts.append(f"⚠️ {name} 有 {len(pids)} 个进程：{pids}")
        except Exception:
            pass
    return "\n".join(alerts) if alerts else "✅ 无重复进程"

# === QQ 推送配置 ===


def run(dry_run: bool | None = None, notify: bool | None = None) -> dict:
    """
    Job Runner 入口：执行状态汇报任务
    
    Args:
        dry_run: 如果为 True，只打印不推送；如果为 None，使用全局配置
        notify: 如果显式指定，覆盖全局 notify_enabled 配置
    
    Returns:
        dict: 包含执行结果的字典
            - status: "success" | "skipped" | "error"
            - reason: 跳过原因（如果适用）
            - report: 生成的汇报文本（如果成功）
            - notified: 是否已推送
            - restarted: 重启的服务列表
    """
    result = {
        "status": "success",
        "reason": None,
        "report": None,
        "notified": False,
        "restarted": []
    }
    
    # 交易日判断：非交易日/节假日时尽早退出
    if not is_trading_day():
        print(f"[{DATE_STR}] 休市日，跳过状态汇报")
        result["status"] = "skipped"
        result["reason"] = "non_trading_day"
        return result

    hour = NOW.hour
    if hour < 10 or hour >= 20:
        print(f"当前 {TIME_STR}，不在汇报时段 (10:00-20:00)，跳过")
        result["status"] = "skipped"
        result["reason"] = "outside_hours"
        return result
    
    # 推送开关：参数优先，其次全局配置
    if notify is not None:
        notify_enabled = notify
    else:
        notify_enabled = is_notify_enabled()
    
    # dry_run 模式：只打印不推送
    if dry_run:
        notify_enabled = False

    # 检查并自动重启
    server_status, server_restarted = check_server()
    news_status, news_restarted = check_news_collector()
    ollama_status, ollama_restarted = check_ollama()
    monitor_restarted = restart_monitor()

    if server_restarted:
        result["restarted"].append("server.py")
    if news_restarted:
        result["restarted"].append("news collector")
    if ollama_restarted:
        result["restarted"].append("Ollama")
    if monitor_restarted:
        result["restarted"].append("monitor")

    restart_note = ""
    if result["restarted"]:
        restart_note = f"\n🔄 自动重启：{', '.join(result['restarted'])}\n"

    report = (
        f"📊 后台任务状态汇报 {DATE_STR} {TIME_STR}\n"
        f"{'─' * 28}\n"
        f"📈 股票监控\n"
        f"{check_monitor()}\n"
        f"{'─' * 28}\n"
        f"📰 新闻采集\n"
        f"{news_status}\n"
        f"{'─' * 28}\n"
        f"🌐 API Server\n"
        f"{server_status}\n"
        f"{'─' * 28}\n"
        f"🤖 Ollama\n"
        f"{ollama_status}\n"
        f"{'─' * 28}\n"
        f"🔍 进程检测\n"
        f"{check_duplicate_processes()}\n"
        f"{'─' * 28}\n"
        f"{get_backfill_status(DATE_STR)}"
        f"{restart_note}"
    )
    
    result["report"] = report
    print(report)
    
    if notify_enabled:
        send_both(report)
        result["notified"] = True
    else:
        print("  跳过推送 (notify_enabled=False)")
    
    return result


def main():
    """CLI 入口：仅负责调用 run() 并处理退出码"""
    sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1, encoding='utf-8', errors='replace')
    
    result = run(dry_run=False, notify=None)
    
    # 退出码：0=成功，1=跳过，2=错误
    if result["status"] == "skipped":
        sys.exit(1)
    elif result["status"] == "error":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
