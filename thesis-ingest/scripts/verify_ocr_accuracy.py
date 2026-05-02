#!/usr/bin/env python3
"""
OCR 准确性验证脚本
生成识别结果对比文件并推送 Telegram 等待用户确认
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests


def load_ocr_result(json_path: str) -> dict:
    """加载 OCR 结构化结果"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_verify_markdown(ocr_data: dict, output_dir: str, image_source: str = "Telegram 用户发送的图片") -> str:
    """
    生成验证对比文件
    
    Args:
        ocr_data: OCR 结构化数据
        output_dir: 输出目录
        image_source: 图片来源描述
        
    Returns:
        生成的文件路径
    """
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(output_dir, f"ocr_verify_{timestamp}.md")
    
    thesis_name = ocr_data.get("thesis_name", "未识别")
    stocks = ocr_data.get("stocks", [])
    parse_time = ocr_data.get("parse_time", "")
    source_file = ocr_data.get("source_file", "")
    
    # 生成 markdown 内容
    lines = [
        f"# OCR 识别结果验证",
        f"",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## 图片来源",
        f"",
        f"{image_source}",
        f"",
        f"## 识别结果",
        f"",
        f"### 题材名称",
        f"",
        f"**{thesis_name}**",
        f"",
        f"### 成分股列表（共 {len(stocks)} 只）",
        f"",
    ]
    
    # 分批显示（每批20只）
    batch_size = 20
    for i, stock in enumerate(stocks, 1):
        code = stock.get("code", "")
        name = stock.get("name", "")
        if code:
            lines.append(f"{i}. **{name}** (代码: `{code}`)")
        else:
            lines.append(f"{i}. {name}")
        
        # 每20只加一个分隔
        if i % batch_size == 0 and i < len(stocks):
            lines.append(f"")
            lines.append(f"---")
            lines.append(f"")
    
    lines.extend([
        f"",
        f"## 元数据",
        f"",
        f"- **原始文件**: `{source_file}`",
        f"- **解析时间**: {parse_time}",
        f"",
        f"## 验证状态",
        f"",
        f"⏳ **等待用户确认**",
        f"",
        f"---",
        f"*请检查以上识别结果是否准确，回复「确认」写入数据库，或「有误」进入修正流程。*",
    ])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return output_path


def send_telegram_message(bot_token: str, chat_id: str, thesis_name: str, stocks: list, verify_file: str) -> bool:
    """
    发送 Telegram 消息（带确认按钮）
    
    Args:
        bot_token: Telegram Bot Token
        chat_id: 目标 Chat ID
        thesis_name: 题材名称
        stocks: 成分股列表
        verify_file: 验证文件路径
        
    Returns:
        是否发送成功
    """
    # 准备消息内容
    stock_count = len(stocks)
    top_20 = stocks[:20]
    
    # 格式化前20只股票
    stock_lines = []
    for i, stock in enumerate(top_20, 1):
        name = stock.get("name", "")
        code = stock.get("code", "")
        if code:
            stock_lines.append(f"{i}. {name} ({code})")
        else:
            stock_lines.append(f"{i}. {name}")
    
    stock_text = '\n'.join(stock_lines)
    if stock_count > 20:
        stock_text += f"\n... 等共 {stock_count} 只"
    
    message = f"""📊 **OCR 识别结果**

**题材名称**: {thesis_name}

**成分股数量**: {stock_count} 只

**前 20 只股票**:
{stock_text}

---

✅ 请确认识别结果是否正确
📝 详细对比文件: `{os.path.basename(verify_file)}`"""
    
    # 发送消息
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ 确认", "callback_data": "confirm_ocr"},
                    {"text": "❌ 有误", "callback_data": "reject_ocr"}
                ]
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            print(f"✅ Telegram 消息发送成功")
            return True
        else:
            print(f"❌ Telegram 发送失败: {result.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='OCR 准确性验证脚本'
    )
    parser.add_argument(
        '--input',
        required=True,
        help='OCR 结构化结果 JSON 文件路径'
    )
    parser.add_argument(
        '--output-dir',
        default='output',
        help='输出目录 (默认: output)'
    )
    parser.add_argument(
        '--bot-token',
        required=True,
        help='Telegram Bot Token'
    )
    parser.add_argument(
        '--chat-id',
        required=True,
        help='目标 Telegram Chat ID'
    )
    parser.add_argument(
        '--image-source',
        default='Telegram 用户发送的图片',
        help='图片来源描述'
    )
    
    args = parser.parse_args()
    
    # 获取工作目录
    script_dir = Path(__file__).parent
    work_dir = script_dir.parent
    
    # 解析路径
    input_path = args.input
    if not os.path.isabs(input_path):
        input_path = os.path.join(work_dir, input_path)
    
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(work_dir, output_dir)
    
    print(f"📂 输入文件: {input_path}")
    print(f"📂 输出目录: {output_dir}")
    
    # 加载 OCR 结果
    try:
        ocr_data = load_ocr_result(input_path)
        print(f"✅ 加载 OCR 结果: {ocr_data.get('thesis_name', 'Unknown')}, {len(ocr_data.get('stocks', []))} 只股票")
    except Exception as e:
        print(f"❌ 加载 OCR 结果失败: {e}")
        return 1
    
    # 生成验证文件
    try:
        verify_file = generate_verify_markdown(ocr_data, output_dir, args.image_source)
        print(f"✅ 生成验证文件: {verify_file}")
    except Exception as e:
        print(f"❌ 生成验证文件失败: {e}")
        return 1
    
    # 发送 Telegram 消息
    success = send_telegram_message(
        args.bot_token,
        args.chat_id,
        ocr_data.get('thesis_name', 'Unknown'),
        ocr_data.get('stocks', []),
        verify_file
    )
    
    if success:
        print(f"\n✅ 验证流程已启动，等待用户回复...")
        return 0
    else:
        print(f"\n❌ Telegram 推送失败")
        return 1


if __name__ == '__main__':
    sys.exit(main())