#!/usr/bin/env python3
"""
开盘啦图片分区域OCR脚本 (T2.5)
对长截图按版面结构切成多个区域进行OCR识别
"""

import os
import sys
import json
import time
from datetime import datetime
from PIL import Image
import numpy as np

# 尝试导入OCR库
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    print("Warning: PaddleOCR not available, will use fallback")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

class SegmentOCR:
    def __init__(self, image_path):
        self.image_path = image_path
        self.image = Image.open(image_path)
        self.width, self.height = self.image.size
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 初始化OCR引擎
        if PADDLE_AVAILABLE:
            print("Using PaddleOCR...")
            self.ocr = PaddleOCR(use_angle_cls=True, lang='ch')
        else:
            self.ocr = None
            print("PaddleOCR not available")
    
    def detect_regions(self):
        """
        根据开盘啦APP的版面结构检测区域
        返回区域列表，每个区域包含坐标和描述
        """
        regions = []
        
        # 分析图片结构 - 开盘啦概念板块列表通常有:
        # 1. 顶部标题栏 (状态栏 + APP标题)
        # 2. 搜索/筛选栏
        # 3. 多个板块分类区域 (AI硬件、光通信、芯片等)
        
        # 根据图片高度进行分区
        # 图片高度约12319像素，宽度1220像素
        
        # 区域1: 顶部状态栏和标题 (约前200像素高度)
        regions.append({
            "id": 1,
            "name": "顶部状态栏与标题区",
            "coords": (0, 0, self.width, min(250, self.height)),
            "description": "包含时间、信号、电池等状态信息以及页面标题"
        })
        
        # 区域2: 搜索筛选栏 (约200-400像素)
        if self.height > 400:
            regions.append({
                "id": 2,
                "name": "搜索筛选栏",
                "coords": (0, 200, self.width, min(450, self.height)),
                "description": "搜索框和筛选条件"
            })
        
        # 区域3: AI硬件板块区 (约450-1200像素)
        if self.height > 1200:
            regions.append({
                "id": 3,
                "name": "AI硬件板块区",
                "coords": (0, 450, self.width, min(1300, self.height)),
                "description": "AI硬件相关概念板块"
            })
        
        # 区域4: 光通信/LPO板块区 (约1300-2000像素)
        if self.height > 2000:
            regions.append({
                "id": 4,
                "name": "光通信/LPO板块区",
                "coords": (0, 1300, self.width, min(2100, self.height)),
                "description": "光通信、LPO等相关板块"
            })
        
        # 区域5: 芯片/半导体板块区 (约2100-3500像素)
        if self.height > 3500:
            regions.append({
                "id": 5,
                "name": "芯片/半导体板块区",
                "coords": (0, 2100, self.width, min(3600, self.height)),
                "description": "芯片、半导体相关概念板块"
            })
        
        # 区域6: 液冷/散热板块区 (约3600-4500像素)
        if self.height > 4500:
            regions.append({
                "id": 6,
                "name": "液冷/散热板块区",
                "coords": (0, 3600, self.width, min(4600, self.height)),
                "description": "液冷、散热相关板块"
            })
        
        # 区域7: 交换机/服务器板块区 (约4600-6000像素)
        if self.height > 6000:
            regions.append({
                "id": 7,
                "name": "交换机/服务器板块区",
                "coords": (0, 4600, self.width, min(6100, self.height)),
                "description": "交换机、服务器相关板块"
            })
        
        # 区域8: PCB/电路板板块区 (约6100-7500像素)
        if self.height > 7500:
            regions.append({
                "id": 8,
                "name": "PCB/电路板板块区",
                "coords": (0, 6100, self.width, min(7600, self.height)),
                "description": "PCB、电路板相关板块"
            })
        
        # 区域9: 电源/能源板块区 (约7600-9000像素)
        if self.height > 9000:
            regions.append({
                "id": 9,
                "name": "电源/能源板块区",
                "coords": (0, 7600, self.width, min(9100, self.height)),
                "description": "电源、能源相关板块"
            })
        
        # 区域10: 数据中心/算力板块区 (约9100-10500像素)
        if self.height > 10500:
            regions.append({
                "id": 10,
                "name": "数据中心/算力板块区",
                "coords": (0, 9100, self.width, min(10600, self.height)),
                "description": "数据中心、算力相关板块"
            })
        
        # 区域11: 其他板块区 (剩余部分)
        if self.height > 10600:
            regions.append({
                "id": 11,
                "name": "其他板块区",
                "coords": (0, 10600, self.width, self.height),
                "description": "其他概念板块"
            })
        
        return regions
    
    def ocr_region(self, region):
        """对单个区域进行OCR识别"""
        x1, y1, x2, y2 = region["coords"]
        
        # 裁剪区域
        region_img = self.image.crop((x1, y1, x2, y2))
        
        # 保存临时文件用于OCR
        temp_path = f"/tmp/region_{region['id']}.png"
        region_img.save(temp_path)
        
        result_text = []
        
        if self.ocr:
            # 使用PaddleOCR
            try:
                ocr_result = self.ocr.predict(temp_path)
                if ocr_result:
                    for item in ocr_result:
                        if item and 'rec_texts' in item:
                            texts = item.get('rec_texts', [])
                            scores = item.get('rec_scores', [])
                            for i, text in enumerate(texts):
                                confidence = scores[i] if i < len(scores) else 0
                                result_text.append({
                                    "text": text,
                                    "confidence": float(confidence)
                                })
            except Exception as e:
                print(f"PaddleOCR error for region {region['id']}: {e}")
        
        # 清理临时文件
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return result_text
    
    def run(self, output_dir):
        """执行分区域OCR"""
        print(f"Processing image: {self.image_path}")
        print(f"Image size: {self.width}x{self.height}")
        print(f"Output directory: {output_dir}")
        
        # 检测区域
        regions = self.detect_regions()
        print(f"\nDetected {len(regions)} regions")
        
        # 对每个区域进行OCR
        results = []
        for region in regions:
            print(f"\nProcessing Region {region['id']}: {region['name']}")
            print(f"  Coords: {region['coords']}")
            
            ocr_texts = self.ocr_region(region)
            
            # 合并文本
            full_text = "\n".join([item["text"] for item in ocr_texts])
            
            result = {
                "region_id": region["id"],
                "region_name": region["name"],
                "coords": {
                    "x1": region["coords"][0],
                    "y1": region["coords"][1],
                    "x2": region["coords"][2],
                    "y2": region["coords"][3]
                },
                "description": region["description"],
                "ocr_text": full_text,
                "ocr_items": ocr_texts
            }
            results.append(result)
            
            print(f"  Found {len(ocr_texts)} text items")
            if ocr_texts:
                preview = full_text[:100].replace('\n', ' ')
                print(f"  Preview: {preview}...")
        
        # 生成输出文件
        json_path = os.path.join(output_dir, f"segmented_ocr_{self.timestamp}.json")
        md_path = os.path.join(output_dir, f"segmented_ocr_{self.timestamp}.md")
        
        # 保存JSON
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "image_path": self.image_path,
                "image_size": {"width": self.width, "height": self.height},
                "timestamp": self.timestamp,
                "region_count": len(results),
                "regions": results
            }, f, ensure_ascii=False, indent=2)
        
        # 生成Markdown
        self.generate_markdown(results, md_path)
        
        print(f"\n{'='*60}")
        print(f"OCR Complete!")
        print(f"JSON output: {json_path}")
        print(f"Markdown output: {md_path}")
        print(f"Total regions: {len(results)}")
        
        return json_path, md_path
    
    def generate_markdown(self, results, output_path):
        """生成Markdown报告"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# 开盘啦图片分区域OCR结果\n\n")
            f.write(f"**图片路径**: `{self.image_path}`\n\n")
            f.write(f"**图片尺寸**: {self.width} x {self.height} 像素\n\n")
            f.write(f"**识别时间**: {self.timestamp}\n\n")
            f.write(f"**区域数量**: {len(results)}\n\n")
            f.write("---\n\n")
            
            for result in results:
                f.write(f"## 区域 {result['region_id']}: {result['region_name']}\n\n")
                f.write(f"**坐标**: ({result['coords']['x1']}, {result['coords']['y1']}) - ")
                f.write(f"({result['coords']['x2']}, {result['coords']['y2']})\n\n")
                f.write(f"**描述**: {result['description']}\n\n")
                f.write(f"**识别文本数**: {len(result['ocr_items'])}\n\n")
                
                f.write("### OCR原文\n\n")
                f.write("```\n")
                f.write(result['ocr_text'] if result['ocr_text'] else "(无识别内容)")
                f.write("\n```\n\n")
                
                if result['ocr_items']:
                    f.write("### 详细识别项\n\n")
                    f.write("| 序号 | 文本 | 置信度 |\n")
                    f.write("|------|------|--------|\n")
                    for i, item in enumerate(result['ocr_items'][:20], 1):  # 只显示前20项
                        text = item['text'].replace('|', '\\|').replace('\n', ' ')
                        conf = f"{item['confidence']:.3f}"
                        f.write(f"| {i} | {text} | {conf} |\n")
                    
                    if len(result['ocr_items']) > 20:
                        f.write(f"\n*... 还有 {len(result['ocr_items']) - 20} 项未显示*\n")
                
                f.write("\n---\n\n")


def main():
    # 默认图片路径
    image_path = "<your-home>/.openclaw/media/inbound/Screenshot_2026-04-09-09-03-23-962_com.aiyu.kaipanla---89b9339e-87b7-4542-b506-99c340b10129.jpg"
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    
    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"Error: Image not found: {image_path}")
        sys.exit(1)
    
    # 输出目录
    output_dir = "os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")/thesis-ingest/output"
    os.makedirs(output_dir, exist_ok=True)
    
    # 执行OCR
    processor = SegmentOCR(image_path)
    json_path, md_path = processor.run(output_dir)
    
    print(f"\nOutput files:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == "__main__":
    main()
