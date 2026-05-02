#!/usr/bin/env python3.10
"""Batch generate descriptions for first_level and second_level nodes in thesis.db."""

import sqlite3
import json
import time
import sys
from openai import OpenAI

sys.path.insert(0, 'scripts')
from thesis_api import resolve_tree_tables

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="https://coding.dashscope.aliyuncs.com/v1"
)

THESES = ['AI 硬件', '光伏', '商业航天', '固态电池', '电力']

def get_nodes_with_context(conn, table):
    """Get all empty-description nodes with parent/child context."""
    cur = conn.cursor()
    
    # Get target nodes
    cur.execute(f'''SELECT node_id, node_name, node_type, parent_id, full_path, depth
                     FROM {table}
                     WHERE node_type IN ('first_level','second_level')
                       AND (description IS NULL OR description = '')
                     ORDER BY depth, node_id''')
    target_nodes = cur.fetchall()
    
    if not target_nodes:
        return []
    
    # Get all nodes in this tree for context
    cur.execute(f'SELECT node_id, node_name, node_type, parent_id, depth FROM {table}')
    all_nodes = {r[0]: {'name': r[1], 'type': r[2], 'parent_id': r[3], 'depth': r[4]} for r in cur.fetchall()}
    
    # Build children map
    children_map = {}
    for nid, info in all_nodes.items():
        pid = info['parent_id']
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(info['name'])
    
    result = []
    for node in target_nodes:
        node_id, node_name, node_type, parent_id, full_path, depth = node
        parent_name = full_path.split(' / ')[-2] if ' / ' in full_path else full_path
        children = children_map.get(node_id, [])
        result.append({
            'node_id': node_id,
            'node_name': node_name,
            'node_type': node_type,
            'parent_name': parent_name,
            'children': children,
            'full_path': full_path
        })
    
    return result


def build_prompt(thesis, nodes):
    """Build LLM prompt for batch description generation."""
    node_lines = []
    for i, n in enumerate(nodes, 1):
        type_label = n['node_type']
        children_str = ', '.join(n['children']) if n['children'] else '无'
        node_lines.append(f"{i}. [{type_label}] {n['node_name']} - 父节点: {n['parent_name']} - 子节点: {children_str}")
    
    nodes_text = '\n'.join(node_lines)
    
    prompt = f"""你是一位专业的A股题材分析师。请为以下"{thesis}"题材的子题材节点生成简短描述。

节点列表：
{nodes_text}

格式要求：
- first_level: "X是...的题材。包含A、B等子题材。"
- second_level: "X是...的子领域，涉及...业务。"
- 每条 30-120 字符
- 输出纯 JSON 数组：[{{"node_name": "节点名", "description": "描述"}}, ...]
- node_name 必须与上面列表完全一致
- 不要任何额外文本，只要 JSON 数组"""
    
    return prompt


def call_llm(prompt):
    """Call LLM and parse JSON response."""
    response = client.chat.completions.create(
        model="qwen3.6-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    
    content = response.choices[0].message.content.strip()
    
    # Handle potential markdown code blocks
    if content.startswith('```'):
        # Remove code block markers
        lines = content.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        content = '\n'.join(lines).strip()
    
    return json.loads(content)


def update_descriptions(conn, table, items):
    """Batch update descriptions in database."""
    cur = conn.cursor()
    count = 0
    for item in items:
        node_name = item['node_name']
        desc = item['description'].strip()
        # Truncate if too long
        if len(desc) > 120:
            desc = desc[:117] + '...'
        cur.execute(
            f"UPDATE {table} SET description = ?, updated_at = datetime('now','localtime') WHERE node_name = ?",
            (desc, node_name)
        )
        count += cur.rowcount
    conn.commit()
    return count


def process_thesis(thesis):
    """Process one thesis: query nodes -> LLM -> update."""
    tree, _ = resolve_tree_tables(thesis)
    conn = sqlite3.connect('thesis.db')
    
    nodes = get_nodes_with_context(conn, tree)
    if not nodes:
        print(f'{thesis}: 无需补充')
        conn.close()
        return 0
    
    print(f'{thesis}: {len(nodes)} 个节点待补充, table={tree}')
    
    # Split into batches of ~40 nodes to avoid context limits
    batch_size = 40
    total_updated = 0
    
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i+batch_size]
        print(f'  批次 {i//batch_size + 1}: {len(batch)} 个节点...')
        
        prompt = build_prompt(thesis, batch)
        
        try:
            result = call_llm(prompt)
            print(f'    LLM 返回 {len(result)} 条描述')
            
            # Validate
            for item in result:
                if 'node_name' not in item or 'description' not in item:
                    print(f'    警告: 无效条目 {item}')
                elif len(item['description']) < 10:
                    print(f'    警告: {item["node_name"]} 描述过短: {item["description"]}')
            
            updated = update_descriptions(conn, tree, result)
            total_updated += updated
            print(f'    更新 {updated} 条')
            
            # Rate limit: wait between batches
            if i + batch_size < len(nodes):
                print('    等待 2 秒...')
                time.sleep(2)
                
        except Exception as e:
            print(f'    错误: {e}')
            # Retry once
            print('    重试...')
            time.sleep(3)
            try:
                result = call_llm(prompt)
                updated = update_descriptions(conn, tree, result)
                total_updated += updated
                print(f'    重试成功，更新 {updated} 条')
            except Exception as e2:
                print(f'    重试也失败: {e2}')
    
    conn.close()
    return total_updated


def verify_all():
    """Verify all theses have descriptions filled."""
    print('\n=== 验证结果 ===')
    for thesis in THESES:
        tree, _ = resolve_tree_tables(thesis)
        conn = sqlite3.connect('thesis.db')
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {tree} WHERE node_type IN ('first_level','second_level')")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {tree} WHERE node_type IN ('first_level','second_level') AND description IS NOT NULL AND description != ''")
        filled = cur.fetchone()[0]
        print(f'{thesis}: {filled}/{total}')
        conn.close()


if __name__ == '__main__':
    for thesis in THESES:
        updated = process_thesis(thesis)
        if updated > 0:
            time.sleep(1)  # Rate limit between theses
    
    verify_all()
