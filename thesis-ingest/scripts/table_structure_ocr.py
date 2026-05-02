#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格结构识别 + OCR 脚本
用于解析开盘啦长图中的分层表格结构
"""

import cv2
import numpy as np
from PIL import Image
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import re

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
        
        # 初始化 OCR 引擎
        if PADDLE_AVAILABLE:
            print("使用 PaddleOCR 进行文字识别...")
            self.ocr = PaddleOCR(
                lang='ch'
            )
        elif TESSERACT_AVAILABLE:
            print("使用 Tesseract 进行文字识别...")
        else:
            print("警告: 未找到 OCR 引擎，将使用简单文本提取")
        
        # 存储检测结果
        self.cells = []
        self.rows = []
        self.columns = []
        self.table_data = []
        
    def detect_table_structure(self):
        """检测表格结构"""
        print("正在检测表格结构...")
        
        # 分析图片布局 - 开盘啦表格通常是固定三列布局
        # 基于图片分析，使用固定列边界
        col1_end = int(self.width * 0.15)   # 大类列
        col2_end = int(self.width * 0.30)   # 小类列
        
        self.columns = [0, col1_end, col2_end, self.width]
        print(f"列边界: {self.columns}")
        
        # 检测行边界 - 使用水平投影
        self.rows = self._detect_rows_by_projection()
        print(f"检测到 {len(self.rows)-1} 行")
        
        # 生成单元格
        self._generate_cells()
        
        return self.columns, self.rows
    
    def _detect_rows_by_projection(self):
        """使用水平投影检测行"""
        # 预处理
        binary = cv2.adaptiveThreshold(self.gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 15, 10)
        
        # 水平投影
        horizontal_proj = np.sum(binary, axis=1)
        
        # 平滑投影曲线 - 使用简单的移动平均
        kernel_size = 5
        smoothed = np.convolve(horizontal_proj, np.ones(kernel_size)/kernel_size, mode='same')
        
        # 找到文本行的位置
        threshold = np.mean(smoothed) * 0.4
        
        rows = [0]  # 从顶部开始
        in_text = False
        text_start = 0
        
        min_row_height = 30  # 最小行高
        last_row_y = 0
        
        for i in range(len(smoothed)):
            if smoothed[i] > threshold and not in_text:
                in_text = True
                text_start = i
            elif smoothed[i] <= threshold and in_text:
                in_text = False
                row_center = (text_start + i) // 2
                
                # 确保行间距
                if row_center - last_row_y >= min_row_height:
                    rows.append(row_center)
                    last_row_y = row_center
        
        rows.append(self.height)  # 添加底部边界
        
        return rows
    
    def _generate_cells(self):
        """根据行列边界生成单元格"""
        self.cells = []
        
        for row_idx in range(len(self.rows) - 1):
            y1 = self.rows[row_idx]
            y2 = self.rows[row_idx + 1]
            
            row_cells = []
            for col_idx in range(len(self.columns) - 1):
                x1 = self.columns[col_idx]
                x2 = self.columns[col_idx + 1]
                
                cell = {
                    'row': row_idx,
                    'col': col_idx,
                    'bbox': (int(x1), int(y1), int(x2), int(y2)),
                    'text': '',
                }
                row_cells.append(cell)
            
            self.cells.append(row_cells)
    
    def ocr_cells(self):
        """对所有单元格进行 OCR 识别"""
        print("正在对单元格进行 OCR...")
        total_cells = sum(len(row) for row in self.cells)
        processed = 0
        
        for row_idx, row in enumerate(self.cells):
            for col_idx, cell in enumerate(row):
                x1, y1, x2, y2 = cell['bbox']
                
                # 添加边距
                margin = 3
                x1 = max(0, x1 - margin)
                y1 = max(0, y1 - margin)
                x2 = min(self.width, x2 + margin)
                y2 = min(self.height, y2 + margin)
                
                # 提取单元格区域
                cell_img = self.image[y1:y2, x1:x2]
                
                if cell_img.size == 0:
                    continue
                
                # OCR 识别
                text = self._ocr_cell(cell_img)
                cell['text'] = text.strip()
                
                processed += 1
                if processed % 50 == 0:
                    print(f"  已处理 {processed}/{total_cells} 个单元格...")
    
    def _ocr_cell(self, cell_img):
        """对单个单元格进行 OCR"""
        if PADDLE_AVAILABLE:
            try:
                result = self.ocr.ocr(cell_img, cls=True)
                if result and len(result) > 0 and result[0]:
                    texts = []
                    for line in result[0]:
                        if line:
                            texts.append(line[1][0])  # 提取文本
                    return ' '.join(texts)
            except Exception as e:
                pass
        
        if TESSERACT_AVAILABLE:
            try:
                # 预处理
                gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                
                # 使用 Tesseract
                text = pytesseract.image_to_string(binary, lang='chi_sim+eng')
                return text.strip()
            except Exception as e:
                pass
        
        return ""
    
    def build_table_data(self):
        """构建表格数据结构，处理合并单元格"""
        print("正在构建表格数据...")
        
        table_data = []
        current_major = ""  # 当前大类
        current_sub = ""    # 当前小类
        
        for row_idx, row in enumerate(self.cells):
            # 获取三列的文本
            major_text = row[0]['text'] if len(row) > 0 else ""
            sub_text = row[1]['text'] if len(row) > 1 else ""
            stock_text = row[2]['text'] if len(row) > 2 else ""
            
            # 跳过表头行
            if row_idx == 0 and ("AI硬件" in major_text or "板块" in major_text):
                continue
            
            # 更新大类（如果不为空）
            if major_text and major_text.strip():
                current_major = major_text.strip()
            
            # 更新小类（如果不为空）
            if sub_text and sub_text.strip():
                current_sub = sub_text.strip()
            
            # 只包含有股票数据的行
            if stock_text and stock_text.strip():
                row_data = {
                    'row_index': row_idx,
                    'major_category': current_major if current_major else None,
                    'sub_category': current_sub if current_sub else None,
                    'stock_text_raw': stock_text.strip(),
                    'bbox_major': row[0]['bbox'] if len(row) > 0 else None,
                    'bbox_sub': row[1]['bbox'] if len(row) > 1 else None,
                    'bbox_stock': row[2]['bbox'] if len(row) > 2 else None,
                }
                table_data.append(row_data)
        
        self.table_data = table_data
        return table_data
    
    def save_results(self, output_dir: str, timestamp: str = None):
        """保存结果到 JSON 和 Markdown 文件"""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存 JSON
        json_path = os.path.join(output_dir, f"table_structure_ocr_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'metadata': {
                    'image_path': self.image_path,
                    'image_size': [self.width, self.height],
                    'columns': self.columns,
                    'row_count': len(self.rows) - 1,
                    'timestamp': timestamp,
                },
                'table_data': self.table_data
            }, f, ensure_ascii=False, indent=2)
        print(f"JSON 已保存: {json_path}")
        
        # 保存 Markdown
        md_path = os.path.join(output_dir, f"table_structure_ocr_{timestamp}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# 表格 OCR 识别结果\n\n")
            f.write(f"**图片**: `{self.image_path}`\n\n")
            f.write(f"**时间**: {timestamp}\n\n")
            f.write(f"**总行数**: {len(self.table_data)}\n\n")
            f.write("---\n\n")
            
            f.write("## 识别结果\n\n")
            f.write("| 行号 | 大类 | 小类 | 股票原文 |\n")
            f.write("|------|------|------|----------|\n")
            
            prev_major = None
            prev_sub = None
            
            for row in self.table_data:
                row_idx = row['row_index']
                major = row['major_category'] or ""
                sub = row['sub_category'] or ""
                stock = row['stock_text_raw'] or ""
                
                # 标记继承关系
                major_display = major if major else "(继承上一行大类)"
                sub_display = sub if sub else "(继承上一行小类)"
                
                # 转义 Markdown 特殊字符
                stock = stock.replace('|', '\\|').replace('\n', ' ')
                
                f.write(f"| {row_idx} | {major_display} | {sub_display} | {stock} |\n")
            
            f.write("\n---\n\n")
            f.write("## 详细数据\n\n")
            
            current_major = None
            current_sub = None
            
            for row in self.table_data:
                major = row['major_category']
                sub = row['sub_category']
                stock = row['stock_text_raw']
                
                # 大类变化时输出标题
                if major and major != current_major:
                    f.write(f"\n### {major}\n\n")
                    current_major = major
                    current_sub = None
                
                # 小类变化时输出子标题
                if sub and sub != current_sub:
                    f.write(f"\n#### {sub}\n\n")
                    current_sub = sub
                
                # 输出股票
                if stock:
                    f.write(f"- {stock}\n")
        
        print(f"Markdown 已保存: {md_path}")
        
        return json_path, md_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='表格结构识别 + OCR')
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
    
    # 检测表格结构
    processor.detect_table_structure()
    
    # OCR 识别
    processor.ocr_cells()
    
    # 构建表格数据
    processor.build_table_data()
    
    print(f"\n识别完成，共 {len(processor.table_data)} 行数据")
    
    # 保存结果
    json_path, md_path = processor.save_results(args.output_dir, args.timestamp)
    
    print(f"\n输出文件:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == '__main__':
    main()
