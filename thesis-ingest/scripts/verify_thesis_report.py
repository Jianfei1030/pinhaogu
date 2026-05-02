#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_thesis_report.py — 从数据库读取题材树结构，生成 Markdown 校验报告。

输出格式：按树状层级缩进，每个叶子节点列出成分股（名称+代码），
方便对照原始截图逐层校验解析结果。

用法:
    python3 scripts/verify_thesis_report.py --image-name "AI 硬件" --db thesis.db --output-dir output
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 添加父目录到 sys.path，以便导入 thesis_api
sys.path.insert(0, str(Path(__file__).parent))
from thesis_api import get_full_tree, resolve_tree_tables


def generate_verify_report(image_name: str, db_path: str = None) -> str:
    """
    从数据库读取完整树结构，生成 Markdown 校验报告。

    Args:
        image_name: 主题材名，如 "AI 硬件"
        db_path: 数据库路径，默认 thesis.db

    Returns:
        Markdown 格式的校验报告字符串
    """
    tree_data = get_full_tree(image_name, db_path)
    nodes = tree_data.get("nodes", [])

    if not nodes:
        return f"# 数据校验报告 — {image_name}\n\n**错误**: 数据库中未找到该题材\n"

    # 按 node_id 排序（BFS 顺序 = 层级顺序）
    nodes.sort(key=lambda n: n["node_id"])

    # 统计
    first_level_count = sum(1 for n in nodes if n["node_type"] == "first_level")
    second_level_count = sum(1 for n in nodes if n["node_type"] == "second_level")
    total_stocks = sum(n["stock_count"] for n in nodes)

    # 构建 node_id → node 映射
    node_by_id = {n["node_id"]: n for n in nodes}

    # 从 thesis_catalog 获取根题材描述，注入到根节点
    try:
        if db_path:
            db_file = Path(db_path) if Path(db_path).is_absolute() else Path(__file__).parent.parent / db_path
        else:
            db_file = Path(__file__).parent.parent / "thesis.db"
        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT description FROM thesis_catalog WHERE image_name = ?",
                (image_name,)
            ).fetchone()
            if row and row[0] and len(row[0]) >= 10:
                nodes[0]["description"] = row[0]
    except Exception:
        pass

    # 构建 parent_id → children 映射
    children_map = {}
    for n in nodes:
        pid = n["parent_id"]
        children_map.setdefault(pid, []).append(n)

    # 对每个层级的子节点按 sort_order / node_name 排序
    for pid in children_map:
        children_map[pid].sort(key=lambda n: (n.get("sort_order", 0), n["node_name"]))

    lines = []
    lines.append(f"# 数据校验报告 — {image_name}")
    lines.append("")
    lines.append(f"**源文件**: {image_name}")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**节点数**: {len(nodes)} | **股票数**: {total_stocks}")
    lines.append("")

    def format_stocks(stocks: list[dict]) -> str:
        """格式化股票列表为 '名称(代码)' 序列"""
        if not stocks:
            return ""
        parts = []
        for s in stocks:
            name = s["stock_name"]
            code = s["stock_code"]
            parts.append(f"{name}({code})")
        return " ".join(parts)

    def render_node(node: dict, depth: int):
        """递归渲染节点"""
        node_name = node["node_name"]
        node_type = node["node_type"]
        stock_count = node["stock_count"]
        stocks = node.get("stocks", [])

        # 根节点用 ##，一级用 ###，二级用 ####
        if depth == 0:
            lines.append(f"## {node_name} ({node_type}) [{stock_count} 股票]")
        elif depth == 1:
            lines.append(f"### {node_name} ({node_type}) [{stock_count} 股票]")
        elif depth == 2:
            lines.append(f"#### {node_name} ({node_type}) [{stock_count} 股票]")
        else:
            lines.append(f"{'#' * (depth + 1)} {node_name} ({node_type}) [{stock_count} 股票]")

        # 描述（如果有）
        desc = node.get("description")
        if desc:
            indent = "  " * max(0, depth)
            lines.append(f"{indent}  > {desc}")

        # 获取子节点
        children = children_map.get(node["node_id"], [])

        if children:
            # 有子节点：先渲染子节点
            for child in children:
                render_node(child, depth + 1)
        else:
            # 叶子节点：列出成分股（缩进对齐标题）
            indent = "  " * max(0, depth - 1)
            if stocks:
                stock_line = format_stocks(stocks)
                lines.append(f"{indent}  - {stock_line}")
            else:
                lines.append(f"{indent}  - (无成分股)")

    # 从根节点开始渲染
    root = nodes[0]  # node_id=1 总是根节点
    render_node(root, 0)

    # 汇总
    lines.append("")
    lines.append("---")
    lines.append(f"**汇总**: {first_level_count} 一级题材, {second_level_count} 二级题材, {total_stocks} 只股票")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="生成题材数据校验报告")
    parser.add_argument("--image-name", required=True, help="主题材名，如 'AI 硬件'")
    parser.add_argument("--db", default="thesis.db", help="数据库路径 (默认: thesis.db)")
    parser.add_argument("--output-dir", default="output", help="输出目录 (默认: output)")
    parser.add_argument(
        "--fixed-name",
        action="store_true",
        help="使用固定文件名（无时间戳），由 orchestrator 控制输出目录"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = generate_verify_report(args.image_name, args.db)
    except Exception as e:
        print(f"❌ 生成报告失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 写入文件
    if args.fixed_name:
        output_file = output_dir / "verify_report.md"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"verify_report_{timestamp}.md"
    output_file.write_text(report, encoding="utf-8")

    # 同时输出到 stdout
    print(report)
    print(f"\n📄 报告已写入: {output_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
