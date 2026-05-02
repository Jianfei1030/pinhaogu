#!/usr/bin/env python3
"""表格结构检测脚本 - T2.5b"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import json
import os
from datetime import datetime
import argparse


def detect_row_boundaries(roi_img, table_roi, column_boundaries):
    x1, y1, x2, y2 = table_roi
    roi_h, roi_w = roi_img.shape[:2]
    
    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                    cv2.THRESH_BINARY_INV, 11, 2)
    
    h_proj = np.sum(binary, axis=1)
    h_proj_norm = h_proj / (roi_w + 1e-6)
    
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    sobel_y = np.abs(sobel_y)
    sobel_y = np.uint8(sobel_y)
    _, edge_binary = cv2.threshold(sobel_y, 50, 255, cv2.THRESH_BINARY)
    edge_proj = np.sum(edge_binary, axis=1)
    
    min_row_height, max_row_height = 55, 140
    text_threshold, line_threshold = 0.03, 0.25
    
    rows, current_y = [], 0
    
    while current_y < roi_h - min_row_height:
        window_size = min(min_row_height, roi_h - current_y)
        window_proj = np.mean(h_proj_norm[current_y:current_y + window_size])
        
        if window_proj > text_threshold:
            row_end = current_y + min_row_height
            
            for y in range(current_y + min_row_height, min(current_y + max_row_height, roi_h)):
                if edge_proj[y] > roi_w * line_threshold:
                    row_end = y
                    break
                if y + 5 < roi_h:
                    if np.mean(h_proj_norm[y:y+5]) < text_threshold * 0.2:
                        row_end = y
                        break
            
            row_height = row_end - current_y
            if min_row_height <= row_height <= max_row_height:
                rows.append({
                    'row_index': len(rows),
                    'row_bbox': [x1, y1 + current_y, x2, y1 + row_end],
                    'row_y1': current_y, 'row_y2': row_end, 'height': row_height
                })
                current_y = row_end
            else:
                current_y += min_row_height // 2
        else:
            current_y += 3
    
    print(f"检测到 {len(rows)} 行")
    return rows


def analyze_cell_content(roi_img, rows, column_boundaries, table_roi):
    x1, y1, x2, y2 = table_roi
    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    major_x1 = max(0, column_boundaries['major'][0] - x1)
    major_x2 = min(roi_img.shape[1], column_boundaries['major'][1] - x1)
    sub_x1 = max(0, column_boundaries['sub'][0] - x1)
    sub_x2 = min(roi_img.shape[1], column_boundaries['sub'][1] - x1)
    stock_x1 = max(0, column_boundaries['stock'][0] - x1)
    stock_x2 = min(roi_img.shape[1], column_boundaries['stock'][1] - x1)
    
    enhanced_rows = []
    
    for i, row in enumerate(rows):
        row_y1, row_y2 = row['row_y1'], row['row_y2']
        
        major_cell = binary[row_y1:row_y2, major_x1:major_x2]
        sub_cell = binary[row_y1:row_y2, sub_x1:sub_x2]
        stock_cell = binary[row_y1:row_y2, stock_x1:stock_x2]
        
        major_density = np.sum(major_cell > 0) / (major_cell.size + 1e-6)
        sub_density = np.sum(sub_cell > 0) / (sub_cell.size + 1e-6)
        stock_density = np.sum(stock_cell > 0) / (stock_cell.size + 1e-6)
        
        major_bg = np.mean(gray[row_y1:row_y2, major_x1:major_x2])
        sub_bg = np.mean(gray[row_y1:row_y2, sub_x1:sub_x2])
        
        major_inherit = major_density < 0.015 and i > 0
        sub_inherit = sub_density < 0.015 and i > 0
        
        if i > 0:
            prev_major_bg = np.mean(gray[rows[i-1]['row_y1']:rows[i-1]['row_y2'], major_x1:major_x2])
            prev_sub_bg = np.mean(gray[rows[i-1]['row_y1']:rows[i-1]['row_y2'], sub_x1:sub_x2])
            
            if abs(major_bg - prev_major_bg) < 12 and major_density < 0.03:
                major_inherit = True
            if abs(sub_bg - prev_sub_bg) < 12 and sub_density < 0.03:
                sub_inherit = True
        
        has_stock_content = stock_density > 0.02
        
        notes = []
        if major_inherit and sub_inherit:
            notes.append('大类小类均继承')
        elif major_inherit:
            notes.append('大类继承')
        elif sub_inherit:
            notes.append('小类继承')
        if not has_stock_content:
            notes.append('股票列无内容(异常)')
        
        enhanced_rows.append({
            'row_index': i,
            'row_bbox': row['row_bbox'],
            'major_cell_bbox': [column_boundaries['major'][0], y1 + row_y1, column_boundaries['major'][1], y1 + row_y2],
            'sub_cell_bbox': [column_boundaries['sub'][0], y1 + row_y1, column_boundaries['sub'][1], y1 + row_y2],
            'stock_cell_bbox': [column_boundaries['stock'][0], y1 + row_y1, column_boundaries['stock'][1], y1 + row_y2],
            'major_inherit_from_prev': bool(major_inherit),
            'sub_inherit_from_prev': bool(sub_inherit),
            'major_density': round(float(major_density), 4),
            'sub_density': round(float(sub_density), 4),
            'stock_density': round(float(stock_density), 4),
            'has_stock_content': bool(has_stock_content),
            'notes': '; '.join(notes) if notes else ''
        })
    
    return enhanced_rows


def generate_debug_image(image_path, result, output_path):
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    roi = result["table_roi"]
    cols = result["column_boundaries"]
    rows = result["rows"]
    
    roi_color = (0, 255, 0)
    col_color = (255, 0, 0)
    row_color = (0, 0, 255)
    inherit_major_color = (255, 165, 0)
    inherit_sub_color = (128, 0, 128)
    inherit_both_color = (255, 0, 255)
    
    draw.rectangle([roi[0], roi[1], roi[2], roi[3]], outline=roi_color, width=4)
    draw.line([cols["sub"][0], roi[1], cols["sub"][0], roi[3]], fill=col_color, width=3)
    draw.line([cols["stock"][0], roi[1], cols["stock"][0], roi[3]], fill=col_color, width=3)
    
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 20)
        small_font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 16)
    except:
        font = ImageFont.load_default()
        small_font = font
    
    for row in rows:
        row_bbox = row['row_bbox']
        
        if row['major_inherit_from_prev'] and row['sub_inherit_from_prev']:
            line_color = inherit_both_color
        elif row['major_inherit_from_prev']:
            line_color = inherit_major_color
        elif row['sub_inherit_from_prev']:
            line_color = inherit_sub_color
        else:
            line_color = row_color
        
        draw.line([row_bbox[0], row_bbox[3], row_bbox[2], row_bbox[3]], fill=line_color, width=2)
        
        mark_x, mark_y = row_bbox[0] + 5, (row_bbox[1] + row_bbox[3]) // 2 - 10
        if row['major_inherit_from_prev'] and row['sub_inherit_from_prev']:
            draw.text((mark_x, mark_y), "M+S", fill=inherit_both_color, font=small_font)
        elif row['major_inherit_from_prev']:
            draw.text((mark_x, mark_y), "M", fill=inherit_major_color, font=small_font)
        elif row['sub_inherit_from_prev']:
            draw.text((mark_x + 30, mark_y), "S", fill=inherit_sub_color, font=small_font)
    
    draw.text((roi[0] + 10, roi[1] - 30), f"TABLE ROI | {len(rows)} rows", fill=roi_color, font=font)
    draw.text((cols["major"][0] + 10, roi[1] + 10), "大类", fill=col_color, font=font)
    draw.text((cols["sub"][0] + 10, roi[1] + 10), "小类", fill=col_color, font=font)
    draw.text((cols["stock"][0] + 10, roi[1] + 10), "股票", fill=col_color, font=font)
    
    img.save(output_path, 'PNG')
    print(f"Debug图已保存: {output_path}")


def generate_markdown(result, output_path, timestamp):
    roi = result["table_roi"]
    cols = result["column_boundaries"]
    rows = result["rows"]
    
    md = f"""# 表格结构检测报告

