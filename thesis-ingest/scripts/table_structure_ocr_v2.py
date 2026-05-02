#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格结构识别 + OCR 脚本 V2
采用"列锚定 + 行切分 + 股票列单独增强 OCR"策略
用于解析开盘啦长图中的分层表格结构
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import re
import argparse

# 尝试导入 PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    print("警告: PaddleOCR 未安装")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


class TableStructureOCR:
    def __init__(self, image_path: str):
        self.image_path = image_path
        self.image = cv2.imread(image_path)
        if self.image is None:
            raise ValueError(f"无法读取图片: {image_path}")
        
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        self.height, self.width = self.image.shape[:2]
        
        print(f"图片尺寸: {self.width}x{self.height}")
        
        # 初始化 OCR 引擎
        if PADDLE_AVAILABLE:
            print("初始化 PaddleOCR...")
            self.ocr = PaddleOCR(
                lang='ch',
                use_angle_cls=True
            )
        
        # 存储检测结果
        self.col_boundaries = []  # 列边界
        self.row_boundaries = []  # 行边界
        self.table_data = []
        
    def detect_column_boundaries(self):
        """
        检测三列边界：
        - 大类列 (左侧深色背景)
        - 小类列 (中间列)
        - 股票原文列 (右侧白色背景)
        """
        print("检测列边界...")
        
        # 基于开盘啦表格的典型布局使用固定比例
        # 从图片观察：
        # - 第1列（大类）：约占 0-13% (约 0-160像素)
        # - 第2列（小类）：约占 13-22% (约 160-270像素)
        # - 第3列（股票）：约占 22-100% (约 270-1220像素)
        
        col1_end = int(self.width * 0.13)
        col2_end = int(self.width * 0.22)
        
        self.col_boundaries = [0, col1_end, col2_end, self.width]
        print(f"列边界: {self.col_boundaries}")
        print(f"  列1 (大类): 0-{col1_end}")
        print(f"  列2 (小类): {col1_end}-{col2_end}")
        print(f"  列3 (股票): {col2_end}-{self.width}")
        
        return self.col_boundaries
    
    def detect_row_boundaries(self):
        """
        检测行边界：使用水平投影找到每行的分隔
        """
        print("检测行边界...")
        
        # 预处理：转换为灰度
        gray = self.gray.copy()
        
        # 使用自适应阈值 - 降低参数以检测更多细节
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 11, 3)
        
        # 水平投影
        horizontal_proj = np.sum(binary, axis=1)
        
        # 平滑
        kernel_size = 5
        smoothed = np.convolve(horizontal_proj, np.ones(kernel_size)/kernel_size, mode='same')
        
        # 找到文本行的位置（投影峰值）
        threshold = np.mean(smoothed) * 0.05  # 进一步降低阈值
        
        rows = []
        in_text = False
        text_start = 0
        min_row_height = 15  # 降低最小行高
        last_row = -min_row_height
        
        for i in range(len(smoothed)):
            if smoothed[i] > threshold and not in_text:
                in_text = True
                text_start = i
            elif smoothed[i] <= threshold and in_text:
                in_text = False
                row_center = int((text_start + i) // 2)
                if row_center - last_row >= min_row_height:
                    rows.append(row_center)
                    last_row = row_center
        
        print(f"检测到 {len(rows)} 行")
        
        # 添加起始和结束边界
        self.row_boundaries = [0] + rows + [int(self.height)]
        
        return self.row_boundaries
    
    def extract_cell_image(self, row_idx: int, col_idx: int):
        """
        提取指定单元格的图像
        """
        if row_idx >= len(self.row_boundaries) - 1 or col_idx >= len(self.col_boundaries) - 1:
            return None, None
        
        y1 = self.row_boundaries[row_idx]
        y2 = self.row_boundaries[row_idx + 1]
        x1 = self.col_boundaries[col_idx]
        x2 = self.col_boundaries[col_idx + 1]
        
        # 添加小边距
        margin = 3
        y1 = max(0, y1 - margin)
        y2 = min(self.height, y2 + margin)
        x1 = max(0, x1 - margin)
        x2 = min(self.width, x2 + margin)
        
        cell_img = self.image[y1:y2, x1:x2]
        return cell_img, (int(x1), int(y1), int(x2), int(y2))
    
    def enhance_dark_background_cell(self, cell_img: np.ndarray) -> np.ndarray:
        """
        针对深色背景单元格（大类/小类列）的图像增强
        开盘啦表格的左列是深色背景配白色文字
        """
        if cell_img is None or cell_img.size == 0:
            return cell_img
        
        # 转换为灰度
        gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
        
        # 反转颜色（深色背景变白底黑字）
        inverted = cv2.bitwise_not(gray)
        
        # 增强对比度
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(inverted)
        
        # 二值化
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 形态学操作：去除噪声
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # 转回 3 通道
        result = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        
        return result
    
    def enhance_light_background_cell(self, cell_img: np.ndarray) -> np.ndarray:
        """
        针对浅色背景单元格（股票列）的图像增强
        """
        if cell_img is None or cell_img.size == 0:
            return cell_img
        
        # 转换为 PIL Image
        pil_img = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
        
        # 增强对比度
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(1.8)
        
        # 增强锐度
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(2.5)
        
        # 转回 OpenCV
        enhanced = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        # 灰度化
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        
        # CLAHE 增强
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)
        
        # 二值化
        _, binary = cv2.threshold(enhanced_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 去噪
        denoised = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)
        
        # 转回 3 通道
        result = cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)
        
        return result
    
    def ocr_cell(self, cell_img: np.ndarray, is_dark_bg: bool = False) -> str:
        """
        OCR 识别单元格
        """
        if cell_img is None or cell_img.size == 0:
            return ""
        
        # 确保最小高度
        h, w = cell_img.shape[:2]
        if h < 25:
            pad_top = (25 - h) // 2
            pad_bottom = 25 - h - pad_top
            cell_img = cv2.copyMakeBorder(cell_img, pad_top, pad_bottom, 0, 0, 
                                          cv2.BORDER_CONSTANT, value=(255, 255, 255))
        
        # 根据背景类型选择增强方式
        if is_dark_bg:
            enhanced = self.enhance_dark_background_cell(cell_img)
        else:
            enhanced = self.enhance_light_background_cell(cell_img)
        
        if PADDLE_AVAILABLE:
            try:
                temp_path = "/tmp/temp_ocr_cell.png"
                cv2.imwrite(temp_path, enhanced)
                result = self.ocr.ocr(temp_path, cls=True)
                
                if result and len(result) > 0 and result[0]:
                    texts = []
                    for line in result[0]:
                        if line and len(line) >= 2:
                            texts.append(line[1][0])
                    return ' '.join(texts).strip()
            except Exception as e:
                pass
        
        if TESSERACT_AVAILABLE:
            try:
                gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
                text = pytesseract.image_to_string(gray, lang='chi_sim+eng')
                return text.strip()
            except Exception as e:
                pass
        
        return ""
    
    def process_table(self):
        """
        主处理流程：列锚定 -> 行切分 -> 逐列 OCR
        """
        print("\n=== 开始表格结构识别 ===\n")
        
        # 1. 检测列边界
        self.detect_column_boundaries()
        
        # 2. 检测行边界
        self.detect_row_boundaries()
        
        # 3. 逐行处理
        print("\n逐行 OCR 识别...")
        
        current_major = ""
        current_sub = ""
        
        # 跳过表头行（前3行通常是标题和表头）
        start_row = 3 if len(self.row_boundaries) > 4 else 1
        
        for row_idx in range(start_row, len(self.row_boundaries) - 1):
            # 提取三列的图像
            col1_img, col1_bbox = self.extract_cell_image(row_idx, 0)  # 大类（深色背景）
            col2_img, col2_bbox = self.extract_cell_image(row_idx, 1)  # 小类
            col3_img, col3_bbox = self.extract_cell_image(row_idx, 2)  # 股票（浅色背景）
            
            # OCR 识别（大类/小类使用深色背景增强，股票列使用浅色背景增强）
            major_text = self.ocr_cell(col1_img, is_dark_bg=True) if col1_img is not None else ""
            sub_text = self.ocr_cell(col2_img, is_dark_bg=True) if col2_img is not None else ""
            stock_text = self.ocr_cell(col3_img, is_dark_bg=False) if col3_img is not None else ""
            
            # 清理文本
            major_text = self.clean_text(major_text)
            sub_text = self.clean_text(sub_text)
            stock_text = self.clean_text(stock_text)
            
            # 更新当前大类/小类
            if major_text:
                current_major = major_text
            if sub_text:
                current_sub = sub_text
            
            # 只记录有股票数据的行
            if stock_text:
                row_data = {
                    'row_index': row_idx - start_row,
                    'major_category_text': current_major,
                    'sub_category_text': current_sub,
                    'stock_text_raw': stock_text,
                    'row_bbox': [
                        int(self.col_boundaries[0]),
                        int(self.row_boundaries[row_idx]),
                        int(self.col_boundaries[3]),
                        int(self.row_boundaries[row_idx + 1])
                    ],
                    'cell_bbox': {
                        'major': col1_bbox,
                        'sub': col2_bbox,
                        'stock': col3_bbox
                    }
                }
                self.table_data.append(row_data)
                
                if (row_idx - start_row + 1) % 10 == 0:
                    print(f"  已处理 {row_idx - start_row + 1} 行...")
        
        print(f"\n识别完成，共 {len(self.table_data)} 行数据")
        return self.table_data
    
    def clean_text(self, text: str) -> str:
        """
        清理 OCR 结果中的噪声
        """
        if not text:
            return ""
        
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊字符，但保留中文、英文、数字、括号、连字符
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\-\(\)（）]', ' ', text)
        
        # 再次清理空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def save_results(self, output_dir: str, timestamp: str = None):
        """
        保存结果到 JSON 和 Markdown 文件
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存 JSON
        json_path = os.path.join(output_dir, f"table_structure_ocr_v2_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'metadata': {
                    'image_path': self.image_path,
                    'image_size': [int(self.width), int(self.height)],
                    'col_boundaries': [int(x) for x in self.col_boundaries],
                    'row_count': len(self.row_boundaries) - 1,
                    'data_row_count': len(self.table_data),
                    'timestamp': timestamp
                },
                'table_data': self.table_data
            }, f, ensure_ascii=False, indent=2)
        print(f"JSON 已保存: {json_path}")
        
        # 保存 Markdown
        md_path = os.path.join(output_dir, f"table_structure_ocr_v2_{timestamp}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# 表格 OCR 识别结果 V2\n\n")
            f.write(f"**图片**: `{self.image_path}`\n\n")
            f.write(f"**时间**: {timestamp}\n\n")
            f.write(f"**图片尺寸**: {self.width}x{self.height}\n\n")
            f.write(f"**列边界**: {self.col_boundaries}\n\n")
            f.write(f"**数据行数**: {len(self.table_data)}\n\n")
            f.write("---\n\n")
            
            # 表格视图
            f.write("## 识别结果（表格视图）\n\n")
            f.write("| 行号 | 大类 | 小类 | 股票原文 |\n")
            f.write("|------|------|------|----------|\n")
            
            prev_major = None
            prev_sub = None
            
            for row in self.table_data:
                row_idx = row['row_index']
                major = row['major_category_text'] or ""
                sub = row['sub_category_text'] or ""
                stock = row['stock_text_raw'] or ""
                
                # 标记继承
                if major and major == prev_major:
                    major_display = "(同上)"
                else:
                    major_display = major if major else ""
                    if major:
                        prev_major = major
                
                if sub and sub == prev_sub:
                    sub_display = "(同上)"
                else:
                    sub_display = sub if sub else ""
                    if sub:
                        prev_sub = sub
                
                # 转义 Markdown
                stock = stock.replace('|', '\\|').replace('\n', ' ')
                
                f.write(f"| {row_idx} | {major_display} | {sub_display} | {stock} |\n")
            
            f.write("\n---\n\n")
            
            # 分类视图
            f.write("## 按分类整理\n\n")
            
            current_major = None
            current_sub = None
            
            for row in self.table_data:
                major = row['major_category_text']
                sub = row['sub_category_text']
                stock = row['stock_text_raw']
                
                if not major and not sub and not stock:
                    continue
                
                # 大类标题
                if major and major != current_major:
                    f.write(f"\n### {major}\n\n")
                    current_major = major
                    current_sub = None
                
                # 小类标题
                if sub and sub != current_sub:
                    f.write(f"**{sub}**\n\n")
                    current_sub = sub
                
                # 股票列表
                if stock:
                    f.write(f"- {stock}\n")
            
            f.write("\n---\n\n")
            f.write("## 原始数据（JSON）\n\n")
            f.write("```json\n")
            f.write(json.dumps(self.table_data, ensure_ascii=False, indent=2))
            f.write("\n```\n")
        
        print(f"Markdown 已保存: {md_path}")
        
        return json_path, md_path


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='表格结构识别 + OCR V2（列锚定 + 行切分 + 股票列增强）')
    parser.add_argument('image_path', help='输入图片路径')
    parser.add_argument('--output-dir', '-o', default='output', help='输出目录')
    parser.add_argument('--timestamp', '-t', help='时间戳（可选）')
    
    args = parser.parse_args()
    
    # 检查图片是否存在
    if not os.path.exists(args.image_path):
        print(f"错误: 图片不存在: {args.image_path}")
        sys.exit(1)
    
    print(f"处理图片: {args.image_path}")
    
    # 创建处理器
    processor = TableStructureOCR(args.image_path)
    
    # 处理表格
    processor.process_table()
    
    # 保存结果
    json_path, md_path = processor.save_results(args.output_dir, args.timestamp)
    
    print(f"\n输出文件:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == '__main__':
    main()
