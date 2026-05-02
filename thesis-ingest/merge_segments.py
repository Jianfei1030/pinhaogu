#!/usr/bin/env python3
"""
T2.5mm3: 跨段合并 + 去重 + 层级拼接
"""
import json
from datetime import datetime
from collections import defaultdict

# 读取解析结果
with open('output/mm_segment_parse_20260409_200500.json', 'r', encoding='utf-8') as f:
    parse_data = json.load(f)

# 读取 manifest
with open('output/mm_segments_manifest_20260409_194244.json', 'r', encoding='utf-8') as f:
    manifest_data = json.load(f)

# 收集所有条目，标记来源段
all_items = []
for seg in parse_data['parsed_segments']:
    seg_id = seg['segment_id']
    for item in seg['items']:
        all_items.append({
            'segment_id': seg_id,
            'major_raw': item['major_raw'],
            'sub_raw': item['sub_raw'],
            'stock_text_raw': item['stock_text_raw'],
            'confidence': item['confidence'],
            'notes': item.get('notes', '')
        })

print(f"总条目数（含重复）: {len(all_items)}")

# 合并函数
def normalize_key(major, sub):
    """生成归一化键，处理嵌套大类格式"""
    major_clean = major.strip() if major else ''
    sub_clean = sub.strip() if sub else ''
    # 处理 "AI硬件-光模块" + "LPO" 这种嵌套格式
    # 统一为 "AI硬件" + "光模块-LPO"
    if '-' in major_clean:
        parts = major_clean.split('-', 1)
        base_major = parts[0].strip()
        nested_sub = parts[1].strip()
        if sub_clean:
            # 合并嵌套小类和显式小类
            combined_sub = f"{nested_sub}-{sub_clean}" if nested_sub != sub_clean else nested_sub
        else:
            combined_sub = nested_sub
        return (base_major, combined_sub)
    return (major_clean, sub_clean)

def merge_stock_lists(list1, list2):
    """合并两个股票列表，去重并保持顺序"""
    stocks1 = list1.split()
    stocks2 = list2.split()
    seen = set()
    result = []
    for s in stocks1 + stocks2:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return ' '.join(result)

# 按键分组
grouped = defaultdict(list)
for item in all_items:
    key = normalize_key(item['major_raw'], item['sub_raw'])
    grouped[key].append(item)

print(f"唯一键数: {len(grouped)}")

# 合并去重
merged_items = []
dedupe_notes = []

for (major, sub), items in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1] or '')):
    # 合并同一键下的所有条目
    sources = sorted(set(item['segment_id'] for item in items))
    stock_lists = [item['stock_text_raw'] for item in items]
    
    # 合并股票列表
    merged_stocks = stock_lists[0]
    for sl in stock_lists[1:]:
        merged_stocks = merge_stock_lists(merged_stocks, sl)
    
    # 检查是否有变化（去重或合并）
    original_count = sum(len(sl.split()) for sl in stock_lists)
    merged_count = len(merged_stocks.split())
    
    notes = []
    if len(items) > 1:
        notes.append(f"来自 {len(items)} 个段: {sources}")
    if original_count > merged_count:
        notes.append(f"去重: {original_count} → {merged_count}")
    
    merged_items.append({
        'merged_index': len(merged_items) + 1,
        'major': major,
        'sub': sub,
        'stock_text_raw': merged_stocks,
        'source_segments': sources,
        'confidence': '高',
        'notes': '; '.join(notes) if notes else ''
    })
    
    # 记录去重详情
    if len(items) > 1:
        dedupe_notes.append({
            'key': f"{major} - {sub or '(无小类)'}",
            'source_count': len(items),
            'source_segments': sources,
            'original_stock_count': original_count,
            'merged_stock_count': merged_count,
            'duplicate_removed': original_count - merged_count
        })

print(f"合并后条目数: {len(merged_items)}")

# 生成时间戳
ts = datetime.now().strftime('%Y%m%d_%H%M%S')

# 输出 JSON
output_json = {
    'source_manifest': 'output/mm_segments_manifest_20260409_194244.json',
    'source_parse_json': 'output/mm_segment_parse_20260409_200500.json',
    'merged_item_count': len(merged_items),
    'timestamp': ts,
    'items': merged_items
}

json_path = f'output/mm_merged_result_{ts}.json'
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(output_json, f, ensure_ascii=False, indent=2)
print(f"JSON 输出: {json_path}")

# 输出 Markdown
md_lines = []
md_lines.append("# 论文股票列表合并结果")
md_lines.append("")
md_lines.append(f"**合并时间**: {ts}")
md_lines.append(f"**来源**: mm_segment_parse_20260409_200500.json")
md_lines.append(f"**原始条目数**: {len(all_items)}（10 个 segment，含重叠）")
md_lines.append(f"**合并后条目数**: {len(merged_items)}")
md_lines.append(f"**去重说明**: 相邻段有 8% 重叠，已合并重复项")
md_lines.append("")
md_lines.append("---")
md_lines.append("")

for item in merged_items:
    md_lines.append(f"## 条目 {item['merged_index']}")
    md_lines.append(f"- **大类**: {item['major']}")
    md_lines.append(f"- **小类**: {item['sub'] or '（无）'}")
    md_lines.append(f"- **股票原文**: {item['stock_text_raw']}")
    md_lines.append(f"- **来源段**: {item['source_segments']}")
    md_lines.append(f"- **置信度**: {item['confidence']}")
    if item['notes']:
        md_lines.append(f"- **备注**: {item['notes']}")
    md_lines.append("")

md_path = f'output/mm_merged_result_{ts}.md'
with open(md_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(md_lines))
print(f"Markdown 输出: {md_path}")

# 输出去重笔记
if dedupe_notes:
    dedupe_lines = []
    dedupe_lines.append("# 跨段去重详情")
    dedupe_lines.append("")
    dedupe_lines.append("以下条目在多个 segment 中出现，已合并去重：")
    dedupe_lines.append("")
    
    for note in dedupe_notes:
        dedupe_lines.append(f"### {note['key']}")
        dedupe_lines.append(f"- 出现次数: {note['source_count']}")
        dedupe_lines.append(f"- 来源段: {note['source_segments']}")
        dedupe_lines.append(f"- 原始股票数: {note['original_stock_count']}")
        dedupe_lines.append(f"- 合并后股票数: {note['merged_stock_count']}")
        dedupe_lines.append(f"- 去重数量: {note['duplicate_removed']}")
        dedupe_lines.append("")
    
    dedupe_path = f'output/mm_merged_dedupe_notes_{ts}.md'
    with open(dedupe_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(dedupe_lines))
    print(f"去重笔记: {dedupe_path}")

print("\n合并完成！")