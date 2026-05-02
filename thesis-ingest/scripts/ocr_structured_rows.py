#!/usr/bin/env python3
"""
T2.5c: 分列OCR + 逐行结构结果导出
对每一行的大类/小类/股票三列分别进行OCR识别
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pytesseract
except ImportError:
    print("Warning: pytesseract not available, using fallback")
    pytesseract = None


def preprocess_for_ocr(image, mode="default"):
    """根据模式预处理图像以提高OCR准确率"""
    if mode == "default":
        return image
    elif mode == "grayscale":
        return image.convert('L')
    elif mode == "binary":
        gray = image.convert('L')
        return gray.point(lambda x: 0 if x < 128 else 255, '1')
    elif mode == "enhanced":
        # 增加对比度
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(2.0)
    elif mode == "sharpen":
        return image.filter(ImageFilter.SHARPEN)
    return image


def ocr_cell(image_path, bbox, preprocess_modes=None):
    """
    对指定区域的单元格进行OCR识别
    尝试多种预处理方式，返回最佳结果
    """
    if preprocess_modes is None:
        preprocess_modes = ["default", "grayscale", "enhanced"]
    
    try:
        # 打开原图
        full_img = Image.open(image_path)
        
        # 裁剪指定区域 (bbox: [x1, y1, x2, y2])
        x1, y1, x2, y2 = bbox
        cell_img = full_img.crop((x1, y1, x2, y2))
        
        # 如果区域太小，可能是空的
        if cell_img.width < 5 or cell_img.height < 5:
            return ""
        
        # 放大图像以提高OCR准确率
        scale = 2
        cell_img = cell_img.resize((cell_img.width * scale, cell_img.height * scale), Image.LANCZOS)
        
        if pytesseract is None:
            # Fallback: 返回占位符
            return "[OCR_UNAVAILABLE]"
        
        # 尝试多种预处理方式
        results = []
        for mode in preprocess_modes:
            try:
                processed = preprocess_for_ocr(cell_img, mode)
                text = pytesseract.image_to_string(processed, lang='chi_sim+eng')
                text = text.strip().replace('\n', ' ').replace('  ', ' ')
                if text:
                    results.append((text, len(text)))
            except Exception as e:
                continue
        
        # 选择最长的结果（通常最完整）
        if results:
            results.sort(key=lambda x: x[1], reverse=True)
            return results[0][0]
        
        return ""
    except Exception as e:
        return f"[ERROR: {str(e)}]"


def perform_ocr_on_rows(image_path, inheritance_data, output_dir):
    """
    对每一行进行分列OCR
    """
    rows_data = inheritance_data['rows']
    row_count = len(rows_data)
    
    # 跟踪继承值用于显示
    last_major = ""
    last_sub = ""
    
    processed_rows = []
    
    print(f"开始OCR处理，共 {row_count} 行...")
    
    for i, row in enumerate(rows_data):
        row_index = row['row_index']
        
        # 获取三个单元格的bbox
        major_bbox = row['major_cell_bbox']
        sub_bbox = row['sub_cell_bbox']
        stock_bbox = row['stock_cell_bbox']
        
        # 获取继承标志
        major_inherit = row.get('major_inherit_from_prev', False)
        sub_inherit = row.get('sub_inherit_from_prev', False)
        
        # OCR识别
        print(f"  处理行 {row_index + 1}/{row_count}...", end='\r')
        
        # 对深色背景的大类/小类列使用增强预处理
        major_text = ocr_cell(image_path, major_bbox, ["enhanced", "grayscale", "default"])
        sub_text = ocr_cell(image_path, sub_bbox, ["enhanced", "grayscale", "default"])
        
        # 股票列使用多种预处理方式
        stock_text = ocr_cell(image_path, stock_bbox, ["default", "grayscale", "enhanced", "sharpen"])
        
        # 计算有效显示值（考虑继承）
        if major_inherit and last_major and not major_text.strip():
            major_display = last_major
        else:
            major_display = major_text
            if major_text.strip():
                last_major = major_text
        
        if sub_inherit and last_sub and not sub_text.strip():
            sub_display = last_sub
        else:
            sub_display = sub_text
            if sub_text.strip():
                last_sub = sub_text
        
        processed_row = {
            "row_index": row_index,
            "row_bbox": row['row_bbox'],
            "major_cell_bbox": major_bbox,
            "sub_cell_bbox": sub_bbox,
            "stock_cell_bbox": stock_bbox,
            "major_inherit_from_prev": major_inherit,
            "sub_inherit_from_prev": sub_inherit,
            "major_text_raw": major_text,
            "sub_text_raw": sub_text,
            "stock_text_raw": stock_text,
            "major_effective_display": major_display,
            "sub_effective_display": sub_display,
            "notes": row.get('notes', '')
        }
        
        processed_rows.append(processed_row)
    
    print(f"\nOCR处理完成，共处理 {len(processed_rows)} 行")
    return processed_rows


def generate_markdown(rows_data, output_path):
    """
    生成适合人工验收的Markdown文档
    """
    lines = []
    lines.append("# 结构化行OCR结果 - 逐行验收文档")
    lines.append("")
    lines.append(f"**总行数**: {len(rows_data)}")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    for row in rows_data:
        row_index = row['row_index']
        major_raw = row['major_text_raw']
        sub_raw = row['sub_text_raw']
        stock_raw = row['stock_text_raw']
        major_inherit = row['major_inherit_from_prev']
        sub_inherit = row['sub_inherit_from_prev']
        major_display = row.get('major_effective_display', major_raw)
        sub_display = row.get('sub_effective_display', sub_raw)
        
        lines.append(f"### 行 {row_index}")
        lines.append("")
        
        # 大类显示
        if major_inherit:
            lines.append(f"- **大类**: {major_display} *(继承自上一行)*")
        else:
            lines.append(f"- **大类**: {major_raw}")
        
        # 小类显示
        if sub_inherit:
            lines.append(f"- **小类**: {sub_display} *(继承自上一行)*")
        else:
            lines.append(f"- **小类**: {sub_raw}")
        
        # 股票原文
        lines.append(f"- **股票原文**: {stock_raw}")
        
        # 原始OCR值（如果与显示值不同）
        if major_inherit and major_raw != major_display:
            lines.append(f"  - 原始OCR值: `{major_raw}`")
        if sub_inherit and sub_raw != sub_display:
            lines.append(f"  - 原始OCR值: `{sub_raw}`")
        
        lines.append("")
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"Markdown文档已生成: {output_path}")


def main():
    """主函数"""
    # 工作目录
    work_dir = Path("os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest")
    output_dir = work_dir / "output"
    output_dir.mkdir(exist_ok=True)
    
    # 输入文件路径
    image_path = "<your-home>/.openclaw/media/inbound/Screenshot_2026-04-09-09-03-23-962_com.aiyu.kaipanla---9054cb9b-6f59-4624-903e-b945a8600919.jpg"
    roi_json = output_dir / "table_roi_20260409_161402.json"
    inheritance_json = output_dir / "inheritance_flags_20260409_184349.json"
    
    # 验证输入文件存在
    if not os.path.exists(image_path):
        print(f"错误: 图片文件不存在: {image_path}")
        return 1
    
    if not os.path.exists(inheritance_json):
        print(f"错误: 继承标志文件不存在: {inheritance_json}")
        return 1
    
    # 加载继承标志数据
    print("加载继承标志数据...")
    with open(inheritance_json, 'r', encoding='utf-8') as f:
        inheritance_data = json.load(f)
    
    # 执行OCR
    print("开始分列OCR识别...")
    processed_rows = perform_ocr_on_rows(image_path, inheritance_data, output_dir)
    
    # 生成输出文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_output = output_dir / f"structured_row_ocr_{timestamp}.json"
    md_output = output_dir / f"structured_row_ocr_{timestamp}.md"
    
    # 加载ROI数据
    with open(roi_json, 'r', encoding='utf-8') as f:
        roi_data = json.load(f)
    
    # 构建输出JSON
    output_data = {
        "image_path": image_path,
        "table_roi": roi_data.get('table_roi', [0, 180, 1220, 12238]),
        "source_files": {
            "roi": str(roi_json),
            "inheritance": str(inheritance_json)
        },
        "row_count": len(processed_rows),
        "rows": processed_rows,
        "generated_at": datetime.now().isoformat()
    }
    
    # 保存JSON
    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"JSON结果已保存: {json_output}")
    
    # 生成Markdown
    generate_markdown(processed_rows, md_output)
    
    print("\n=== T2.5c 完成 ===")
    print(f"输出文件:")
    print(f"  - JSON: {json_output}")
    print(f"  - Markdown: {md_output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())