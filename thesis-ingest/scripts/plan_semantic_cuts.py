#!/usr/bin/env python3
"""
plan_semantic_cuts.py - T2.5path0 语义切割规划脚本（多模态优先版）

核心策略：
- 默认使用多模态模型（qwen3.6-plus）直接识别图片中的一级子题材及其 y 坐标范围
- 增强版 prompt 描述开盘啦 UI 视觉特征，引导模型精确输出坐标
- 后置 validate_cut_plan() 校验修复：去重、钳位、padding、解决重叠、合并过短段
- OCR (Tesseract) 作为 fallback，在多模态 API 不可用时保证脚本可用

Usage:
    python plan_semantic_cuts.py --image /path/to/img.jpg
    python plan_semantic_cuts.py --output-dir ./output
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


def detect_full_width_red_lines(
    image_path: str,
    width_ratio: float = 0.85,
    min_band_height: int = 2,
    max_band_height: int = 40,
    top_skip_ratio: float = 0.10,
    bottom_skip_px: int = 50,
) -> List[int]:
    """
    检测全宽红色水平线的 y 坐标，作为一级子题材之间的分界线。

    开盘啦 APP 的表格中，每个一级子题材之间有横跨整个图片宽度的红色分隔线。
    通过检测这些红线，可以精确定位切割边界。
    排除顶部 APP 标题栏和底部评论区的红色 UI 元素。

    返回: 分界线 y 坐标列表（每条线取 band 中点），按升序排列
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("警告: opencv-python 未安装，无法使用红色水平线检测", file=sys.stderr)
        return []

    img = cv2.imread(image_path)
    if img is None:
        print(f"警告: 无法读取图片: {image_path}", file=sys.stderr)
        return []

    h, w = img.shape[:2]

    # BGR -> 红色通道检测
    b, g, r = cv2.split(img)
    red_mask = (r.astype(int) > 150) & (g.astype(int) < 80) & (b.astype(int) < 80)
    red_mask = red_mask.astype(np.uint8)

    # 水平投影：每行的红色像素数
    projection = red_mask.sum(axis=1)

    # 全宽红线阈值：红色像素数 > 宽度的 width_ratio
    threshold = int(w * width_ratio)

    # 找到超过阈值的行
    border_rows = np.where(projection >= threshold)[0]
    if len(border_rows) == 0:
        return []

    # 合并连续行为 band
    gaps = np.diff(border_rows)
    band_starts = [int(border_rows[0])]
    band_ends = []
    for i, gap in enumerate(gaps):
        if gap > 3:
            band_ends.append(int(border_rows[i]))
            band_starts.append(int(border_rows[i + 1]))
    band_ends.append(int(border_rows[-1]))

    # 过滤：
    # 1. 只保留合理高度的 band（排除顶部标题栏的大块红色区域）
    # 2. 跳过图片顶部 top_skip_ratio 区域（根题材标题栏）
    # 3. 跳过图片底部 bottom_skip_px 像素（Home indicator 等 UI 元素）
    top_skip = int(h * top_skip_ratio)
    bottom_skip = h - bottom_skip_px
    line_positions: List[int] = []
    for s, e in zip(band_starts, band_ends):
        band_h = e - s + 1
        mid = (s + e) // 2
        if min_band_height <= band_h <= max_band_height and mid > top_skip and mid < bottom_skip:
            line_positions.append(mid)

    return line_positions


def build_segments_from_borders(
    red_lines: List[int],
    topic_names: List[str],
    image_width: int,
    image_height: int,
    root_topic: str,
) -> List[Dict[str, Any]]:
    """
    根据红色分界线和多模态模型给出的子题材名称，构建切割方案。

    red_lines: 全宽红色水平线的 y 坐标列表（升序）
    topic_names: 多模态模型给出的一级子题材名称列表（从上到下）

    策略：
    - 红色分界线作为 segment 之间的边界
    - 第一个 segment 从 y=0 开始，到最后一条红线结束
    - 最后一个 segment 从最后一条红线到图片底部
    - 如果红线数量 != 名称数量，取前 min(n_lines-1, n_names) 个名称匹配
    """
    segments: List[Dict[str, Any]] = []

    # 红色分界线定义了 segment 的边界
    # 第一个 segment: y=0 到第一条红线
    # 中间 segments: 红线[i] 到 红线[i+1]
    # 最后一个 segment: 最后一条红线 到 图片底部

    # 构建边界点列表：[0, line1, line2, ..., lineN, image_height]
    boundaries = [0] + red_lines + [image_height]

    # segment 数量 = 边界数量 - 1
    n_segments = len(boundaries) - 1
    n_names = len(topic_names)

    for i in range(n_segments):
        y_start = boundaries[i]
        y_end = boundaries[i + 1]

        # 分配名称
        if i < n_names:
            name = topic_names[i]
        else:
            name = f"未命名_{i+1}"

        segments.append({
            "segment_id": i + 1,
            "proposed_name": name,
            "crop_bbox": [0, y_start, image_width, y_end],
            "expected_topics": [name],
            "expected_path_examples": [f"{root_topic} / {name} / 示例细分"],
            "notes": "红色分界线定位: y={}--{}".format(y_start, y_end),
        })

    return segments


