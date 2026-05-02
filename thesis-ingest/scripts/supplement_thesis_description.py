#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
supplement_thesis_description.py — T34.0 题材描述补充

连接 thesis.db，读取 thesis_catalog 中 description 为空的题材，
调用 LLM 根据题材名 + 子题材节点名生成描述，写回数据库。

Usage:
    python3 scripts/supplement_thesis_description.py
"""

import os
import sys
import time
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径设置：本脚本位于 scripts/，项目根在 scripts/ 上一级
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "thesis.db"

# 将 scripts/ 加入 sys.path 以便导入 thesis_api
sys.path.insert(0, str(SCRIPT_DIR))

from thesis_api import get_full_tree, update_thesis_catalog

# ---------------------------------------------------------------------------
# LLM 调用（复用项目现有模式：OpenAI SDK + 百炼 API）
# ---------------------------------------------------------------------------

API_KEY = "YOUR_API_KEY"
BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
MODEL = "qwen3.6-plus"
MAX_RETRIES = 3


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM 生成文本，返回 response text"""
    from openai import OpenAI

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=512,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def generate_description(image_name: str, node_names: list[str]) -> str:
    """
    根据题材名和子题材节点名列表，生成 1-2 句话的描述。

    约束：
    - 描述长度 10-200 字符
    - 必须包含题材关键词
    - 说明题材范围和核心标的
    """
    # 去重但保留顺序
    seen = set()
    unique_nodes = []
    for n in node_names:
        if n not in seen:
            seen.add(n)
            unique_nodes.append(n)

    # 排除根节点名（它和 image_name 重复）
    child_nodes = [n for n in unique_nodes if n != image_name]

    system_prompt = (
        "你是一位专业的 A 股/港股题材分析师。你的任务是根据题材名称和其子题材节点列表，"
        "生成一段简短、准确的题材描述。"
        "要求：\n"
        "1. 只输出描述文本本身，不要任何解释、前缀或格式标记\n"
        "2. 长度控制在 10-200 个中文字符之间\n"
        "3. 必须包含题材核心关键词（例如题材名为'AI硬件'则需含 AI、芯片、算力等关键词）\n"
        "4. 说明该题材覆盖的范围和涉及的上市公司类型\n"
        "5. 用 1-2 句话表述，语言精炼、专业"
    )

    nodes_str = "、".join(child_nodes) if child_nodes else "暂无子题材分类"
    user_prompt = (
        f"题材名称：{image_name}\n"
        f"子题材节点：{nodes_str}\n\n"
        f"请为「{image_name}」题材生成一段描述。"
    )

    # 重试机制
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_llm(system_prompt, user_prompt)
            # 清理可能的引号包裹
            result = result.strip().strip('"').strip("'").strip()
            if len(result) < 10:
                raise ValueError(f"描述过短 ({len(result)} 字符)，可能生成失败")
            if len(result) > 200:
                result = result[:197] + "..."
            return result
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 * attempt
                print(f"    ⚠ 第 {attempt} 次 LLM 调用失败: {e}，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"    ✗ 第 {attempt} 次 LLM 调用失败，已达最大重试次数")

    raise last_error


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("T34.0 题材描述补充")
    print("=" * 60)

    # 1. 查找 description 为空的题材
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    missing_rows = conn.execute(
        "SELECT image_name, node_count, total_stock_count "
        "FROM thesis_catalog "
        "WHERE description IS NULL OR description = '' "
        "ORDER BY image_name"
    ).fetchall()
    conn.close()

    if not missing_rows:
        print("✅ 所有题材已有描述，无需补充。")
        return

    missing = [dict(r) for r in missing_rows]
    print(f"\n📋 发现 {len(missing)} 个题材缺少描述：")
    for m in missing:
        print(f"   - {m['image_name']} (节点={m['node_count']}, 股票={m['total_stock_count']})")

    print()
    success_count = 0
    skip_count = 0

    # 2. 逐个生成描述并更新
    for m in missing:
        name = m["image_name"]
        print(f"🔄 处理题材：{name}")

        try:
            # 获取完整树
            tree = get_full_tree(name)
            node_names = [n["node_name"] for n in tree.get("nodes", [])]

            print(f"   📂 子节点数：{len(node_names)}")

            # LLM 生成描述
            desc = generate_description(name, node_names)
            print(f"   📝 生成描述：{desc}")

            # 验证
            if len(desc) < 10:
                print(f"   ⚠ 描述过短 ({len(desc)} 字符)，跳过")
                skip_count += 1
                continue

            # 写回数据库
            ok = update_thesis_catalog(name, description=desc)
            if ok:
                print(f"   ✅ 已更新 thesis_catalog")
                success_count += 1
            else:
                print(f"   ✗ 数据库更新失败（题材不存在）")
                skip_count += 1

        except Exception as e:
            print(f"   ✗ 处理失败：{e}")
            skip_count += 1

        # 请求间隔，避免限流
        time.sleep(1)

    # 3. 最终验证
    print()
    print("=" * 60)
    print("📊 最终验证")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    all_rows = conn.execute(
        "SELECT image_name, description FROM thesis_catalog ORDER BY image_name"
    ).fetchall()
    conn.close()

    for r in all_rows:
        desc = r["description"] or "(空)"
        if len(desc) > 50:
            desc = desc[:47] + "..."
        has = "✅" if r["description"] and len(r["description"]) >= 10 else "❌"
        print(f"  {has} {r['image_name']:12s}  {desc}")

    print()
    total = len(all_rows)
    filled = sum(1 for r in all_rows if r["description"] and len(r["description"]) >= 10)
    print(f"✅ 完成：{filled}/{total} 题材已有有效描述")
    print(f"   本次新增：{success_count} | 跳过：{skip_count}")


if __name__ == "__main__":
    main()
