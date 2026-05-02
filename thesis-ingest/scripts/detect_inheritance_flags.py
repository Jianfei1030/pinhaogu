#!/usr/bin/env python3
"""
T2.5b2b: Major/Sub 继承标记检测
基于视觉特征（背景连续性、像素密度）判断每行是否继承上一行的 major/sub 值
"""

import json
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any


def compute_region_features(image: np.ndarray, bbox: List[int]) -> Dict[str, float]:
    """
    计算区域视觉特征
    bbox: [x1, y1, x2, y2]
    """
    x1, y1, x2, y2 = bbox
    h, w = image.shape[:2]
    
    # 边界检查
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    
    if x2 <= x1 or y2 <= y1:
        return {"mean": 0, "std": 0, "dark_ratio": 0, "edge_density": 0}
    
    region = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if len(region.shape) == 3 else region
    
    # 基础统计
    mean_val = float(np.mean(gray))
    std_val = float(np.std(gray))
    
    # 深色像素比例（假设文本是深色）
    dark_threshold = 80
    dark_ratio = float(np.sum(gray < dark_threshold) / gray.size)
    
    # 边缘密度（文本区域通常有更多边缘）
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.sum(edges > 0) / edges.size)
    
    return {
        "mean": mean_val,
        "std": std_val,
        "dark_ratio": dark_ratio,
        "edge_density": edge_density
    }


def compute_region_similarity(feat1: Dict, feat2: Dict) -> float:
    """计算两个区域特征的相似度"""
    # 使用均值和方差的差异
    mean_diff = abs(feat1["mean"] - feat2["mean"])
    std_diff = abs(feat1["std"] - feat2["std"])
    
    # 归一化差异（假设像素值范围 0-255）
    mean_sim = max(0, 1 - mean_diff / 100)
    std_sim = max(0, 1 - std_diff / 50)
    
    return (mean_sim + std_sim) / 2


def is_likely_empty(feat: Dict[str, float]) -> bool:
    """判断区域是否可能是空的（继承情况）"""
    # 空区域特征：低深色比例、低边缘密度、高均值（亮背景）
    return feat["dark_ratio"] < 0.05 and feat["edge_density"] < 0.02


def detect_inheritance(
    image: np.ndarray,
    cell_bbox: Dict[str, Any],
    prev_cell_bbox: Dict[str, Any],
    column: str  # "major" or "sub"
) -> Tuple[bool, float, str]:
    """
    检测当前行是否继承上一行的指定列
    返回: (is_inherited, confidence, reason)
    """
    curr_bbox = cell_bbox[f"{column}_cell_bbox"]
    prev_bbox = prev_cell_bbox[f"{column}_cell_bbox"]
    
    # 计算当前区域和上一行区域的特征
    curr_feat = compute_region_features(image, curr_bbox)
    prev_feat = compute_region_features(image, prev_bbox)
    
    # 策略1: 如果当前区域明显为空（无文本），则可能是继承
    if is_likely_empty(curr_feat):
        # 进一步检查：如果上一行有内容，则更可能是继承
        if not is_likely_empty(prev_feat):
            return True, 0.85, "empty_cell_with_prev_content"
        else:
            return True, 0.6, "both_empty"
    
    # 策略2: 计算与上一行同列区域的相似度
    similarity = compute_region_similarity(curr_feat, prev_feat)
    
    # 策略3: 检查背景连续性（均值接近表示背景连续）
    background_continuous = abs(curr_feat["mean"] - prev_feat["mean"]) < 15
    
    # 策略4: 如果当前区域有内容但与上一行非常相似，也可能是继承（相同分类）
    if similarity > 0.85 and background_continuous:
        return True, min(0.9, similarity), f"high_similarity_{similarity:.2f}"
    
    # 策略5: 如果当前区域有明显文本内容且与上一行差异大，则不是继承
    if curr_feat["dark_ratio"] > 0.1 and curr_feat["edge_density"] > 0.03:
        if not background_continuous or similarity < 0.6:
            return False, 0.8, "distinct_content"
    
    # 默认情况：基于相似度判断
    is_inherited = similarity > 0.7
    confidence = similarity if is_inherited else (1 - similarity)
    
    return is_inherited, confidence, f"similarity_based_{similarity:.2f}"


