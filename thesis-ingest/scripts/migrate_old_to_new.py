#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_old_to_new.py — 从旧 schema 迁移到新树状 schema

旧 schema: thesis_list (扁平) + thesis_stocks_{md5} (261 张表)
新 schema: thesis_catalog + thesis_tree_{suffix} + thesis_stocks_tree_{suffix}

迁移策略:
1. 扫描所有 thesis_stocks_* 表
2. 从 thesis_description 字段提取 "来源路径: ..."
3. 按根题材（路径第一个元素）分组
4. 重建树结构，写入新表

Usage:
    python3 scripts/migrate_old_to_new.py --db thesis.db
    python3 scripts/migrate_old_to_new.py --db thesis.db --dry-run
"""

import argparse
import hashlib
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def extract_source_path(description: str) -> list[str] | None:
    """从 thesis_description 提取路径，如 '来源路径: 卫星相关 / 零部件'"""
    if not description:
        return None
    m = re.search(r'来源路径:\s*(.+?)(?:\n|$)', description)
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw:
        return None
    return [p.strip() for p in raw.split(" / ") if p.strip()]


def normalize_path(path: list[str], known_first_level: set[str], root_topic: str = "商业航天") -> list[str]:
    """
    规范化路径：如果路径缺少根题材前缀，自动补上。

    旧数据中有些路径是 "卫星相关 / 零部件"（缺少 "商业航天" 前缀），
    或者 "3D打印"（一级题材直接当根了）。
    """
    if not path:
        return path

    first = path[0]

    # 如果第一个元素就是根题材，直接返回
    if first == root_topic:
        return path

    # 如果第一个元素是已知的一级题材，补上根题材
    if first in known_first_level:
        return [root_topic] + path

    # 如果路径只有 1 层且不在已知一级题材中，可能是独立的一级题材
    # 也补上根题材（旧数据的"独立题材"实际上都属于商业航天）
    if len(path) == 1:
        return [root_topic] + path

    return path


def migrate(db_path: str, dry_run: bool = False):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. 找到所有旧表
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
          AND name LIKE 'thesis_stocks_%'
          AND name NOT LIKE 'thesis_stocks_tree_%'
          AND name NOT IN ('thesis_stocks_template')
        ORDER BY name
    """)
    old_tables = [r[0] for r in cur.fetchall()]
    print(f"找到 {len(old_tables)} 个旧 thesis_stocks 表")

    # 1.5 从 thesis_list 识别一级题材名（用于路径规范化）
    # 所有 thesis_list 中的条目都是一级或二级题材（根题材不在 thesis_list 中）
    cur.execute("SELECT thesis_name FROM thesis_list")
    known_first_level = set(name for (name,) in cur.fetchall())
    print(f"识别到 {len(known_first_level)} 个题材名（用于路径规范化）")

    # 2. 扫描所有行，提取路径
    # image_name -> full_path -> {(stock_code, stock_name)}
    images = defaultdict(lambda: defaultdict(set))
    total_rows = 0
    skipped_no_path = 0
    skipped_no_code = 0

    for table_name in old_tables:
        try:
            rows = cur.execute(f"""
                SELECT stock_code, stock_name, thesis_description
                FROM {table_name}
            """).fetchall()
        except sqlite3.OperationalError as e:
            print(f"  [WARN] 跳过 {table_name}: {e}", file=sys.stderr)
            continue

        total_rows += len(rows)

        for stock_code, stock_name, thesis_desc in rows:
            path = extract_source_path(thesis_desc)
            if not path:
                skipped_no_path += 1
                continue
            if not stock_code:
                skipped_no_code += 1
                continue

            # 规范化路径（补上缺失的根题材前缀）
            path = normalize_path(path, known_first_level)
            image_name = path[0]
            full_path = " / ".join(path)
            images[image_name][full_path].add((stock_code, stock_name))

    print(f"总行数: {total_rows}")
    print(f"跳过 (无路径): {skipped_no_path}")
    print(f"跳过 (无代码): {skipped_no_code}")
    print(f"识别到 {len(images)} 个主题材: {list(images.keys())}")

    if dry_run:
        print("\n[DRY RUN] 不写入数据库")
        for image_name, path_stocks in sorted(images.items()):
            node_count = set()
            for full_path in path_stocks:
                parts = full_path.split(" / ")
                for d in range(len(parts)):
                    node_count.add(" / ".join(parts[:d+1]))
            print(f"  {image_name}: {len(node_count)} 节点, {sum(len(v) for v in path_stocks.values())} 股票条目")
        conn.close()
        return

    # 3. 确保新表存在
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

    # 4. 为每个主题材构建树并写入
    for image_name, path_stocks in sorted(images.items()):
        suffix = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
        tree_table = f"thesis_tree_{suffix}"
        stocks_table = f"thesis_stocks_tree_{suffix}"

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
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_m_{suffix}_parent ON {tree_table}(parent_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_m_{suffix}_path ON {tree_table}(full_path)")

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
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_ms_{suffix}_node ON {stocks_table}(node_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_ms_{suffix}_code ON {stocks_table}(stock_code)")

        # 构建节点
        nodes = {}
        for full_path in path_stocks:
            parts = full_path.split(" / ")
            for depth, name in enumerate(parts):
                p = " / ".join(parts[:depth + 1])
                pp = " / ".join(parts[:depth]) if depth > 0 else None
                node_type = {0: "root", 1: "first_level", 2: "second_level"}.get(depth, "second_level")
                if p not in nodes:
                    nodes[p] = {
                        "node_name": name,
                        "node_type": node_type,
                        "depth": depth,
                        "full_path": p,
                        "parent_path": pp,
                    }

        # BFS 分配 node_id
        path_to_id = {}
        next_id = 1
        roots = sorted(p for p, n in nodes.items() if n["depth"] == 0)
        queue = list(roots)
        while queue:
            cp = queue.pop(0)
            if cp in path_to_id:
                continue
            path_to_id[cp] = next_id
            next_id += 1
            children = sorted(p for p, n in nodes.items() if n.get("parent_path") == cp)
            queue.extend(children)

        # 插入根节点（如果路径中没有显式根节点，创建一个）
        if image_name not in path_to_id:
            conn.execute(f"""
                INSERT OR IGNORE INTO {tree_table}
                    (node_id, parent_id, node_name, node_type, depth, full_path)
                VALUES (1, NULL, ?, 'root', 0, ?)
            """, (image_name, image_name))
            path_to_id[image_name] = 1

        # 插入所有节点
        for full_path, node_info in sorted(nodes.items(), key=lambda x: path_to_id.get(x[0], 0)):
            node_id = path_to_id[full_path]
            parent_path = node_info.get("parent_path")
            parent_id = path_to_id.get(parent_path) if parent_path else None

            # 根节点的 parent_id 可能是 None
            if node_info["depth"] == 0:
                parent_id = None

            conn.execute(f"""
                INSERT OR REPLACE INTO {tree_table}
                    (node_id, parent_id, node_name, node_type, depth, full_path, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (node_id, parent_id, node_info["node_name"],
                  node_info["node_type"], node_info["depth"], full_path, None))

        # 插入成分股
        total_stocks = 0
        for leaf_path, stock_set in path_stocks.items():
            node_id = path_to_id.get(leaf_path)
            if not node_id:
                # 如果 leaf_path 没有对应节点（比如路径不含根题材），尝试匹配
                print(f"  [WARN] 无对应节点: {leaf_path}", file=sys.stderr)
                continue
            for stock_code, stock_name in stock_set:
                conn.execute(f"""
                    INSERT OR IGNORE INTO {stocks_table}
                        (node_id, stock_code, stock_name, stock_description)
                    VALUES (?, ?, ?, ?)
                """, (node_id, stock_code, stock_name, ""))
                total_stocks += 1

        # 更新 catalog
        conn.execute("""
            INSERT OR REPLACE INTO thesis_catalog
                (image_name, node_count, total_stock_count, updated_at)
            VALUES (?, ?, ?, datetime('now', 'localtime'))
        """, (image_name, len(nodes), total_stocks))

        conn.commit()
        print(f"  ✓ {image_name} → {len(nodes)} 节点, {total_stocks} 股票")

    # 5. 验证
    cat_count = conn.execute("SELECT COUNT(*) FROM thesis_catalog").fetchone()[0]
    tree_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'thesis_tree_%'"
    ).fetchone()[0]
    stocks_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'thesis_stocks_tree_%'"
    ).fetchone()[0]

    print(f"\n迁移完成:")
    print(f"  thesis_catalog: {cat_count} 条")
    print(f"  thesis_tree_*: {tree_count} 张表")
    print(f"  thesis_stocks_tree_*: {stocks_count} 张表")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="从旧 schema 迁移到新树状 schema")
    parser.add_argument("--db", default="thesis.db", help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="仅分析不写入")
    args = parser.parse_args()

    db = PROJECT_ROOT / args.db
    migrate(str(db), args.dry_run)


if __name__ == "__main__":
    main()
