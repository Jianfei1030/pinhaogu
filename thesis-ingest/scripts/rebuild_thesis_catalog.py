#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebuild thesis_list as a flat LLM-facing thesis catalog.

Usage:
    cd os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest
    python3 scripts/rebuild_thesis_catalog.py --input output/path_ancestor_candidates_20260409_224845.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

EXCLUDED_THEMES = [
    "其他",
    "自有产品",
    "股权相关",
    "供货海外",
    "解决方案",
    "技术研发",
    "产品",
    "设备厂商",
]
EXCLUDED_SET = set(EXCLUDED_THEMES)


def normalize_label(label: str) -> str:
    value = str(label or "").strip()
    if value == "AI硬件":
        return "AI 硬件"
    return value


def split_stock_names(stock_text_raw: str) -> List[str]:
    return [x for x in re.split(r"\s+", str(stock_text_raw or "").strip()) if x]


def add_unique(seq: List[str], value: str) -> None:
    if value and value not in seq:
        seq.append(value)


def build_catalog(data: dict) -> Dict[str, dict]:
    catalog: Dict[str, dict] = OrderedDict()

    for item in data.get("items", []):
        raw_path = [normalize_label(x) for x in item.get("path_raw", []) if str(x or "").strip()]
        if not raw_path:
            continue
        stock_names = split_stock_names(item.get("stock_text_raw", ""))

        for idx, theme in enumerate(raw_path):
            if theme in EXCLUDED_SET:
                continue

            entry = catalog.setdefault(
                theme,
                {
                    "thesis_name": theme,
                    "parents": [],
                    "children": [],
                    "stocks": set(),
                },
            )
            entry["stocks"].update(stock_names)

            if idx > 0:
                parent = raw_path[idx - 1]
                add_unique(entry["parents"], parent)

            if idx < len(raw_path) - 1:
                child = raw_path[idx + 1]
                add_unique(entry["children"], child)

    return catalog


def build_description(theme: str, parents: List[str], children: List[str]) -> str:
    shown_children = children[:8]
    child_text = "、".join(shown_children)
    parent_text = "、".join(parents)

    if not parents and children:
        return f"{theme} 是当前题材总目录中的上层题材,当前识别到的相关子题材包括:{child_text}。"
    if parents and children:
        return f"{theme} 是 {parent_text} 方向下的细分题材,当前识别到的相关子题材包括:{child_text}。"
    if parents and not children:
        return f"{theme} 是 {parent_text} 方向下的细分题材。"
    return f"{theme} 是当前题材总目录中的独立题材。"


def backup_thesis_list(conn: sqlite3.Connection, output_dir: Path, timestamp: str) -> tuple[Path, Path, int]:
    cursor = conn.cursor()
    cursor.execute("SELECT id, thesis_name, created_at, updated_at, stock_count, description FROM thesis_list ORDER BY id")
    rows = cursor.fetchall()
    backup_json = output_dir / f"thesis_list_backup_before_catalog_{timestamp}.json"
    backup_md = output_dir / f"thesis_list_backup_before_catalog_{timestamp}.md"

    payload = [
        {
            "id": row[0],
            "thesis_name": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "stock_count": row[4],
            "description": row[5],
        }
        for row in rows
    ]
    backup_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# thesis_list backup", ""]
    for row in payload:
        lines.append(f"- `{row['thesis_name']}` | stock_count={row['stock_count']}")
    backup_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return backup_json, backup_md, len(payload)


def build_thesis_to_table_map_from_insert_summary(base_dir: Path) -> Dict[str, str]:
    """
    Build mapping from simplified thesis_name to table_name by reading insert summary JSON.

    Strategy:
    1. Find the latest thesis_insert_result_*.json file
    2. Read thesis_to_table mapping
    3. Convert full-path names to simplified names
    """
    output_dir = base_dir / "output"

    # Find latest insert summary
    insert_summary_files = list(output_dir.glob("thesis_insert_result_*.json"))
    if not insert_summary_files:
        print("⚠️  未找到写库摘要文件,将使用数据库反查策略")
        return {}

    latest_insert_summary = max(insert_summary_files, key=lambda p: p.stat().st_mtime)
    print(f"📖 使用写库摘要: {latest_insert_summary.name}")

    # Read mapping
    with open(latest_insert_summary, 'r', encoding='utf-8') as f:
        insert_data = json.load(f)

    thesis_to_table_full = insert_data.get("thesis_to_table", {})

    # Convert full-path names to simplified names
    thesis_to_table: Dict[str, str] = {}
    for full_path, table_name in thesis_to_table_full.items():
        # Extract leaf name from full path
        leaf_name = full_path.split(" / ")[-1]
        thesis_to_table[leaf_name] = table_name

    return thesis_to_table


