#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
insert_thesis_tree.py — 从 path_ancestor_candidates JSON 写入新树状结构表

从 expand_path_ancestors.py 产出的 path_ancestor_candidates_*.json 读取数据，
构建树状结构，写入 thesis_catalog + thesis_tree_{suffix} + thesis_stocks_tree_{suffix}。

Usage:
    python3 scripts/insert_thesis_tree.py --input output/path_ancestor_candidates_TIMESTAMP.json
    python3 scripts/insert_thesis_tree.py --input output/path_ancestor_candidates_TIMESTAMP.json --db thesis.db
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# 股票代码查找
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent / "workspace"
SCRIPTS_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(WORKSPACE_ROOT))
from services.stock_lookup_service import lookup_a_stock_code_by_name  # noqa: E402


# ---------------------------------------------------------------------------
# 表名工具
# ---------------------------------------------------------------------------

def resolve_tree_tables(image_name: str) -> tuple[str, str]:
    """返回 (tree_table, stocks_table) 名称。"""
    h = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
    return f"thesis_tree_{h}", f"thesis_stocks_tree_{h}"


def normalize_root_name(name: str) -> str:
    """特殊题材名归一化。"""
    if name == "AI硬件":
        return "AI 硬件"
    return name


# ---------------------------------------------------------------------------
# 树构建
# ---------------------------------------------------------------------------

def build_tree_from_items(items: list[dict], root_name: str = None) -> dict:
    """
    从 parsed items 构建树。

    如果指定了 root_name，所有 path_raw 自动补上根题材前缀，
    使得同一张截图下的所有一级子题材都挂在同一个根节点下。

    Returns:
        {
            "商业航天": {
                "nodes": { full_path: {node_name, node_type, depth, parent_path}, ... },
                "stocks": { full_path: [(code, name, desc), ...], ... }
            }
        }
    """
    images = defaultdict(lambda: {"nodes": {}, "stocks": defaultdict(list)})

    for item in items:
        path_raw = item.get("path_raw", [])
        if not path_raw:
            continue

        normalized_path = [normalize_root_name(n) for n in path_raw]

        # 如果指定了 root_name 且路径第一个元素不是根题材，补上前缀
        if root_name and (len(normalized_path) == 0 or normalized_path[0] != root_name):
            normalized_path = [root_name] + normalized_path

        image_name = normalized_path[0]

        # 注册路径上的每个节点
        for depth, name in enumerate(normalized_path):
            full_path = " / ".join(normalized_path[:depth + 1])
            parent_path = " / ".join(normalized_path[:depth]) if depth > 0 else None
            node_type = {0: "root", 1: "first_level", 2: "second_level"}.get(depth, "second_level")

            if full_path not in images[image_name]["nodes"]:
                images[image_name]["nodes"][full_path] = {
                    "node_name": name,
                    "node_type": node_type,
                    "depth": depth,
                    "full_path": full_path,
                    "parent_path": parent_path,
                }

        # 注册叶子节点的股票
        stock_text = item.get("stock_text_raw", "")
        leaf_path = " / ".join(normalized_path)
        stock_names = [s for s in stock_text.split() if s]

        for stock_name_raw in stock_names:
            lookup = lookup_a_stock_code_by_name(stock_name_raw)
            if lookup:
                images[image_name]["stocks"][leaf_path].append(
                    (lookup["stock_code"], lookup["stock_name"], "")
                )
            else:
                print(f"  [WARN] 未找到股票代码: {stock_name_raw}", file=sys.stderr)

    return dict(images)


def assign_node_ids(nodes: dict) -> dict:
    """BFS 分配 node_id，返回 full_path → node_id 映射。"""
    path_to_id = {}
    next_id = 1

    roots = sorted(p for p, n in nodes.items() if n["depth"] == 0)
    queue = list(roots)

    while queue:
        current_path = queue.pop(0)
        if current_path in path_to_id:
            continue
        path_to_id[current_path] = next_id
        next_id += 1

        children = sorted(
            p for p, n in nodes.items()
            if n.get("parent_path") == current_path
        )
        queue.extend(children)

    return path_to_id


# ---------------------------------------------------------------------------
# 数据库操作
# ---------------------------------------------------------------------------

