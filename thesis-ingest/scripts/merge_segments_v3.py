#!/usr/bin/env python3
"""
T2.5mm3 V3: 跨段合并 + 去重 + 层级拼接（最终版）
改进：
1. 大类标准化：AI硬件-光模块 → AI硬件
2. 小类标准化：光模块-LPO → LPO
3. 处理跨段延续的大类小类合并
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
    major = major.strip()
    # AI硬件-光模块 → AI硬件
    if major.startswith("AI硬件"):
        return "AI硬件"
    return major


def normalize_sub(sub):
    """标准化小类名称"""
    if not sub:
        return None
    sub = sub.strip()
    # 光模块-LPO → LPO
    if sub.startswith("光模块-"):
        return sub.replace("光模块-", "")
    return sub


def get_stock_set(stock_text):
    """将股票文本转为集合"""
    if not stock_text:
        return set()
    return set(stock_text.split())


def should_merge(item1, item2):
    """
    判断两个条目是否应该合并
    基于标准化后的大类小类和股票重叠
    """
    norm_major1 = normalize_major(item1.get("major_raw", ""))
    norm_major2 = normalize_major(item2.get("major_raw", ""))
    
    # 大类必须匹配
    if norm_major1 != norm_major2:
        return False, None, "major mismatch"
    
    norm_sub1 = normalize_sub(item1.get("sub_raw"))
    norm_sub2 = normalize_sub(item2.get("sub_raw"))
    
    # 小类必须匹配（None 也视为匹配）
    if norm_sub1 != norm_sub2:
        return False, None, "sub mismatch"
    
    stocks1 = get_stock_set(item1.get("stock_text_raw", ""))
    stocks2 = get_stock_set(item2.get("stock_text_raw", ""))
    
    if not stocks1 or not stocks2:
        return False, None, "empty stocks"
    
    # 判断股票关系
    if stocks1 == stocks2:
        return True, "duplicate", "完全重复"
    
    if stocks1.issubset(stocks2):
        return True, "subset1", f"item1是item2子集"
    
    if stocks2.issubset(stocks1):
        return True, "subset2", f"item2是item1子集"
    
    # 有交集则合并
    intersection = stocks1 & stocks2
    if intersection:
        return True, "overlap", f"交集{len(intersection)}股"
    
    return False, None, "no overlap"


def merge_stocks(stock_sets):
    """合并多个股票集合"""
    result = set()
    for s in stock_sets:
        result |= s
    return result


def main():
    with open(PARSE_PATH, "r", encoding="utf-8") as f:
        parse_data = json.load(f)
    
    print(f"加载: {PARSE_PATH.name}")
    print(f"共 {parse_data['segment_count']} 个 segment")
    
    # 收集所有条目
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
    
    # ===== 合并策略 =====
    # 1. 先按标准化后的 (major, sub) 分组
    # 2. 每组内合并股票列表
    
    groups = {}  # key: (norm_major, norm_sub), value: list of items
    
    for item in all_items:
        key = (normalize_major(item["major_raw"]), normalize_sub(item["sub_raw"]))
        if key not in groups:
            groups[key] = []
        groups[key].append(item)
    
    print(f"分组数: {len(groups)}")
    
    # 合并每组
    merged_items = []
    dedupe_log = []
    
    for key, group_items in groups.items():
        norm_major, norm_sub = key
        
        # 收集所有股票和来源段
        all_stocks = set()
        all_sources = []
        all_confidences = []
        original_notes = []
        original_majors = []
        
        for item in group_items:
            stocks = get_stock_set(item["stock_text_raw"])
            all_stocks |= stocks
            all_sources.append(item["source_segment"])
            all_confidences.append(item["confidence"])
            original_notes.append(item["notes"])
            original_majors.append(item["major_raw"])
        
        # 确定最佳原始大类名称（优先选择不带后缀的）
        best_major = None
        for m in original_majors:
            if not m.startswith("AI硬件-"):
                best_major = m
                break
        if not best_major:
            best_major = original_majors[0]
        
        # 确定最佳原始小类名称
        best_sub = group_items[0]["sub_raw"]
        
        # 确定置信度
        final_conf = "高" if "高" in all_confidences else "中"
        
        # 去重来源段
        unique_sources = sorted(list(set(all_sources)))
        
        # 备注
        final_note = ""
        if len(group_items) > 1:
            final_note = f"合并自段{','.join(map(str, unique_sources))}，去重后{len(all_stocks)}股"
        else:
            final_note = group_items[0]["notes"]
        
        merged_items.append({
            "major": best_major,
            "sub": best_sub,
            "stock_text_raw": " ".join(sorted(all_stocks)),
            "source_segments": unique_sources,
            "confidence": final_conf,
            "notes": final_note
        })
        
        # 记录去重
        if len(group_items) > 1:
            dedupe_log.append({
                "norm_major": norm_major,
                "norm_sub": norm_sub or "(无)",
                "item_count": len(group_items),
                "sources": unique_sources,
                "merged_stocks": len(all_stocks),
                "original_items": [
                    {
                        "segment": item["source_segment"],
                        "major": item["major_raw"],
                        "sub": item["sub_raw"],
                        "stocks": item["stock_text_raw"]
                    }
                    for item in group_items
                ]
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
    print(f"输出: {json_path.name}")
    
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
    print(f"输出: {md_path.name}")
    
    # 去重笔记
    if dedupe_log:
        dedupe_lines = [
            "# 去重合并记录（T2.5mm3）\n",
            f"**去重合并数**: {len(dedupe_log)}",
            "",
            "---\n"
        ]
        
        for log in dedupe_log:
            dedupe_lines.append(f"### {log['norm_major']} / {log['norm_sub']}\n")
            dedupe_lines.append(f"- **合并条目数**: {log['item_count']}")
            dedupe_lines.append(f"- **来源段**: {','.join(map(str, log['sources']))}")
            dedupe_lines.append(f"- **合并后股票数**: {log['merged_stocks']}")
            dedupe_lines.append("")
            dedupe_lines.append("原始条目:")
            for orig in log['original_items']:
                dedupe_lines.append(f"  - 段{orig['segment']}: {orig['major']}/{orig['sub'] or '(无)'} → {orig['stocks']}")
            dedupe_lines.append("")
        
        dedupe_path = OUTPUT_DIR / f"mm_merged_dedupe_notes_{TIMESTAMP}.md"
        with open(dedupe_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dedupe_lines))
        print(f"输出: {dedupe_path.name}")
    
    print("\n完成！")


if __name__ == "__main__":
    main()