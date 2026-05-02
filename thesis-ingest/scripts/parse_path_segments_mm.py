#!/usr/bin/env python3
"""
parse_path_segments_mm.py
多模态解析 segment 图片，提取题材路径和股票列表

输入:
  - path_segments_manifest_{timestamp}.json
  - segment_01.png ~ segment_09.png

输出:
  - output/path_segment_parse_{timestamp}.json
  - output/path_segment_parse_{timestamp}.md
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any


def get_openclaw_config() -> dict:
    """读取 OpenClaw 配置获取 API 设置"""
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def call_kimi_k25_image(image_path: str, prompt: str, config: dict) -> str:
    """
    调用 kimi-k2.5 模型分析图片
    使用 OpenAI SDK 调用 bailian API
    """
    try:
        from openai import OpenAI
        import base64
        
        # 读取图片并转为 base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # 检测图片格式
        ext = os.path.splitext(image_path)[1].lower()
        media_type = "image/png" if ext == ".png" else "image/jpeg"
        
        # 强制使用 API Key (sk-sp 开头的也是合法的，但要确保 baseUrl 正确)
        api_key = "YOUR_API_KEY"
        base_url = "https://coding.dashscope.aliyuncs.com/v1"
        
        # 构建系统提示词
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
        
        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
        response = client.chat.completions.create(
            model="qwen3.6-plus",
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
        
    except ImportError:
        print(f"警告: openai SDK 未安装，请运行: pip install openai", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"警告: 调用模型时出错: {e}", file=sys.stderr)
        return ""


def call_copilot_image(image_path: str, prompt: str) -> str:
    """
    调用 GitHub Copilot SDK (gpt-5-mini) 分析图片。
    使用 copilot Python SDK，通过 attachments 传入本地图片。
    """
    import asyncio
    from copilot import CopilotClient
    from copilot.types import PermissionRequestResult

    def approve_all(request, invocation):
        return PermissionRequestResult(kind="approved")

    async def _call():
        client = CopilotClient({'use_logged_in_user': True})
        await client.start()
        session = None
        try:
            session = await client.create_session({
                'on_permission_request': approve_all,
                'model': 'gpt-5-mini',
                'streaming': True,
            })
            done = asyncio.Event()
            response_parts = []

            def on_event(event):
                event_type = event.type.value
                data = event.data
                if hasattr(data, 'delta_content') and data.delta_content:
                    response_parts.append(data.delta_content)
                if event_type in ('session.idle', 'error'):
                    done.set()

            session.on(on_event)
            await session.send({
                'prompt': prompt,
                'attachments': [{'type': 'file', 'path': image_path}],
            })
            await done.wait()
            return ''.join(response_parts)
        finally:
            if session:
                await session.destroy()
            await client.stop()

    try:
        return asyncio.run(_call())
    except Exception as e:
        print(f"警告: Copilot 调用出错: {e}", file=sys.stderr)
        return ""


def extract_json_from_response(response: str) -> list:
    """从模型响应中提取 JSON 数据"""
    import re

    # 尝试直接解析整个响应
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    json_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    matches = re.findall(json_pattern, response)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 尝试提取方括号包裹的数组
    array_pattern = r'\[[\s\S]*\]'
    match = re.search(array_pattern, response)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 尝试提取花括号包裹的对象（可能是单个对象）
    obj_pattern = r'\{[\s\S]*\}'
    match = re.search(obj_pattern, response)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

    return []


def parse_segment_with_mm(segment: dict, segment_dir: Path, config: dict,
                          max_retries: int = 2, model_backend: str = "qwen",
                          root_name: str = None) -> list:
    """
    使用多模态模型解析单个 segment，失败后自动重试。
    max_retries 次全部失败则返回 None（调用方应终止流程）。
    model_backend: "qwen" (百炼 qwen3.6-plus) 或 "copilot" (GitHub Copilot gpt-5-mini)
    root_name: 根题材名，告知模型图片所属的根题材
    """
    segment_id = segment.get("segment_id", 0)
    proposed_name = segment.get("proposed_name", "")
    image_file = segment.get("image_path", f"segment_{segment_id:02d}.png")
    expected_topics = segment.get("expected_topics", [])
    expected_paths = segment.get("expected_path_examples", [])
    notes = segment.get("notes", "")

    image_path = segment_dir / image_file
    if not image_path.exists():
        print(f"警告: Segment {segment_id} 的图片不存在: {image_path}", file=sys.stderr)
        return None

    # 构建提示词，包含先验信息
    root_hint = f"\n本截图所属根题材: {root_name}\n" if root_name else ""

    prompt = f"""解析这张开盘啦题材截图（Segment {segment_id}: {proposed_name}）
{root_hint}
预期题材范围:
{chr(10).join(f"- {t}" for t in expected_topics)}

