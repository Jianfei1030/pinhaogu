#!/usr/bin/env python3
"""
T2.5b2a: 生成每行三列 cell bbox
- 输入: row_boundaries JSON
- 输出: cell_bboxes JSON + Markdown + debug PNG
- 不做继承标记、不做 OCR、不推进后续步骤
"""

import json
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# 配置
COLUMN_BOUNDARIES = {
    "major": [0, 238],
    "sub": [238, 618],
    "stock": [618, 1220]
}

ROW_SOURCE_FILE = "output/row_boundaries_20260409_172139.json"
IMAGE_PATH = "<your-home>/.openclaw/media/inbound/Screenshot_2026-04-09-09-03-23-962_com.aiyu.kaipanla---9054cb9b-6f59-4624-903e-b945a8600919.jpg"
OUTPUT_DIR = "output"


def load_row_boundaries(filepath):
    """加载行边界数据"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_cell_bboxes(rows, column_boundaries):
    """
    为每一行生成三列 cell bbox
    返回包含 cell bbox 的行数据列表
    """
    result_rows = []
    
    for row in rows:
        row_bbox = row["row_bbox"]
        row_y1, row_y2 = row_bbox[1], row_bbox[3]
        
        # 生成三列 cell bbox
        major_cell_bbox = [
            column_boundaries["major"][0],
            row_y1,
            column_boundaries["major"][1],
            row_y2
        ]
        
        sub_cell_bbox = [
            column_boundaries["sub"][0],
            row_y1,
            column_boundaries["sub"][1],
            row_y2
        ]
        
        stock_cell_bbox = [
            column_boundaries["stock"][0],
            row_y1,
            column_boundaries["stock"][1],
            row_y2
        ]
        
        result_rows.append({
            "row_index": row["row_index"],
            "row_bbox": row_bbox,
            "major_cell_bbox": major_cell_bbox,
            "sub_cell_bbox": sub_cell_bbox,
            "stock_cell_bbox": stock_cell_bbox,
            "notes": row.get("notes", "")
        })
    
    return result_rows


def generate_debug_image(image_path, output_path, table_roi, column_boundaries, rows):
    """生成 debug 可视化图像"""
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # 尝试加载字体
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 20)
        small_font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 14)
    except:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    
    # 绘制 ROI 大框 (蓝色)
    roi_x1, roi_y1, roi_x2, roi_y2 = table_roi
    draw.rectangle([roi_x1, roi_y1, roi_x2, roi_y2], outline="blue", width=3)
    
    # 绘制列边界线 (绿色虚线效果 - 用细线)
    for col_name, (x1, x2) in column_boundaries.items():
        # 左边界
        draw.line([(x1, roi_y1), (x1, roi_y2)], fill="green", width=2)
        # 右边界
        draw.line([(x2, roi_y1), (x2, roi_y2)], fill="green", width=2)
    
    # 绘制每一行的三格 bbox
    colors = {
        "major": "red",
        "sub": "orange",
        "stock": "purple"
    }
    
    for row in rows:
        # major cell (红色)
        bbox = row["major_cell_bbox"]
        draw.rectangle([bbox[0], bbox[1], bbox[2], bbox[3]], outline=colors["major"], width=1)
        
        # sub cell (橙色)
        bbox = row["sub_cell_bbox"]
        draw.rectangle([bbox[0], bbox[1], bbox[2], bbox[3]], outline=colors["sub"], width=1)
        
        # stock cell (紫色)
        bbox = row["stock_cell_bbox"]
        draw.rectangle([bbox[0], bbox[1], bbox[2], bbox[3]], outline=colors["stock"], width=1)
        
        # 每10行标注行号
        if row["row_index"] % 10 == 0:
            y_center = (row["row_bbox"][1] + row["row_bbox"][3]) // 2
            draw.text((5, y_center), f"R{row['row_index']}", fill="white", font=small_font)
    
    # 添加图例
    legend_y = roi_y2 + 20
    draw.text((10, legend_y), "Cell BBox Debug View", fill="white", font=font)
    draw.text((10, legend_y + 25), "Red=Major Orange=Sub Purple=Stock Blue=ROI Green=ColBoundary", fill="white", font=small_font)
    
    img.save(output_path)
    print(f"Debug image saved: {output_path}")


def generate_markdown(output_path, table_roi, column_boundaries, row_count, rows):
    """生成 Markdown 报告"""
    lines = []
    lines.append("# Cell BBox 生成报告 (T2.5b2a)")
    lines.append("")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    lines.append("## 参数配置")
    lines.append("")
    lines.append(f"- **Table ROI**: `{table_roi}`")
    lines.append(f"- **总行数**: {row_count}")
    lines.append("")
    
    lines.append("### 列边界")
    lines.append("")
    lines.append("| 列名 | 边界 (x1, x2) | 宽度 |")
    lines.append("|------|---------------|------|")
    for col_name, (x1, x2) in column_boundaries.items():
        width = x2 - x1
        lines.append(f"| {col_name} | [{x1}, {x2}] | {width}px |")
    lines.append("")
    
    lines.append("## Cell BBox 列表")
    lines.append("")
    lines.append("| 行号 | Row BBox (y1,y2) | Major Cell | Sub Cell | Stock Cell | 备注 |")
    lines.append("|------|------------------|------------|----------|------------|------|")
    
    for row in rows[:50]:  # 显示前50行
        row_idx = row["row_index"]
        row_bbox = row["row_bbox"]
        major = row["major_cell_bbox"]
        sub = row["sub_cell_bbox"]
        stock = row["stock_cell_bbox"]
        notes = row.get("notes", "") or ""
        
        row_y = f"{row_bbox[1]},{row_bbox[3]}"
        major_str = f"[{major[0]},{major[2]}]"
        sub_str = f"[{sub[0]},{sub[2]}]"
        stock_str = f"[{stock[0]},{stock[2]}]"
        
        lines.append(f"| {row_idx} | {row_y} | {major_str} | {sub_str} | {stock_str} | {notes} |")
    
    if len(rows) > 50:
        lines.append(f"| ... | ... | ... | ... | ... | ... |")
        lines.append(f"| {rows[-1]['row_index']} | {rows[-1]['row_bbox'][1]},{rows[-1]['row_bbox'][3]} | ... | ... | ... | {rows[-1].get('notes', '')} |")
        lines.append("")
        lines.append(f"*共 {row_count} 行，显示前 50 行和最后一行*")
    
    lines.append("")
    lines.append("## 统计信息")
    lines.append("")
    
    # 检查异常行
    abnormal_rows = [r for r in rows if r.get("notes")]
    lines.append(f"- 总行数: {row_count}")
    lines.append(f"- 异常行数: {len(abnormal_rows)}")
    if abnormal_rows:
        lines.append(f"- 异常行索引: {[r['row_index'] for r in abnormal_rows]}")
    lines.append("")
    
    lines.append("## 输出文件")
    lines.append("")
    lines.append("- JSON: `cell_bboxes_<timestamp>.json`")
    lines.append("- Markdown: `cell_bboxes_<timestamp>.md`")
    lines.append("- Debug PNG: `cell_bboxes_<timestamp>_debug.png`")
    lines.append("")
    
    lines.append("---")
    lines.append("*T2.5b2a 任务完成 - 仅生成 cell bbox，未做继承标记*")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"Markdown report saved: {output_path}")


def main():
    print("=" * 60)
    print("T2.5b2a: Cell BBox 生成")
    print("=" * 60)
    
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 加载行边界数据
    print(f"\n加载行边界: {ROW_SOURCE_FILE}")
    row_data = load_row_boundaries(ROW_SOURCE_FILE)
    rows = row_data["rows"]
    table_roi = row_data["table_roi"]
    row_count = row_data["row_count"]
    
    print(f"  - 总行数: {row_count}")
    print(f"  - Table ROI: {table_roi}")
    
    # 生成 cell bboxes
    print("\n生成每行三列 cell bbox...")
    cell_rows = generate_cell_bboxes(rows, COLUMN_BOUNDARIES)
    print(f"  - 已生成 {len(cell_rows)} 行的 cell bbox")
    
    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 构建输出数据结构
    output_data = {
        "image_path": IMAGE_PATH,
        "table_roi": table_roi,
        "column_boundaries": COLUMN_BOUNDARIES,
        "row_source": ROW_SOURCE_FILE,
        "row_count": row_count,
        "rows": cell_rows,
        "generated_at": datetime.now().isoformat()
    }
    
    # 保存 JSON
    json_path = os.path.join(OUTPUT_DIR, f"cell_bboxes_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"  - JSON saved: {json_path}")
    
    # 生成 Markdown
    md_path = os.path.join(OUTPUT_DIR, f"cell_bboxes_{timestamp}.md")
    generate_markdown(md_path, table_roi, COLUMN_BOUNDARIES, row_count, cell_rows)
    
    # 生成 Debug 图
    debug_path = os.path.join(OUTPUT_DIR, f"cell_bboxes_{timestamp}_debug.png")
    generate_debug_image(IMAGE_PATH, debug_path, table_roi, COLUMN_BOUNDARIES, cell_rows)
    
    print("\n" + "=" * 60)
    print("T2.5b2a 任务完成!")
    print("=" * 60)
    print(f"\n输出文件:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
    print(f"  - Debug PNG: {debug_path}")


if __name__ == "__main__":
    main()