#!/usr/bin/env python3
"""
T2.5mm3 V2: 跨段合并 + 去重 + 层级拼接（改进版）
正确处理：
1. 完全重复
2. 子集重复（后一段是前一段的子集）
3. 跨段延续（同一大类小类跨段出现）
"""
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path("os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest")
OUTPUT_DIR = BASE_DIR / "output"

MANIFEST_PATH = OUTPUT_DIR / "mm_segments_manifest_20260409_194244.json"
PARSE_PATH = OUTPUT_DIR / "mm_segment_parse_20260409_200500.json"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_major(major):
    """标准化大类名称"""
    if not major:
        return ""
    # 处理变体：AI硬件-光模块 → AI硬件
    if major.startswith("AI硬件"):
        return "AI硬件"
    return major.strip()


def normalize_sub(sub):
    """标准化小类名称"""
    if not sub:
        return None
    sub = sub.strip()
    return sub


def get_stock_set(stock_text):
    """将股票文本转为集合"""
    if not stock_text:
        return set()
    return set(stock_text.split())


def is_subset_or_overlap(set1, set2):
    """
    判断两个集合的关系
    返回: (relation, overlap_ratio)
    - relation: "identical" / "subset1" / "subset2" / "overlap" / "disjoint"
    - overlap_ratio: 重叠比例
    """
    if not set1 or not set2:
        return "disjoint", 0.0
    
    if set1 == set2:
        return "identical", 1.0
    
    if set1.issubset(set2):
        return "subset1", len(set1) / len(set2)
    
    if set2.issubset(set1):
        return "subset2", len(set2) / len(set1)
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    if intersection > 0:
        return "overlap", intersection / union
    
    return "disjoint", 0.0


def should_merge(item1, item2):
    """
    判断两个条目是否应该合并
    返回: (should_merge, merge_type, reason)
    """
    major1 = normalize_major(item1.get("major_raw", ""))
    major2 = normalize_major(item2.get("major_raw", ""))
    
    # 大类必须匹配
    if major1 != major2:
        return False, None, "major mismatch"
    
    sub1 = normalize_sub(item1.get("sub_raw"))
    sub2 = normalize_sub(item2.get("sub_raw"))
    
    # 小类必须匹配（None 也视为匹配）
    if sub1 != sub2:
        return False, None, "sub mismatch"
    
    stocks1 = get_stock_set(item1.get("stock_text_raw", ""))
    stocks2 = get_stock_set(item2.get("stock_text_raw", ""))
    
    relation, ratio = is_subset_or_overlap(stocks1, stocks2)
    
    if relation == "identical":
        return True, "duplicate", "完全重复"
    
    if relation == "subset1":
        # item1 是 item2 的子集
        return True, "subset_merge", f"item1({len(stocks1)}股)是item2({len(stocks2)}股)的子集，保留item2"
    
    if relation == "subset2":
        # item2 是 item1 的子集
        return True, "subset_merge", f"item2({len(stocks2)}股)是item1({len(stocks1)}股)的子集，保留item1"
    
    if relation == "overlap" and ratio >= 0.3:
        # 有交集，合并成完整列表
        return True, "overlap_merge", f"交集比例{ratio:.1%}，合并成完整列表"
    
    return False, None, "no significant overlap"