def build_thesis_to_table_map_from_db(conn: sqlite3.Connection) -> Dict[str, str]:
    """
    Fallback: Build mapping from existing thesis_list table.

    Strategy (v2 - improved):
    1. Read thesis_name -> table_name mapping directly from thesis_list
    2. This preserves the correct mapping that was established during insert
    3. No need to guess leaf names from thesis_description
    """
    cursor = conn.cursor()

    # Get thesis_name -> table_name from thesis_list (if it exists)
    try:
        cursor.execute("SELECT thesis_name, table_name FROM thesis_list WHERE table_name IS NOT NULL")
        rows = cursor.fetchall()
        thesis_to_table = {row[0]: row[1] for row in rows if row[1]}
        if thesis_to_table:
            print(f"📖 从 thesis_list 获取现有映射: {len(thesis_to_table)} 条")
            return thesis_to_table
    except sqlite3.OperationalError:
        # thesis_list might not exist yet
        pass

    # Fallback: Build from thesis_description sampling (original strategy)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'thesis_stocks_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall() if row[0] != 'thesis_stocks_template']

    thesis_to_table: Dict[str, str] = {}

    for table_name in tables:
        try:
            # Sample ALL rows to get thesis_description (limit to 100 for performance)
            cursor.execute(f"SELECT thesis_description FROM {table_name} LIMIT 100")
            rows = cursor.fetchall()

            # Collect leaf names
            leaf_counts: Dict[str, int] = {}
            for row in rows:
                if row and row[0]:
                    desc = row[0]
                    if "来源路径: " in desc:
                        full_path = desc.split("来源路径: ")[1].split("\n")[0].strip()
                        leaf_name = full_path.split(" / ")[-1]
                        leaf_counts[leaf_name] = leaf_counts.get(leaf_name, 0) + 1

            # Use most common leaf name
            if leaf_counts:
                most_common_leaf = max(leaf_counts.items(), key=lambda x: x[1])[0]
                thesis_to_table[most_common_leaf] = table_name
        except Exception as e:
            print(f"Warning: Failed to process {table_name}: {e}")
            continue

    return thesis_to_table


def build_thesis_to_table_map(conn: sqlite3.Connection, base_dir: Path) -> Dict[str, str]:
    """
    Build mapping from simplified thesis_name to table_name.
    Priority: database fallback (thesis_list) > insert summary JSON.

    Note: Database fallback now reads from existing thesis_list first,
    which preserves correct mappings from previous inserts.
    """
    # Try database first (improved strategy)
    thesis_to_table = build_thesis_to_table_map_from_db(conn)

    if thesis_to_table:
        return thesis_to_table

    # Fallback to insert summary
    return build_thesis_to_table_map_from_insert_summary(base_dir)


