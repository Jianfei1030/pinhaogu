#!/usr/bin/env python3
"""
表格ROI精裁剪脚本 - T2.5a
只负责：1) 定位表格区域 2) 建议三列边界 3) 生成debug图
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import json
import os
from datetime import datetime
import argparse


def detect_table_roi(image_path: str, output_dir: str = "output") -> dict:
    """
    检测表格ROI区域和三列边界
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    
    h, w = img.shape[:2]
    print(f"原图尺寸: {w}x{h}")
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    h_proj = np.sum(binary, axis=1)
    
    # 检测顶部边界
    top_margin = 0
    for y in range(min(400, h)):
        if h_proj[y] < w * 0.05:
            if y > 100:
                top_margin = y
                break
    
    if top_margin < 150:
        for y in range(150, min(350, h)):
            if h_proj[y] > w * 0.3 and h_proj[y-10] < w * 0.1:
                top_margin = y - 10
                break
    
    if top_margin < 150:
        top_margin = 180
    
    print(f"检测到表格顶部边界: y={top_margin}")
    
    # 检测底部边界
    bottom_margin = h
    for y in range(h-1, max(h-500, top_margin), -1):
        if h_proj[y] < w * 0.02:
            continue
        else:
            if y < h - 100:
                bottom_margin = y + 20
                break
    
    bottom_region = img[h-100:h, :]
    bottom_gray = cv2.cvtColor(bottom_region, cv2.COLOR_BGR2GRAY)
    bottom_mean = np.mean(bottom_gray)
    
    if bottom_mean < 100:
        for y in range(h-150, max(h-400, top_margin), -1):
            row = img[y, :]
            row_mean = np.mean(cv2.cvtColor(row.reshape(1, -1, 3), cv2.COLOR_BGR2GRAY))
            if row_mean > 150:
                bottom_margin = y
                break
    
    if bottom_margin > h - 50:
        bottom_margin = h - 100
    
    print(f"检测到表格底部边界: y={bottom_margin}")
    
    # 检测左右边界
    v_proj = np.sum(binary, axis=0)
    
    left_margin = 0
    for x in range(min(100, w)):
        if v_proj[x] > h * 0.1:
            left_margin = max(0, x - 5)
            break
    
    right_margin = w
    for x in range(w-1, max(w-100, left_margin), -1):
        if v_proj[x] > h * 0.1:
            right_margin = min(w, x + 5)
            break
    
    print(f"检测到表格左右边界: x=[{left_margin}, {right_margin}]")
    
    # 建议三列边界
    roi_binary = binary[top_margin:bottom_margin, left_margin:right_margin]
    roi_v_proj = np.sum(roi_binary, axis=0)
    roi_w = right_margin - left_margin
    
    window = 10
    smoothed = np.convolve(roi_v_proj, np.ones(window)/window, mode='same')
    
    col1_end = int(roi_w * 0.22)
    col2_end = int(roi_w * 0.50)
    search_range = 30
    
    best_col1 = col1_end
    min_val1 = smoothed[col1_end]
    for x in range(max(0, col1_end-search_range), min(roi_w, col1_end+search_range)):
        if smoothed[x] < min_val1:
            min_val1 = smoothed[x]
            best_col1 = x
    
    best_col2 = col2_end
    min_val2 = smoothed[col2_end]
    for x in range(max(0, col2_end-search_range), min(roi_w, col2_end+search_range)):
        if smoothed[x] < min_val2:
            min_val2 = smoothed[x]
            best_col2 = x
    
    col1_x = left_margin + best_col1
    col2_x = left_margin + best_col2
    
    suggested_columns = {
        "major": [left_margin, col1_x],
        "sub": [col1_x, col2_x],
        "stock": [col2_x, right_margin]
    }
    
    print(f"建议三列边界:")
    print(f"  大类列: [{left_margin}, {col1_x}]")
    print(f"  小类列: [{col1_x}, {col2_x}]")
    print(f"  股票列: [{col2_x}, {right_margin}]")
    
    result = {
        "image_path": image_path,
        "image_size": [w, h],
        "table_roi": [left_margin, top_margin, right_margin, bottom_margin],
        "suggested_columns": suggested_columns,
        "notes": {
            "cropped_regions": {
                "top": f"0-{top_margin}px: 标题栏、题材简介、创建时间",
                "bottom": f"{bottom_margin}-{h}px: 免责声明、评论区、底部导航",
                "left": f"0-{left_margin}px" if left_margin > 0 else "无",
                "right": f"{right_margin}-{w}px" if right_margin < w else "无"
            },
            "roi_dimensions": {
                "width": right_margin - left_margin,
                "height": bottom_margin - top_margin
            },
            "column_widths": {
                "major": best_col1,
                "sub": best_col2 - best_col1,
                "stock": right_margin - col2_x
            }
        }
    }
    
    return result, img


