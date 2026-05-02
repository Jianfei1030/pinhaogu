#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thesis_api.py — 题材树状数据库的全套查询和增删改查接口

查询接口:
    1. list_all_thesis()            — 获取所有主题材名称及描述
    2. get_constituent_stocks()     — 获取某题材下的成分股
    3. get_child_theses()           — 获取某题材的子题材
    4. get_parent_thesis()          — 获取某题材的父题材
    5. get_full_tree()              — 获取完整树结构

增删改查接口:
    6. add_thesis_image()           — 新增一个主题材（建表）
    7. add_node()                   — 新增一个题材节点
    8. update_node_description()    — 修改题材描述
    9. update_stock_description()   — 修改成分股归因描述
    10. add_stocks()                — 批量添加成分股到某节点
    11. remove_stock()              — 移除某节点下的成分股
    12. delete_node()               — 删除一个题材节点
    13. update_thesis_catalog()     — 更新 thesis_catalog 字段

Usage:
    from thesis_api import *
    list_all_thesis()
    get_constituent_stocks("商业航天", "卫星相关", "千帆星座")
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "thesis.db"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _connect(db_path: str = None) -> sqlite3.Connection:
    db = str(db_path or DEFAULT_DB)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def resolve_tree_tables(image_name: str) -> tuple[str, str]:
    """返回 (tree_table, stocks_table) 名称。"""
    h = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
    return f"thesis_tree_{h}", f"thesis_stocks_tree_{h}"


def _get_node_id_by_path(conn: sqlite3.Connection, tree_table: str,
                         full_path: str) -> Optional[int]:
    """根据 full_path 查找 node_id。"""
    row = conn.execute(
        f"SELECT node_id FROM {tree_table} WHERE full_path = ?",
        (full_path,)
    ).fetchone()
    return row["node_id"] if row else None


# ===================================================================
# 查询接口
# ===================================================================