def ensure_catalog_table(conn: sqlite3.Connection):
    """确保 thesis_catalog 表存在。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thesis_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT NOT NULL UNIQUE,
            source_image TEXT,
            description TEXT,
            total_stock_count INTEGER DEFAULT 0,
            node_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_name ON thesis_catalog(image_name)")
    conn.commit()


def create_image_tables(conn: sqlite3.Connection, suffix: str) -> tuple[str, str]:
    """创建某题材的树节点表和成分股表，返回表名。"""
    tree_table = f"thesis_tree_{suffix}"
    stocks_table = f"thesis_stocks_tree_{suffix}"

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
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{suffix}_parent ON {tree_table}(parent_id)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{suffix}_path ON {tree_table}(full_path)")

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
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_stocks_{suffix}_node ON {stocks_table}(node_id)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_stocks_{suffix}_code ON {stocks_table}(stock_code)")

    conn.commit()
    return tree_table, stocks_table


def insert_tree_data(conn: sqlite3.Connection, image_name: str, tree_data: dict,
                     source_image: str = None) -> dict:
    """将一个题材的树数据写入数据库。"""
    suffix = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
    tree_table, stocks_table = create_image_tables(conn, suffix)

    nodes = tree_data["nodes"]
    stocks = tree_data["stocks"]
    path_to_id = assign_node_ids(nodes)

    # 更新 thesis_catalog
    total_stocks = sum(len(v) for v in stocks.values())
    conn.execute("""
        INSERT OR REPLACE INTO thesis_catalog
            (image_name, source_image, total_stock_count, node_count, updated_at)
        VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
    """, (image_name, source_image, total_stocks, len(nodes)))

    # 插入树节点
    for full_path, node_info in sorted(nodes.items(), key=lambda x: path_to_id.get(x[0], 0)):
        node_id = path_to_id[full_path]
        parent_path = node_info.get("parent_path")
        parent_id = path_to_id.get(parent_path) if parent_path else None

        conn.execute(f"""
            INSERT OR REPLACE INTO {tree_table}
                (node_id, parent_id, node_name, node_type, depth, full_path, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (node_id, parent_id, node_info["node_name"],
              node_info["node_type"], node_info["depth"], full_path, None))

    # 插入成分股
    for leaf_path, stock_list in stocks.items():
        node_id = path_to_id.get(leaf_path)
        if not node_id:
            continue
        for stock_code, stock_name, stock_desc in stock_list:
            conn.execute(f"""
                INSERT OR IGNORE INTO {stocks_table}
                    (node_id, stock_code, stock_name, stock_description)
                VALUES (?, ?, ?, ?)
            """, (node_id, stock_code, stock_name, stock_desc))

    conn.commit()

    return {
        "image_name": image_name,
        "suffix": suffix,
        "tree_table": tree_table,
        "stocks_table": stocks_table,
        "node_count": len(nodes),
        "stock_entries": total_stocks,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="从 path_ancestor_candidates JSON 写入树状结构表")
    parser.add_argument("--input", required=True, help="path_ancestor_candidates JSON 文件路径")
    parser.add_argument("--db", default="thesis.db", help="数据库路径 (默认: thesis.db)")
    parser.add_argument("--source-image", default=None, help="原始截图文件名（可选）")
    parser.add_argument("--root-name", default=None, help="根题材名，所有 path 自动补上此前缀")
    args = parser.parse_args()

    base_dir = PROJECT_ROOT
    db_path = base_dir / args.db
    json_path = base_dir / args.input if not Path(args.input).is_absolute() else Path(args.input)

    print(f"[insert_thesis_tree] 读取: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print("没有找到 items 数据，退出。")
        return

    print(f"  共 {len(items)} 条记录")
    images = build_tree_from_items(items, root_name=args.root_name)
    print(f"  识别到 {len(images)} 个主题材")

    conn = sqlite3.connect(str(db_path))
    ensure_catalog_table(conn)

    results = []
    for image_name, tree_data in sorted(images.items()):
        r = insert_tree_data(conn, image_name, tree_data, args.source_image)
        results.append(r)
        print(f"  ✓ {image_name} → {r['tree_table']} "
              f"({r['node_count']} 节点, {r['stock_entries']} 股票)")

    # 更新统计
    cur = conn.cursor()
    for r in results:
        cur.execute("""
            UPDATE thesis_catalog
            SET node_count = ?, total_stock_count = ?, updated_at = datetime('now', 'localtime')
            WHERE image_name = ?
        """, (r["node_count"], r["stock_entries"], r["image_name"]))
    conn.commit()
    conn.close()

    # === 自动生成描述 ===
    try:
        from auto_generate_descriptions import generate_thesis_description
        for r in results:
            print(f"\n📝 自动生成描述: {r['image_name']}")
            try:
                ok = generate_thesis_description(r["image_name"], str(db_path))
                if ok:
                    print(f"  ✅ 描述生成完成")
                else:
                    print(f"  ⚠ 描述生成部分失败（不影响入库）")
            except Exception as e:
                print(f"  ⚠ 描述生成异常: {e}（不影响入库）")
    except ImportError:
        print("\n[WARN] auto_generate_descriptions 模块未找到，跳过描述生成")

    print(f"\n[insert_thesis_tree] 完成: {len(results)} 个题材写入 {db_path}")


if __name__ == "__main__":
    main()
