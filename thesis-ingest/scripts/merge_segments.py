#!/usr/bin/env python3
"""
T2.5mm3: 跨段合并 + 去重 + 层级拼接
将 10 段多模态解析结果合并成完整可验收的结构化结果
"""
import json
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

# 工作目录
BASE_DIR = Path("os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest")
OUTPUT_DIR = BASE_DIR / "output"

# 输入文件
MANIFEST_PATH = OUTPUT_DIR / "mm_segments_manifest_20260409_194244.json"
PARSE_PATH = OUTPUT_DIR / "mm_segment_parse_20260409_200500.json"

# 时间戳
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_major(major):
    """标准化大类名称"""
    if not major:
        return ""
    # 处理 "AI硬件-光模块" → "AI硬件"
    if major.startswith("AI硬件"):
        return "AI硬件"
    return major.strip()


def normalize_sub(sub):
    """标准化小类名称"""
    if not sub:
        return None
    sub = sub.strip()
    # 处理 "光模块-LPO" → "LPO"
    if sub.startswith("光模块-"):
        return sub.replace("光模块-", "")
    return sub


def stocks_similarity(stocks1, stocks2):
    """计算两个股票字符串的相似度"""
    if not stocks1 or not stocks2:
        return 0.0
    # 分词成集合
    set1 = set(stocks1.split())
    set2 = set(stocks2.split())
    if not set1 or not set2:
        return 0.0
    # Jaccard 相似度
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def is_duplicate(item1, item2):
    """
    判断两个条目是否重复
    返回: (is_dup, dup_type)
    - is_dup: True/False
    - dup_type: "exact"/"partial"/None
    """
    major1 = normalize_major(item1.get("major_raw", ""))
    major2 = normalize_major(item2.get("major_raw", ""))
    sub1 = normalize_sub(item1.get("sub_raw"))
    sub2 = normalize_sub(item2.get("sub_raw"))
    
    # 大类必须相同
    if major1 != major2:
        return False, None
    
    # 小类必须相同（或都为 None）
    if sub1 != sub2:
        return False, None
    
    # 比较股票列表
    stocks1 = item1.get("stock_text_raw", "")
    stocks2 = item2.get("stock_text_raw", "")
    sim = stocks_similarity(stocks1, stocks2)
    
    if sim >= 0.8:
        return True, "exact"
    elif sim >= 0.3:
        return True, "partial"
    
    return False, None


def merge_two_items(item1, item2, seg1, seg2):
    """
    合并两个重复条目
    优先保留语义更完整、股票列表更长的一条
    """
    stocks1 = item1.get("stock_text_raw", "")
    stocks2 = item2.get("stock_text_raw", "")
    
    # 合并股票列表（去重）
    all_stocks = set(stocks1.split()) | set(stocks2.split())
    merged_stocks = " ".join(sorted(all_stocks))
    
    # 选择更完整的大类/小类
    major = item1.get("major_raw", "") or item2.get("major_raw", "")
    sub = item1.get("sub_raw") or item2.get("sub_raw")
    
    # 合并置信度
    conf1 = item1.get("confidence", "中")
    conf2 = item2.get("confidence", "中")
    merged_conf = "高" if "高" in [conf1, conf2] else ("中" if "中" in [conf1, conf2] else "低")
    
    return {
        "major": major,
        "sub": sub,
        "stock_text_raw": merged_stocks,
        "source_segments": sorted(list(set([seg1, seg2]))),
        "confidence": merged_conf,
        "notes": f"合并自段{seg1}和段{seg2}，去重后股票数{len(all_stocks)}"
    }


