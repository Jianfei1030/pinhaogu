#!/usr/bin/env python3
"""
generate_debug_visualization.py - 生成语义切割方案的可视化debug图

在原图上标出建议切割线和块编号
"""

from PIL import Image, ImageDraw, ImageFont
import json
from datetime import datetime


def load_plan(json_path: str) -> dict:
    """加载切割方案JSON"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_debug_image(plan: dict, output_path: str):
    """生成带标注的debug图"""
    
    # 加载原图
    image_path = plan['image_path']
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # 尝试加载字体
    try:
        # macOS系统字体
        font_large = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 36)
        font_medium = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 24)
        font_small = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 18)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # 颜色定义
    colors = {
        'cut_line': (255, 0, 0),      # 红色 - 切割线
        'segment_border': (0, 255, 0), # 绿色 - segment边界
        'text': (255, 255, 255),       # 白色 - 文字
        'text_bg': (0, 0, 0, 180),     # 半透明黑 - 文字背景
        'highlight': (255, 255, 0),    # 黄色 - 高亮
    }
    
    width = plan['image_size'][0]
    
    # 绘制每个segment的边界和标注
    for seg in plan['segments']:
        bbox = seg['crop_bbox']
        x1, y1, x2, y2 = bbox
        seg_id = seg['segment_id']
        seg_name = seg['proposed_name']
        
        # 绘制segment边界框（左右边界）
        draw.line([(x1, y1), (x1, y2)], fill=colors['segment_border'], width=3)
        draw.line([(x2, y1), (x2, y2)], fill=colors['segment_border'], width=3)
        
        # 绘制顶部切割线（第一个segment不画顶部）
        if seg_id > 1:
            draw.line([(0, y1), (width, y1)], fill=colors['cut_line'], width=2)
            # 在线旁边标注
            draw.text((10, y1 - 25), f"--- Cut {seg_id-1}/{seg_id} ---", 
                     fill=colors['cut_line'], font=font_small)
        
        # 绘制底部边界线（最后一个segment）
        if seg_id == len(plan['segments']):
            draw.line([(0, y2), (width, y2)], fill=colors['cut_line'], width=2)
        
        # 在segment中间添加编号和名称标签
        mid_y = (y1 + y2) // 2
        label_text = f"[{seg_id}] {seg_name}"
        
        # 计算文字尺寸
        bbox_text = draw.textbbox((0, 0), label_text, font=font_medium)
        text_width = bbox_text[2] - bbox_text[0]
        text_height = bbox_text[3] - bbox_text[1]
        
        # 绘制文字背景
        padding = 10
        draw.rectangle(
            [(x1 + 20, mid_y - text_height//2 - padding), 
             (x1 + 20 + text_width + padding*2, mid_y + text_height//2 + padding)],
            fill=colors['text_bg']
        )
        
        # 绘制文字
        draw.text((x1 + 20 + padding, mid_y - text_height//2), 
                 label_text, fill=colors['text'], font=font_medium)
        
        # 在segment顶部添加高度信息
        height_px = y2 - y1
        height_text = f"{height_px}px"
        draw.text((x1 + 10, y1 + 5), height_text, 
                 fill=colors['highlight'], font=font_small)
    
    # 添加标题
    title = f"Semantic Cut Plan - {plan['timestamp']}"
    draw.text((10, 10), title, fill=colors['text'], font=font_large)
    
    subtitle = f"Strategy: {plan['planning_basis']['new_strategy']} | Segments: {plan['proposed_segment_count']}"
    draw.text((10, 50), subtitle, fill=colors['highlight'], font=font_medium)
    
    # 保存图片
    img.save(output_path, quality=90)
    print(f"[OK] Debug image saved: {output_path}")
    
    return output_path


def main():
    """主函数"""
    
    # 加载最新的plan
    import glob
    import os
    
    plan_files = glob.glob("output/path_cut_plan_*.json")
    if not plan_files:
        print("[Error] No plan files found in output/")
        return
    
    # 获取最新的plan文件
    latest_plan = max(plan_files, key=os.path.getctime)
    print(f"[Info] Loading plan: {latest_plan}")
    
    plan = load_plan(latest_plan)
    
    # 生成debug图
    timestamp = plan['timestamp']
    output_path = f"output/path_cut_plan_{timestamp}_debug.png"
    
    generate_debug_image(plan, output_path)
    
    print(f"\n[Visualization Complete]")
    print(f"  - Output: {output_path}")


if __name__ == '__main__':
    main()