预期路径示例:
{chr(10).join(f"- {p}" for p in expected_paths)}

注意事项: {notes}

=== 关键规则 ===
1. 题材节点 vs 股票名称：图片中左侧是题材名称（如"硫化物"、"正极"、"涂覆设备"），右侧是股票名称（如"赣锋锂业"、"当升科技"）。题材名称进入 path_raw，股票名称进入 stock_text_raw。
2. 股票名称永远不要放入 path_raw 或 leaf_raw。path_raw 只包含题材层级。
3. 如果某行只有股票名称没有题材名，根据上方最近的题材名归属。
4. 路径深度：大部分题材 2-3 层（根题材 / 一级子题材 / 二级子题材）。不要把单个股票名当作一层题材。
5. 同一题材下的多只股票合并为一条记录，不要为每只股票单独建一条。
6. A股股票名称长度：2-4个字最常见，最多不超过5个字（含ST/*ST前缀）。超过5个字的几乎一定是题材名而非股票名。
7. path_raw 第一层应为根题材名（如"{root_name or '根题材'}"），与图片顶部的总标题对应。

=== 输出格式 ===
每个题材条目包含:
- path_raw: 完整层级路径（数组格式），只含题材名，如 ["{root_name or '根题材'}", "电池材料", "硫化物"]
- leaf_raw: 最后一层题材名，如 "硫化物"
- stock_text_raw: 该题材下所有股票名称，空格分隔，如 "赣锋锂业 天赐材料 天齐锂业"
- confidence: 识别置信度（高/中/低）
- notes: 简短说明

输出 JSON 数组格式。"""

    for attempt in range(max_retries + 1):
        if attempt > 0:
            print(f"  重试 {attempt}/{max_retries} segment {segment_id}: {proposed_name}...")
            time.sleep(2)  # 重试前等待
        else:
            print(f"  正在解析 segment {segment_id}: {proposed_name}...")

        if model_backend == "copilot":
            response = call_copilot_image(str(image_path), prompt)
        else:
            response = call_kimi_k25_image(str(image_path), prompt, config)

        if not response:
            print(f"  警告: Segment {segment_id} 第 {attempt + 1} 次调用无响应", file=sys.stderr)
            continue

        items = extract_json_from_response(response)
        if not items:
            print(f"  警告: Segment {segment_id} 第 {attempt + 1} 次调用未解析出 JSON", file=sys.stderr)
            continue

        # 标准化 items
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

    # 全部重试失败
    print(f"❌ Segment {segment_id} ({proposed_name}) 在 {max_retries + 1} 次尝试后仍然失败", file=sys.stderr)
    return None

    return normalized_items


def generate_markdown(parsed_segments: list, timestamp: str) -> str:
    """生成 Markdown 报告"""
    lines = [
        f"# Path Segment 解析报告\n",
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

        for item in items:
            local_idx = item.get("local_index", 0)
            path_raw = item.get("path_raw", [])
            leaf = item.get("leaf_raw", "")
            stocks = item.get("stock_text_raw", "")
            confidence = item.get("confidence", "中")
            notes = item.get("notes", "")

            path_str = " / ".join(path_raw) if path_raw else leaf

            lines.append(f"### {local_idx}. {path_str}\n\n")
            lines.append(f"- **叶子节点**: {leaf}\n")
            lines.append(f"- **股票**: {stocks}\n")
            lines.append(f"- **置信度**: {confidence}\n")
            if notes:
                lines.append(f"- **备注**: {notes}\n")
            lines.append("\n")

        lines.append("---\n\n")

    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="多模态解析 segment 图片，提取题材路径和股票列表"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to path_segments_manifest_*.json"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between API calls in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--model",
        default="qwen",
        choices=["qwen", "copilot"],
        help="图片识别模型后端: qwen (百炼 qwen3.6-plus) 或 copilot (GitHub Copilot gpt-5-mini)"
    )
    parser.add_argument(
        "--root-name",
        default=None,
        help="根题材名，告知模型图片所属的根题材"
    )
    parser.add_argument(
        "--fixed-name",
        action="store_true",
        help="使用固定文件名（无时间戳），由 orchestrator 控制输出目录"
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"错误: Manifest 文件不存在: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    # 读取 manifest
    print(f"读取 manifest: {manifest_path}")
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    # 获取配置
    config = get_openclaw_config()

    segments = manifest.get("segments", [])

    print(f"发现 {len(segments)} 个 segments")

    # 确定 segment 图片目录
    segment_dir = manifest_path.parent

    # 并发解析每个 segment
    parsed_segments = [None] * len(segments)
    max_workers = min(4, len(segments))  # 并发数，最多 4 路（避免限流）

    def _parse_one(i, segment):
        print(f"\n处理 segment {i+1}/{len(segments)}...")
        items = parse_segment_with_mm(segment, segment_dir, config,
                                       model_backend=args.model,
                                       root_name=args.root_name)
        return i, {
            "segment_id": segment.get("segment_id", i + 1),
            "proposed_name": segment.get("proposed_name", ""),
            "image_path": str(segment_dir / segment.get("image_path", f"segment_{i+1:02d}.png")),
            "items": items
        }

    failed_segments = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_parse_one, i, seg): i
            for i, seg in enumerate(segments)
        }
        for future in as_completed(futures):
            i, parsed_segment = future.result()
            if parsed_segment["items"] is None:
                failed_segments.append(parsed_segment["proposed_name"])
            else:
                parsed_segments[i] = parsed_segment
                print(f"  ✓ segment {i+1}/{len(segments)} 完成 ({len(parsed_segment['items'])} 条)")

    if failed_segments:
        print(f"\n❌ 以下 segment 解析失败，流程终止: {', '.join(failed_segments)}", file=sys.stderr)
        sys.exit(1)

    # 此处 parsed_segments 不应含 None（失败已提前终止）
    parsed_segments = [s for s in parsed_segments if s is not None]

    # 生成输出文件名
    output_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.fixed_name:
        json_output_path = output_dir / "segment_parse.json"
        md_output_path = output_dir / "segment_parse.md"
    else:
        json_output_path = output_dir / f"path_segment_parse_{output_timestamp}.json"
        md_output_path = output_dir / f"path_segment_parse_{output_timestamp}.md"

    # 构建输出 JSON
    output_data = {
        "manifest_path": str(manifest_path),
        "segment_count": len(parsed_segments),
        "timestamp": output_timestamp,
        "parsed_segments": parsed_segments
    }

    # 写入 JSON
    with open(json_output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 输出: {json_output_path}")

    # 写入 Markdown
    md_content = generate_markdown(parsed_segments, output_timestamp)
    with open(md_output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    print(f"Markdown 输出: {md_output_path}")

    # 生成运行记录（非 fixed-name 模式）
    if not args.fixed_name:
        run_record = {
            "run_timestamp": output_timestamp,
            "manifest_path": str(manifest_path),
            "segment_count": len(segments),
            "parsed_segment_count": len(parsed_segments),
            "output_json": str(json_output_path),
            "output_md": str(md_output_path),
            "status": "success"
        }

        run_record_path = output_dir / f"path_segment_parse_run_{output_timestamp}.json"
        with open(run_record_path, 'w', encoding='utf-8') as f:
            json.dump(run_record, f, ensure_ascii=False, indent=2)
        print(f"运行记录: {run_record_path}")

    # 打印摘要
    print("\n" + "="*60)
    print("解析完成摘要")
    print("="*60)
    print(f"Segment 总数: {len(parsed_segments)}")
    total_items = sum(len(s.get("items", [])) for s in parsed_segments)
    print(f"题材条目总数: {total_items}")
    print("\n路径示例:")
    example_count = 0
    for seg in parsed_segments:
        for item in seg.get("items", []):
            path_raw = item.get("path_raw", [])
            if path_raw:
                print(f"  {' / '.join(path_raw)}")
                example_count += 1
                if example_count >= 5:
                    break
        if example_count >= 5:
            break
    print("="*60)


if __name__ == "__main__":
    main()