**生成时间**: {timestamp}

## 原图信息

- **图片路径**: `{result['image_path']}`

## 表格ROI坐标

| 参数 | 值 |
|------|-----|
| 左上角 (x1, y1) | ({roi[0]}, {roi[1]}) |
| 右下角 (x2, y2) | ({roi[2]}, {roi[3]}) |
| ROI宽度 | {roi[2] - roi[0]} px |
| ROI高度 | {roi[3] - roi[1]} px |

## 最终列边界

| 列名 | X坐标范围 | 宽度 |
|------|----------|------|
| 大类列 | [{cols['major'][0]}, {cols['major'][1]}] | {cols['major'][1] - cols['major'][0]} px |
| 小类列 | [{cols['sub'][0]}, {cols['sub'][1]}] | {cols['sub'][1] - cols['sub'][0]} px |
| 股票列 | [{cols['stock'][0]}, {cols['stock'][1]}] | {cols['stock'][1] - cols['stock'][0]} px |

## 行检测结果

**总行数**: {len(rows)}

## 逐行详情

| 行号 | 行BBOX | 大类格 | 小类格 | 股票格 | 继承标记 | 备注 |
|------|--------|--------|--------|--------|----------|------|
"""
    
    for row in rows:
        row_bbox = row['row_bbox']
        major_bbox = row['major_cell_bbox']
        sub_bbox = row['sub_cell_bbox']
        stock_bbox = row['stock_cell_bbox']
        
        inherit_mark = []
        if row['major_inherit_from_prev']:
            inherit_mark.append("大类")
        if row['sub_inherit_from_prev']:
            inherit_mark.append("小类")
        inherit_str = "+".join(inherit_mark) if inherit_mark else "-"
        
        md += f"| {row['row_index']} | [{row_bbox[0]},{row_bbox[1]},{row_bbox[2]},{row_bbox[3]}] | "
        md += f"[{major_bbox[0]},{major_bbox[1]},{major_bbox[2]},{major_bbox[3]}] | "
        md += f"[{sub_bbox[0]},{sub_bbox[1]},{sub_bbox[2]},{sub_bbox[3]}] | "
        md += f"[{stock_bbox[0]},{stock_bbox[1]},{stock_bbox[2]},{stock_bbox[3]}] | "
        md += f"{inherit_str} | {row.get('notes', '')} |\n"
    
    md += """
