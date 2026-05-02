import glob
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional

# 从统一配置读取数据根目录
try:
    from config import get_config
    _DATA_ROOT = Path(get_config('data.root', 'data'))
except Exception:
    # Fallback: 使用硬编码默认值
    _DATA_ROOT = Path('data')

KLINE_TABLES = {
    "kline_1min",
    "kline_5min",
    "kline_15min",
    "kline_30min",
    "kline_60min",
    "kline_120min",
    "kline_1d",
    "kline_1wk",
}

KLINE_COLUMNS = [
    "bar_time", "open", "high", "low", "close", "volume", "amount", "turnover",
    "dif", "dea", "macd_hist",
    "profit_ratio", "avg_cost", "concentration_90", "cost_90_low", "cost_90_high",
    "total_mv", "circ_mv"
]


def get_db_path(market: str, symbol: str, date: str) -> str:
    """返回数据库文件路径：data/{market}/{market}{symbol}/{date}.db"""
    market = str(market).upper().strip()
    symbol = str(symbol).strip()
    date = str(date).strip()
    return str(_DATA_ROOT / market.upper() / f"{market}{symbol}" / f"{date}.db")


def list_db_dates(market: str, symbol: str, db_dir: str = None) -> list[str]:
    """列出某标的全部可用日期（扫描 data 目录下的 .db 文件）。
    
    Args:
        market: 市场标识 (如 'HK', 'A')
        symbol: 股票代码
        db_dir: 数据根目录（默认为配置中的 data 目录）
    
    Returns:
        按日期字符串升序排列的列表
    """
    import glob as _glob
    if db_dir is None:
        db_dir = _DATA_ROOT
    pattern = os.path.join(db_dir, str(market).upper(), f"{market}{symbol}", "*.db")
    files = _glob.glob(pattern)
    dates = []
    for f in files:
        basename = os.path.splitext(os.path.basename(f))[0]
        dates.append(basename)
    return sorted(dates)


def _ensure_parent_dir(db_path: str):
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _connect(db_path: str) -> sqlite3.Connection:
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _validate_kline_table(table: str):
    if table not in KLINE_TABLES:
        raise ValueError(f"unsupported kline table: {table}")


def _add_missing_columns(conn: sqlite3.Connection, table: str):
    """对已有 DB 表，缺失 total_mv/circ_mv 列时自动 ALTER TABLE 添加。"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for col_name in ("total_mv", "circ_mv"):
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} REAL")


def init_db(db_path: str):
    """创建数据库及所有表（如不存在）"""
    with closing(_connect(db_path)) as conn:
        cursor = conn.cursor()
        for table in sorted(KLINE_TABLES):
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    bar_time TEXT PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    amount REAL,
                    turnover REAL,
                    dif REAL,
                    dea REAL,
                    macd_hist REAL,
                    profit_ratio REAL,
                    avg_cost REAL,
                    concentration_90 REAL,
                    cost_90_low REAL,
                    cost_90_high REAL,
                    total_mv REAL,
                    circ_mv REAL
                )
                """
            )
        # 对已有表，补全缺失列
        for table in sorted(KLINE_TABLES):
            _add_missing_columns(conn, table)
        conn.commit()


def upsert_kline(db_path: str, table: str, rows: list[dict]):
    """批量写入 K 线数据，ON CONFLICT UPDATE（支持所有字段）"""
    _validate_kline_table(table)
    if not rows:
        return

    init_db(db_path)
    sql = f"""
        INSERT INTO {table} (
            bar_time, open, high, low, close, volume, amount, turnover,
            dif, dea, macd_hist,
            profit_ratio, avg_cost, concentration_90, cost_90_low, cost_90_high,
            total_mv, circ_mv
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bar_time) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            amount=excluded.amount,
            turnover=excluded.turnover,
            dif=excluded.dif,
            dea=excluded.dea,
            macd_hist=excluded.macd_hist,
            profit_ratio=excluded.profit_ratio,
            avg_cost=excluded.avg_cost,
            concentration_90=excluded.concentration_90,
            cost_90_low=excluded.cost_90_low,
            cost_90_high=excluded.cost_90_high,
            total_mv=excluded.total_mv,
            circ_mv=excluded.circ_mv
    """
    payload = [
        (
            row["bar_time"],
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume"),
            row.get("amount"),
            row.get("turnover"),
            row.get("dif"),
            row.get("dea"),
            row.get("macd_hist"),
            row.get("profit_ratio"),
            row.get("avg_cost"),
            row.get("concentration_90"),
            row.get("cost_90_low"),
            row.get("cost_90_high"),
            row.get("total_mv"),
            row.get("circ_mv"),
        )
        for row in rows
    ]

    with closing(_connect(db_path)) as conn:
        conn.executemany(sql, payload)
        conn.commit()