def generate_debug_image(image_path: str, result: dict, output_path: str):
    """生成debug标注图"""
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    w, h = img.size
    roi = result["table_roi"]
    cols = result["suggested_columns"]
    
    roi_color = (0, 255, 0)
    col_color = (255, 0, 0)
    crop_color = (128, 128, 128)
    
    # 绘制半透明遮罩
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([0, 0, w, roi[1]], fill=(100, 100, 100, 100))
    overlay_draw.rectangle([0, roi[3], w, h], fill=(100, 100, 100, 100))
    
    img = Image.alpha_composite(img.convert('RGBA'), overlay)
    draw = ImageDraw.Draw(img)
    
    # 绘制ROI框
    draw.rectangle([roi[0], roi[1], roi[2], roi[3]], outline=roi_color, width=6)
    
    # 绘制列边界线
    draw.line([cols["sub"][0], roi[1], cols["sub"][0], roi[3]], fill=col_color, width=4)
    draw.line([cols["stock"][0], roi[1], cols["stock"][0], roi[3]], fill=col_color, width=4)
    
    # 字体
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 40)
        small_font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 28)
    except:
        font = ImageFont.load_default()
        small_font = font
    
    # 文字标注
    draw.text((roi[0] + 15, roi[1] + 15), "TABLE ROI", fill=roi_color, font=font)
    draw.text((cols["major"][0] + 10, roi[1] + 60), "大类", fill=col_color, font=small_font)
    draw.text((cols["sub"][0] + 10, roi[1] + 60), "小类", fill=col_color, font=small_font)
    draw.text((cols["stock"][0] + 10, roi[1] + 60), "股票", fill=col_color, font=small_font)
    draw.text((10, 10), f"已裁剪: 顶部标题栏 (0-{roi[1]}px)", fill=(255, 255, 0), font=small_font)
    draw.text((10, h - 40), f"已裁剪: 底部导航/评论 ({roi[3]}-{h}px)", fill=(255, 255, 0), font=small_font)
    
    img.convert('RGB').save(output_path, 'PNG')
    print(f"Debug图已保存: {output_path}")


def generate_markdown(result: dict, output_path: str, timestamp: str):
    """生成Markdown报告"""
    w, h = result["image_size"]
    roi = result["table_roi"]
    cols = result["suggested_columns"]
    notes = result["notes"]
    
    md_content = f"""# 表格ROI检测报告

**生成时间**: {timestamp}

## 原图信息

- **图片路径**: `{result['image_path']}`
- **原图尺寸**: {w} x {h} 像素

## 表格ROI坐标

| 参数 | 值 |
|------|-----|
| 左上角 (x1, y1) | ({roi[0]}, {roi[1]}) |
| 右下角 (x2, y2) | ({roi[2]}, {roi[3]}) |
| ROI宽度 | {notes['roi_dimensions']['width']} px |
| ROI高度 | {notes['roi_dimensions']['height']} px |

## 建议三列边界

| 列名 | X坐标范围 | 宽度 |
|------|----------|------|
| 大类列 | [{cols['major'][0]}, {cols['major'][1]}] | {notes['column_widths']['major']} px |
| 小类列 | [{cols['sub'][0]}, {cols['sub'][1]}] | {notes['column_widths']['sub']} px |
| 股票列 | [{cols['stock'][0]}, {cols['stock'][1]}] | {notes['column_widths']['stock']} px |

## 已裁剪区域

- **顶部**: {notes['cropped_regions']['top']}
- **底部**: {notes['cropped_regions']['bottom']}
- **左侧**: {notes['cropped_regions']['left']}
- **右侧**: {notes['cropped_regions']['right']}

## Debug图说明

Debug图 (`table_roi_{timestamp}_debug.png`) 包含以下内容：

1. **绿色粗框**: 标识检测到的表格ROI区域
2. **红色竖线**: 标识建议的三列边界（大类/小类/股票）
3. **灰色半透明遮罩**: 标识被裁剪掉的顶部和底部区域
4. **文字标注**: 各列名称和裁剪区域说明

## 下一步

此输出仅包含表格ROI定位结果，不包含OCR文本识别。后续步骤将基于本ROI进行：
- 行检测与分割
- 单元格内容OCR
- 合并单元格检测
- 结构化数据提取
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"Markdown报告已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='表格ROI检测')
    parser.add_argument('image', help='输入图片路径')
    parser.add_argument('--output-dir', '-o', default='output', help='输出目录')
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print(f"处理图片: {args.image}")
    result, _ = detect_table_roi(args.image, args.output_dir)
    
    # 保存JSON
    json_path = os.path.join(args.output_dir, f'table_roi_{timestamp}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"JSON结果已保存: {json_path}")
    
    # 保存Markdown
    md_path = os.path.join(args.output_dir, f'table_roi_{timestamp}.md')
    generate_markdown(result, md_path, timestamp)
    
    # 保存Debug图
    debug_path = os.path.join(args.output_dir, f'table_roi_{timestamp}_debug.png')
    generate_debug_image(args.image, result, debug_path)
    
    print("\n完成!")
    print(f"输出文件:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
    print(f"  - Debug图: {debug_path}")


if __name__ == '__main__':
    main()