## 继承标记说明

- **大类继承**: 该行大类列内容与上一行相同（合并单元格）
- **小类继承**: 该行小类列内容与上一行相同（合并单元格）
- **-**: 该行有独立内容，不继承

## Debug图说明

Debug图 (`table_structure_layout_""" + timestamp + """_debug.png`) 包含：

1. **绿色粗框**: 表格ROI区域
2. **红色竖线**: 三列边界（大类/小类/股票）
3. **彩色横线**: 行边界
   - 蓝色: 普通行
   - 橙色: 大类继承行
   - 紫色: 小类继承行
   - 洋红: 大类小类均继承行
4. **标记文字**: M=大类继承, S=小类继承, M+S=两者均继承

## 输出文件

- JSON: `table_structure_layout_""" + timestamp + """.json`
- Markdown: `table_structure_layout_""" + timestamp + """.md`
- Debug图: `table_structure_layout_""" + timestamp + """_debug.png`
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"Markdown报告已保存: {output_path}")


def detect_table_structure(image_path, roi_json_path, output_dir="output"):
    with open(roi_json_path, 'r', encoding='utf-8') as f:
        roi_data = json.load(f)
    
    table_roi = roi_data['table_roi']
    initial_columns = roi_data['suggested_columns']
    
    print(f"加载图片: {image_path}")
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    
    x1, y1, x2, y2 = table_roi
    roi_img = img[y1:y2, x1:x2]
    print(f"ROI尺寸: {roi_img.shape[1]}x{roi_img.shape[0]}")
    
    print("检测行边界...")
    rows = detect_row_boundaries(roi_img, table_roi, initial_columns)
    
    print("分析单元格内容...")
    enhanced_rows = analyze_cell_content(roi_img, rows, initial_columns, table_roi)
    
    result = {
        "image_path": image_path,
        "table_roi": table_roi,
        "column_boundaries": initial_columns,
        "rows": enhanced_rows,
        "stats": {
            "total_rows": len(enhanced_rows),
            "major_inherit_count": sum(1 for r in enhanced_rows if r['major_inherit_from_prev']),
            "sub_inherit_count": sum(1 for r in enhanced_rows if r['sub_inherit_from_prev']),
            "both_inherit_count": sum(1 for r in enhanced_rows if r['major_inherit_from_prev'] and r['sub_inherit_from_prev'])
        }
    }
    
    return result, img


def main():
    parser = argparse.ArgumentParser(description='表格结构检测')
    parser.add_argument('image', help='输入图片路径')
    parser.add_argument('--roi-json', '-r', required=True, help='ROI JSON文件路径')
    parser.add_argument('--output-dir', '-o', default='output', help='输出目录')
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print(f"处理图片: {args.image}")
    result, _ = detect_table_structure(args.image, args.roi_json, args.output_dir)
    
    json_path = os.path.join(args.output_dir, f'table_structure_layout_{timestamp}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"JSON结果已保存: {json_path}")
    
    md_path = os.path.join(args.output_dir, f'table_structure_layout_{timestamp}.md')
    generate_markdown(result, md_path, timestamp)
    
    debug_path = os.path.join(args.output_dir, f'table_structure_layout_{timestamp}_debug.png')
    generate_debug_image(args.image, result, debug_path)
    
    print("\n完成!")
    print(f"输出文件:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
    print(f"  - Debug图: {debug_path}")


if __name__ == '__main__':
    main()