def main():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(PARSE_PATH, "r", encoding="utf-8") as f:
        parse_data = json.load(f)
    
    print(f"加载: {PARSE_PATH.name}")
    print(f"共 {parse_data['segment_count']} 个 segment")
    
    # 按段顺序收集所有条目
    all_items = []
    for seg in parse_data["parsed_segments"]:
        seg_id = seg["segment_id"]
        for item in seg["items"]:
            all_items.append({
                "major_raw": item.get("major_raw", ""),
                "sub_raw": item.get("sub_raw"),
                "stock_text_raw": item.get("stock_text_raw", ""),
                "confidence": item.get("confidence", "中"),
                "notes": item.get("notes", ""),
                "source_segment": seg_id
            })
    
    print(f"原始条目总数: {len(all_items)}")
    
    # 去重合并
    merged_items = []
    used_indices = set()
    dedupe_log = []
    
    for i in range(len(all_items)):
        if i in used_indices:
            continue
        
        item1 = all_items[i]
        current_major = normalize_major(item1["major_raw"])
        current_sub = normalize_sub(item1["sub_raw"])
        current_stocks = get_stock_set(item1["stock_text_raw"])
        current_sources = [item1["source_segment"]]
        current_conf = item1["confidence"]
        current_notes = item1["notes"]
        
        # 向前查找后续条目
        for j in range(i + 1, len(all_items)):
            if j in used_indices:
                continue
            
            item2 = all_items[j]
            should, merge_type, reason = should_merge(item1, item2)
            
            if should:
                stocks2 = get_stock_set(item2["stock_text_raw"])
                
                if merge_type == "subset_merge":
                    # 子集合并：保留更大的股票列表
                    if len(stocks2) > len(current_stocks):
                        current_stocks = stocks2
                    # 合并来源段
                    current_sources.append(item2["source_segment"])
                    current_conf = "高" if "高" in [current_conf, item2["confidence"]] else current_conf
                    
                elif merge_type == "overlap_merge" or merge_type == "duplicate":
                    # 合并股票列表
                    current_stocks = current_stocks | stocks2
                    current_sources.append(item2["source_segment"])
                    current_conf = "高" if "高" in [current_conf, item2["confidence"]] else current_conf
                
                used_indices.add(j)
                
                dedupe_log.append({
                    "type": merge_type,
                    "segment1": item1["source_segment"],
                    "segment2": item2["source_segment"],
                    "major": current_major,
                    "sub": current_sub,
                    "reason": reason,
                    "stocks_before_merge": item1["stock_text_raw"],
                    "stocks_added": item2["stock_text_raw"]
                })
        
        used_indices.add(i)
        
        # 构建最终条目
        final_stocks = " ".join(sorted(current_stocks))
        final_note = current_notes
        if len(current_sources) > 1:
            final_note = f"合并自段{','.join(map(str, sorted(set(current_sources))))}，去重后{len(current_stocks)}股"
        
        merged_items.append({
            "major": item1["major_raw"],  # 保持原文，但大类标准化
            "sub": item1["sub_raw"],
            "stock_text_raw": final_stocks,
            "source_segments": sorted(list(set(current_sources))),
            "confidence": current_conf,
            "notes": final_note
        })
    
    print(f"合并后条目数: {len(merged_items)}")
    print(f"去重合并数: {len(dedupe_log)}")
    
    # 分配索引
    for idx, item in enumerate(merged_items, 1):
        item["merged_index"] = idx
    
    # 输出 JSON
    output_json = {
        "source_manifest": MANIFEST_PATH.name,
        "source_parse_json": PARSE_PATH.name,
        "original_item_count": len(all_items),
        "merged_item_count": len(merged_items),
        "dedupe_count": len(dedupe_log),
        "items": merged_items
    }
    
    json_path = OUTPUT_DIR / f"mm_merged_result_{TIMESTAMP}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    print(f"输出 JSON: {json_path.name}")
    
    # 输出 Markdown
    md_lines = [
        "# 多模态解析合并结果（T2.5mm3）\n",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**来源**: {PARSE_PATH.name}",
        f"**原始条目数**: {len(all_items)}",
        f"**合并后条目数**: {len(merged_items)}",
        f"**去重合并数**: {len(dedupe_log)}",
        "",
        "---\n"
    ]
    
    for item in merged_items:
        md_lines.append(f"## 条目 {item['merged_index']}\n")
        md_lines.append(f"- **大类**: {item['major'] or '(无)'}")
        md_lines.append(f"- **小类**: {item['sub'] or '(无)'}")
        md_lines.append(f"- **股票原文**: {item['stock_text_raw']}")
        md_lines.append(f"- **来源段**: {','.join(map(str, item['source_segments']))}")
        md_lines.append(f"- **置信度**: {item['confidence']}")
        if item['notes']:
            md_lines.append(f"- **备注**: {item['notes']}")
        md_lines.append("")
    
    md_path = OUTPUT_DIR / f"mm_merged_result_{TIMESTAMP}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"输出 Markdown: {md_path.name}")
    
    # 去重笔记
    if dedupe_log:
        dedupe_lines = [
            "# 去重合并记录（T2.5mm3）\n",
            f"**去重合并数**: {len(dedupe_log)}",
            "",
            "---\n"
        ]
        
        for log in dedupe_log:
            dedupe_lines.append(f"### {log['major']} / {log['sub'] or '(无)'}\n")
            dedupe_lines.append(f"- **类型**: {log['type']}")
            dedupe_lines.append(f"- **来源**: 段{log['segment1']} + 段{log['segment2']}")
            dedupe_lines.append(f"- **原因**: {log['reason']}")
            dedupe_lines.append(f"- **原文**: {log['stocks_before_merge']}")
            dedupe_lines.append(f"- **补充**: {log['stocks_added']}")
            dedupe_lines.append("")
        
        dedupe_path = OUTPUT_DIR / f"mm_merged_dedupe_notes_{TIMESTAMP}.md"
        with open(dedupe_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dedupe_lines))
        print(f"输出去重笔记: {dedupe_path.name}")
    
    print("\n完成！")
    return json_path, md_path


if __name__ == "__main__":
    main()