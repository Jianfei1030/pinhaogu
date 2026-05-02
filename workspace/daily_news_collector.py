"""
daily_news_collector.py — 每日财经新闻持续采集脚本

功能：
  - 并行抓取 5 个数据源（同花顺/新浪/东方财富/富途/财联社）
  - 仅使用 Ollama embedding 语义去重（bge-m3），不做精确匹配或 hash 去重
  - 持续后台运行，可配置采集间隔
  - 存储：news_data/financial_news_YYYY-MM-DD.json
  - 嵌入缓存：news_data/embed_cache_YYYY-MM-DD.json（持久化，避免重复 embed）

用法：
  python daily_news_collector.py                  # 持续运行，默认300s间隔
  python daily_news_collector.py --interval 600   # 自定义间隔
  python daily_news_collector.py --once           # 单次执行（适合cron）
"""

import akshare as ak
import pandas as pd
import numpy as np
import json
import os
import time
import socket
import datetime
import hashlib
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential
import requests

# ── 配置 ─────────────────────────────────────────────────────────────────────

OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_ENDPOINT = f"{OLLAMA_HOST}/api/embed"
EMBEDDING_MODEL = "qwen3-embedding:4b"
SIMILARITY_THRESHOLD = 0.75   # 余弦相似度阈值，高于此值视为重复
SOCKET_TIMEOUT = 15           # akshare 请求超时（秒）
DEFAULT_INTERVAL = 600        # 默认采集间隔（秒）

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DATA_DIR = os.path.join(_BASE_DIR, "news_data")
LOG_FILE = os.path.join(_BASE_DIR, "daily_news.log")

# ── 日志 ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Embedding 工具 ────────────────────────────────────────────────────────────

