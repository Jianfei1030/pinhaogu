#!/usr/bin/env python3
"""
parse_path_segments_mm_gemini.py
使用 Gemini 3 Flash (via GitHub Copilot) 解析 segment 图片
"""

import argparse
import json
import os
import sys
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import Any
from openai import OpenAI

def call_gemini_image(image_path: str, prompt: str) -> str:
    """调用 Gemini 3 Flash 模型分析图片"""
    try:
        # 从环境变量获取 Token
        api_key = os.environ.get("GITHUB_COPILOT_TOKEN")
        if not api_key:
            print(f"警告: 未找到 GITHUB_COPILOT_TOKEN", file=sys.stderr)
            return ""
        
        # 读取图片并转为 base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # 检测图片格式
        ext = os.path.splitext(image_path)[1].lower()
        media_type = "image/png" if ext == ".png" else "image/jpeg"
        
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.githubcopilot.com"
        )
        
        system_prompt = """你是一个专业的金融题材解析助手。你的任务是从开盘啦 APP 的题材截图中提取层级化的题材路径和对应的股票列表。

输出格式要求：
1. 每个题材条目必须包含：
   - path_raw: 层级路径数组，如 ["商业航天", "月球开发概念", "技术与研发"]
   - leaf_raw: 叶子节点名称
   - stock_text_raw: 空格分隔的股票名称列表
   - confidence: 高/中/低
   - notes: 简短说明

2. 保持图片中原始的层级父子关系，根题材以图片中实际显示为准
3. 股票名称用空格分隔，保持原文中的名称
4. 如果某行只有股票没有明确题材，根据上下文推断

请严格按照 JSON 数组格式输出，每个元素是一个题材条目。"""

        full_prompt = f"{system_prompt}\n\n{prompt}\n\n请解析图片中的题材层级和股票列表，以 JSON 格式输出。"
        
        response = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}"
                        }
                    }
                ]
            }],
            max_tokens=4000,
            temperature=0.1
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"警告: 调用模型时出错: {e}", file=sys.stderr)
        return ""

def extract_json_from_response(response: str) -> list:
    """从模型响应中提取 JSON 数据"""
    import re
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass
    json_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    matches = re.findall(json_pattern, response)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue
    array_pattern = r'\[[\s\S]*\]'
    match = re.search(array_pattern, response)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []

def parse_segment_with_mm(segment: dict, segment_dir: Path) -> list:
    """使用多模态模型解析单个 segment"""
    segment_id = segment.get("segment_id", 0)
    proposed_name = segment.get("proposed_name", "")
    image_file = segment.get("image_path", f"segment_{segment_id:02d}.png")
    expected_topics = segment.get("expected_topics", [])
    expected_paths = segment.get("expected_path_examples", [])
    notes = segment.get("notes", "")

    image_path = segment_dir / image_file
    if not image_path.exists():
        print(f"警告: Segment {segment_id} 的图片不存在: {image_path}", file=sys.stderr)
        return []

    prompt = f"""解析这张开盘啦题材截图（Segment {segment_id}: {proposed_name}）

预期题材范围:
{chr(10).join(f"- {t}" for t in expected_topics)}

预期路径示例:
{chr(10).join(f"- {p}" for p in expected_paths)}

注意事项: {notes}

请提取所有可见的题材条目，每个条目包含:
1. path_raw: 完整层级路径（数组格式）
2. leaf_raw: 当前节点名称
3. stock_text_raw: 关联的股票名称（空格分隔）
4. confidence: 识别置信度（高/中/低）
5. notes: 识别到的题材在图中的特征

输出 JSON 数组格式。"""

    print(f"  正在解析 segment {segment_id}: {proposed_name}...")
    response = call_gemini_image(str(image_path), prompt)
    if not response:
        return []
    items = extract_json_from_response(response)
    normalized_items = []
    for idx, item in enumerate(items, 1):
        normalized = {
            "local_index": idx,
            "path_raw": item.get("path_raw", []),
            "leaf_raw": item.get("leaf_raw", ""),
            "stock_text_raw": item.get("stock_text_raw", ""),
            "confidence": item.get("confidence", "中"),
            "notes": item.get("notes", "")
        }
        normalized_items.append(normalized)
    return normalized_items

def generate_markdown(parsed_segments: list, timestamp: str) -> str:
    """生成 Markdown 报告"""
    lines = [
        f"# Gemini 3 Flash 解析报告 (商业航天)\n",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"**Timestamp**: {timestamp}\n",
        f"**Segment 数量**: {len(parsed_segments)}\n\n",
        "---\n\n"
    ]
    for seg in parsed_segments:
        seg_id = seg.get("segment_id", 0)
        proposed_name = seg.get("proposed_name", "")
        items = seg.get("items", [])
        lines.append(f"## Segment {seg_id}: {proposed_name}\n\n")
        if not items:
            lines.append("*(未识别到题材)*\n\n")
            continue
        for item in items:
            path_str = " / ".join(item.get("path_raw", [])) or item.get("leaf_raw", "")
            lines.append(f"### {item.get('local_index')}. {path_str}\n\n")
            lines.append(f"- **股票**: {item.get('stock_text_raw')}\n")
            lines.append(f"- **备注**: {item.get('notes')}\n\n")
        lines.append("---\n\n")
    return "".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Gemini 3 Flash 解析 segment 图片")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    segments = manifest.get("segments", [])
    segment_dir = manifest_path.parent
    
    parsed_segments = []
    for i, segment in enumerate(segments):
        items = parse_segment_with_mm(segment, segment_dir)
        parsed_segments.append({
            "segment_id": segment.get("segment_id", i + 1),
            "proposed_name": segment.get("proposed_name", ""),
            "items": items
        })
        time.sleep(1)

    output_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = output_dir / f"path_segment_parse_gemini_{output_timestamp}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_segments, f, ensure_ascii=False, indent=2)
    
    md_content = generate_markdown(parsed_segments, output_timestamp)
    with open(output_dir / f"path_segment_parse_gemini_{output_timestamp}.md", 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    print(f"\n解析完成。JSON: {json_path}")
    
    print("\n[一级题材列表]")
    first_level = set()
    for seg in parsed_segments:
        for item in seg.get("items", []):
            path = item.get("path_raw", [])
            if path:
                first_level.add(path[0])
    for topic in sorted(list(first_level)):
        print(f"- {topic}")

if __name__ == "__main__":
    main()