def get_openclaw_config() -> dict:
    """读取 OpenClaw 配置获取 API 设置"""
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def call_kimi_k25_image(image_path: str, prompt: str, config: dict) -> str:
    """
    调用 qwen3.6-plus 模型分析图片（OCR 不可用时 fallback）
    使用 OpenAI SDK 调用 bailian API
    """
    try:
        from openai import OpenAI
        import base64

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(image_path)[1].lower()
        media_type = "image/png" if ext == ".png" else "image/jpeg"

        bailian_config = config.get("models", {}).get("providers", {}).get("bailian", {})
        api_key = bailian_config.get("apiKey", "")
        base_url = bailian_config.get("baseUrl", "https://coding.dashscope.aliyuncs.com/v1")

        if not api_key:
            api_key = os.environ.get("BAILIAN_API_KEY", "")

        if not api_key:
            print("警告: 未找到 BAILIAN_API_KEY", file=sys.stderr)
            return ""

        client = OpenAI(api_key=api_key, base_url=base_url)

        response = client.chat.completions.create(
            model="qwen3.6-plus",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                        },
                    ],
                }
            ],
            max_tokens=4000,
            temperature=0.1,
        )

        return response.choices[0].message.content

    except ImportError:
        print("错误: openai SDK 未安装，请运行: pip install openai", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"警告: 调用模型时出错: {e}", file=sys.stderr)
        return ""


def extract_json_from_response(response: str) -> dict:
    """从模型响应中提取 JSON 数据"""
    import re

    response = response.strip()

    json_pattern = r"```(?:json)?\s*([\s\S]*?)```"
    matches = re.findall(json_pattern, response)
    if matches:
        content = matches[0].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            last_brace = content.rfind("}")
            if last_brace != -1:
                try:
                    potential_json = content[: last_brace + 1]
                    if '"segments": [' in potential_json and potential_json.count("[") > potential_json.count("]"):
                        potential_json += "]}"
                    elif potential_json.count("{") > potential_json.count("}"):
                        potential_json += "}"
                    return json.loads(potential_json)
                except json.JSONDecodeError:
                    pass

    obj_pattern = r"\{[\s\S]*\}"
    match = re.search(obj_pattern, response)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            content = match.group()
            last_brace = content.rfind("}")
            if last_brace != -1:
                try:
                    return json.loads(content[: last_brace + 1])
                except json.JSONDecodeError:
                    pass

    return {}


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = text.replace("|", "")
    return text.strip()


def _is_text_noise(text: str) -> bool:
    if not text:
        return True
    s = _normalize_text(text)
    if not s:
        return True
    if len(s) <= 1 and not re.search(r"[\u4e00-\u9fffA-Za-z]", s):
        return True
    if re.fullmatch(r"[\d\W_]+", s):
        return True
    return False


def _combine_words(words: List[str]) -> str:
    cleaned = [w.strip() for w in words if w and w.strip()]
    if not cleaned:
        return ""

    text = ""
    for word in cleaned:
        if not text:
            text = word
            continue
        prev = text[-1]
        if re.search(r"[\u4e00-\u9fff]$", prev) or re.search(r"^[\u4e00-\u9fff]", word):
            text += word
        else:
            text += " " + word
    return text.strip()