def get_embedding(text: str) -> list | None:
    """调用 Ollama /api/embed 接口，返回向量列表；失败返回 None。"""
    try:
        resp = requests.post(
            EMBEDDING_ENDPOINT,
            json={"model": EMBEDDING_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings")
        if not embeddings or not isinstance(embeddings, list):
            return None
        # /api/embed 返回 {"embeddings": [[dim0, dim1, ...]]}
        first = embeddings[0]
        return first if isinstance(first, list) else embeddings
    except Exception as e:
        logger.warning(f"Embedding 请求失败: {e}")
        return None


def cosine_sim(a: list, b: list) -> float:
    """计算两个向量的余弦相似度。"""
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


def text_key(title: str, detail: str) -> str:
    """用 title+detail 生成 MD5 作为 embedding cache 的 key。"""
    raw = f"{title}|||{detail}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()

# ── 存储 ──────────────────────────────────────────────────────────────────────

def _news_path(date_str: str) -> str:
    return os.path.join(NEWS_DATA_DIR, f"financial_news_{date_str}.json")

def _cache_path(date_str: str) -> str:
    return os.path.join(NEWS_DATA_DIR, f"embed_cache_{date_str}.json")


def load_news(date_str: str) -> list:
    path = _news_path(date_str)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_news(date_str: str, news_list: list):
    path = _news_path(date_str)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(news_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存新闻失败 {path}: {e}")


def load_embed_cache(date_str: str) -> dict:
    """返回 {md5_key: embedding_list}"""
    path = _cache_path(date_str)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_embed_cache(date_str: str, cache: dict):
    path = _cache_path(date_str)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"保存 embed cache 失败: {e}")

# ── 新闻抓取（复用 sync 版各源逻辑，去掉 circuit/llm/sklearn 依赖） ─────────

def _empty():
    return pd.DataFrame(columns=["title", "time", "date", "detail", "links"])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def get_news_ths() -> pd.DataFrame:
    orig = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(SOCKET_TIMEOUT)
        df = ak.stock_info_global_ths()
        if not {"标题", "内容", "发布时间", "链接"}.issubset(df.columns):
            return _empty()
        dt = pd.to_datetime(df["发布时间"])
        result = pd.DataFrame({
            "title":  df["标题"].values,
            "detail": df["内容"].values,
            "links":  df["链接"].values,
            "date":   dt.dt.strftime("%Y-%m-%d").values,
            "time":   dt.dt.strftime("%H:%M:%S").values,
        })
        return result[["title", "time", "date", "detail", "links"]]
    except Exception as e:
        logger.error(f"同花顺抓取异常: {e}")
        raise  # 让 tenacity 重试
    finally:
        socket.setdefaulttimeout(orig)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def get_news_sina() -> pd.DataFrame:
    orig = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(SOCKET_TIMEOUT)
        df = ak.stock_info_global_sina()
        if not {"时间", "内容"}.issubset(df.columns):
            return _empty()
        dt = pd.to_datetime(df["时间"])
        result = pd.DataFrame({
            "title":  df["内容"].str.slice(0, 20).str.replace(r"[【】#]", "", regex=True) + "...",
            "detail": df["内容"].values,
            "links":  pd.NA,
            "date":   dt.dt.strftime("%Y-%m-%d").values,
            "time":   dt.dt.strftime("%H:%M:%S").values,
        })
        return result[["title", "time", "date", "detail", "links"]]
    except Exception as e:
        logger.error(f"新浪抓取异常: {e}")
        raise
    finally:
        socket.setdefaulttimeout(orig)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def get_news_em() -> pd.DataFrame:
    orig = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(SOCKET_TIMEOUT)
        df = ak.stock_info_global_em()
        if not {"标题", "摘要", "发布时间", "链接"}.issubset(df.columns):
            return _empty()
        dt = pd.to_datetime(df["发布时间"])
        result = pd.DataFrame({
            "title":  df["标题"].values,
            "detail": df["摘要"].values,
            "links":  df["链接"].values,
            "date":   dt.dt.strftime("%Y-%m-%d").values,
            "time":   dt.dt.strftime("%H:%M:%S").values,
        })
        return result[["title", "time", "date", "detail", "links"]]
    except Exception as e:
        logger.error(f"东方财富抓取异常: {e}")
        raise
    finally:
        socket.setdefaulttimeout(orig)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def get_news_futu() -> pd.DataFrame:
    orig = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(SOCKET_TIMEOUT)
        df = ak.stock_info_global_futu()
        if not {"标题", "内容", "发布时间", "链接"}.issubset(df.columns):
            return _empty()
        dt = pd.to_datetime(df["发布时间"])
        result = pd.DataFrame({
            "title":  df["标题"].values,
            "detail": df["内容"].values,
            "links":  df["链接"].values,
            "date":   dt.dt.strftime("%Y-%m-%d").values,
            "time":   dt.dt.strftime("%H:%M:%S").values,
        })
        return result[["title", "time", "date", "detail", "links"]]
    except Exception as e:
        logger.error(f"富途抓取异常: {e}")
        raise
    finally:
        socket.setdefaulttimeout(orig)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def get_news_cls() -> pd.DataFrame:
    orig = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(SOCKET_TIMEOUT)
        df = ak.stock_info_global_cls(symbol="全部")
        if not {"标题", "内容", "发布日期", "发布时间"}.issubset(df.columns):
            return _empty()
        result = pd.DataFrame({
            "title":  df["标题"].values,
            "detail": df["内容"].values,
            "links":  pd.NA,
            "date":   df["发布日期"].astype(str).values,
            "time":   df["发布时间"].astype(str).values,
        })
        return result[["title", "time", "date", "detail", "links"]]
    except Exception as e:
        logger.error(f"财联社抓取异常: {e}")
        raise
    finally:
        socket.setdefaulttimeout(orig)


def fetch_all_news() -> pd.DataFrame:
    """并行抓取全部5个数据源，合并返回。"""
    sources = {
        "同花顺": get_news_ths,
        "新浪":   get_news_sina,
        "东方财富": get_news_em,
        "富途":   get_news_futu,
        "财联社": get_news_cls,
    }
    dfs = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(fn): name for name, fn in sources.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                df = future.result(timeout=60)
                if not df.empty:
                    df = df.copy()
                    df["source"] = name
                    dfs.append(df)
                    logger.info(f"  {name}: {len(df)} 条")
            except Exception as e:
                logger.error(f"  {name}: 抓取失败 — {e}")

    if not dfs:
        return pd.DataFrame(columns=["title", "time", "date", "detail", "links", "source"])
    return pd.concat(dfs, ignore_index=True)

# ── 核心：embedding 去重 + 存储 ───────────────────────────────────────────────

def process_and_save(news_df: pd.DataFrame) -> int:
    """
    对抓取结果进行 embedding 去重，增量写入当日 JSON 文件。
    去重逻辑：
      1. 加载当日已存 embedding cache（{md5: vector}）
      2. 对每条新闻计算 embedding
      3. 与所有已有 embedding（含本批次已通过的条目）做余弦相似度
      4. 相似度 >= SIMILARITY_THRESHOLD 则丢弃，否则保留并加入 cache
    返回本轮新增条数。
    """
    if news_df.empty:
        return 0

    os.makedirs(NEWS_DATA_DIR, exist_ok=True)

    # 清理 date 列，按日期分组
    df = news_df.copy()
    df["date"] = df["date"].astype(str).str.strip()
    df = df[~df["date"].isin(["", "nan", "NaT", "None", "NaN"])]

    total_new = 0

    for date_str, group in df.groupby("date"):
        existing_news = load_news(date_str)
        embed_cache = load_embed_cache(date_str)

        # 把 cache 中所有向量收集为列表，供批量比对
        cached_embeddings: list[list] = list(embed_cache.values())

        new_items: list[dict] = []
        cache_updates: dict = {}

        for _, row in group.iterrows():
            title  = str(row.get("title",  "") or "")
            detail = str(row.get("detail", "") or "")
            text   = f"{title} {detail}".strip()
            if not text:
                continue

            key = text_key(title, detail)

            # 若 cache 中已有此 key，说明之前已处理过（是重复），跳过
            if key in embed_cache:
                continue

            emb = get_embedding(text)

            if emb is None:
                # Ollama 不可用时，保留该条（不丢弃），但不入 cache
                logger.warning(f"Embedding 失败，直接保留: {title[:40]}")
                item = _build_item(row, date_str)
                new_items.append(item)
                continue

            # 与所有已有 embedding（历史 + 本批已通过）比较
            is_dup = False
            all_existing = cached_embeddings + [v for v in cache_updates.values()]
            for existing_emb in all_existing:
                if cosine_sim(emb, existing_emb) >= SIMILARITY_THRESHOLD:
                    is_dup = True
                    break

            if is_dup:
                logger.debug(f"语义重复，丢弃: {title[:50]}")
                # 把 key 写入 cache（值用哨兵[]），防止同一条多次计算
                cache_updates[key] = []
                continue

            # 新内容 ✓
            item = _build_item(row, date_str)
            new_items.append(item)
            cache_updates[key] = emb
            cached_embeddings.append(emb)   # 加入本批已通过列表，供后续条目比对

        if new_items:
            updated = existing_news + new_items
            save_news(date_str, updated)
            embed_cache.update(cache_updates)
            save_embed_cache(date_str, embed_cache)
            logger.info(f"  [{date_str}] 新增 {len(new_items)} 条（累计 {len(updated)} 条）")
            total_new += len(new_items)
        else:
            # 仍然持久化新出现的"重复条目 key"，减少下次 embedding 调用
            if cache_updates:
                embed_cache.update(cache_updates)
                save_embed_cache(date_str, embed_cache)
            logger.info(f"  [{date_str}] 无新增")

    return total_new


def _build_item(row: pd.Series, date_str: str) -> dict:
    links = row.get("links")
    return {
        "title":  str(row.get("title",  "") or ""),
        "time":   str(row.get("time",   "") or ""),
        "date":   date_str,
        "detail": str(row.get("detail", "") or ""),
        "links":  str(links) if pd.notna(links) else None,
        "source": str(row.get("source", "") or ""),
    }

# ── 运行入口 ──────────────────────────────────────────────────────────────────

def run_once() -> int:
    logger.info("══════ 开始采集新闻 ══════")
    df = fetch_all_news()
    logger.info(f"各源合计抓取: {len(df)} 条，开始 embedding 去重...")
    n = process_and_save(df)
    logger.info(f"本轮新增: {n} 条 ══════")
    return n


def run_loop(interval: int = DEFAULT_INTERVAL):
    logger.info(f"持续采集模式启动，间隔 {interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            logger.error(f"run_once 异常（已捕获，继续运行）: {e}", exc_info=True)
        next_time = datetime.datetime.now() + datetime.timedelta(seconds=interval)
        logger.info(f"下次采集: {next_time.strftime('%H:%M:%S')}（休眠 {interval}s）")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="每日财经新闻持续采集脚本")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"采集间隔（秒），默认 {DEFAULT_INTERVAL}")
    parser.add_argument("--once", action="store_true",
                        help="只执行一次后退出（适合 cron）")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_loop(interval=args.interval)