def process_inheritance_detection(
    image_path: str,
    cell_bbox_json: str,
    row_json: str,
    output_dir: str
) -> Dict[str, Any]:
    """主处理函数"""
    
    # 加载图像
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"无法加载图像: {image_path}")
    
    # 加载 cell bbox 数据
    with open(cell_bbox_json, 'r', encoding='utf-8') as f:
        cell_data = json.load(f)
    
    # 加载 row 数据（用于验证）
    with open(row_json, 'r', encoding='utf-8') as f:
        row_data = json.load(f)
    
    rows = cell_data["rows"]
    row_count = len(rows)
    
    # 处理每一行
    results = []
    major_inherit_count = 0
    sub_inherit_count = 0
    
    for i, row in enumerate(rows):
        row_result = {
            "row_index": row["row_index"],
            "row_bbox": row["row_bbox"],
            "major_cell_bbox": row["major_cell_bbox"],
            "sub_cell_bbox": row["sub_cell_bbox"],
            "stock_cell_bbox": row["stock_cell_bbox"],
            "major_inherit_from_prev": False,
            "sub_inherit_from_prev": False,
            "confidence_major": 0.0,
            "confidence_sub": 0.0,
            "notes": ""
        }
        
        if i == 0:
            # 第一行默认不继承
            row_result["notes"] = "first_row_no_inherit"
        else:
            prev_row = rows[i - 1]
            
            # 检测 major 继承
            major_inherit, major_conf, major_reason = detect_inheritance(
                image, row, prev_row, "major"
            )
            row_result["major_inherit_from_prev"] = major_inherit
            row_result["confidence_major"] = round(major_conf, 3)
            
            # 检测 sub 继承
            sub_inherit, sub_conf, sub_reason = detect_inheritance(
                image, row, prev_row, "sub"
            )
            row_result["sub_inherit_from_prev"] = sub_inherit
            row_result["confidence_sub"] = round(sub_conf, 3)
            
            # 统计
            if major_inherit:
                major_inherit_count += 1
            if sub_inherit:
                sub_inherit_count += 1
            
            row_result["notes"] = f"major:{major_reason},sub:{sub_reason}"
        
        results.append(row_result)
    
    # 构建输出
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        "image_path": image_path,
        "table_roi": cell_data["table_roi"],
        "source_row_json": row_json,
        "source_cell_bbox_json": cell_bbox_json,
        "row_count": row_count,
        "rows": results,
        "stats": {
            "major_inherit_count": major_inherit_count,
            "sub_inherit_count": sub_inherit_count,
            "major_inherit_ratio": round(major_inherit_count / max(1, row_count - 1), 3),
            "sub_inherit_ratio": round(sub_inherit_count / max(1, row_count - 1), 3)
        },
        "generated_at": datetime.now().isoformat()
    }
    
    # 保存 JSON
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    json_file = output_path / f"inheritance_flags_{timestamp}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # 生成 Markdown
    md_file = output_path / f"inheritance_flags_{timestamp}.md"
    generate_markdown(output, md_file)
    
    # 生成 Debug 图
    debug_file = output_path / f"inheritance_flags_{timestamp}_debug.png"
    generate_debug_image(image, output, debug_file)
    
    return output


