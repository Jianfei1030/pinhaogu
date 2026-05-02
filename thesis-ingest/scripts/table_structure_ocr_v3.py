#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格结构识别 + OCR 脚本 V3
采用"ROI精裁剪 + 真实行列检测 + 合并单元格继承 + 分列OCR"策略
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


class TableStructureOCRV3:
    def __init__(self, image_path: str):
        self.image_path = image_path
        self.image = cv2.imread(image_path)
        if self.image is None:
            raise ValueError(f"无法读取图片: {image_path}")
        
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        self.height, self.width = self.image.shape[:2]
        
        print(f"原始图片尺寸: {self.width}x{self.height}")
        
        # 初始化 OCR 引擎
        if PADDLE_AVAILABLE:
            print("初始化 PaddleOCR...")
            self.ocr = PaddleOCR(lang='ch')
        
        # 存储检测结果
        self.table_roi = None
        self.col_boundaries = []
        self.row_boundaries = []
        self.table_data = []
        
    def detect_table_roi(self) -> Tuple[int, int, int, int]:
        """检测表格区域ROI，裁剪掉非表格区域"""
        print("检测表格ROI...")
        
        gray = self.gray.copy()
        edges = cv2.Canny(gray, 50, 150)
        horizontal_proj = np.sum(edges, axis=1)
        threshold = np.mean(horizontal_proj) * 0.3
        
        y_start = 0
        for i in range(min(500, len(horizontal_proj))):
            if horizontal_proj[i] > threshold:
                y_start = max(0, i - 50)
                break
        
        y_end = self.height
        for i in range(self.height - 1, max(self.height - 500, 0), -1):
            if horizontal_proj[i] > threshold:
                y_end = min(self.height, i + 50)
                break
        
        # 基于开盘啦表格特点调整
        if y_start < 400:
            y_start = 400
        if y_end > self.height - 300:
            y_end = self.height - 300
        
        self.table_roi = (0, int(y_start), self.width, int(y_end))
        print(f"表格ROI: y={y_start}-{y_end}, 尺寸: {self.width}x{y_end-y_start}")
        return self.table_roi
    
    def detect_column_boundaries(self) -> List[int]:
        """检测三列边界"""
        print("检测列边界...")
        
        if self.table_roi is None:
            self.detect_table_roi()
        
        x1, y1, x2, y2 = self.table_roi
        roi_width = x2 - x1
        
        col1_end = x1 + int(roi_width * 0.13)
        col2_end = x1 + int(roi_width * 0.28)
        
        self.col_boundaries = [x1, col1_end, col2_end, x2]
        print(f"列边界: 大类={x1}-{col1_end}, 小类={col1_end}-{col2_end}, 股票={col2_end}-{x2}")
        return self.col_boundaries
    
    def detect_row_boundaries(self) -> List[int]:
        """检测行边界"""
        print("检测行边界...")
        
        if self.table_roi is None:
            self.detect_table_roi()
        
        x1, y1, x2, y2 = self.table_roi
        roi_gray = self.gray[y1:y2, x1:x2]
        
        binary = cv2.adaptiveThreshold(roi_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 15, 5)
        horizontal_proj = np.sum(binary, axis=1)
        
        kernel_size = 5
        smoothed = np.convolve(horizontal_proj, np.ones(kernel_size)/kernel_size, mode='same')
        threshold = np.mean(smoothed) * 0.15
        
        rows = []
        in_text = False
        text_start = 0
        min_row_height = 35
        
        for i in range(len(smoothed)):
            if smoothed[i] > threshold and not in_text:
                in_text = True
                text_start = i
            elif smoothed[i] <= threshold and in_text:
                in_text = False
                row_center = int((text_start + i) // 2)
                if len(rows) == 0 or (row_center - rows[-1]) >= min_row_height:
                    rows.append(row_center)
        
        self.row_boundaries = [0] + rows + [y2 - y1]
        print(f"检测到 {len(rows)} 行")
        return self.row_boundaries
    
    def extract_cell_image(self, row_idx: int, col_idx: int):
        """提取指定单元格的图像"""
        if self.table_roi is None:
            self.detect_table_roi()
        if len(self.col_boundaries) < 4:
            self.detect_column_boundaries()
        if len(self.row_boundaries) < 2:
            self.detect_row_boundaries()
        
        if row_idx >= len(self.row_boundaries) - 1 or col_idx >= len(self.col_boundaries) - 1:
            return None, None
        
        x1, y1, x2, y2 = self.table_roi
        cell_y1 = y1 + self.row_boundaries[row_idx]
        cell_y2 = y1 + self.row_boundaries[row_idx + 1]
        cell_x1 = self.col_boundaries[col_idx]
        cell_x2 = self.col_boundaries[col_idx + 1]
        
        margin = 3
        cell_y1 = max(y1, cell_y1 - margin)
        cell_y2 = min(y2, cell_y2 + margin)
        cell_x1 = max(x1, cell_x1 - margin)
        cell_x2 = min(x2, cell_x2 + margin)
        
        cell_img = self.image[cell_y1:cell_y2, cell_x1:cell_x2]
        return cell_img, (int(cell_x1), int(cell_y1), int(cell_x2), int(cell_y2))
    
    def enhance_for_dark_bg(self, cell_img: np.ndarray) -> np.ndarray:
        """深色背景单元格增强"""
        if cell_img is None or cell_img.size == 0:
            return cell_img
        gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
        inverted = cv2.bitwise_not(gray)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(inverted)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    
    def enhance_for_light_bg(self, cell_img: np.ndarray) -> np.ndarray:
        """浅色背景单元格增强"""
        if cell_img is None or cell_img.size == 0:
            return cell_img
        pil_img = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(1.5)
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(2.0)
        enhanced = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(gray)
        _, binary = cv2.threshold(enhanced_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)
        return cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)
    
    def ocr_cell(self, cell_img: np.ndarray, is_dark_bg: bool = False) -> str:
        """OCR识别单元格"""
        if cell_img is None or cell_img.size == 0:
            return ""
        
        h, w = cell_img.shape[:2]
        if h < 20:
            pad_top = (20 - h) // 2
            pad_bottom = 20 - h - pad_top
            cell_img = cv2.copyMakeBorder(cell_img, pad_top, pad_bottom, 0, 0, 
                                          cv2.BORDER_CONSTANT, value=(255, 255, 255))
        
        if is_dark_bg:
            enhanced = self.enhance_for_dark_bg(cell_img)
        else:
            enhanced = self.enhance_for_light_bg(cell_img)
        
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
                text = pytesseract.image_to_string(gray, lang='chi_sim')
                return text.strip()
            except Exception as e:
                pass
        
        return ""
    
    def multi_version_ocr_stock(self, cell_img: np.ndarray) -> Tuple[str, List[Dict]]:
        """股票列多版本OCR选优"""
        if cell_img is None or cell_img.size == 0:
            return "", []
        
        candidates = []
        
        # 版本1: 原图
        try:
            text1 = self._ocr_raw(cell_img)
            candidates.append({"version": "raw", "text": text1, "score": self._score_text(text1)})
        except:
            pass
        
        # 版本2: 灰度增强
        try:
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            text2 = self._ocr_raw(enhanced_bgr)
            candidates.append({"version": "clahe", "text": text2, "score": self._score_text(text2)})
        except:
            pass
        
        # 版本3: 二值化
        try:
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            text3 = self._ocr_raw(binary_bgr)
            candidates.append({"version": "binary", "text": text3, "score": self._score_text(text3)})
        except:
            pass
        
        # 版本4: 放大2倍
        try:
            h, w = cell_img.shape[:2]
            resized = cv2.resize(cell_img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
            text4 = self._ocr_raw(resized)
            candidates.append({"version": "2x", "text": text4, "score": self._score_text(text4)})
        except:
            pass
        
        # 版本5: 锐化
        try:
            pil_img = Image.fromarray(cv2.cvtColor(cell_img, cv2.COLOR_BGR2RGB))
            enhancer = ImageEnhance.Sharpness(pil_img)
            sharpened = enhancer.enhance(3.0)
            sharpened_cv = cv2.cvtColor(np.array(sharpened), cv2.COLOR_RGB2BGR)
            text5 = self._ocr_raw(sharpened_cv)
            candidates.append({"version": "sharpen", "text": text5, "score": self._score_text(text5)})
        except:
            pass
        
        # 选择得分最高的
        if candidates:
            best = max(candidates, key=lambda x: x["score"])
            return best["text"], candidates
        
        return "", []
    
    def _ocr_raw(self, cell_img: np.ndarray) -> str:
        """原始OCR调用"""
        if PADDLE_AVAILABLE:
            try:
                temp_path = "/tmp/temp_ocr_stock.png"
                cv2.imwrite(temp_path, cell_img)
                result = self.ocr.ocr(temp_path, cls=True)
                if result and len(result) > 0 and result[0]:
                    texts = []
                    for line in result[0]:
                        if line and len(line) >= 2:
                            texts.append(line[1][0])
                    return ' '.join(texts).strip()
            except:
                pass
        return ""
    
    def _score_text(self, text: str) -> float:
        """评分函数：中文比例 + 可读性"""
        if not text:
            return 0.0
        
        # 中文字符比例
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text.replace(' ', ''))
        if total_chars == 0:
            return 0.0
        
        chinese_ratio = chinese_chars / total_chars
        
        # 惩罚过短的文本
        length_score = min(1.0, len(text) / 20)
        
        # 惩罚包含太多乱码字符的文本
        garbage_chars = len(re.findall(r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s]', text))
        garbage_ratio = garbage_chars / max(len(text), 1)
        
        score = chinese_ratio * 0.5 + length_score * 0.3 + (1 - garbage_ratio) * 0.2
        return score
    
    def process_table(self):
        """处理整个表格"""
        print("开始处理表格...")
        
        # 检测ROI
        self.detect_table_roi()
        
        # 检测列边界
        self.detect_column_boundaries()
        
        # 检测行边界
        self.detect_row_boundaries()
        
        # 处理每一行
        num_rows = len(self.row_boundaries) - 1
        print(f"处理 {num_rows} 行数据...")
        
        prev_major = ""
        prev_sub = ""
        
        for row_idx in range(num_rows):
            if row_idx % 10 == 0:
                print(f"  处理第 {row_idx}/{num_rows} 行...")
            
            # 提取三列
            major_img, major_bbox = self.extract_cell_image(row_idx, 0)
            sub_img, sub_bbox = self.extract_cell_image(row_idx, 1)
            stock_img, stock_bbox = self.extract_cell_image(row_idx, 2)
            
            # OCR识别
            major_text = self.ocr_cell(major_img, is_dark_bg=True) if major_img is not None else ""
            sub_text = self.ocr_cell(sub_img, is_dark_bg=True) if sub_img is not None else ""
            
            # 股票列使用多版本OCR
            if stock_img is not None:
                stock_text, stock_candidates = self.multi_version_ocr_stock(stock_img)
            else:
                stock_text, stock_candidates = "", []
            
            # 处理合并单元格继承
            inherit_major = False
            inherit_sub = False
            
            major_raw = major_text.strip()
            sub_raw = sub_text.strip()
            
            if not major_raw and prev_major:
                major_raw = prev_major
                inherit_major = True
            else:
                prev_major = major_raw
            
            if not sub_raw and prev_sub:
                sub_raw = prev_sub
                inherit_sub = True
            else:
                prev_sub = sub_raw
            
            # 计算行bbox
            x1, y1, x2, y2 = self.table_roi
            row_y1 = y1 + self.row_boundaries[row_idx]
            row_y2 = y1 + self.row_boundaries[row_idx + 1]
            row_bbox = [0, row_y1, self.width, row_y2]
            
            row_data = {
                "row_index": row_idx,
                "major_category_raw": major_raw,
                "sub_category_raw": sub_raw,
                "stock_text_raw": stock_text,
                "inherit_major_from_prev": inherit_major,
                "inherit_sub_from_prev": inherit_sub,
                "row_bbox": row_bbox,
                "cell_bbox": {
                    "major": list(major_bbox) if major_bbox else [],
                    "sub": list(sub_bbox) if sub_bbox else [],
                    "stock": list(stock_bbox) if stock_bbox else []
                }
            }
            
            if stock_candidates:
                row_data["stock_ocr_candidates"] = stock_candidates
            
            self.table_data.append(row_data)
        
        print(f"处理完成，共 {len(self.table_data)} 行")
        return self.table_data
    
    def create_debug_image(self, output_path: str):
        """创建调试图像"""
        debug_img = self.image.copy()
        
        # 绘制ROI
        if self.table_roi:
            x1, y1, x2, y2 = self.table_roi
            cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 3)
        
        # 绘制列边界
        if self.col_boundaries:
            for x in self.col_boundaries[1:-1]:
                cv2.line(debug_img, (x, 0), (x, self.height), (255, 0, 0), 2)
        
        # 绘制行边界
        if self.table_roi and self.row_boundaries:
            x1, y1, x2, y2 = self.table_roi
            for ry in self.row_boundaries:
                y = y1 + ry
                cv2.line(debug_img, (0, y), (self.width, y), (0, 0, 255), 1)
        
        cv2.imwrite(output_path, debug_img)
        print(f"调试图像已保存: {output_path}")
    
    def save_results(self, output_dir: str):
        """保存结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存JSON
        json_path = os.path.join(output_dir, f"table_structure_ocr_v3_{timestamp}.json")
        result = {
            "metadata": {
                "image_path": self.image_path,
                "image_size": [self.width, self.height],
                "timestamp": timestamp,
                "version": "v3"
            },
            "table_roi": list(self.table_roi) if self.table_roi else [],
            "column_boundaries": self.col_boundaries,
            "row_boundaries": self.row_boundaries,
            "table_data": self.table_data
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"JSON结果已保存: {json_path}")
        
        # 保存Markdown
        md_path = os.path.join(output_dir, f"table_structure_ocr_v3_{timestamp}.md")
        self._save_markdown(md_path, timestamp)
        print(f"Markdown结果已保存: {md_path}")
        
        # 保存调试图像
        debug_path = os.path.join(output_dir, f"table_structure_ocr_v3_{timestamp}_debug.png")
        self.create_debug_image(debug_path)
        
        return json_path, md_path
    
    def _save_markdown(self, output_path: str, timestamp: str):
        """保存Markdown报告"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# 表格 OCR 识别结果 V3\n\n")
            f.write(f"**图片**: `{self.image_path}`\n\n")
            f.write(f"**时间**: {timestamp}\n\n")
            f.write(f"**图片尺寸**: {self.width}x{self.height}\n\n")
            
            if self.table_roi:
                f.write(f"**表格ROI**: {self.table_roi}\n\n")
            
            if self.col_boundaries:
                f.write(f"**列边界**: {self.col_boundaries}\n\n")
            
            f.write(f"**数据行数**: {len(self.table_data)}\n\n")
            f.write("---\n\n")
            
            f.write("## 识别结果（逐行）\n\n")
            
            for row in self.table_data:
                row_idx = row["row_index"]
                major = row["major_category_raw"]
                sub = row["sub_category_raw"]
                stock = row["stock_text_raw"]
                inherit_major = row["inherit_major_from_prev"]
                inherit_sub = row["inherit_sub_from_prev"]
                
                f.write(f"### 行 {row_idx}\n\n")
                
                if inherit_major:
                    f.write(f"- **大类**: {major} (继承上一行)\n")
                else:
                    f.write(f"- **大类**: {major}\n")
                
                if inherit_sub:
                    f.write(f"- **小类**: {sub} (继承上一行)\n")
                else:
                    f.write(f"- **小类**: {sub}\n")
                
                f.write(f"- **股票原文**: {stock}\n\n")
            
            f.write("---\n\n")
            f.write("## 按分类整理\n\n")
            
            # 按大类分组
            current_major = ""
            current_sub = ""
            
            for row in self.table_data:
                major = row["major_category_raw"]
                sub = row["sub_category_raw"]
                stock = row["stock_text_raw"]
                
                if major and major != current_major:
                    f.write(f"\n### {major}\n\n")
                    current_major = major
                    current_sub = ""
                
                if sub and sub != current_sub:
                    f.write(f"**{sub}**\n\n")
                    current_sub = sub
                
                if stock:
                    f.write(f"- {stock}\n")


def main():
    if len(sys.argv) < 2:
        print("用法: python table_structure_ocr_v3.py <图片路径> [输出目录]")
        sys.exit(1)
    
    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    
    print(f"处理图片: {image_path}")
    print(f"输出目录: {output_dir}")
    
    try:
        ocr = TableStructureOCRV3(image_path)
        ocr.process_table()
        json_path, md_path = ocr.save_results(output_dir)
        print(f"\n完成!")
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
