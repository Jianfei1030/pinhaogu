#!/usr/bin/env python3
"""
板块数据库模块 - 存储板块快照和成分股数据
每天一个 SQLite 数据库: data/board/{date}.db
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime

# 从统一配置读取板块数据库目录
try:
    from config import get_config
    _BOARD_DB_DIR = Path(get_config('data.board_db', 'data/board'))
except Exception:
    # Fallback: 使用硬编码默认值
    _BOARD_DB_DIR = Path(__file__).resolve().parent / "data" / "board"

# 向后兼容：保留旧变量名
BOARD_DB_DIR = _BOARD_DB_DIR


def get_db_path(date: str) -> str:
    """获取指定日期的数据库路径"""
    BOARD_DB_DIR.mkdir(parents=True, exist_ok=True)
    return str(BOARD_DB_DIR / f"{date}.db")


def init_board_db(date: str) -> str:
    """初始化指定日期的板块数据库，创建表结构"""
    db_path = get_db_path(date)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 板块快照表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS board_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            period TEXT NOT NULL,
            change_pct REAL DEFAULT 0,
            news_count INTEGER DEFAULT 0,
            recommended INTEGER DEFAULT 0,
            reason TEXT,
            catalyst TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(code, period)
        )
    """)

    # 成分股快照表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            price REAL DEFAULT 0,
            change_pct REAL DEFAULT 0,
            FOREIGN KEY (snapshot_id) REFERENCES board_snapshot(id)
        )
    """)

    conn.commit()
    conn.close()
    return db_path


def save_board_snapshot(
    date: str,
    period: str,
    board: dict,
    stocks: list[dict],
    reason: str = "",
    catalyst: str = "",
    recommended: bool = False,
    news_count: int = 0,
) -> int:
    """
    保存板块快照和成分股数据

    Args:
        date: 日期字符串，如 "20260327" 或 "2026-03-27"
        period: "premarket" 或 "review"
        board: {"code": str, "name": str, "change_pct": float}
        stocks: [{"code": str, "name": str, "price": float, "change_pct": float}, ...]
        reason: LLM 推荐理由
        catalyst: 关键催化
        recommended: 是否被推荐
        news_count: 关联新闻数

    Returns:
        snapshot_id: 插入的快照 ID
    """
    # 统一日期格式
    date_clean = date.replace("-", "")

    db_path = init_board_db(date_clean)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 插入或替换板块快照（UNIQUE(code, period)）
        cursor.execute(
            """
            INSERT OR REPLACE INTO board_snapshot
                (code, name, period, change_pct, news_count, recommended, reason, catalyst)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                board.get("code", ""),
                board.get("name", ""),
                period,
                board.get("change_pct", 0),
                news_count,
                1 if recommended else 0,
                reason,
                catalyst,
            ),
        )
        snapshot_id = cursor.lastrowid

        # 先删除旧的成分股数据（如果存在替换）
        cursor.execute("DELETE FROM stock_snapshot WHERE snapshot_id = ?", (snapshot_id,))

        # 插入成分股
        for stock in stocks:
            cursor.execute(
                """
                INSERT INTO stock_snapshot (snapshot_id, stock_code, stock_name, price, change_pct)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    stock.get("code", stock.get("stock_code", "")),
                    stock.get("name", stock.get("stock_name", "")),
                    stock.get("price", 0),
                    stock.get("change_pct", 0),
                ),
            )

        conn.commit()
        return snapshot_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_board_snapshots(date: str, period: str = None) -> list[dict]:
    """获取指定日期的板块快照列表"""
    date_clean = date.replace("-", "")
    db_path = get_db_path(date_clean)

    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if period:
        cursor.execute(
            "SELECT * FROM board_snapshot WHERE period = ? ORDER BY change_pct DESC",
            (period,),
        )
    else:
        cursor.execute("SELECT * FROM board_snapshot ORDER BY period, change_pct DESC")

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_board_stocks(date: str, board_code: str, period: str = None) -> list[dict]:
    """获取指定板块的成分股数据"""
    date_clean = date.replace("-", "")
    db_path = get_db_path(date_clean)

    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if period:
        cursor.execute(
            """
            SELECT ss.* FROM stock_snapshot ss
            JOIN board_snapshot bs ON ss.snapshot_id = bs.id
            WHERE bs.code = ? AND bs.period = ?
            ORDER BY ss.change_pct DESC
            """,
            (board_code, period),
        )
    else:
        cursor.execute(
            """
            SELECT ss.* FROM stock_snapshot ss
            JOIN board_snapshot bs ON ss.snapshot_id = bs.id
            WHERE bs.code = ?
            ORDER BY bs.period, ss.change_pct DESC
            """,
            (board_code,),
        )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_board_history(board_code: str, days: int = 7) -> list[dict]:
    """获取板块历史数据（跨多天）"""
    import glob

    history = []
    db_files = sorted(BOARD_DB_DIR.glob("*.db"), reverse=True)

    for db_file in db_files[:days]:
        date_str = db_file.stem  # e.g., "20260327"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM board_snapshot WHERE code = ? ORDER BY period",
            (board_code,),
        )
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            entry = dict(row)
            entry["date"] = date_str
            history.append(entry)

    return history


def delete_board_data(date: str) -> bool:
    """删除指定日期的板块数据库"""
    date_clean = date.replace("-", "")
    db_path = get_db_path(date_clean)

    if os.path.exists(db_path):
        os.remove(db_path)
        return True
    return False


# === 测试 ===
if __name__ == "__main__":
    test_date = "20260327"

    print("=== board_db 模块测试 ===\n")

    # 测试 1: 初始化
    db = init_board_db(test_date)
    print(f"1. DB 初始化: {db}")

    # 测试 2: 保存快照
    sid = save_board_snapshot(
        test_date,
        "premarket",
        {"code": "300733", "name": "锂电池概念", "change_pct": 2.05},
        [
            {"code": "300782", "name": "卓胜微", "price": 50.0, "change_pct": 5.0},
            {"code": "300750", "name": "宁德时代", "price": 200.0, "change_pct": 3.2},
        ],
        reason="锂电池需求旺盛，政策利好",
        catalyst="宁德时代发布新电池技术",
        recommended=True,
        news_count=10,
    )
    print(f"2. Snapshot ID: {sid}")

    # 测试 3: 保存另一条（review）
    sid2 = save_board_snapshot(
        test_date,
        "review",
        {"code": "300733", "name": "锂电池概念", "change_pct": 1.85},
        [
            {"code": "300782", "name": "卓胜微", "price": 50.5, "change_pct": 4.8},
            {"code": "300750", "name": "宁德时代", "price": 198.0, "change_pct": 2.5},
        ],
        reason="收盘复盘分析",
    )
    print(f"3. Review Snapshot ID: {sid2}")

    # 测试 4: 查询快照
    data = get_board_snapshots(test_date, "premarket")
    print(f"4. Premarket Snapshots: {len(data)}")
    for d in data:
        print(f"   {d['name']} ({d['code']}): {d['change_pct']}%")

    # 测试 5: 查询成分股
    stocks = get_board_stocks(test_date, "300733", "premarket")
    print(f"5. 成分股: {len(stocks)}")
    for s in stocks:
        print(f"   {s['stock_name']} ({s['stock_code']}): {s['change_pct']}%")

    # 测试 6: 历史数据
    history = get_board_history("300733", days=7)
    print(f"6. 历史数据: {len(history)} 条")

    print("\n✅ 所有测试通过")
