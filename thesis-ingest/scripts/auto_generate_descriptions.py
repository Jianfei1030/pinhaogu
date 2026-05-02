#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_generate_descriptions.py — 题材描述自动生成模块

为指定题材生成根题材描述 + 所有子题材节点的 description。
入库完成后自动调用，失败不影响入库流程。

Usage:
    from scripts.auto_generate_descriptions import generate_thesis_description
    generate_thesis_description("AI 硬件", "thesis.db")
"""

import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------

# 百炼 qwen（备选）
QWEN_API_KEY = "YOUR_API_KEY"
QWEN_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
QWEN_MODEL = "qwen3.6-plus"

# GitHub Copilot gpt-5-mini（默认）
COPILOT_MODEL = "gpt-5-mini"

MAX_RETRIES = 3
BATCH_SIZE = 10

# 默认后端：copilot 优先，qwen 备选
# 可通过 CLI --backend 或 generate_thesis_description(backend=...) 覆盖
DEFAULT_BACKEND = "copilot"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# 表名工具
# ---------------------------------------------------------------------------

def resolve_tree_tables(image_name: str) -> tuple[str, str]:
    """返回 (tree_table, stocks_table) 名称。"""
    h = hashlib.md5(image_name.strip().encode('utf-8')).hexdigest()[:8]
    return f"thesis_tree_{h}", f"thesis_stocks_tree_{h}"


# ---------------------------------------------------------------------------
# LLM 调用 — Copilot (gpt-5-mini)
# ---------------------------------------------------------------------------

def _call_copilot(system_prompt: str, user_prompt: str) -> str:
    """调用 GitHub Copilot SDK (gpt-5-mini) 生成文本。

    使用本机已登录的 GitHub 账号，不依赖 OpenAI key。
    """
    import asyncio
    from copilot import CopilotClient
    from copilot.types import PermissionRequestResult

    def approve_all(request, invocation=None):
        return PermissionRequestResult(kind="approved")

    async def _run():
        client = CopilotClient({"use_logged_in_user": True})
        await client.start()
        session = None
        try:
            session = await client.create_session({
                "on_permission_request": approve_all,
                "model": COPILOT_MODEL,
                "streaming": True,
            })
            done = asyncio.Event()
            response_parts = []

            def on_event(event):
                data = event.data
                if hasattr(data, "delta_content") and data.delta_content:
                    response_parts.append(data.delta_content)
                if event.type.value in ("session.idle", "error"):
                    done.set()

            session.on(on_event)
            await session.send({
                "prompt": system_prompt + "\n\n" + user_prompt,
            })
            await done.wait()
            return "".join(response_parts).strip()
        finally:
            if session:
                await session.destroy()
            await client.stop()

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# LLM 调用 — 百炼 qwen（备选）
# ---------------------------------------------------------------------------

def _call_qwen(system_prompt: str, user_prompt: str) -> str:
    """调用百炼 API（openai 兼容接口），作为 Copilot 失败时的备选。
    """
    from openai import OpenAI

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=2048,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 * attempt
                print(f"    [WARN] qwen 调用第 {attempt} 次失败: {e}，{wait}s 后重试...")
                time.sleep(wait)
            else:
                print(f"    [ERROR] qwen 调用失败，已达最大重试次数: {e}")

    raise last_error


# ---------------------------------------------------------------------------
# LLM 调用 — 路由（copilot 优先 → qwen fallback）
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str, backend: str = None) -> str:
    """调用 LLM 生成文本，优先 Copilot SDK，失败后可 fallback 到 qwen。"""
    if backend is None:
        backend = DEFAULT_BACKEND

    if backend == "qwen":
        return _call_qwen(system_prompt, user_prompt)

    if backend in ("copilot", "auto"):
        try:
            result = _call_copilot(system_prompt, user_prompt)
            if result:
                return result
        except Exception as e:
            print(f"    [WARN] copilot 调用失败: {e}")
            print(f"    自动 fallback 到 qwen ({QWEN_MODEL})...")
            return _call_qwen(system_prompt, user_prompt)

    raise Exception(f"未知后端: {backend}")


def _parse_json_response(text: str) -> list[dict]:
    """解析 LLM 返回的 JSON，处理可能的 markdown code block 包裹。"""
    text = text.strip()
    # 去掉可能的 ```json ... ``` 包裹
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    return json.loads(text)


# ---------------------------------------------------------------------------
# 根题材描述生成
# ---------------------------------------------------------------------------

def _generate_root_description(
    image_name: str,
    child_node_names: list[str],
    total_stock_count: int,
    node_count: int,
    backend: str = None,
) -> str:
    """生成根题材描述。"""
    system_prompt = (
        "你是一位专业的 A 股题材分析师。请根据题材名称和子题材列表生成一段简短描述。"
        "要求：\n"
        "1. 50-200 个中文字符\n"
        "2. 说明题材定位和覆盖范围\n"
        "3. 列出包含的核心子题材方向\n"
        "4. 只输出描述文本，不要前缀或格式标记"
    )

    # 去重，排除根节点名本身
    seen = set()
    unique_children = []
    for n in child_node_names:
        if n not in seen and n != image_name:
            seen.add(n)
            unique_children.append(n)

    nodes_str = "、".join(unique_children) if unique_children else "暂无子题材分类"

    user_prompt = (
        f"题材名称：{image_name}\n"
        f"子题材列表：{nodes_str}\n"
        f"题材总股票数：{total_stock_count}\n"
        f"题材节点数：{node_count}"
    )

    result = _call_llm(system_prompt, user_prompt, backend=backend)
    # 清理引号包裹
    result = result.strip().strip('"').strip("'").strip()
    if len(result) > 250:
        result = result[:247] + "..."
    return result


# ---------------------------------------------------------------------------
# 子题材批量描述生成
# ---------------------------------------------------------------------------

def _build_sub_node_prompt(image_name: str, nodes: list[dict]) -> str:
    """构建子题材批量 prompt 的 user 部分。"""
    json_str = json.dumps(nodes, ensure_ascii=False)
    return (
        "你是一位专业的 A 股题材分析师。请为以下子题材节点生成简短描述。\n\n"
        f"题材：{image_name}\n\n"
        "节点列表（JSON格式，每个节点包含 node_id, node_name, parent_name, children, full_path, node_type）：\n"
        f"{json_str}\n\n"
        "要求：\n"
        '1. first_level 节点：30-120 字，格式 "X是{父题材}的核心方向，涉及[一句话描述]。包含以下子方向：A、B、C等。"\n'
        '2. second_level 节点：30-120 字，格式 "X是{父节点}的子领域，涉及[一句话描述]。"\n'
        '3. 输出纯 JSON 数组：[{"node_id": 节点ID, "node_name": "节点名", "description": "描述"}, ...]\n'
        "4. node_id 和 node_name 必须与输入完全一致\n"
        "5. 不要任何额外文本，只要 JSON 数组\n"
        "6. first_level 节点必须在描述中明确列出所有 children（二级子题材名称）\n"
    )


def _generate_sub_descriptions(
    image_name: str,
    sub_nodes: list[dict],
    backend: str = None,
) -> list[dict]:
    """批量生成子题材描述，每批 BATCH_SIZE 个节点。"""
    system_prompt = "你是一位专业的 A 股题材分析师，擅长根据题材结构生成精炼描述。"

    all_results = []
    for i in range(0, len(sub_nodes), BATCH_SIZE):
        batch = sub_nodes[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(sub_nodes) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"    批次 {batch_num}/{total_batches} ({len(batch)} 节点)...")

        user_prompt = _build_sub_node_prompt(image_name, batch)

        # 批次级重试（最多 3 次）
        valid = []
        last_error = None
        for retry in range(1, 4):
            try:
                if retry > 1:
                    print(f"    重试 {retry}/3...")
                    time.sleep(2)
                raw = _call_llm(system_prompt, user_prompt, backend=backend)
                parsed = _parse_json_response(raw)

                # 验证返回结果
                # 优先用 node_id 匹配，LLM 没返回则用位置匹配
                valid = []
                for idx, item in enumerate(parsed):
                    if "node_name" not in item or "description" not in item:
                        print(f"    [WARN] 无效条目（缺少字段）: {item}")
                        continue

                    node_id = item.get("node_id")
                    if node_id is None and idx < len(batch):
                        # LLM 没返回 node_id，用输入的位置 ID 补上
                        node_id = batch[idx].get("node_id")

                    if node_id is not None:
                        item["node_id"] = node_id
                    valid.append(item)

                all_results.extend(valid)
                print(f"    ✓ 批次 {batch_num} 生成 {len(valid)} 条描述{f' (重试 {retry-1} 次)' if retry > 1 else ''}")
                last_error = None  # 成功，清除错误
                break  # 成功，跳出重试循环

            except json.JSONDecodeError as e:
                last_error = f"JSON 解析失败: {e}"
                if retry < 3:
                    print(f"    [WARN] 批次 {batch_num} {last_error}")
                else:
                    print(f"    [ERROR] 批次 {batch_num} JSON 解析失败，已达最大重试: {e}")
            except Exception as e:
                last_error = str(e)
                if retry < 3:
                    print(f"    [WARN] 批次 {batch_num} 生成失败: {e}")
                else:
                    print(f"    [ERROR] 批次 {batch_num} 生成失败，已达最大重试: {e}")

        # 批次间 sleep 避免限流
        if i + BATCH_SIZE < len(sub_nodes):
            time.sleep(1)

    return all_results


# ---------------------------------------------------------------------------
# 数据库写入
# ---------------------------------------------------------------------------

def _write_root_description(
    conn: sqlite3.Connection,
    image_name: str,
    description: str,
) -> bool:
    """写入根题材描述到 thesis_catalog。"""
    cur = conn.execute("""
        UPDATE thesis_catalog
        SET description = ?, updated_at = datetime('now', 'localtime')
        WHERE image_name = ?
    """, (description, image_name))
    conn.commit()
    return cur.rowcount > 0


def _write_sub_descriptions(
    conn: sqlite3.Connection,
    tree_table: str,
    descriptions: list[dict],
) -> int:
    """批量写入子题材描述到 thesis_tree_{suffix}。

    ⚠️ 使用 node_id 而非 node_name，避免同名节点被覆盖。
    """
    count = 0
    for item in descriptions:
        node_id = item.get("node_id")
        desc = item["description"]
        if node_id is None:
            continue
        cur = conn.execute(f"""
            UPDATE {tree_table}
            SET description = ?, updated_at = datetime('now', 'localtime')
            WHERE node_id = ?
        """, (desc, node_id))
        if cur.rowcount > 0:
            count += 1
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def generate_thesis_description(image_name: str, db_path: str = "thesis.db", backend: str = None) -> bool:
    """
    为指定题材生成根题材描述 + 所有子题材节点的 description。

    流程：
    1. 连接数据库，获取该题材的完整树结构
    2. 如果 thesis_catalog.description 已有值 → 跳过
    3. 构建根题材 prompt（题材名 + 所有子节点列表）→ 调 LLM 生成根描述
    4. 批量生成子题材描述（按 20 个节点/批）
    5. 打印统计：根描述 + X 条子描述
    6. 返回 True（成功）或 False（部分失败但继续）
    """
    db_file = str(Path(db_path) if not Path(db_path).is_absolute()
                  else PROJECT_ROOT / db_path)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    try:
        # 1. 检查根题材是否存在
        catalog_row = conn.execute(
            "SELECT description, node_count, total_stock_count FROM thesis_catalog WHERE image_name = ?",
            (image_name,)
        ).fetchone()

        if not catalog_row:
            print(f"    [ERROR] 题材不存在: {image_name}")
            return False

        # 2. 如果根描述已有值 → 跳过
        if catalog_row["description"] and len(catalog_row["description"]) >= 10:
            print(f"    [SKIP] 根描述已存在，跳过")
            # 但仍然检查子节点描述是否需要补充
        else:
            # 3. 获取树结构
            tree_table, stocks_table = resolve_tree_tables(image_name)

            # 检查树表是否存在
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (tree_table,)
            ).fetchone()
            if not table_exists:
                print(f"    [ERROR] 树表不存在: {tree_table}")
                return False

            # 获取所有节点（排除 root 节点）
            node_rows = conn.execute(f"""
                SELECT node_id, node_name, node_type, depth, full_path, parent_id, description
                FROM {tree_table}
                WHERE node_type != 'root'
                ORDER BY depth, node_name
            """).fetchall()

            child_names = [r["node_name"] for r in node_rows]

            # 4. 生成根描述
            print(f"    生成根题材描述...")
            try:
                root_desc = _generate_root_description(
                    image_name,
                    child_names,
                    catalog_row["total_stock_count"] or 0,
                    catalog_row["node_count"] or 0,
                    backend=backend,
                )
                _write_root_description(conn, image_name, root_desc)
                print(f"    ✓ 根描述: {root_desc[:60]}...")
            except Exception as e:
                print(f"    [ERROR] 根描述生成失败: {e}")
                return False

        # 5. 批量生成子题材描述
        tree_table, _ = resolve_tree_tables(image_name)

        # 获取所有需要补充描述的子节点
        sub_nodes_rows = conn.execute(f"""
            SELECT t.node_id, t.node_name, t.node_type, t.depth, t.full_path, t.parent_id,
                   p.node_name as parent_name,
                   (SELECT COUNT(*) FROM {tree_table} c WHERE c.parent_id = t.node_id) as child_count
            FROM {tree_table} t
            LEFT JOIN {tree_table} p ON t.parent_id = p.node_id
            WHERE t.node_type != 'root'
              AND (t.description IS NULL OR t.description = '')
            ORDER BY t.depth, t.node_name
        """).fetchall()

        if not sub_nodes_rows:
            print(f"    [SKIP] 所有子节点已有描述")
            conn.close()
            return True

        # 构建子节点数据
        sub_nodes = []
        for r in sub_nodes_rows:
            # 获取子节点名称列表
            children_rows = conn.execute(
                f"SELECT node_name FROM {tree_table} WHERE parent_id = ? ORDER BY node_name",
                (r["node_id"],)
            ).fetchall()
            children = [cr["node_name"] for cr in children_rows]

            sub_nodes.append({
                "node_id": r["node_id"],
                "node_name": r["node_name"],
                "node_type": r["node_type"],
                "full_path": r["full_path"],
                "parent_name": r["parent_name"] or "",
                "children": children,
            })

        print(f"    生成 {len(sub_nodes)} 个子题材描述（{BATCH_SIZE} 个/批）...")
        sub_descriptions = _generate_sub_descriptions(image_name, sub_nodes, backend=backend)

        # 6. 写入子描述
        if sub_descriptions:
            written = _write_sub_descriptions(conn, tree_table, sub_descriptions)
            print(f"    ✓ 已写入 {written}/{len(sub_nodes)} 条子描述")
        else:
            print(f"    [WARN] 未生成任何子描述")
            written = 0

        # 7. 统计
        total_sub = len(sub_nodes)
        print(f"    📊 完成: 根描述 + {written}/{total_sub} 条子描述")

        return written > 0 or (catalog_row["description"] and len(catalog_row["description"]) >= 10)

    except Exception as e:
        print(f"    [ERROR] generate_thesis_description 异常: {e}")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="题材描述自动生成")
    parser.add_argument("--image", required=True, help="题材名称")
    parser.add_argument("--db", default="thesis.db", help="数据库路径")
    parser.add_argument("--backend", default=None, choices=["copilot", "qwen", "auto"],
                        help="LLM 后端: copilot (gpt-5-mini 默认), qwen (qwen3.6-plus 备选), auto (自动fallback)")
    args = parser.parse_args()

    ok = generate_thesis_description(args.image, args.db, backend=args.backend)
    sys.exit(0 if ok else 1)
