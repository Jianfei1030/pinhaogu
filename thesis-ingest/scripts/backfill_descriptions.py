#!/usr/bin/env python3
"""
backfill_descriptions.py — 批量补全已入库题材的子节点描述

用法:
    .venv/bin/python3 scripts/backfill_descriptions.py          # 补全所有缺失
    .venv/bin/python3 scripts/backfill_descriptions.py 光伏      # 只补全指定题材
"""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

# Ensure we can import from scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.auto_generate_descriptions import _call_llm, _parse_json_response, _write_sub_descriptions, resolve_tree_tables


BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 2


def get_empty_nodes(conn: sqlite3.Connection, tree_table: str) -> list[dict]:
    """获取所有缺少描述的子节点（含 parent_name）"""
    rows = conn.execute(f"""
        SELECT t.node_id, t.node_name, t.node_type, t.depth, t.full_path, t.parent_id,
               p.node_name as parent_name
        FROM {tree_table} t
        LEFT JOIN {tree_table} p ON t.parent_id = p.node_id
        WHERE t.node_type != 'root'
          AND (t.description IS NULL OR TRIM(t.description) = '')
        ORDER BY t.depth, t.node_name
    """).fetchall()
    return [dict(r) for r in rows]


def build_sub_nodes(conn: sqlite3.Connection, tree_table: str, empty_rows: list[dict]) -> list[dict]:
    """构建批量描述请求所需的节点数据"""
    sub_nodes = []
    for r in empty_rows:
        children = conn.execute(
            f"SELECT node_name FROM {tree_table} WHERE parent_id = ? ORDER BY node_name",
            (r["node_id"],)
        ).fetchall()
        sub_nodes.append({
            "node_id": r["node_id"],
            "node_name": r["node_name"],
            "node_type": r["node_type"],
            "full_path": r["full_path"],
            "parent_name": r["parent_name"] or "",
            "children": [cr["node_name"] for cr in children],
        })
    return sub_nodes


def fill_thesis(image_name: str, db_path: str = "thesis.db") -> dict:
    """为指定题材补全所有缺失的描述，返回统计"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tree_table, _ = resolve_tree_tables(image_name)
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tree_table,)
    ).fetchone()
    if not table_exists:
        print(f"  [SKIP] 树表不存在: {tree_table}")
        return {"skipped": True}

    empty_rows = get_empty_nodes(conn, tree_table)
    total_empty = len(empty_rows)

    if total_empty == 0:
        print(f"  [SKIP] 无缺失描述")
        return {"skipped": True, "total_empty": 0}

    print(f"  缺失描述: {total_empty} 条")

    sub_nodes = build_sub_nodes(conn, tree_table, empty_rows)
    total_batches = (len(sub_nodes) + BATCH_SIZE - 1) // BATCH_SIZE
    total_written = 0
    total_failed = 0

    sys_prompt = "你是一位专业的 A 股题材分析师，擅长根据题材结构生成精炼描述。"

    for i in range(0, len(sub_nodes), BATCH_SIZE):
        batch = sub_nodes[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"  批次 {batch_num}/{total_batches} ({len(batch)} 节点)...", end=" ", flush=True)

        try:
            from scripts.auto_generate_descriptions import _build_sub_node_prompt
            user_prompt = _build_sub_node_prompt(image_name, batch)

            raw = _call_llm(sys_prompt, user_prompt, backend="copilot")
            parsed = _parse_json_response(raw)

            # Fix missing node_id
            for idx, item in enumerate(parsed):
                if "node_id" not in item and idx < len(batch):
                    item["node_id"] = batch[idx]["node_id"]

            written = _write_sub_descriptions(conn, tree_table, parsed)
            print(f"✓ 写入 {written}/{len(batch)}")
            total_written += written
            total_failed += max(0, len(batch) - written)

        except Exception as e:
            print(f"✗ {e}")
            total_failed += len(batch)

        # Sleep between batches
        if i + BATCH_SIZE < len(sub_nodes):
            time.sleep(SLEEP_BETWEEN_BATCHES)

    conn.close()
    return {"total_empty": total_empty, "written": total_written, "failed": total_failed}


def main():
    parser = argparse.ArgumentParser(description="批量补全题材子节点描述")
    parser.add_argument("thesis", nargs="?", default=None, help="题材名称，不传则补全所有")
    parser.add_argument("--db", default="thesis.db", help="数据库路径")
    args = parser.parse_args()

    if args.thesis:
        theses = [args.thesis]
    else:
        # 找出所有缺失描述的题材
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        cats = conn.execute("SELECT image_name FROM thesis_catalog ORDER BY image_name").fetchall()
        conn.close()
        theses = [r["image_name"] for r in cats]

    results = {}
    for thesis in theses:
        print(f"\n## {thesis}")
        result = fill_thesis(thesis, args.db)
        results[thesis] = result

    print("\n" + "=" * 50)
    print("汇总")
    print("=" * 50)
    for thesis, r in results.items():
        if r.get("skipped"):
            print(f"  {thesis}: 跳过")
        else:
            print(f"  {thesis}: 缺失 {r['total_empty']}, 已写入 {r['written']}, 失败 {r['failed']}")


if __name__ == "__main__":
    main()
