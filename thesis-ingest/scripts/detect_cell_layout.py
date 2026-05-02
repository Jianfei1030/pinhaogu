#!/usr/bin/env python3
"""
T2.5b2: 列单元格 bbox + 合并单元格继承标记检测
基于已有的172行row boundaries，切分三列并标记继承关系
"""

import json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import os


def detect_cell_layout(
    image_path: str,
    row_boundaries_json: str,
    table_roi: list,
    column_boundaries: dict,
    output_dir: str = "output"
):
    """
    基于行边界检测单元格布局和继承标记
    
    Args:
        image_path: 原图路径
        row_boundaries_json: 行边界JSON文件路径
        table_roi: [x1, y1, x2, y2] 表格ROI
        column_boundaries: {major: [x1, x2], sub: [x1, x2], stock: [x1, x2]}
        output_dir: 输出目录
    """
    
    # 加载行边界数据
    with open(row_boundaries_json, 'r', encoding='utf-8') as f:
        row_data = json.load(f)
    
    rows = row_data['rows']
    roi_x1, roi_y1, roi_x2, roi_y2 = table_roi
    
    # 列边界（相对于ROI的绝对坐标）
    major_x1 = column_boundaries['major'][0]
    major_x2 = column_boundaries['major'][1]
    sub_x1 = column_boundaries['sub'][0]
    sub_x2 = column_boundaries['sub'][1]
    stock_x1 = column_boundaries['stock'][0]
    stock_x2 = column_boundaries['stock'][1]
    
    # 加载图像用于分析背景
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法加载图像: {image_path}")
    
    # 转换为灰度图用于背景分析
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 处理每一行，生成单元格bbox和继承标记
    cell_rows = []
    prev_major_text = None
    prev_sub_text = None
    
    for i, row in enumerate(rows):
        row_bbox = row['row_bbox']
        row_y1, row_y2 = row_bbox[1], row_bbox[3]
        
        # 计算三列单元格的bbox
        major_cell_bbox = [major_x1, row_y1, major_x2, row_y2]
        sub_cell_bbox = [sub_x1, row_y1, sub_x2, row_y2]
        stock_cell_bbox = [stock_x1, row_y1, stock_x2, row_y2]
        
        # 分析major列的背景特征（用于判断是否为合并单元格）
        major_roi = gray[row_y1:row_y2, major_x1:major_x2]
        major_mean = np.mean(major_roi) if major_roi.size > 0 else 255
        
        # 分析sub列的背景特征
        sub_roi = gray[row_y1:row_y2, sub_x1:sub_x2]
        sub_mean = np.mean(sub_roi) if sub_roi.size > 0 else 255
        
        # 判断是否为继承行（基于背景连续性）
        # 深色背景（值较小）通常表示有内容，浅色背景（值较大）可能是合并单元格的延续
        # 这里使用启发式规则：
        # 1. 第一行不继承
        # 2. 如果当前行背景明显比上一行浅，可能是继承
        
        major_inherit = False
        sub_inherit = False
        notes = ""
        
        if i == 0:
            # 第一行不继承
            major_inherit = False
            sub_inherit = False
        else:
            # 获取上一行的背景信息（从已处理的行中）
            prev_row = cell_rows[i-1]
            
            # 分析当前行major列是否有明显内容（非继承）
            # 使用方差判断：有文字的区域方差通常较大
            major_std = np.std(major_roi) if major_roi.size > 0 else 0
            
            # 如果方差很小（很均匀），可能是继承上一行
            # 阈值需要根据实际图像调整
            if major_std < 15:  # 非常均匀的背景
                major_inherit = True
                notes += "major背景均匀，可能继承;"
            
            # 同样分析sub列
            sub_std = np.std(sub_roi) if sub_roi.size > 0 else 0
            if sub_std < 15:
                sub_inherit = True
                notes += "sub背景均匀，可能继承;"
        
        cell_row = {
            "row_index": i,
            "row_bbox": row_bbox,
            "major_cell_bbox": major_cell_bbox,
            "sub_cell_bbox": sub_cell_bbox,
            "stock_cell_bbox": stock_cell_bbox,
            "major_inherit_from_prev": major_inherit,
            "sub_inherit_from_prev": sub_inherit,
            "major_bg_mean": float(major_mean),
            "sub_bg_mean": float(sub_mean),
            "notes": notes
        }
        cell_rows.append(cell_row)
    
    # 后处理：修正继承标记（基于视觉连续性）
    # 如果连续多行都是继承，只有第一行应该标记为继承
    for i in range(1, len(cell_rows)):
        curr = cell_rows[i]
        prev = cell_rows[i-1]
        
        # 如果上一行已经继承，当前行不应该再继承（避免链式继承标记）
        # 实际上，合并单元格的中间行应该都标记为继承
        # 这里保持原始标记
        pass
    
    # 构建输出JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        "image_path": image_path,
        "table_roi": table_roi,
        "column_boundaries": column_boundaries,
        "row_source": row_boundaries_json,
        "row_count": len(cell_rows),
        "rows": cell_rows,
        "stats": {
            "major_inherit_count": sum(1 for r in cell_rows if r["major_inherit_from_prev"]),
            "sub_inherit_count": sum(1 for r in cell_rows if r["sub_inherit_from_prev"]),
            "total_rows": len(cell_rows)
        }
    }
    
    # 保存JSON
    json_path = os.path.join(output_dir, f"cell_layout_{timestamp}.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # 生成Markdown报告
    md_path = os.path.join(output_dir, f"cell_layout_{timestamp}.md")
    generate_markdown_report(output, md_path)
    
    # 生成Debug图
    debug_path = os.path.join(output_dir, f"cell_layout_{timestamp}_debug.png")
    generate_debug_image(image_path, output, debug_path)
    
    return json_path, md_path, debug_path


def generate_markdown_report(data: dict, output_path: str):
    """生成Markdown报告"""
    
    lines = []
    lines.append("# Cell Layout 检测报告 (T2.5b2)")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # 使用的ROI
    lines.append("## 使用的ROI")
    lines.append(f"```")
    lines.append(f"table_roi: {data['table_roi']}")
    lines.append(f"```")
    lines.append("")
    
    # 列边界
    lines.append("## 最终列边界")
    lines.append(f"- **major**: {data['column_boundaries']['major']}")
    lines.append(f"- **sub**: {data['column_boundaries']['sub']}")
    lines.append(f"- **stock**: {data['column_boundaries']['stock']}")
    lines.append("")
    
    # 总行数
    lines.append(f"## 总行数: {data['row_count']}")
    lines.append("")
    
    # 继承统计
    lines.append("## 继承统计")
    lines.append(f"- major继承行数: {data['stats']['major_inherit_count']}")
    lines.append(f"- sub继承行数: {data['stats']['sub_inherit_count']}")
    lines.append("")
    
    # 逐行列表
    lines.append("## 逐行单元格布局")
    lines.append("")
    lines.append("| 行号 | Row BBox | Major Cell | Sub Cell | Stock Cell | Major继承 | Sub继承 | 备注 |")
    lines.append("|------|----------|------------|----------|------------|-----------|---------|------|")
    
    for row in data['rows']:
        row_bbox_str = f"[{row['row_bbox'][0]}, {row['row_bbox'][1]}, {row['row_bbox'][2]}, {row['row_bbox'][3]}]"
        major_bbox_str = f"[{row['major_cell_bbox'][0]}, {row['major_cell_bbox'][1]}, {row['major_cell_bbox'][2]}, {row['major_cell_bbox'][3]}]"
        sub_bbox_str = f"[{row['sub_cell_bbox'][0]}, {row['sub_cell_bbox'][1]}, {row['sub_cell_bbox'][2]}, {row['sub_cell_bbox'][3]}]"
        stock_bbox_str = f"[{row['stock_cell_bbox'][0]}, {row['stock_cell_bbox'][1]}, {row['stock_cell_bbox'][2]}, {row['stock_cell_bbox'][3]}]"
        
        major_inherit = "✓" if row['major_inherit_from_prev'] else ""
        sub_inherit = "✓" if row['sub_inherit_from_prev'] else ""
        notes = row.get('notes', '').replace(';', ', ')
        
        lines.append(f"| {row['row_index']} | {row_bbox_str} | {major_bbox_str} | {sub_bbox_str} | {stock_bbox_str} | {major_inherit} | {sub_inherit} | {notes} |")
    
    lines.append("")
    lines.append("---")
    lines.append("*本文件由 detect_cell_layout.py 自动生成*")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def generate_debug_image(image_path: str, data: dict, output_path: str):
    """生成Debug可视化图像"""
    
    # 加载原图
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # 颜色定义
    colors = {
        'roi': (255, 0, 0),        # 红色 - ROI
        'col_line': (0, 255, 0),   # 绿色 - 列边界线
        'row_line': (0, 0, 255),   # 蓝色 - 行边界线
        'major_cell': (255, 165, 0),   # 橙色 - major单元格
        'sub_cell': (128, 0, 128),     # 紫色 - sub单元格
        'stock_cell': (0, 128, 128),   # 青色 - stock单元格
        'major_inherit': (255, 0, 255),    # 洋红 - major继承
        'sub_inherit': (255, 255, 0),      # 黄色 - sub继承
    }
    
    # 绘制ROI大框
    roi = data['table_roi']
    draw.rectangle([(roi[0], roi[1]), (roi[2], roi[3])], outline=colors['roi'], width=3)
    
    # 绘制列边界线
    col_bounds = data['column_boundaries']
    for col_name, (x1, x2) in col_bounds.items():
        draw.line([(x1, roi[1]), (x1, roi[3])], fill=colors['col_line'], width=2)
    # 绘制最后一列的右边界
    draw.line([(col_bounds['stock'][1], roi[1]), (col_bounds['stock'][1], roi[3])], fill=colors['col_line'], width=2)
    
    # 绘制每一行的单元格
    for row in data['rows']:
        row_bbox = row['row_bbox']
        row_y1, row_y2 = row_bbox[1], row_bbox[3]
        
        # 绘制行边界线（细线）
        draw.line([(roi[0], row_y1), (roi[2], row_y1)], fill=colors['row_line'], width=1)
        
        # major单元格
        major_bbox = row['major_cell_bbox']
        major_color = colors['major_inherit'] if row['major_inherit_from_prev'] else colors['major_cell']
        draw.rectangle([(major_bbox[0], major_bbox[1]), (major_bbox[2], major_bbox[3])], 
                       outline=major_color, width=2)
        
        # sub单元格
        sub_bbox = row['sub_cell_bbox']
        sub_color = colors['sub_inherit'] if row['sub_inherit_from_prev'] else colors['sub_cell']
        draw.rectangle([(sub_bbox[0], sub_bbox[1]), (sub_bbox[2], sub_bbox[3])], 
                       outline=sub_color, width=2)
        
        # stock单元格
        stock_bbox = row['stock_cell_bbox']
        draw.rectangle([(stock_bbox[0], stock_bbox[1]), (stock_bbox[2], stock_bbox[3])], 
                       outline=colors['stock_cell'], width=2)
        
        # 在单元格内添加继承标记
        if row['major_inherit_from_prev']:
            draw.text((major_bbox[0] + 5, major_bbox[1] + 5), "↑M", fill=colors['major_inherit'])
        if row['sub_inherit_from_prev']:
            draw.text((sub_bbox[0] + 5, sub_bbox[1] + 5), "↑S", fill=colors['sub_inherit'])
    
    # 保存
    img.save(output_path)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='检测表格单元格布局和继承标记')
    parser.add_argument('--image', required=True, help='输入图像路径')
    parser.add_argument('--row-json', required=True, help='行边界JSON文件路径')
    parser.add_argument('--output-dir', default='output', help='输出目录')
    
    args = parser.parse_args()
    
    # 配置参数
    image_path = args.image
    row_boundaries_json = args.row_json
    output_dir = args.output_dir
    
    # 表格ROI（从输入文件读取）
    table_roi = [0, 180, 1220, 12238]
    
    # 列边界（基于T2.5a的建议）
    column_boundaries = {
        "major": [0, 238],
        "sub": [238, 618],
        "stock": [618, 1220]
    }
    
    # 执行检测
    json_path, md_path, debug_path = detect_cell_layout(
        image_path=image_path,
        row_boundaries_json=row_boundaries_json,
        table_roi=table_roi,
        column_boundaries=column_boundaries,
        output_dir=output_dir
    )
    
    print(f"JSON输出: {json_path}")
    print(f"Markdown报告: {md_path}")
    print(f"Debug图像: {debug_path}")


if __name__ == "__main__":
    main()