def generate_markdown(data: Dict, output_file: Path):
    """生成 Markdown 报告"""
    lines = [
        "# T2.5b2b: Major/Sub 继承标记检测报告",
        "",
        f"**生成时间**: {data['generated_at']}",
        "",
        "## 输入文件",
        f"- 原图: `{data['image_path']}`",
        f"- Row JSON: `{data['source_row_json']}`",
        f"- Cell BBox JSON: `{data['source_cell_bbox_json']}`",
        "",
        "## 统计信息",
        f"- **总行数**: {data['row_count']}",
        f"- **Major 继承行数**: {data['stats']['major_inherit_count']} ({data['stats']['major_inherit_ratio']*100:.1f}%)",
        f"- **Sub 继承行数**: {data['stats']['sub_inherit_count']} ({data['stats']['sub_inherit_ratio']*100:.1f}%)",
        "",
        "## 逐行继承标记",
        "",
        "| 行号 | Major继承 | Sub继承 | 置信度(Major) | 置信度(Sub) | 备注 |",
        "|------|-----------|---------|---------------|-------------|------|"
    ]
    
    # 逐行数据
    low_confidence_rows = []
    for row in data['rows']:
        major_str = "✓" if row['major_inherit_from_prev'] else "✗"
        sub_str = "✓" if row['sub_inherit_from_prev'] else "✗"
        lines.append(
            f"| {row['row_index']} | {major_str} | {sub_str} | "
            f"{row['confidence_major']:.2f} | {row['confidence_sub']:.2f} | {row.get('notes', '')} |"
        )
        
        # 收集低置信度行
        if row['confidence_major'] < 0.7 or row['confidence_sub'] < 0.7:
            low_confidence_rows.append(row)
    
    # 低置信度行汇总
    if low_confidence_rows:
        lines.extend([
            "",
            "## 低置信度/异常行",
            "",
            "| 行号 | Major继承 | Sub继承 | 置信度(Major) | 置信度(Sub) | 备注 |",
            "|------|-----------|---------|---------------|-------------|------|"
        ])
        for row in low_confidence_rows:
            major_str = "✓" if row['major_inherit_from_prev'] else "✗"
            sub_str = "✓" if row['sub_inherit_from_prev'] else "✗"
            lines.append(
                f"| {row['row_index']} | {major_str} | {sub_str} | "
                f"{row['confidence_major']:.2f} | {row['confidence_sub']:.2f} | {row.get('notes', '')} |"
            )
    
    lines.extend([
        "",
        "---",
        "*报告由 T2.5b2b 继承标记检测脚本生成*"
    ])
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def generate_debug_image(image: np.ndarray, data: Dict, output_file: Path):
    """生成 Debug 可视化图像"""
    debug_img = image.copy()
    
    table_roi = data['table_roi']
    roi_x1, roi_y1, roi_x2, roi_y2 = table_roi
    
    # 绘制 ROI 大框
    cv2.rectangle(debug_img, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 255, 0), 3)
    
    # 列边界
    major_x = 238
    sub_x = 618
    cv2.line(debug_img, (major_x, roi_y1), (major_x, roi_y2), (255, 0, 0), 2)
    cv2.line(debug_img, (sub_x, roi_y1), (sub_x, roi_y2), (255, 0, 0), 2)
    
    # 绘制每一行
    for row in data['rows']:
        row_idx = row['row_index']
        row_bbox = row['row_bbox']
        major_bbox = row['major_cell_bbox']
        sub_bbox = row['sub_cell_bbox']
        stock_bbox = row['stock_cell_bbox']
        
        # 行框（浅灰色）
        cv2.rectangle(debug_img, 
                      (row_bbox[0], row_bbox[1]), 
                      (row_bbox[2], row_bbox[3]), 
                      (200, 200, 200), 1)
        
        # Major 继承标记（蓝色填充）
        if row['major_inherit_from_prev']:
            cv2.rectangle(debug_img,
                          (major_bbox[0], major_bbox[1]),
                          (major_bbox[2], major_bbox[3]),
                          (255, 100, 100), 2)
        else:
            cv2.rectangle(debug_img,
                          (major_bbox[0], major_bbox[1]),
                          (major_bbox[2], major_bbox[3]),
                          (100, 100, 255), 1)
        
        # Sub 继承标记（绿色填充）
        if row['sub_inherit_from_prev']:
            cv2.rectangle(debug_img,
                          (sub_bbox[0], sub_bbox[1]),
                          (sub_bbox[2], sub_bbox[3]),
                          (100, 255, 100), 2)
        else:
            cv2.rectangle(debug_img,
                          (sub_bbox[0], sub_bbox[1]),
                          (sub_bbox[2], sub_bbox[3]),
                          (100, 100, 255), 1)
        
        # Stock 列（紫色，细线）
        cv2.rectangle(debug_img,
                      (stock_bbox[0], stock_bbox[1]),
                      (stock_bbox[2], stock_bbox[3]),
                      (255, 0, 255), 1)
        
        # 稀疏标注行号（每10行）
        if row_idx % 10 == 0:
            cv2.putText(debug_img, str(row_idx),
                        (5, row_bbox[1] + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    # 图例
    legend_y = roi_y1 + 30
    cv2.putText(debug_img, "Red thick=Major inherit", (roi_x2 + 10, legend_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 100), 1)
    cv2.putText(debug_img, "Green thick=Sub inherit", (roi_x2 + 10, legend_y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 100), 1)
    cv2.putText(debug_img, "Blue thin=New content", (roi_x2 + 10, legend_y + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 255), 1)
    
    cv2.imwrite(str(output_file), debug_img)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="T2.5b2b: Major/Sub 继承标记检测")
    parser.add_argument("--image", required=True, help="输入图像路径")
    parser.add_argument("--cell-bbox", required=True, help="Cell bbox JSON 路径")
    parser.add_argument("--row-json", required=True, help="Row boundaries JSON 路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    
    args = parser.parse_args()
    
    result = process_inheritance_detection(
        args.image,
        args.cell_bbox,
        args.row_json,
        args.output_dir
    )
    
    print(f"处理完成: {result['row_count']} 行")
    print(f"Major 继承: {result['stats']['major_inherit_count']} 行")
    print(f"Sub 继承: {result['stats']['sub_inherit_count']} 行")