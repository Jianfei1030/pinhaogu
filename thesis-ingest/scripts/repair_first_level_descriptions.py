#!/usr/bin/env python3
"""
repair_first_level_descriptions.py — 修复一级子题材描述

清空指定题材的一级节点描述，用新 prompt 重新生成。
新 prompt 要求 first_level 节点必须列出包含的二级子方向。

Usage:
    .venv/bin/python3 scripts/repair_first_level_descriptions.py [题材名 ...]
    不传参数则修复所有已知有问题的题材
"""

import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# 百炼 qwen
QWEN_API_KEY = "YOUR_API_KEY"
QWEN_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
QWEN_MODEL = "qwen3.6-plus"

BATCH_SIZE = 10
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

KNOWN_ISSUES = [
    "AI 硬件", "人形机器人", "储能概念", "创新药_cropped",
    "商业航天", "大厂算力梳理", "海峡两岸_cropped", "锂矿",
]


def _call_qwen(system_prompt: str, user_prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    resp = client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2048,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def _parse_json(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


def repair_topic(image_name: str, db_path: str = "thesis.db") -> dict:
    db_file = str(Path(db_path) if Path(db_path).is_absolute()
                  else PROJECT_ROOT / db_path)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    h = hashlib.md5(image_name.encode()).hexdigest()[:8]
    tree = f'thesis_tree_{h}'

    # 获取所有一级节点
    f1_rows = conn.execute(
        f"SELECT node_id, node_name, description FROM {tree} WHERE depth = 1 ORDER BY node_name"
    ).fetchall()

    if not f1_rows:
        conn.close()
        return {"image_name": image_name, "skipped": True, "reason": "无一级节点"}

    # 检查哪些一级节点有子节点（需要列子方向）
    nodes_to_fix = []
    for row in f1_rows:
        children = conn.execute(
            f"SELECT node_name FROM {tree} WHERE parent_id = ? ORDER BY node_name",
            (row["node_id"],)
        ).fetchall()
        child_names = [c["node_name"] for c in children]
        desc = row["description"] or ""
        # 有子节点但未提及任何一个 → 需要修复
        if child_names and not any(cn in desc for cn in child_names):
            nodes_to_fix.append({
                "node_id": row["node_id"],
                "node_name": row["node_name"],
                "parent_name": image_name,
                "children": child_names,
            })

    if not nodes_to_fix:
        conn.close()
        return {"image_name": image_name, "skipped": True, "reason": "所有一级节点已列子方向"}

    print(f"\n## {image_name}")
    print(f"  需修复: {len(nodes_to_fix)} 个一级节点")

    # 清空旧描述
    for n in nodes_to_fix:
        conn.execute(
            f"UPDATE {tree} SET description = NULL WHERE node_id = ?",
            (n["node_id"],)
        )
    conn.commit()

    # 用新 prompt 重新生成
    system_prompt = "你是一位专业的 A 股题材分析师，擅长根据题材结构生成精炼描述。"

    results = []
    for i in range(0, len(nodes_to_fix), BATCH_SIZE):
        batch = nodes_to_fix[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(nodes_to_fix) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  批次 {batch_num}/{total_batches} ({len(batch)} 节点)...")

        json_str = json.dumps(batch, ensure_ascii=False)
        user_prompt = (
            f"题材：{image_name}\n\n"
            f"需要修复的一级节点列表（JSON格式）：\n{json_str}\n\n"
            "要求：\n"
            '1. 格式："X是{父题材}的核心方向，涉及[一句话描述]。包含以下子方向：A、B、C等。"\n'
            "2. 必须在描述中明确列出 children 中的所有二级子题材名称\n"
            "3. 30-120 字\n"
            '4. 输出纯 JSON 数组：[{"node_id": 节点ID, "node_name": "节点名", "description": "描述"}, ...]\n'
            "5. node_id 和 node_name 必须与输入完全一致\n"
            "6. 不要任何额外文本，只要 JSON 数组\n"
        )

        try:
            raw = _call_qwen(system_prompt, user_prompt)
            parsed = _parse_json(raw)
            for item in parsed:
                nid = item.get("node_id")
                desc = item.get("description", "")
                if nid and desc:
                    conn.execute(
                        f"UPDATE {tree} SET description = ?, updated_at = datetime('now', 'localtime') WHERE node_id = ?",
                        (desc, nid)
                    )
            conn.commit()
            print(f"    ✓ 写入 {len(parsed)}/{len(batch)}")
            results.extend(parsed)
        except Exception as e:
            print(f"    ✗ 失败: {e}")

        if i + BATCH_SIZE < len(nodes_to_fix):
            time.sleep(1)

    # 验证
    fixed_count = 0
    for n in nodes_to_fix:
        r = conn.execute(f"SELECT description FROM {tree} WHERE node_id = ?", (n["node_id"],)).fetchone()
        desc = r["description"] or "" if r else ""
        if desc:
            mentioned = [cn for cn in n["children"] if cn in desc]
            if mentioned:
                fixed_count += 1

    conn.close()
    return {
        "image_name": image_name,
        "fixed": fixed_count,
        "total": len(nodes_to_fix),
    }


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else KNOWN_ISSUES

    print(f"修复 {len(targets)} 个题材的一级子题材描述")
    print(f"使用后端: qwen3.6-plus")

    results = []
    for name in targets:
        r = repair_topic(name)
        results.append(r)

    print(f"\n{'='*50}")
    print("汇总")
    print(f"{'='*50}")
    for r in results:
        if r.get("skipped"):
            print(f"  {r['image_name']}: 跳过 ({r.get('reason', '')})")
        else:
            print(f"  {r['image_name']}: 修复 {r['fixed']}/{r['total']}")