def upsert_chip_distribution(db_path: str, chip: dict):
    """更新最新交易日期的筹码分布数据（profit_ratio/avg_cost/concentration_90 等）到 kline_1d 表。"""
    init_db(db_path)
    sql = """
        UPDATE kline_1d SET
            profit_ratio = :profit_ratio,
            avg_cost = :avg_cost,
            concentration_90 = :concentration_90,
            cost_90_low = :cost_90_low,
            cost_90_high = :cost_90_high
        WHERE bar_time = (
            SELECT MAX(bar_time) FROM kline_1d
        )
    """
    with closing(_connect(db_path)) as conn:
        conn.execute(sql, {
            "profit_ratio": chip.get("profit_ratio"),
            "avg_cost": chip.get("avg_cost"),
            "concentration_90": chip.get("concentration_90"),
            "cost_90_low": chip.get("cost_90_low"),
            "cost_90_high": chip.get("cost_90_high"),
        })
        conn.commit()


def _get_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """获取表的列名列表"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def query_kline(db_path: str, table: str, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
    """查询 K 线数据，按 bar_time 升序。start/end 为时间字符串如'09:30'，None 表示不限"""
    _validate_kline_table(table)
    init_db(db_path)

    with closing(_connect(db_path)) as conn:
        # 动态获取表的实际列名，兼容不同版本的数据库结构
        available_columns = _get_table_columns(conn, table)
        
        # 基础列必须存在
        base_columns = ["bar_time", "open", "high", "low", "close", "volume", "amount"]
        # 可选列（新表结构可能有，旧表可能没有）
        optional_columns = ["turnover", "dif", "dea", "macd_hist",
                           "profit_ratio", "avg_cost", "concentration_90", "cost_90_low", "cost_90_high",
                           "total_mv", "circ_mv"]
        
        # 构建查询列列表
        columns = base_columns + [col for col in optional_columns if col in available_columns]
        columns_str = ", ".join(columns)
        
        sql = f"""SELECT {columns_str} FROM {table} WHERE 1=1"""
        params = []

        if start:
            sql += " AND bar_time >= ?"
            params.append(start)
        if end:
            sql += " AND bar_time <= ?"
            params.append(end)

        sql += " ORDER BY bar_time ASC"

        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    return [dict(row) for row in rows]


def cleanup_redundant_tables(db_path: str):
    """清理冗余表（indicators, chip_distribution）"""
    if not os.path.exists(db_path):
        return
    
    with closing(_connect(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        if "indicators" in tables:
            cursor.execute("DROP TABLE IF EXISTS indicators")
            print(f"已删除 indicators 表")
        
        if "chip_distribution" in tables:
            cursor.execute("DROP TABLE IF EXISTS chip_distribution")
            print(f"已删除 chip_distribution 表")
        
        conn.commit()


def write_indicators(db_path: str, period: str, rows: list[dict]):
    """写入 MACD 指标数据到对应的 K 线表
    
    Args:
        db_path: 数据库文件路径
        period: 周期（如 '5min', '15min', '30min' 等）
        rows: 指标数据列表，每条包含 bar_time, macd, macd_dea, macd_hist
    """
    table = f"kline_{period}"
    if not rows:
        return
    
    init_db(db_path)
    sql = f"""
        INSERT INTO {table} (bar_time, dif, dea, macd_hist)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(bar_time) DO UPDATE SET
            dif=excluded.dif,
            dea=excluded.dea,
            macd_hist=excluded.macd_hist
    """
    payload = [
        (
            row.get("bar_time"),
            row.get("macd"),
            row.get("macd_dea"),
            row.get("macd_hist"),
        )
        for row in rows
    ]
    
    with closing(_connect(db_path)) as conn:
        conn.executemany(sql, payload)
        conn.commit()


def query_kline_multi_days(market: str, symbol: str, table: str, dates: list[str], db_dir: str = None) -> list[dict]:
    """从多个日期的数据库文件读取 K 线数据并合并。"""
    _validate_kline_table(table)
    if db_dir is None:
        db_dir = _DATA_ROOT
    all_rows = []
    for date in dates:
        db_path = os.path.join(db_dir, str(market).upper(), f"{market}{symbol}", f"{date}.db")
        if os.path.exists(db_path):
            try:
                rows = query_kline(db_path, table)
                all_rows.extend(rows)
            except Exception:
                continue
    return all_rows