def get_actual_table_count(conn: sqlite3.Connection, table_name: str) -> int:
    """Get actual row count from a thesis_stocks_* table."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    except:
        return 0


def rebuild_catalog_table(conn: sqlite3.Connection, catalog: Dict[str, dict], base_dir: Path) -> Dict[str, str]:
    """Rebuild thesis_list with proper table_name and actual stock_count."""
    cursor = conn.cursor()

    # Build mapping from simplified thesis_name to table_name
    thesis_to_table = build_thesis_to_table_map(conn, base_dir)

    print(f"\n📊 找到 {len(thesis_to_table)} 个已存在的表映射")

    cursor.execute("DELETE FROM thesis_list")

    mapped_count = 0
    unmapped_themes = []

    for theme in sorted(catalog.keys()):
        entry = catalog[theme]
        description = build_description(theme, entry["parents"], entry["children"])

        # Try to find table_name from mapping
        table_name = thesis_to_table.get(theme)

        if table_name:
            # Use actual count from the table
            stock_count = get_actual_table_count(conn, table_name)
            mapped_count += 1
        else:
            # Fallback to catalog count and NULL table_name
            stock_count = len(entry["stocks"])
            unmapped_themes.append(theme)

        cursor.execute(
            """
            INSERT INTO thesis_list (thesis_name, table_name, stock_count, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))
            """,
            (theme, table_name, stock_count, description),
        )

    conn.commit()

    print(f"✅ 映射成功: {mapped_count} 个主题")
    if unmapped_themes:
        print(f"⚠️  未映射: {len(unmapped_themes)} 个主题")
        for theme in unmapped_themes[:5]:
            print(f"   - {theme}")
        if len(unmapped_themes) > 5:
            print(f"   ... 共 {len(unmapped_themes)} 个")

    return thesis_to_table


def write_summary(output_dir: Path, timestamp: str, input_rel: str, old_count: int, catalog: Dict[str, dict], thesis_to_table: Dict[str, str], conn: sqlite3.Connection) -> tuple[Path, Path]:
    summary_json = output_dir / f"thesis_catalog_rebuild_{timestamp}.json"
    summary_md = output_dir / f"thesis_catalog_rebuild_{timestamp}.md"

    cursor = conn.cursor()

    items = []
    mapped_items = []
    unmapped_items = []

    for theme in sorted(catalog.keys()):
        entry = catalog[theme]
        table_name = thesis_to_table.get(theme)

        if table_name:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            actual_count = cursor.fetchone()[0]
            mapped_items.append({
                "thesis_name": theme,
                "table_name": table_name,
                "stock_count": actual_count,
                "parents": entry["parents"],
                "children": entry["children"],
                "description": build_description(theme, entry["parents"], entry["children"]),
            })
            items.append(mapped_items[-1])
        else:
            unmapped_items.append({
                "thesis_name": theme,
                "table_name": None,
                "stock_count": len(entry["stocks"]),
                "parents": entry["parents"],
                "children": entry["children"],
                "description": build_description(theme, entry["parents"], entry["children"]),
            })
            items.append(unmapped_items[-1])

    payload = {
        "timestamp": timestamp,
        "input_file": input_rel,
        "old_thesis_list_count": old_count,
        "new_thesis_list_count": len(items),
        "mapped_count": len(mapped_items),
        "unmapped_count": len(unmapped_items),
        "excluded_labels": EXCLUDED_THEMES,
        "items": items,
    }
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Thesis Catalog Rebuild",
        "",
        f"- 时间: `{timestamp}`",
        f"- 输入文件: `{input_rel}`",
        f"- 原 thesis_list 条数: **{old_count}**",
        f"- 新 thesis_list 条数: **{len(items)}**",
        f"- 映射成功: **{len(mapped_items)}**",
        f"- 未映射: **{len(unmapped_items)}**",
        f"- 排除标签: {', '.join(EXCLUDED_THEMES)}",
        "",
        "## 映射成功的题材",
        "",
    ]
    for item in mapped_items:
        lines.append(f"- `{item['thesis_name']}` | table={item['table_name']} | stock_count={item['stock_count']}")

    if unmapped_items:
        lines.extend([
            "",
            "## 未映射的题材",
            "",
        ])
        for item in unmapped_items:
            lines.append(f"- `{item['thesis_name']}` | stock_count={item['stock_count']} (catalog)")

    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary_json, summary_md


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild thesis_list as flat thesis catalog")
    parser.add_argument("--input", required=True, help="Input JSON path relative to thesis-ingest")
    parser.add_argument("--db", default="thesis.db", help="Database file name")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]
    input_path = base_dir / args.input
    db_path = base_dir / args.db
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    catalog = build_catalog(data)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    conn = sqlite3.connect(db_path)
    try:
        backup_json, backup_md, old_count = backup_thesis_list(conn, output_dir, timestamp)
        thesis_to_table = rebuild_catalog_table(conn, catalog, base_dir)
        summary_json, summary_md = write_summary(output_dir, timestamp, str(input_path.relative_to(base_dir)), old_count, catalog, thesis_to_table, conn)

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM thesis_list")
        new_count = cursor.fetchone()[0]
        cursor.execute("SELECT thesis_name, stock_count FROM thesis_list ORDER BY thesis_name LIMIT 10")
        first_ten = cursor.fetchall()

        print(f"backup_json={backup_json}")
        print(f"backup_md={backup_md}")
        print(f"summary_json={summary_json}")
        print(f"summary_md={summary_md}")
        print(f"old_count={old_count}")
        print(f"new_count={new_count}")
        print("first_ten=")
        for row in first_ten:
            print(row)

        for theme in ["AI 硬件", "CPU", "光模块"]:
            cursor.execute("SELECT description FROM thesis_list WHERE thesis_name = ?", (theme,))
            row = cursor.fetchone()
            print(f"description::{theme}::{row[0] if row else 'NOT_FOUND'}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
