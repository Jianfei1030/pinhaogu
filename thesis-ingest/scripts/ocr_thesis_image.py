#!/usr/bin/env python3
"""
OCR 识别脚本 - 从开盘啦图片中提取文字内容
支持从 AI 硬件产业链题材图片中提取题材名、细分分类和成分股列表
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    import pytesseract
except ImportError as e:
    print(f"Error: Missing required dependency - {e}")
    print("Please install: pip3 install pytesseract Pillow")
    sys.exit(1)


def extract_text_from_image(image_path: str) -> str:
    """
    从图片中提取文字内容
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        提取的文本内容
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # 打开图片
    image = Image.open(image_path)
    
    # 使用 tesseract 进行 OCR 识别
    # --psm 6: 假设是统一的文本块
    # -l chi_sim+eng: 使用简体中文和英文语言包
    text = pytesseract.image_to_string(
        image, 
        lang='chi_sim+eng',
        config='--psm 6'
    )
    
    return text


def save_ocr_result(text: str, output_dir: str) -> str:
    """
    保存 OCR 结果到文件
    
    Args:
        text: OCR 提取的文本
        output_dir: 输出目录
        
    Returns:
        保存的文件路径
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成文件名: ocr_raw_<timestamp>.txt
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"ocr_raw_{timestamp}.txt")
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='OCR 识别脚本 - 从开盘啦图片中提取文字内容'
    )
    parser.add_argument(
        '--image', 
        required=True, 
        help='输入图片路径'
    )
    parser.add_argument(
        '--output-dir',
        default='output',
        help='输出目录 (默认: output)'
    )
    
    args = parser.parse_args()
    
    # 获取工作目录（脚本所在目录的父目录）
    script_dir = Path(__file__).parent
    work_dir = script_dir.parent
    
    # 解析图片路径
    image_path = args.image
    if not os.path.isabs(image_path):
        image_path = os.path.join(os.getcwd(), image_path)
    
    # 解析输出目录
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(work_dir, output_dir)
    
    print(f"Processing image: {image_path}")
    
    try:
        # 执行 OCR
        extracted_text = extract_text_from_image(image_path)
        
        if not extracted_text.strip():
            print("Warning: No text extracted from image")
            extracted_text = "[OCR 未能识别到文字内容]"
        
        # 保存结果
        output_path = save_ocr_result(extracted_text, output_dir)
        
        print(f"\nOCR completed successfully!")
        print(f"Output saved to: {output_path}")
        print(f"\n--- Extracted Text Preview ---")
        print(extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text)
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
