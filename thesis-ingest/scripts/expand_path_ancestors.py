#!/usr/bin/env python3
"""
T2.5path3: 展开 path_raw 为祖先题材归属候选
生成 JSON + Markdown 供用户验收
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

def load_source_data(json_path: str) -> dict:
    """加载源 JSON 数据"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def expand_candidate_topics(path_raw: list) -> list:
    """
    展开路径为候选题材归属
    
    例如 ["AI硬件", "光模块", "法拉第旋光片"]
    展开为 ["AI硬件", "光模块", "法拉第旋光片"]
    
    即每条路径上的所有节点都是候选归属题材
    """
    return path_raw.copy()

def process_items(source_data: dict) -> list:
    """处理所有条目，展开候选题材"""
    items = []
    global_index = 0
    
    for segment in source_data.get('parsed_segments', []):
        segment_id = segment.get('segment_id')
        proposed_name = segment.get('proposed_name', '')
        
        for local_item in segment.get('items', []):
            global_index += 1
            
            path_raw = local_item.get('path_raw', [])
            candidate_topics = expand_candidate_topics(path_raw)
            
            item = {
                'source_index': global_index,
                'source_segment_id': segment_id,
                'segment_name': proposed_name,
                'path_raw': path_raw,
                'path_display': ' / '.join(path_raw),
                'leaf_raw': local_item.get('leaf_raw', ''),
                'stock_text_raw': local_item.get('stock_text_raw', ''),
                'candidate_topics': candidate_topics,
                'candidate_topics_display': '; '.join(candidate_topics),
                'confidence': local_item.get('confidence', ''),
                'notes': local_item.get('notes', '')
            }
            
            # 添加额外备注
            depth = len(path_raw)
            if depth == 1:
                item['depth_note'] = '单层题材，股票仅属于该题材'
            elif depth == 2:
                item['depth_note'] = '双层题材，股票同时属于父题材和叶子题材'
            else:
                item['depth_note'] = f'{depth}层题材，股票同时属于路径上所有{depth}个题材节点'
            
            items.append(item)
    
    return items

def generate_json_output(source_data: dict, items: list, timestamp: str, source_path: str) -> dict:
    """生成 JSON 输出结构"""
    return {
        'source_path_json': source_path,
        'source_item_count': len(items),
        'expanded_candidate_count': len(items),
        'timestamp': timestamp,
        'task': 'T2.5path3',
        'description': '将 path_raw 展开为祖先题材归属候选，供用户验收',
        'note': '每个 candidate_topics 表示股票应同时属于该路径上的所有题材节点',
        'items': items
    }

def generate_markdown_output(items: list, timestamp: str, source_path: str) -> str:
    """生成 Markdown 输出"""
    lines = []
    
    # 标题
    lines.append('# 祖先题材归属候选展开报告')
    lines.append('')
    lines.append(f'**生成时间**: {timestamp}')
    lines.append(f'**任务**: T2.5path3')
    lines.append(f'**来源**: `{source_path}`')
    lines.append('')
    
    # 统计摘要
    lines.append('## 统计摘要')
    lines.append('')
    lines.append(f'- 原始 path 条目数量: **{len(items)}**')
    lines.append(f'- 展开后候选条目数量: **{len(items)}** (每条 path 都已展开)')
    lines.append('')
    
    # 深度分布统计
    depth_counts = {}
    for item in items:
        d = len(item['path_raw'])
        depth_counts[d] = depth_counts.get(d, 0) + 1
    
    lines.append('### 深度分布')
    lines.append('')
    lines.append('| 层级深度 | 条目数 | 说明 |')
    lines.append('|----------|--------|------|')
    for d in sorted(depth_counts.keys()):
        note = f'股票同时属于 {d} 个题材节点' if d > 1 else '股票仅属于单一题材'
        lines.append(f'| {d}层 | {depth_counts[d]} | {note} |')
    lines.append('')
    
    # 展开原则说明
    lines.append('## 展开原则')
    lines.append('')
    lines.append('对于每条路径，**股票同时属于路径上的所有题材节点**。')
    lines.append('')
    lines.append('例如：')
    lines.append('- 路径 `AI硬件 / 光模块 / 法拉第旋光片`')
    lines.append('- 股票 `福晶科技` 同时属于：')
    lines.append('  - AI硬件')
    lines.append('  - 光模块')
    lines.append('  - 法拉第旋光片')
    lines.append('')
    lines.append('---')
    lines.append('')
    
    # 详细条目列表
    lines.append('## 详细条目列表')
    lines.append('')
    
    for item in items:
        idx = item['source_index']
        lines.append(f'### 条目 {idx}')
        lines.append('')
        lines.append(f'- **来源 Segment**: {item["source_segment_id"]} ({item["segment_name"]})')
        lines.append(f'- **路径**: {item["path_display"]}')
        lines.append(f'- **叶子题材**: {item["leaf_raw"]}')
        lines.append(f'- **股票原文**: {item["stock_text_raw"]}')
        lines.append(f'- **候选归属题材**: {item["candidate_topics_display"]}')
        lines.append(f'- **置信度**: {item["confidence"]}')
        lines.append(f'- **层级说明**: {item["depth_note"]}')
        
        if item['notes']:
            lines.append(f'- **备注**: {item["notes"]}')
        
        lines.append('')
    
    # 底部说明
    lines.append('---')
    lines.append('')
    lines.append('*本报告仅为候选归属展开，不做股票名标准化、不做字典清洗、不写入数据库。*')
    lines.append('*请用户验收候选题材是否合理，确认后可进入 T2.5path4 写库阶段。*')
    
    return '\n'.join(lines)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="展开 path_raw 为祖先题材归属候选"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to path_segment_parse_*.json"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--fixed-name",
        action="store_true",
        help="使用固定文件名（无时间戳），由 orchestrator 控制输出目录"
    )
    args = parser.parse_args()
    
    # 输入文件
    source_json = Path(args.source)
    if not source_json.exists():
        print(f"错误: 源文件不存在: {source_json}")
        return None, None
    
    # 输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 时间戳
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 加载源数据
    source_data = load_source_data(str(source_json))
    
    # 处理条目
    items = process_items(source_data)
    
    # 生成输出
    json_output = generate_json_output(source_data, items, timestamp, str(source_json))
    md_output = generate_markdown_output(items, timestamp, str(source_json))
    
    if args.fixed_name:
        json_path = output_dir / 'ancestor_candidates.json'
        md_path = output_dir / 'ancestor_candidates.md'
    else:
        json_path = output_dir / f'path_ancestor_candidates_{timestamp}.json'
        md_path = output_dir / f'path_ancestor_candidates_{timestamp}.md'
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_output)
    
    print(f'✅ 完成: {len(items)} 条目已展开')
    print(f'✅ JSON: {json_path}')
    print(f'✅ Markdown: {md_path}')
    
    # 生成运行记录（非 fixed-name 模式）
    if not args.fixed_name:
        run_record = {
            "run_timestamp": timestamp,
            "source_json": str(source_json),
            "item_count": len(items),
            "output_json": str(json_path),
            "output_md": str(md_path),
            "status": "success"
        }

        run_record_path = output_dir / f"path_ancestor_candidates_run_{timestamp}.json"
        with open(run_record_path, 'w', encoding='utf-8') as f:
            json.dump(run_record, f, ensure_ascii=False, indent=2)
        print(f'✅ 运行记录: {run_record_path}')
    
    return str(json_path), str(md_path)

if __name__ == '__main__':
    main()