def _box_center(bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _bbox_width(bbox: Tuple[int, int, int, int]) -> int:
    return max(0, bbox[2] - bbox[0])


def _bbox_height(bbox: Tuple[int, int, int, int]) -> int:
    return max(0, bbox[3] - bbox[1])


def _estimate_mean_rgb(image, bbox: Tuple[int, int, int, int]) -> Tuple[float, float, float]:
    try:
        from PIL import ImageStat

        x0, y0, x1, y1 = bbox
        crop = image.crop((max(0, x0), max(0, y0), min(image.width, x1), min(image.height, y1)))
        if crop.width <= 0 or crop.height <= 0:
            return (0.0, 0.0, 0.0)
        stat = ImageStat.Stat(crop)
        if len(stat.mean) >= 3:
            return float(stat.mean[0]), float(stat.mean[1]), float(stat.mean[2])
    except Exception:
        pass
    return (0.0, 0.0, 0.0)


def _is_redish(mean_rgb: Tuple[float, float, float]) -> bool:
    r, g, b = mean_rgb
    return r >= 110 and (r - max(g, b)) >= 25


def _line_score(item: Dict[str, Any], image_width: int, image_height: int, median_height: float) -> float:
    x0, y0, x1, y1 = item["bbox"]
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    cx, cy = _box_center(item["bbox"])
    mean_rgb = item.get("mean_rgb", (0.0, 0.0, 0.0))
    red_score = 1.0 if _is_redish(mean_rgb) else 0.0
    left_score = 1.0 - min(1.0, x0 / max(1.0, image_width * 0.65))
    size_score = min(1.0, height / max(1.0, median_height * 1.4))
    top_score = 1.0 - min(1.0, cy / max(1.0, image_height * 0.7))
    text = item.get("text", "")
    text_len = len(_normalize_text(text))
    text_score = 1.0 if 2 <= text_len <= 12 else 0.3 if text_len <= 18 else 0.0
    width_score = 1.0 - min(1.0, width / max(1.0, image_width * 0.9))
    return (
        0.40 * red_score
        + 0.20 * left_score
        + 0.15 * size_score
        + 0.10 * top_score
        + 0.10 * text_score
        + 0.05 * width_score
    )


def _preprocess_for_ocr(image: "Image.Image") -> "Image.Image":
    """
    对暗色背景截图做预处理，提升 Tesseract OCR 识别率。

    步骤：灰度 → 反转（暗底亮字 → 亮底暗字）→ 二值化
    这对开盘啦这类暗色背景 APP 截图效果显著。
    """
    from PIL import ImageOps

    gray = image.convert("L")
    inverted = ImageOps.invert(gray)
    binary = inverted.point(lambda x: 255 if x > 120 else 0)
    return binary


def ocr_image(image_path: str) -> List[Dict[str, Any]]:
    """对图片执行 OCR，返回按行聚合后的文字与 bbox 结果。"""
    try:
        from PIL import Image
        import pytesseract
        from pytesseract import Output
    except Exception as e:
        raise RuntimeError(f"OCR 依赖不可用: {e}")

    image = Image.open(image_path).convert("RGB")
    # 预处理：暗色背景反转 + 二值化
    processed = _preprocess_for_ocr(image)
    data = pytesseract.image_to_data(
        processed,
        output_type=Output.DICT,
        lang="chi_sim+eng",
        config="--oem 3 --psm 6",
    )

    lines: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = defaultdict(list)
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        conf_raw = data.get("conf", ["-1"] * n)[i]
        try:
            conf = float(conf_raw)
        except Exception:
            conf = -1.0
        if conf < 20 or _is_text_noise(text):
            continue
        left = int(data["left"][i])
        top = int(data["top"][i])
        width = int(data["width"][i])
        height = int(data["height"][i])
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines[key].append(
            {
                "text": text,
                "bbox": (left, top, left + width, top + height),
                "conf": conf,
            }
        )

    results: List[Dict[str, Any]] = []
    for key, words in lines.items():
        words.sort(key=lambda item: item["bbox"][0])
        text = _combine_words([w["text"] for w in words])
        if _is_text_noise(text):
            continue

        x0 = min(w["bbox"][0] for w in words)
        y0 = min(w["bbox"][1] for w in words)
        x1 = max(w["bbox"][2] for w in words)
        y1 = max(w["bbox"][3] for w in words)
        bbox = (x0, y0, x1, y1)
        mean_rgb = _estimate_mean_rgb(image, bbox)
        results.append(
            {
                "text": text.strip(),
                "bbox": bbox,
                "conf": sum(w["conf"] for w in words) / max(1, len(words)),
                "mean_rgb": mean_rgb,
                "line_key": key,
            }
        )

    results.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return results


def ocr_left_column_titles(
    image_path: str,
    left_ratio: float = 0.25,
    min_height: int = 40,
    conf_threshold: float = 50.0,
    merge_gap: int = 100,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    用预处理后的 OCR 从左侧列提取一级子题材标题。

    策略：
    1. 裁剪左侧区域（left_ratio 宽度）
    2. 灰度反转 + 二值化预处理
    3. Tesseract OCR 识别
    4. 按行聚合，合并 y 坐标接近的相邻行（解决同一标题被拆成多行的问题）
    5. 过滤低置信度和小字号行
    6. 第一行高置信度大字作为根题材，其余作为一级子题材

    返回: (root_topic, [{"name": str, "y": int, "conf": float}, ...])
    """
    try:
        from PIL import Image, ImageOps
        import pytesseract
        from pytesseract import Output
    except Exception:
        return "", []

    image = Image.open(image_path).convert("RGB")
    w, h = image.size

    # 裁剪左侧区域
    left_crop = image.crop((0, 0, int(w * left_ratio), h))

    # 预处理
    processed = _preprocess_for_ocr(left_crop)

    # OCR
    data = pytesseract.image_to_data(
        processed,
        output_type=Output.DICT,
        lang="chi_sim+eng",
        config="--oem 3 --psm 6",
    )

    # 按行聚合
    n = len(data.get("text", []))
    lines: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
    for i in range(n):
        text = (data["text"][i] or "").strip()
        conf_raw = data.get("conf", ["-1"] * n)[i]
        try:
            conf = float(conf_raw)
        except Exception:
            conf = -1.0
        if conf < 0 or not text or _is_text_noise(text):
            continue

        top = int(data["top"][i])
        height = int(data["height"][i])
        left = int(data["left"][i])
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        if key not in lines:
            lines[key] = {"words": [], "top": top, "height": height, "confs": [], "left": left}
        lines[key]["words"].append(text)
        lines[key]["confs"].append(conf)
        lines[key]["top"] = min(lines[key]["top"], top)
        lines[key]["height"] = max(lines[key]["height"], height)

    # 初筛：只保留字号足够大的行
    raw_candidates: List[Dict[str, Any]] = []
    for line in lines.values():
        if line["height"] < min_height:
            continue
        name = _combine_words(line["words"])
        if _is_text_noise(name):
            continue
        # 清理 OCR 噪声：去掉尾部的 "-"、"_"、"|" 等符号
        name = re.sub(r'[\s\-_·|©]+$', '', name).strip()
        name = re.sub(r'^[\s\-_·|©]+', '', name).strip()
        if not name or len(_normalize_text(name)) < 2:
            continue
        raw_candidates.append({
            "name": name,
            "y": line["top"],
            "height": line["height"],
            "avg_conf": sum(line["confs"]) / len(line["confs"]),
            "min_conf": min(line["confs"]),
        })

    # 按 y 坐标排序
    raw_candidates.sort(key=lambda x: x["y"])

    # 合并相邻行：y 间距 < merge_gap 且字号相近的行合并为一个标题
    merged: List[Dict[str, Any]] = []
    for item in raw_candidates:
        if merged and abs(item["y"] - (merged[-1]["y"] + merged[-1]["height"])) < merge_gap:
            prev = merged[-1]
            prev["name"] = prev["name"] + item["name"]
            prev["avg_conf"] = (prev["avg_conf"] + item["avg_conf"]) / 2
            prev["min_conf"] = min(prev["min_conf"], item["min_conf"])
            prev["height"] = item["y"] + item["height"] - prev["y"]
        else:
            merged.append(dict(item))

    # 过滤：置信度达标
    candidates: List[Dict[str, Any]] = []
    for item in merged:
        if item["min_conf"] >= conf_threshold:
            candidates.append({
                "name": item["name"],
                "y": item["y"],
                "conf": round(item["avg_conf"], 1),
                "min_conf": round(item["min_conf"], 1),
            })

    if not candidates:
        return "", []

    # 第一个（最顶部、字号最大）作为根题材
    root_topic = candidates[0]["name"]
    # 其余作为一级子题材（跳过根题材自身）
    topics = [c for c in candidates[1:] if c["name"] != root_topic]

    return root_topic, topics


def detect_root_topic(ocr_results: List[Dict[str, Any]], image_width: int, image_height: int) -> str:
    """根据 OCR 结果识别根题材标题。"""
    if not ocr_results:
        return "未知"

    heights = [max(1, _bbox_height(item["bbox"])) for item in ocr_results]
    median_height = median(heights) if heights else 1.0

    candidates: List[Tuple[float, Dict[str, Any]]] = []
    for item in ocr_results:
        x0, y0, x1, y1 = item["bbox"]
        text = item["text"]
        if _is_text_noise(text):
            continue
        if y0 > image_height * 0.28:
            continue
        width = max(1, x1 - x0)
        if width < image_width * 0.12:
            continue
        cx, _ = _box_center(item["bbox"])
        center_score = 1.0 - min(1.0, abs(cx - image_width * 0.5) / max(1.0, image_width * 0.5))
        red_score = 1.0 if _is_redish(item.get("mean_rgb", (0.0, 0.0, 0.0))) else 0.0
        size_score = min(1.0, _bbox_height(item["bbox"]) / max(1.0, median_height * 1.6))
        width_score = min(1.0, width / max(1.0, image_width * 0.7))
        score = 0.35 * red_score + 0.25 * center_score + 0.2 * size_score + 0.2 * width_score
        candidates.append((score, item))

    if not candidates:
        top_item = min(ocr_results, key=lambda item: (item["bbox"][1], -_bbox_width(item["bbox"])))
        return top_item["text"]

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]["text"]


def filter_first_level_topics(
    ocr_results: List[Dict[str, Any]],
    image_width: int,
    image_height: int,
    root_topic: str,
) -> List[Dict[str, Any]]:
    """
    筛选一级子题材标题。

    规则（尽量贴合"商业航天图"这类长图）：
    - 位于左侧树状结构区域
    - 通常为红色 / 明显偏红
    - 文字长度短，属于题材名称
    - 去掉顶部根题材标题和明显噪声
    """
    if not ocr_results:
        return []

    heights = [max(1, _bbox_height(item["bbox"])) for item in ocr_results]
    median_height = median(heights) if heights else 1.0
    root_norm = _normalize_text(root_topic)

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for item in ocr_results:
        text = item["text"]
        norm = _normalize_text(text)
        if _is_text_noise(text):
            continue
        if root_norm and norm == root_norm:
            continue

        x0, y0, x1, y1 = item["bbox"]
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        cx, cy = _box_center(item["bbox"])

        # 一级子题材通常在左侧树状区域，避免把正文大块文本误判进去
        if x0 > image_width * 0.62:
            continue
        if y0 < image_height * 0.03:
            # 顶部区域更可能是根题材或说明区
            continue
        if width > image_width * 0.5:
            continue
        if height > median_height * 3.0:
            continue

        mean_rgb = item.get("mean_rgb", (0.0, 0.0, 0.0))
        redish = _is_redish(mean_rgb)
        red_score = 1.0 if redish else 0.0
        left_score = 1.0 - min(1.0, x0 / max(1.0, image_width * 0.6))
        size_score = min(1.0, height / max(1.0, median_height * 1.2))
        top_bias = 1.0 - min(1.0, cy / max(1.0, image_height * 0.95))
        text_len = len(norm)
        text_score = 1.0 if 2 <= text_len <= 10 else 0.5 if text_len <= 14 else 0.0
        conf_score = min(1.0, max(0.0, item.get("conf", 0.0)) / 100.0)
        score = (
            0.42 * red_score
            + 0.20 * left_score
            + 0.14 * size_score
            + 0.10 * top_bias
            + 0.08 * text_score
            + 0.06 * conf_score
        )

        # 若不是红色，也允许"左侧 + 较大字号 + 可信度高"的候选进入备选池
        if redish or (left_score > 0.55 and size_score > 0.75 and conf_score > 0.55):
            scored.append((score, item))

    if not scored:
        # 兜底：按 y 排序取左侧区域的短文本，尽量保证能生成切割方案
        fallback = []
        for item in ocr_results:
            text = item["text"]
            norm = _normalize_text(text)
            x0, y0, x1, y1 = item["bbox"]
            if _is_text_noise(text):
                continue
            if x0 > image_width * 0.45:
                continue
            if y0 < image_height * 0.05:
                continue
            if len(norm) > 12:
                continue
            fallback.append(item)

        fallback.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
        return _dedupe_topics(fallback, image_height)

    scored.sort(key=lambda pair: (pair[1]["bbox"][1], -pair[0], pair[1]["bbox"][0]))
    ordered = [item for _, item in scored]
    return _dedupe_topics(ordered, image_height)


def _dedupe_topics(topics: List[Dict[str, Any]], image_height: int) -> List[Dict[str, Any]]:
    """基于 y 位置和文本去重，避免 OCR 产生重复行。"""
    deduped: List[Dict[str, Any]] = []
    seen_norms: set = set()
    min_gap = max(8, int(image_height * 0.008))

    for item in topics:
        norm = _normalize_text(item.get("text", ""))
        if not norm:
            continue
        y0 = item["bbox"][1]
        if norm in seen_norms:
            continue
        if deduped:
            prev = deduped[-1]
            prev_y = prev["bbox"][1]
            prev_norm = _normalize_text(prev.get("text", ""))
            if abs(y0 - prev_y) <= min_gap and norm[:8] == prev_norm[:8]:
                continue
        seen_norms.add(norm)
        deduped.append(item)

    return deduped


def _build_mm_topic_list_prompt() -> str:
    """构建多模态 prompt：只让模型列出一级子题材名称和顺序（不猜坐标）。"""
    return """你是一个专业的金融题材分析助手。请分析这张"开盘啦"APP题材长截图。

## 你的任务
1. 识别根题材名称（图片顶部的红色大字标题）
2. 从上到下，列出所有可见的**一级子题材**名称

## 什么是一级子题材
- 在左侧树状结构中，紧跟在根题材后面的第一层节点
- 字号比二级子题材和股票名称大
- 通常是白色或浅色文字

## 输出格式
严格输出以下 JSON 对象（不要输出其他内容，不要猜坐标）：
{
  "root_topic": "根题材名称",
  "topic_names": ["一级子题材1", "一级子题材2", "一级子题材3", ...]
}

## 注意事项
- 只列一级子题材，不要列二级子题材
- 按从上到下的顺序排列
- 不要遗漏，不要重复
- 不需要提供 y 坐标，只需要名称列表"""


def validate_cut_plan(
    analysis: Dict[str, Any],
    image_width: int,
    image_height: int,
    padding: int = 100,
    min_segment_height: int = 50,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    校验并修复多模态模型返回的切割方案。

    - 按 y_start 排序
    - 去重（同名且 y 坐标接近的 segment）
    - 首段 y_start 钳位到 0，末段 y_end 钳位到图片高度
    - 应用 padding 扩展每个 segment
    - 解决重叠：取中点作为边界
    - 最小高度检查：低于阈值的 segment 合并到相邻段
    - 间隙警告
    - 重新编号 segment_id
    """
    warnings: List[str] = []
    segments = analysis.get("segments", [])

    if not segments:
        warnings.append("没有找到任何 segment")
        return analysis, warnings

    # 1. 按 y_start 排序
    segments.sort(key=lambda s: s.get("crop_bbox", [0, 0, 0, 0])[1])

    # 2. 去重：同名且 y_start 差值 < 100px 视为重复
    deduped: List[Dict[str, Any]] = []
    for seg in segments:
        bbox = seg.get("crop_bbox", [0, 0, 0, 0])
        y_start = int(bbox[1])
        name = seg.get("proposed_name", "")
        is_dup = False
        if deduped:
            prev = deduped[-1]
            prev_bbox = prev.get("crop_bbox", [0, 0, 0, 0])
            prev_y = int(prev_bbox[1])
            prev_name = prev.get("proposed_name", "")
            if name == prev_name and abs(y_start - prev_y) < 100:
                is_dup = True
                warnings.append(f"去重: 移除重复的 segment '{name}' (y={y_start})")
        if not is_dup:
            deduped.append(seg)
    segments = deduped

    if not segments:
        warnings.append("去重后没有剩余 segment")
        return analysis, warnings

    # 3. 钳位首段和末段
    first_bbox = list(segments[0].get("crop_bbox", [0, 0, 0, 0]))
    if first_bbox[1] != 0:
        warnings.append(f"修正首段 y_start: {first_bbox[1]} -> 0")
    first_bbox[0] = 0
    first_bbox[1] = 0
    segments[0]["crop_bbox"] = first_bbox

    last_bbox = list(segments[-1].get("crop_bbox", [0, 0, 0, 0]))
    if last_bbox[3] != image_height:
        warnings.append(f"修正末段 y_end: {last_bbox[3]} -> {image_height}")
    last_bbox[2] = image_width
    last_bbox[3] = image_height
    segments[-1]["crop_bbox"] = last_bbox

    # 4. 应用 padding 扩展每个 segment 的范围
    # 策略：每个 segment 向上下扩展 padding，允许相邻 segment 之间有重叠。
    # 重叠是故意的——宁可多裁一些也不要切掉内容。
    # 重叠区域在后续多模态解析阶段会自然去重（同一行股票出现在两个 segment 中）。
    for i in range(len(segments)):
        bbox = list(segments[i].get("crop_bbox", [0, 0, 0, 0]))
        bbox[0] = 0
        bbox[2] = image_width
        bbox[1] = max(0, int(bbox[1]) - padding)
        if i < len(segments) - 1:
            bbox[3] = min(image_height, int(bbox[3]) + padding)
        segments[i]["crop_bbox"] = bbox

    # 5. 最小高度检查：低于阈值的 segment 合并到相邻段
    merged: List[Dict[str, Any]] = []
    for seg in segments:
        bbox = seg["crop_bbox"]
        height = bbox[3] - bbox[1]
        if height < min_segment_height and merged:
            # 合并到前一个 segment
            prev_bbox = merged[-1]["crop_bbox"]
            prev_bbox[3] = bbox[3]
            prev_name = merged[-1].get("proposed_name", "")
            curr_name = seg.get("proposed_name", "")
            merged[-1]["proposed_name"] = f"{prev_name}+{curr_name}"
            merged[-1]["expected_topics"] = list(
                set(
                    merged[-1].get("expected_topics", [])
                    + seg.get("expected_topics", [])
                )
            )
            warnings.append(
                f"合并过短 segment '{curr_name}' (h={height}px) 到 '{prev_name}'"
            )
        else:
            merged.append(seg)
    segments = merged

    # 6. 间隙警告（只检查真正的间隙，重叠是故意的所以不警告）
    for i in range(len(segments) - 1):
        curr_end = segments[i]["crop_bbox"][3]
        next_start = segments[i + 1]["crop_bbox"][1]
        gap = next_start - curr_end
        if gap > 100:
            warnings.append(
                f"警告: segment '{segments[i].get('proposed_name')}' 和 "
                f"'{segments[i+1].get('proposed_name')}' 之间有 {gap}px 间隙"
            )
        elif gap < 0:
            overlap = -gap
            warnings.append(
                f"重叠: segment '{segments[i].get('proposed_name')}' 和 "
                f"'{segments[i+1].get('proposed_name')}' 重叠 {overlap}px"
            )

    # 7. 重新编号 segment_id
    for i, seg in enumerate(segments):
        seg["segment_id"] = i + 1

    analysis["segments"] = segments
    return analysis, warnings


def analyze_image_structure(image_path: str, config: dict, strategy: str = "ocr") -> Dict[str, Any]:
    """
    分析图片结构并生成切割计划。

    mm 策略（默认）：红色水平线定位边界 + OCR 识别名称（主）+ 多模态兜底
    ocr 策略：Tesseract OCR 识别标题位置（纯 OCR fallback）
    """
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception:
        width, height = 1220, 12000
        print(f"警告: 无法读取图片尺寸，使用默认值 {width}x{height}")

    if strategy == "mm":
        print(f"正在分析图片: {image_path} ...")

        # 第一步：用红色水平线检测精确定位切割边界
        print("  [1/3] 检测全宽红色水平线...")
        red_lines = detect_full_width_red_lines(image_path)
        print(f"  检测到 {len(red_lines)} 条红色分界线")

        if len(red_lines) < 2:
            print("警告: 红色分界线不足，回退到 OCR 方案", file=sys.stderr)
        else:
            # 第二步：多模态模型识别一级子题材名称（准确）
            print("  [2/3] 多模态识别子题材名称...")
            prompt = _build_mm_topic_list_prompt()
            response = call_kimi_k25_image(image_path, prompt, config)
            mm_names = []
            root_topic = "未知"
            if response:
                mm_result = extract_json_from_response(response)
                if mm_result and "topic_names" in mm_result:
                    root_topic = mm_result.get("root_topic", "未知")
                    mm_names = mm_result.get("topic_names", [])
                    print(f"  根题材: {root_topic}")
                    print(f"  一级子题材 ({len(mm_names)} 个): {mm_names}")

            if mm_names:
                # 第三步：将名称与红色线边界匹配
                print("  [3/3] 匹配名称与红色分界线...")
                segments = build_segments_from_borders(
                    red_lines, mm_names, width, height, root_topic
                )
                if segments:
                    return {
                        "root_topic": root_topic,
                        "segments": segments,
                        "red_line_count": len(red_lines),
                        "red_lines": red_lines,
                        "name_method": "mm",
                        "analysis_method": "mm_redline_analysis",
                    }

            print("警告: 多模态命名失败，回退到 OCR 方案", file=sys.stderr)

    # OCR fallback
    try:
        ocr_results = ocr_image(image_path)
        if not ocr_results:
            raise RuntimeError("OCR 未识别到有效文本")

        root_topic = detect_root_topic(ocr_results, width, height)
        first_level_topics = filter_first_level_topics(ocr_results, width, height, root_topic)

        if len(first_level_topics) < 1:
            first_level_topics = []
            for item in ocr_results:
                x0, y0, x1, y1 = item["bbox"]
                norm = _normalize_text(item["text"])
                if x0 > width * 0.5:
                    continue
                if len(norm) > 12:
                    continue
                if y0 < height * 0.04:
                    continue
                first_level_topics.append(item)
            first_level_topics = _dedupe_topics(sorted(first_level_topics, key=lambda it: (it["bbox"][1], it["bbox"][0])), height)

        if not first_level_topics:
            raise RuntimeError("未能从 OCR 中筛选出一级子题材标题")

        segments: List[Dict[str, Any]] = []
        for i, topic in enumerate(first_level_topics):
            y_start = max(0, int(topic["bbox"][1]))
            if i < len(first_level_topics) - 1:
                y_end = max(y_start + 1, int(first_level_topics[i + 1]["bbox"][1]))
            else:
                y_end = height

            proposed_name = topic["text"].strip()
            segments.append(
                {
                    "segment_id": i + 1,
                    "proposed_name": proposed_name,
                    "crop_bbox": [0, y_start, width, y_end],
                    "expected_topics": [proposed_name],
                    "expected_path_examples": [f"{root_topic} / {proposed_name} / 示例细分"],
                    "notes": f"OCR 识别到的一级子题材标题，位于 y={y_start} 附近",
                    "source_bbox": list(topic["bbox"]),
                    "source_confidence": round(float(topic.get("conf", 0.0)), 2),
                }
            )

        return {
            "root_topic": root_topic,
            "segments": segments,
            "ocr_count": len(ocr_results),
            "analysis_method": "ocr_structure_analysis",
        }

    except Exception as ocr_error:
        print(f"错误: OCR 结构分析也失败了: {ocr_error}", file=sys.stderr)
        sys.exit(1)


def generate_markdown(plan: Dict[str, Any]) -> str:
    """生成 Markdown 格式的切割方案文档"""
    timestamp = plan.get("timestamp", "")
    image_path = plan.get("image_path", "")
    width, height = plan.get("image_size", [0, 0])
    root_topic = plan.get("root_topic", "未知")
    method = plan.get("analysis_method", "ocr_structure_analysis")

    md = f"""# 语义切割方案 - {root_topic}

**生成时间**: {timestamp}
**原图**: `{image_path}`
**图像尺寸**: {width} x {height} px
**识别根题材**: {root_topic}
**分析方式**: {method}

---

## 1. 切割策略说明

本方案支持 **多模态优先 / OCR fallback** 两种模式。优先识别图片中的结构语义，再根据一级子题材标题的 y 坐标生成切割边界；OCR 仅作为兜底路径，用于在多模态分析失败时保证脚本可用。

---

## 2. Segment 详细规划

"""
    for seg in plan["segments"]:
        md += f"""
### Segment {seg['segment_id']}: {seg['proposed_name']}

| 属性 | 值 |
|------|-----|
| **裁剪区域** | y: {seg['crop_bbox'][1]} - {seg['crop_bbox'][3]} px |
| **高度** | {seg['crop_bbox'][3] - seg['crop_bbox'][1]} px |

**预期覆盖题材**:
"""
        for topic in seg.get("expected_topics", []):
            md += f"- {topic}\n"

        md += f"\n**预期路径示例**:\n"
        for path in seg.get("expected_path_examples", []):
            md += f"- `{path}`\n"

        md += f"\n**备注**: {seg.get('notes', '')}\n\n---\n"

    md += """
## 3. 下一步工作

1. 按新的 `crop_bbox` 裁剪原图。
2. 对每个 segment 使用多模态模型解析。
3. 提取题材路径和股票列表。

---
*Generated by plan_semantic_cuts.py (multimodal-first / OCR fallback version)*
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="生成语义切割方案 (T2.5path0 - 多模态优先/OCR fallback版)")
    parser.add_argument("--image", required=True, help="原图路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--strategy",
        choices=["ocr", "mm"],
        default="mm",
        help="切割策略：mm=多模态优先(默认)，ocr=OCR优先",
    )
    parser.add_argument(
        "--fixed-name",
        action="store_true",
        help="使用固定文件名（无时间戳），由 orchestrator 控制输出目录"
    )
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"错误: 图片不存在: {args.image}")
        sys.exit(1)

    config = get_openclaw_config()
    analysis = analyze_image_structure(args.image, config, strategy=args.strategy)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        from PIL import Image

        with Image.open(args.image) as img:
            img_size = list(img.size)
    except Exception:
        img_size = [1220, 12000]

    plan = {
        "image_path": os.path.abspath(args.image),
        "image_size": img_size,
        "timestamp": timestamp,
        "root_topic": analysis.get("root_topic", "未知"),
        "segment_count": len(analysis.get("segments", [])),
        "segments": analysis.get("segments", []),
        "analysis_method": analysis.get("analysis_method", "ocr_structure_analysis"),
        "ocr_count": analysis.get("ocr_count", 0),
    }

    os.makedirs(args.output_dir, exist_ok=True)

    if args.fixed_name:
        json_filename = "cut_plan.json"
        md_filename = "cut_plan.md"
    else:
        json_filename = f"path_cut_plan_{timestamp}.json"
        md_filename = f"path_cut_plan_{timestamp}.md"

    json_path = os.path.join(args.output_dir, json_filename)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON saved: {json_path}")

    md_content = generate_markdown(plan)
    md_path = os.path.join(args.output_dir, md_filename)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"[OK] Markdown saved: {md_path}")

    print("\n[T2.5path0 Complete]")
    print(f"  - Root Topic: {plan['root_topic']}")
    print(f"  - Segments: {plan['segment_count']}")
    print(f"  - OCR Count: {plan.get('ocr_count', 0)}")
    print(f"  - Output dir: {args.output_dir}")


if __name__ == "__main__":
    main()