def list_all_thesis(db_path: str = None) -> list[dict]:
    """
    API 0: 获取所有主题材名称及描述。

    Returns:
        [{"image_name": "商业航天", "description": "...", "total_stock_count": 120, "node_count": 45}, ...]
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("""
            SELECT image_name, description, total_stock_count, node_count
            FROM thesis_catalog
            ORDER BY image_name
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_thesis_stocks(image_name: str, db_path: str = None) -> list[dict]:
    """
    API 新增: 获取某根题材下的所有成分股（聚合所有子节点）。

    Args:
        image_name: 根题材名，如 "AI 硬件"
        db_path: 数据库路径（可选）

    Returns:
        [{"stock_code": "600118", "stock_name": "中国卫星"}, ...] 去重后的完整股票列表
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        # 验证根题材是否存在
        exists = conn.execute(
            "SELECT 1 FROM thesis_catalog WHERE image_name = ?",
            (image_name,)
        ).fetchone()
        if not exists:
            return []

        # 检查 stocks 表是否存在
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (stocks_table,)
        ).fetchone()
        if not table_exists:
            return []

        # 单次查询：从该题材所有节点中聚合股票，使用 GROUP BY 去重
        # 同一 stock_code 取第一条记录的 name/description
        rows = conn.execute(f"""
            SELECT s.stock_code, s.stock_name, s.stock_description
            FROM {stocks_table} s
            GROUP BY s.stock_code
            ORDER BY s.stock_code
        """).fetchall()
        return [{"stock_code": r["stock_code"], "stock_name": r["stock_name"]} for r in rows]
    finally:
        conn.close()


def get_constituent_stocks(
    image_name: str,
    first_level: str = None,
    second_level: str = None,
    db_path: str = None,
) -> list[dict]:
    """
    API 1: 获取某题材节点下的成分股。

    Args:
        image_name: 主题材名，如 "商业航天"
        first_level: 一级题材名，如 "卫星相关"（None = 根节点股票）
        second_level: 二级题材名，如 "千帆星座"（None = 一级题材直接挂的股票）

    Returns:
        [{"stock_code": "600118", "stock_name": "中国卫星", "stock_description": "..."}, ...]

    Examples:
        get_constituent_stocks("商业航天", "卫星相关", "千帆星座")
        get_constituent_stocks("商业航天", "3D打印")
        get_constituent_stocks("商业航天")
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)

    if second_level:
        full_path = f"{image_name} / {first_level} / {second_level}"
    elif first_level:
        full_path = f"{image_name} / {first_level}"
    else:
        full_path = image_name

    conn = _connect(db_path)
    try:
        rows = conn.execute(f"""
            SELECT s.stock_code, s.stock_name, s.stock_description
            FROM {stocks_table} s
            JOIN {tree_table} t ON s.node_id = t.node_id
            WHERE t.full_path = ?
            ORDER BY s.stock_code
        """, (full_path,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_child_theses(
    image_name: str,
    parent_path: str,
    db_path: str = None,
) -> list[dict]:
    """
    API 2: 获取某题材节点的直接子题材。

    Args:
        image_name: 主题材名
        parent_path: 父节点的 full_path，如 "商业航天" 或 "商业航天 / 卫星相关"

    Returns:
        [{"node_name": "千帆星座", "node_type": "second_level", "full_path": "...",
          "description": "...", "stock_count": 12}, ...]
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        parent_row = conn.execute(
            f"SELECT node_id FROM {tree_table} WHERE full_path = ?",
            (parent_path,)
        ).fetchone()
        if not parent_row:
            return []

        parent_id = parent_row["node_id"]
        rows = conn.execute(f"""
            SELECT t.node_id, t.node_name, t.node_type, t.full_path, t.description,
                   COUNT(s.id) as stock_count
            FROM {tree_table} t
            LEFT JOIN {stocks_table} s ON s.node_id = t.node_id
            WHERE t.parent_id = ?
            GROUP BY t.node_id
            ORDER BY t.sort_order, t.node_name
        """, (parent_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_parent_thesis(
    image_name: str,
    node_path: str,
    db_path: str = None,
) -> Optional[dict]:
    """
    API 3: 获取某题材节点的父题材。

    Args:
        image_name: 主题材名
        node_path: 节点的 full_path，如 "商业航天 / 卫星相关 / 千帆星座"

    Returns:
        {"node_name": "卫星相关", "node_type": "first_level",
         "full_path": "商业航天 / 卫星相关", "description": "..."}
        根节点返回 None。
    """
    tree_table, _ = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        row = conn.execute(f"""
            SELECT p.node_name, p.node_type, p.full_path, p.description
            FROM {tree_table} c
            JOIN {tree_table} p ON c.parent_id = p.node_id
            WHERE c.full_path = ?
        """, (node_path,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_full_tree(image_name: str, db_path: str = None) -> dict:
    """
    API 4: 获取完整树结构（含每个节点的股票）。

    Returns:
        {"image_name": "商业航天", "nodes": [{node_id, parent_id, node_name,
         node_type, depth, full_path, description, stock_count,
         stocks: [{stock_code, stock_name, stock_description}]}, ...]}
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        node_rows = conn.execute(f"""
            SELECT t.node_id, t.parent_id, t.node_name, t.node_type, t.depth,
                   t.full_path, t.description,
                   COUNT(s.id) as stock_count
            FROM {tree_table} t
            LEFT JOIN {stocks_table} s ON s.node_id = t.node_id
            GROUP BY t.node_id
            ORDER BY t.depth, t.sort_order, t.node_name
        """).fetchall()

        stock_rows = conn.execute(f"""
            SELECT node_id, stock_code, stock_name, stock_description
            FROM {stocks_table}
            ORDER BY stock_code
        """).fetchall()

        stocks_by_node = {}
        for sr in stock_rows:
            nid = sr["node_id"]
            stocks_by_node.setdefault(nid, []).append({
                "stock_code": sr["stock_code"],
                "stock_name": sr["stock_name"],
                "stock_description": sr["stock_description"],
            })

        nodes = []
        for nr in node_rows:
            d = dict(nr)
            d["stocks"] = stocks_by_node.get(d["node_id"], [])
            nodes.append(d)

        return {"image_name": image_name, "nodes": nodes}
    finally:
        conn.close()


# ===================================================================
# 增删改查接口
# ===================================================================

def add_thesis_image(
    image_name: str,
    source_image: str = None,
    description: str = None,
    db_path: str = None,
) -> dict:
    """
    API 5: 新增一个主题材（在 thesis_catalog 中创建条目并建表）。

    Returns:
        {"image_name": "...", "tree_table": "...", "stocks_table": "..."}
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        # 建 catalog
        conn.execute("""
            INSERT OR IGNORE INTO thesis_catalog (image_name, source_image, description)
            VALUES (?, ?, ?)
        """, (image_name, source_image, description))

        # 建树节点表
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {tree_table} (
                node_id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL CHECK(node_type IN ('root', 'first_level', 'second_level')),
                depth INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                full_path TEXT NOT NULL UNIQUE,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (parent_id) REFERENCES {tree_table}(node_id)
            )
        """)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{image_name[:8]}_parent ON {tree_table}(parent_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{image_name[:8]}_path ON {tree_table}(full_path)")

        # 建成分股表
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {stocks_table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                stock_description TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (node_id) REFERENCES {tree_table}(node_id),
                UNIQUE(node_id, stock_code)
            )
        """)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_stocks_{image_name[:8]}_node ON {stocks_table}(node_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_stocks_{image_name[:8]}_code ON {stocks_table}(stock_code)")

        # 插入根节点
        conn.execute(f"""
            INSERT OR IGNORE INTO {tree_table}
                (node_id, parent_id, node_name, node_type, depth, full_path, description)
            VALUES (1, NULL, ?, 'root', 0, ?, ?)
        """, (image_name, image_name, description))

        conn.commit()
        return {"image_name": image_name, "tree_table": tree_table, "stocks_table": stocks_table}
    finally:
        conn.close()


def add_node(
    image_name: str,
    parent_path: str,
    node_name: str,
    node_type: str = "second_level",
    description: str = None,
    db_path: str = None,
) -> dict:
    """
    API 6: 新增一个题材节点。

    Args:
        image_name: 主题材名
        parent_path: 父节点 full_path
        node_name: 新节点名
        node_type: "first_level" 或 "second_level"
        description: 描述

    Returns:
        {"node_id": N, "full_path": "...", "node_name": "..."}
    """
    tree_table, _ = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        parent_id = _get_node_id_by_path(conn, tree_table, parent_path)
        if not parent_id:
            raise ValueError(f"父节点不存在: {parent_path}")

        # 获取父节点 depth
        parent_row = conn.execute(
            f"SELECT depth FROM {tree_table} WHERE node_id = ?", (parent_id,)
        ).fetchone()
        depth = parent_row["depth"] + 1 if parent_row else 0

        full_path = f"{parent_path} / {node_name}"

        # 获取 sort_order (当前最大 + 1)
        max_order = conn.execute(
            f"SELECT COALESCE(MAX(sort_order), 0) FROM {tree_table} WHERE parent_id = ?",
            (parent_id,)
        ).fetchone()[0]

        cur = conn.execute(f"""
            INSERT OR IGNORE INTO {tree_table}
                (parent_id, node_name, node_type, depth, full_path, description, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (parent_id, node_name, node_type, depth, full_path, description, max_order + 1))

        node_id = cur.lastrowid
        conn.commit()

        # 更新 catalog node_count
        _update_catalog_stats(conn, image_name)

        return {"node_id": node_id, "full_path": full_path, "node_name": node_name}
    finally:
        conn.close()


def update_node_description(
    image_name: str,
    node_path: str,
    description: str,
    db_path: str = None,
) -> bool:
    """
    API 7: 修改题材节点描述。

    Returns:
        True if updated, False if node not found.
    """
    tree_table, _ = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        cur = conn.execute(f"""
            UPDATE {tree_table}
            SET description = ?, updated_at = datetime('now', 'localtime')
            WHERE full_path = ?
        """, (description, node_path))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_stock_description(
    image_name: str,
    node_path: str,
    stock_code: str,
    description: str,
    db_path: str = None,
) -> bool:
    """
    API 8: 修改成分股归因描述。

    Returns:
        True if updated, False if not found.
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        node_id = _get_node_id_by_path(conn, tree_table, node_path)
        if not node_id:
            return False

        cur = conn.execute(f"""
            UPDATE {stocks_table}
            SET stock_description = ?
            WHERE node_id = ? AND stock_code = ?
        """, (description, node_id, stock_code))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_stocks(
    image_name: str,
    node_path: str,
    stocks: list[dict],
    db_path: str = None,
) -> int:
    """
    API 9: 批量添加成分股到某节点。

    Args:
        stocks: [{"stock_code": "600118", "stock_name": "中国卫星", "description": "..."}, ...]

    Returns:
        成功插入的数量。
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        node_id = _get_node_id_by_path(conn, tree_table, node_path)
        if not node_id:
            raise ValueError(f"节点不存在: {node_path}")

        count = 0
        for s in stocks:
            conn.execute(f"""
                INSERT OR IGNORE INTO {stocks_table}
                    (node_id, stock_code, stock_name, stock_description)
                VALUES (?, ?, ?, ?)
            """, (node_id, s["stock_code"], s["stock_name"], s.get("description", "")))
            count += 1

        conn.commit()
        _update_catalog_stats(conn, image_name)
        return count
    finally:
        conn.close()


def remove_stock(
    image_name: str,
    node_path: str,
    stock_code: str,
    db_path: str = None,
) -> bool:
    """
    API 10: 移除某节点下的成分股。

    Returns:
        True if removed, False if not found.
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        node_id = _get_node_id_by_path(conn, tree_table, node_path)
        if not node_id:
            return False

        cur = conn.execute(
            f"DELETE FROM {stocks_table} WHERE node_id = ? AND stock_code = ?",
            (node_id, stock_code)
        )
        conn.commit()
        if cur.rowcount > 0:
            _update_catalog_stats(conn, image_name)
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_node(
    image_name: str,
    node_path: str,
    cascade: bool = False,
    db_path: str = None,
) -> dict:
    """
    API 11: 删除一个题材节点。

    Args:
        cascade: True = 级联删除所有子孙节点和股票；False = 仅在无子节点时删除

    Returns:
        {"deleted": True/False, "reason": "...", "nodes_deleted": N, "stocks_deleted": N}
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)
    conn = _connect(db_path)
    try:
        node_id = _get_node_id_by_path(conn, tree_table, node_path)
        if not node_id:
            return {"deleted": False, "reason": "节点不存在", "nodes_deleted": 0, "stocks_deleted": 0}

        # 检查是否有子节点
        children = conn.execute(
            f"SELECT COUNT(*) as cnt FROM {tree_table} WHERE parent_id = ?",
            (node_id,)
        ).fetchone()["cnt"]

        if children > 0 and not cascade:
            return {"deleted": False, "reason": f"有 {children} 个子节点，使用 cascade=True 级联删除",
                    "nodes_deleted": 0, "stocks_deleted": 0}

        nodes_deleted = 0
        stocks_deleted = 0

        if cascade:
            # 收集所有要删除的节点 ID（BFS）
            to_delete = [node_id]
            queue = [node_id]
            while queue:
                nid = queue.pop(0)
                subs = conn.execute(
                    f"SELECT node_id FROM {tree_table} WHERE parent_id = ?", (nid,)
                ).fetchall()
                for sub in subs:
                    to_delete.append(sub["node_id"])
                    queue.append(sub["node_id"])

            # 删除股票
            placeholders = ",".join("?" * len(to_delete))
            cur = conn.execute(
                f"DELETE FROM {stocks_table} WHERE node_id IN ({placeholders})",
                to_delete
            )
            stocks_deleted = cur.rowcount

            # 删除节点
            cur = conn.execute(
                f"DELETE FROM {tree_table} WHERE node_id IN ({placeholders})",
                to_delete
            )
            nodes_deleted = cur.rowcount
        else:
            # 先删股票
            cur = conn.execute(
                f"DELETE FROM {stocks_table} WHERE node_id = ?", (node_id,)
            )
            stocks_deleted = cur.rowcount

            # 再删节点
            cur = conn.execute(
                f"DELETE FROM {tree_table} WHERE node_id = ?", (node_id,)
            )
            nodes_deleted = cur.rowcount

        conn.commit()
        _update_catalog_stats(conn, image_name)

        return {"deleted": True, "nodes_deleted": nodes_deleted, "stocks_deleted": stocks_deleted,
                "reason": "OK"}
    finally:
        conn.close()


def update_thesis_catalog(
    image_name: str,
    db_path: str = None,
    **fields,
) -> bool:
    """
    API 12: 更新 thesis_catalog 字段。

    支持的字段: description, source_image

    Returns:
        True if updated, False if not found.
    """
    allowed = {"description", "source_image"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [image_name]

    conn = _connect(db_path)
    try:
        cur = conn.execute(f"""
            UPDATE thesis_catalog
            SET {set_clause}, updated_at = datetime('now', 'localtime')
            WHERE image_name = ?
        """, values)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _update_catalog_stats(conn: sqlite3.Connection, image_name: str):
    """更新 thesis_catalog 的 node_count 和 total_stock_count。"""
    tree_table, stocks_table = resolve_tree_tables(image_name)

    node_count = conn.execute(
        f"SELECT COUNT(*) FROM {tree_table}"
    ).fetchone()[0]

    stock_count = conn.execute(
        f"SELECT COUNT(*) FROM {stocks_table}"
    ).fetchone()[0]

    conn.execute("""
        UPDATE thesis_catalog
        SET node_count = ?, total_stock_count = ?, updated_at = datetime('now', 'localtime')
        WHERE image_name = ?
    """, (node_count, stock_count, image_name))
    conn.commit()


def get_thesis_tree_structure(image_name: str, db_path: str = None) -> dict:
    """
    提取题材的一级+二级子题材树状结构。

    Args:
        image_name: 主题材名，如 "商业航天"
        db_path: 数据库路径（可选）

    Returns:
        {
            "root": "商业航天",
            "first_levels": [
                {
                    "node_id": 2,
                    "name": "蓝箭航天",
                    "full_path": "商业航天 / 蓝箭航天",
                    "stock_count": 36,
                    "description": "...",
                    "second_levels": [
                        {
                            "node_id": 5,
                            "name": "供应商",
                            "full_path": "商业航天 / 蓝箭航天 / 供应商",
                            "stock_count": 12,
                            "description": "..."
                        },
                        ...
                    ]
                },
                ...
            ],
            "total_first": 15,
            "total_second": 120
        }
    """
    tree_table, stocks_table = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        # 1. 获取根节点名
        root_row = conn.execute(
            f"SELECT node_name FROM {tree_table} WHERE depth = 0"
        ).fetchone()
        root_name = root_row["node_name"] if root_row else image_name

        # 2. 查询所有 first_level 节点（depth=1），按 sort_order 排序
        first_rows = conn.execute(f"""
            SELECT t.node_id, t.node_name, t.full_path, t.description,
                   COUNT(s.id) as stock_count
            FROM {tree_table} t
            LEFT JOIN {stocks_table} s ON s.node_id = t.node_id
            WHERE t.depth = 1
            GROUP BY t.node_id
            ORDER BY t.sort_order, t.node_name
        """).fetchall()

        # 3. 批量查询所有 second_level 节点（depth=2），按 parent_id 分组
        second_rows = conn.execute(f"""
            SELECT t.node_id, t.parent_id, t.node_name, t.full_path, t.description,
                   COUNT(s.id) as stock_count
            FROM {tree_table} t
            LEFT JOIN {stocks_table} s ON s.node_id = t.node_id
            WHERE t.depth = 2
            GROUP BY t.node_id
            ORDER BY t.parent_id, t.sort_order, t.node_name
        """).fetchall()

        # 4. 按 parent_id 分组 second_level 节点
        second_by_parent: dict[int, list[dict]] = {}
        for sr in second_rows:
            second_by_parent.setdefault(sr["parent_id"], []).append({
                "node_id": sr["node_id"],
                "name": sr["node_name"],
                "full_path": sr["full_path"],
                "stock_count": sr["stock_count"],
                "description": sr["description"],
            })

        # 5. 组装 first_levels
        first_levels = []
        for fr in first_rows:
            first_levels.append({
                "node_id": fr["node_id"],
                "name": fr["node_name"],
                "full_path": fr["full_path"],
                "stock_count": fr["stock_count"],
                "description": fr["description"],
                "second_levels": second_by_parent.get(fr["node_id"], []),
            })

        total_second = sum(len(v) for v in second_by_parent.values())

        return {
            "root": root_name,
            "first_levels": first_levels,
            "total_first": len(first_levels),
            "total_second": total_second,
        }
    finally:
        conn.close()


def get_stocks_by_nodes(
    image_name: str,
    node_ids: list[int],
    db_path: str = None,
) -> list[dict]:
    """
    根据选中的子题材 node_id 列表获取成分股（合并去重）。

    Args:
        image_name: 主题材名，如 "商业航天"
        node_ids: 选中的 node_id 列表，如 [5, 8, 12]
        db_path: 数据库路径（可选）

    Returns:
        [
            {"stock_code": "600118", "stock_name": "中国卫星", "node_id": 5,
             "node_path": "商业航天 / 卫星相关 / 制造"},
            ...
        ]
    """
    if not node_ids:
        return []

    tree_table, stocks_table = resolve_tree_tables(image_name)

    conn = _connect(db_path)
    try:
        # 验证题材是否存在
        exists = conn.execute(
            "SELECT 1 FROM thesis_catalog WHERE image_name = ?",
            (image_name,)
        ).fetchone()
        if not exists:
            return []

        # 验证 stocks 表是否存在
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (stocks_table,)
        ).fetchone()
        if not table_exists:
            return []

        placeholders = ",".join("?" * len(node_ids))

        # 查询所有节点的 full_path（用于后续拼 node_path）
        node_paths = {}
        tree_rows = conn.execute(
            f"SELECT node_id, full_path FROM {tree_table} WHERE node_id IN ({placeholders})",
            node_ids
        ).fetchall()
        for row in tree_rows:
            node_paths[row["node_id"]] = row["full_path"]

        # 查询成分股，按 stock_code 去重（同一 stock_code 只保留第一条）
        stock_rows = conn.execute(
            f"SELECT stock_code, stock_name, node_id FROM {stocks_table} "
            f"WHERE node_id IN ({placeholders}) ORDER BY node_id",
            node_ids
        ).fetchall()

        seen = set()
        result = []
        for sr in stock_rows:
            code = sr["stock_code"]
            if code in seen:
                continue
            seen.add(code)
            result.append({
                "stock_code": code,
                "stock_name": sr["stock_name"],
                "node_id": sr["node_id"],
                "node_path": node_paths.get(sr["node_id"], ""),
            })

        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI 入口（方便调试）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 thesis_api.py list")
        print("  python3 thesis_api.py tree <image_name>")
        print("  python3 thesis_api.py stocks <image_name> [first_level] [second_level]")
        print("  python3 thesis_api.py allstocks <image_name>")
        print("  python3 thesis_api.py children <image_name> <parent_path>")
        print("  python3 thesis_api.py parent <image_name> <node_path>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list":
        for t in list_all_thesis():
            print(f"  {t['image_name']:12s}  nodes={t['node_count']:3d}  stocks={t['total_stock_count']:4d}  {t['description'] or ''}")

    elif cmd == "tree":
        name = sys.argv[2]
        tree = get_full_tree(name)
        for n in tree["nodes"]:
            indent = "  " * n["depth"]
            stock_info = f" ({n['stock_count']} stocks)" if n["stock_count"] else ""
            print(f"{indent}{n['node_name']} [{n['node_type']}]{stock_info}")

    elif cmd == "stocks":
        name = sys.argv[2]
        fl = sys.argv[3] if len(sys.argv) > 3 else None
        sl = sys.argv[4] if len(sys.argv) > 4 else None
        for s in get_constituent_stocks(name, fl, sl):
            print(f"  {s['stock_code']}  {s['stock_name']}  {s['stock_description'] or ''}")

    elif cmd == "allstocks":
        import json
        name = sys.argv[2]
        stocks = get_all_thesis_stocks(name)
        json.dump(stocks, sys.stdout, ensure_ascii=False)

    elif cmd == "children":
        name = sys.argv[2]
        parent = sys.argv[3]
        for c in get_child_theses(name, parent):
            print(f"  {c['node_name']} [{c['node_type']}] stocks={c['stock_count']}  {c['description'] or ''}")

    elif cmd == "parent":
        name = sys.argv[2]
        node = sys.argv[3]
        p = get_parent_thesis(name, node)
        if p:
            print(f"  {p['node_name']} [{p['node_type']}]  {p['description'] or ''}")
        else:
            print("  (根节点，无父题材)")
