#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格结构识别 + OCR 脚本 V4
优化重点：
1. 深色背景单元格：反色处理 + 颜色通道分离 + 自适应阈值 + 局部对比度增强
2. 股票列识别：优化列边界 + 专用预处理 + OCR 参数调优
3. 行边界检测：改进水平投影参数 + 文字行高统计
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
    print("警告：PaddleOCR 未安装")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


class TableStructureOCRV4:
    def __init__(self, image_path: str):
        self.image_path = image_path
        self.image = cv2.imread(image_path)
        if self.image is None:
            raise ValueError(f"无法读取图片：{image_path}")
        
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        self.height, self.width = self.image.shape[:2]
        
        print(f"原始图片尺寸：{self.width}x{self.height}")
        
        # 初始化 OCR 引擎
        if PADDLE_AVAILABLE:
            print("初始化 PaddleOCR...")
            # V4 优化：使用默认参数（新版 PaddleOCR 已弃用旧参数名）
            self.ocr = PaddleOCR(lang='ch')
        
        # 存储检测结果
        self.table_roi = None
        self.col_boundaries = []
        self.row_boundaries = []
        self.table_data = []
        
    def detect_table_roi(self) -> Tuple[int, int, int, int]:
        """检测表格区域 ROI，裁剪掉非表格区域"""
        print("检测表格 ROI...")
        
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
        print(f"表格 ROI: y={y_start}-{y_end}, 尺寸：{self.width}x{y_end-y_start}")
        return self.table_roi
    
    def detect_column_boundaries(self) -> List[int]:
        """检测三列边界 - V4 优化：根据实际表格结构调整比例"""
        print("检测列边界...")
        
        if self.table_roi is None:
            self.detect_table_roi()
        
        x1, y1, x2, y2 = self.table_roi
        roi_width = x2 - x1
        
        # V4 优化：调整列边界比例（根据实际表格视觉宽度）
        col1_end = x1 + int(roi_width * 0.12)  # 大类列稍窄
        col2_end = x1 + int(roi_width * 0.25)  # 小类列
        
        self.col_boundaries = [x1, col1_end, col2_end, x2]
        print(f"列边界：大类={x1}-{col1_end}, 小类={col1_end}-{col2_end}, 股票={col2_end}-{x2}")
        return self.col_boundaries
    
    def detect_row_boundaries(self) -> List[int]:
        """检测行边界 - V4 优化：改进投影参数"""
        print("检测行边界...")
        
        if self.table_roi is None:
            self.detect_table_roi()
        
        x1, y1, x2, y2 = self.table_roi
        roi_gray = self.gray[y1:y2, x1:x2]
        
        # V4 优化：多方法结合检测行边界
        # 方法 1: Canny 边缘检测 + 水平投影
        edges = cv2.Canny(roi_gray, 80, 200)
        horizontal_proj_edges = np.sum(edges, axis=1)
        
        # 方法 2: 自适应阈值二值化 + 水平投影
        binary = cv2.adaptiveThreshold(roi_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 15, 5)
        horizontal_proj_binary = np.sum(binary, axis=1)
        
        # 合并两种方法的投影
        horizontal_proj = horizontal_proj_edges * 0.6 + horizontal_proj_binary * 0.4
        
        # V4 优化：调整平滑和阈值参数
        kernel_size = 5
        smoothed = np.convolve(horizontal_proj, np.ones(kernel_size)/kernel_size, mode='same')
        threshold = np.mean(smoothed) * 0.15
        
        rows = []
        in_text = False
        text_start = 0
        min_row_height = 30  # 最小行高
        max_gap = 50  # 最大行间距
        
        for i in range(len(smoothed)):
            if smoothed[i] > threshold and not in_text:
                in_text = True
                text_start = i
            elif smoothed[i] <= threshold and in_text:
                in_text = False
                row_center = int((text_start + i) // 2)
                if len(rows) == 0 or (row_center - rows[-1]) >= min_row_height:
                    rows.append(row_center)
        
        # V4 补充：如果检测到的行太少，使用固定行高 fallback
        if len(rows) < 5:
            print("  警告：检测到的行太少，使用固定行高 fallback...")
            rows = []
            estimated_row_height = 120  # 估计行高
            roi_height = y2 - y1
            for y in range(estimated_row_height // 2, roi_height, estimated_row_height):
                rows.append(y)
        
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
    
    def process_cell_ocr(self, cell_img: np.ndarray, cell_type: str = 'text') -> str:
        """
        V4 核心优化：根据单元格类型应用不同预处理
        cell_type: 'major' | 'sub' | 'stock' | 'text'
        """
        if cell_img is None or cell_img.size == 0:
            return ""
        
        h, w = cell_img.shape[:2]
        
        # 小单元格放大处理
        if h < 25:
            scale = 3.0 if h < 15 else 2.0
            cell_img = cv2.resize(cell_img, (int(w * scale), int(h * scale)), 
                                  interpolation=cv2.INTER_CUBIC)
        
        if cell_type in ['major', 'sub']:
            # 深色背景单元格优化处理
            enhanced = self.enhance_dark_background(cell_img)
        elif cell_type == 'stock':
            # 股票列专用优化
            enhanced = self.enhance_stock_column(cell_img)
        else:
            # 标准处理
            enhanced = self.enhance_for_light_bg(cell_img)
        
        # OCR 识别
        if PADDLE_AVAILABLE:
            try:
                temp_path = "/tmp/temp_ocr_cell_v4.png"
                cv2.imwrite(temp_path, enhanced)
                # V4 修复：使用新版 API（移除 cls 参数）
                result = self.ocr.ocr(temp_path)
                if result and len(result) > 0 and result[0]:
                    texts = []
                    for line in result[0]:
                        if line and len(line) >= 2:
                            texts.append(line[1][0])
                    return ' '.join(texts).strip()
            except Exception as e:
                print(f"OCR 错误：{e}")
                pass
        
        if TESSERACT_AVAILABLE:
            try:
                gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
                text = pytesseract.image_to_string(gray, lang='chi_sim')
                return text.strip()
            except Exception as e:
                pass
        
        return ""
    
    def enhance_dark_background(self, cell_img: np.ndarray) -> np.ndarray:
        """
        V4 深色背景单元格增强：反色 + 颜色通道分离 + 对比度增强
        适用于红色/橙色背景的单元格
        """
        if cell_img is None or cell_img.size == 0:
            return cell_img
        
        # 1. 转换到 HSV 空间，检测红色/橙色区域
        hsv = cv2.cvtColor(cell_img, cv2.COLOR_BGR2HSV)
        
        # 红色范围（开盘啦大类/小类标题通常是红色/橙色背景）
        lower_red1 = np.array([0, 100, 100])
        upper_red1 = np.array([15, 255, 255])
        lower_red2 = np.array([160, 100, 100])
        upper_red2 = np.array([180, 255, 255])
        
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        mask_red = cv2.bitwise_or(mask1, mask2)
        
        # 橙色范围
        lower_orange = np.array([10, 150, 150])
        upper_orange = np.array([20, 255, 255])
        mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
        
        # 合并掩码
        dark_bg_mask = cv2.bitwise_or(mask_red, mask_orange)
        
        # 2. 如果检测到深色背景，应用特殊处理
        if np.sum(dark_bg_mask) > 100:  # 有显著的深色区域
            # 提取红色/橙色通道
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            
            # 3. 反色处理（深色背景->浅色背景）
            inverted = cv2.bitwise_not(gray)
            
            # 4. 对反色后的图像应用 CLAHE
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(10, 10))
            enhanced = clahe.apply(inverted)
            
            # 5. 自适应阈值二值化
            _, binary = cv2.threshold(enhanced, 0, 255, 
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 6. 形态学操作去噪
            kernel = np.ones((2, 2), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            
            # 7. 转回 BGR 格式
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        
        # 如果没有检测到深色背景，使用标准增强
        return self.enhance_for_light_bg(cell_img)
    
    def enhance_stock_column(self, cell_img: np.ndarray) -> np.ndarray:
        """
        V4 股票列专用增强：灰度化 + 去噪 + 对比度增强
        适用于白色背景、黑色文字的股票名称列
        """
        if cell_img is None or cell_img.size == 0:
            return cell_img
        
        # 1. 转换为灰度图
        gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
        
        # 2. 非局部均值去噪（保持边缘）
        denoised = cv2.fastNlMeansDenoising(gray, None, 8, 9, 21)
        
        # 3. CLAHE 增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        
        # 4. 自适应阈值二值化
        _, binary = cv2.threshold(enhanced, 0, 255, 
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 5. 轻微形态学操作（连接断裂笔画）
        kernel = np.ones((2, 1), np.uint8)  # 垂直方向连接
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        
        # 6. 转回 BGR
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    
    def enhance_for_light_bg(self, cell_img: np.ndarray) -> np.ndarray:
        """浅色背景单元格增强（保留 V3 逻辑）"""
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
    
    def multi_version_ocr_stock(self, cell_img: np.ndarray) -> Tuple[str, List[Dict]]:
        """股票列多版本 OCR 选优 - V4 增加反色版本"""
        if cell_img is None or cell_img.size == 0:
            return "", []
        
        candidates = []
        
        # 版本 1: V4 专用股票列增强
        try:
            enhanced_v4 = self.enhance_stock_column(cell_img)
            text1 = self._ocr_raw(enhanced_v4)
            candidates.append({"version": "v4_stock", "text": text1, "score": self._score_text(text1)})
        except Exception as e:
            pass
        
        # 版本 2: 原图
        try:
            text2 = self._ocr_raw(cell_img)
            candidates.append({"version": "raw", "text": text2, "score": self._score_text(text2)})
        except:
            pass
        
        # 版本 3: CLAHE 增强
        try:
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            text3 = self._ocr_raw(enhanced_bgr)
            candidates.append({"version": "clahe", "text": text3, "score": self._score_text(text3)})
        except:
            pass
        
        # 版本 4: 二值化
        try:
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            text4 = self._ocr_raw(binary_bgr)
            candidates.append({"version": "binary", "text": text4, "score": self._score_text(text4)})
        except:
            pass
        
        # 版本 5: 放大 2 倍
        try:
            h, w = cell_img.shape[:2]
            resized = cv2.resize(cell_img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
            text5 = self._ocr_raw(resized)
            candidates.append({"version": "2x", "text": text5, "score": self._score_text(text5)})
        except:
            pass
        
        # 版本 6: 反色处理（应对可能的深色背景）
        try:
            gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
            inverted = cv2.bitwise_not(gray)
            inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
            text6 = self._ocr_raw(inverted_bgr)
            candidates.append({"version": "inverted", "text": text6, "score": self._score_text(text6)})
        except:
            pass
        
        # 选择得分最高的
        if candidates:
            best = max(candidates, key=lambda x: x["score"])
            return best["text"], candidates
        
        return "", []
    
    def _ocr_raw(self, cell_img: np.ndarray) -> str:
        """原始 OCR 调用"""
        if PADDLE_AVAILABLE:
            try:
                temp_path = "/tmp/temp_ocr_stock_v4.png"
                cv2.imwrite(temp_path, cell_img)
                # V4 修复：使用新版 API（移除 cls 参数）
                result = self.ocr.ocr(temp_path)
                if result and len(result) > 0 and result[0]:
                    texts = []
                    for line in result[0]:
                        if line and len(line) >= 2:
                            texts.append(line[1][0])
                    return ' '.join(texts).strip()
            except Exception as e:
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
        """处理整个表格 - V4 使用新的 process_cell_ocr 函数"""
        print("开始处理表格...")
        
        # 检测 ROI
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
            
            # V4 优化：使用 process_cell_ocr 根据单元格类型应用不同预处理
            major_text = self.process_cell_ocr(major_img, cell_type='major') if major_img is not None else ""
            sub_text = self.process_cell_ocr(sub_img, cell_type='sub') if sub_img is not None else ""
            
            # 股票列使用多版本 OCR
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
            
            # 计算行 bbox
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
        
        # 绘制 ROI
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
        print(f"调试图像已保存：{output_path}")
    
    def save_results(self, output_dir: str):
        """保存结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存 JSON
        json_path = os.path.join(output_dir, f"table_structure_ocr_v4_{timestamp}.json")
        result = {
            "metadata": {
                "image_path": self.image_path,
                "image_size": [self.width, self.height],
                "timestamp": timestamp,
                "version": "v4"
            },
            "table_roi": list(self.table_roi) if self.table_roi else [],
            "column_boundaries": self.col_boundaries,
            "row_boundaries": self.row_boundaries,
            "table_data": self.table_data
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"JSON 结果已保存：{json_path}")
        
        # 保存 Markdown
        md_path = os.path.join(output_dir, f"table_structure_ocr_v4_{timestamp}.md")
        self._save_markdown(md_path, timestamp)
        print(f"Markdown 结果已保存：{md_path}")
        
        # 保存调试图像
        debug_path = os.path.join(output_dir, f"table_structure_ocr_v4_{timestamp}_debug.png")
        self.create_debug_image(debug_path)
        
        return json_path, md_path
    
    def _save_markdown(self, output_path: str, timestamp: str):
        """保存 Markdown 报告"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# 表格 OCR 识别结果 V4\n\n")
            f.write(f"**图片**: `{self.image_path}`\n\n")
            f.write(f"**时间**: {timestamp}\n\n")
            f.write(f"**图片尺寸**: {self.width}x{self.height}\n\n")
            
            if self.table_roi:
                f.write(f"**表格 ROI**: {self.table_roi}\n\n")
            
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
        print("用法：python table_structure_ocr_v4.py <图片路径> [输出目录]")
        sys.exit(1)
    
    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    
    print(f"处理图片：{image_path}")
    print(f"输出目录：{output_dir}")
    
    try:
        ocr = TableStructureOCRV4(image_path)
        ocr.process_table()
        json_path, md_path = ocr.save_results(output_dir)
        print(f"\n完成!")
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
    except Exception as e:
        print(f"错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