def main():
    # 加载数据
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(PARSE_PATH, "r", encoding="utf-8") as f:
        parse_data = json.load(f)
    
    print(f"加载 manifest: {MANIFEST_PATH.name}")
    print(f"加载解析数据: {PARSE_PATH.name}")
    print(f"共 {parse_data['segment_count']} 个 segment")
    
    # 收集所有条目，记录来源段
    all_items = []
    for seg in parse_data["parsed_segments"]:
        seg_id = seg["segment_id"]
        for item in seg["items"]:
            item_with_seg = {
                "major_raw": item.get("major_raw", ""),
                "sub_raw": item.get("sub_raw"),
                "stock_text_raw": item.get("stock_text_raw", ""),
                "confidence": item.get("confidence", "中"),
                "notes": item.get("notes", ""),
                "source_segment": seg_id
            }
            all_items.append(item_with_seg)
    
    print(f"解析条目总数: {len(all_items)}")
    
    # 去重合并
    merged_items = []
    used_indices = set()
    dedupe_notes = []
    
    for i, item1 in enumerate(all_items):
        if i in used_indices:
            continue
        
        # 检查是否与已有合并项重复
        current_item = {
            "major": item1["major_raw"],
            "sub": item1["sub_raw"],
            "stock_text_raw": item1["stock_text_raw"],
            "source_segments": [item1["source_segment"]],
            "confidence": item1["confidence"],
            "notes": item1["notes"]
        }
        
        # 向前查找后续条目是否有重复
        for j in range(i + 1, len(all_items)):
            if j in used_indices:
                continue
            item2 = all_items[j]
            
            is_dup, dup_type = is_duplicate(item1, item2)
            if is_dup:
                # 合并
                merged = merge_two_items(
                    current_item, item2,
                    current_item["source_segments"][0], item2["source_segment"]
                )
                current_item = merged
                used_indices.add(j)
                
                # 记录去重笔记
                dedupe_notes.append({
                    "type": dup_type,
                    "segment1": item1["source_segment"],
                    "segment2": item2["source_segment"],
                    "major": normalize_major(item1["major_raw"]),
                    "sub": normalize_sub(item1["sub_raw"]),
                    "original_stocks_1": item1["stock_text_raw"],
                    "original_stocks_2": item2["stock_text_raw"],
                    "merged_stocks": merged["stock_text_raw"]
                })
        
        used_indices.add(i)
        merged_items.append(current_item)
    
    print(f"合并后条目数: {len(merged_items)}")
    print(f"去重条目数: {len(dedupe_notes)}")
    
    # 分配 merged_index
    for idx, item in enumerate(merged_items, 1):
        item["merged_index"] = idx
    
    # 构建输出 JSON
    output_json = {
        "source_manifest": str(MANIFEST_PATH.name),
        "source_parse_json": str(PARSE_PATH.name),
        "merged_item_count": len(merged_items),
        "dedupe_count": len(dedupe_notes),
        "items": merged_items
    }
    
    # 输出文件路径
    output_json_path = OUTPUT_DIR / f"mm_merged_result_{TIMESTAMP}.json"
    output_md_path = OUTPUT_DIR / f"mm_merged_result_{TIMESTAMP}.md"
    dedupe_notes_path = OUTPUT_DIR / f"mm_merged_dedupe_notes_{TIMESTAMP}.md"
    
    # 写入 JSON
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    print(f"写入 JSON: {output_json_path.name}")
    
    # 生成 Markdown
    md_lines = []
    md_lines.append("# 多模态解析合并结果（T2.5mm3）\n")
    md_lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"- **来源文件**: {PARSE_PATH.name}")
    md_lines.append(f"- **原始条目数**: {len(all_items)}")
    md_lines.append(f"- **合并后条目数**: {len(merged_items)}")
    md_lines.append(f"- **去重条目数**: {len(dedupe_notes)}")
    md_lines.append("")
    md_lines.append("---\n")
    
    for item in merged_items:
        idx = item["merged_index"]
        major = item["major"] or "(无)"
        sub = item["sub"] or "(无)"
        stocks = item["stock_text_raw"]
        segs = ", ".join(map(str, item["source_segments"]))
        conf = item["confidence"]
        notes = item.get("notes", "")
        
        md_lines.append(f"### 条目 {idx}\n")
        md_lines.append(f"- **大类**: {major}")
        md_lines.append(f"- **小类**: {sub}")
        md_lines.append(f"- **股票原文**: {stocks}")
        md_lines.append(f"- **来源段**: {segs}")
        md_lines.append(f"- **置信度**: {conf}")
        if notes:
            md_lines.append(f"- **备注**: {notes}")
        md_lines.append("")
    
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"写入 Markdown: {output_md_path.name}")
    
    # 生成去重笔记 Markdown
    if dedupe_notes:
        dedupe_lines = []
        dedupe_lines.append("# 去重合并记录（T2.5mm3）\n")
        dedupe_lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        dedupe_lines.append(f"- **去重条目数**: {len(dedupe_notes)}")
        dedupe_lines.append("")
        dedupe_lines.append("---\n")
        
        for note in dedupe_notes:
            dedupe_lines.append(f"### {note['major']} / {note['sub'] or '(无)'}\n")
            dedupe_lines.append(f"- **去重类型**: {note['type']}")
            dedupe_lines.append(f"- **来源段**: {note['segment1']} vs {note['segment2']}")
            dedupe_lines.append(f"- **原文1**: {note['original_stocks_1']}")
            dedupe_lines.append(f"- **原文2**: {note['original_stocks_2']}")
            dedupe_lines.append(f"- **合并后**: {note['merged_stocks']}")
            dedupe_lines.append("")
        
        with open(dedupe_notes_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dedupe_lines))
        print(f"写入去重笔记: {dedupe_notes_path.name}")
    
    print("\n完成！")
    return output_json_path, output_md_path, dedupe_notes_path if dedupe_notes else None


if __name__ == "__main__":
    main()