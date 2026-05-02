#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一推送服务层

提供 Telegram 和 QQ 推送的核心实现。

用法:
    from services.push_service import send_telegram, send_qq, send_both
    
    # 只推 Telegram
    send_telegram("消息内容")
    
    # 只推 QQ
    send_qq("消息内容")
    
    # 同时推送
    send_both("消息内容")

修复历史:
    2026-04-10: 修复 400 Bad Request 错误
                - 添加 split_telegram() 函数拆分长消息（Telegram 限制 4096 字符）
                - 添加 escape_markdown() 函数转义特殊字符
                - send_telegram() 支持消息分片发送
                - 处理 Markdown 特殊字符避免解析错误
"""
import subprocess
import logging
from pathlib import Path
import sys

# 确保能导入 config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config

logger = logging.getLogger(__name__)


def split_telegram(text: str, max_len: int = 4000) -> list[str]:
    """
    将长文本拆分为适合 Telegram 发送的片段
    
    Telegram API 单条消息限制 4096 字符。
    为安全起见，使用 4000 字符作为上限。
    优先按行拆分，保持消息可读性。
    
    Args:
        text: 待拆分的文本
        max_len: 单条消息最大长度（默认 4000）
    
    Returns:
        list[str]: 拆分后的消息列表
    """
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    current = ""
    
    for line in text.split("\n"):
        # 如果当前行本身就超过限制，强制拆分
        if len(line) > max_len:
            if current:
                chunks.append(current.strip())
                current = ""
            # 强制按字符拆分超长行
            for i in range(0, len(line), max_len):
                chunks.append(line[i:i+max_len])
        # 如果添加这行会超限，先保存当前内容，再开始新片段
        elif len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    
    # 保存最后一段
    if current.strip():
        chunks.append(current.strip())
    
    return chunks


def escape_markdown(text: str) -> str:
    """
    转义 Telegram Markdown 特殊字符
    
    Telegram MarkdownV2 需要转义的字符:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    对于普通 Markdown 模式，需要转义的字符较少:
    _ * [ `
    
    Args:
        text: 待转义的文本
    
    Returns:
        str: 转义后的文本
    """
    # Telegram Markdown 模式需要转义的字符
    # 注意：不转义 ** 和 __ 因为它们是格式标记
    special_chars = ['[', ']', '(', ')', '`']
    
    result = text
    for char in special_chars:
        result = result.replace(char, f'\\{char}')
    
    return result


def send_telegram(message: str, use_markdown: bool = False) -> bool:
    """
    推送到 Telegram
    
    修复点:
        1. 长消息自动拆分为多条发送（每条最大 4000 字符）
        2. 可选的 Markdown 模式支持（默认纯文本，避免格式错误）
        3. 特殊字符自动转义（当检测到表格时强制纯文本模式）
        4. 分片消息逐条发送，所有分片成功才算成功
    
    Args:
        message: 消息内容
        use_markdown: 是否使用 Markdown 模式（默认 False）
    
    Returns:
        bool: 是否成功（所有分片都成功才返回 True）
    """
    import requests
    
    # 检测是否包含表格，如果包含则禁用 Markdown 并转义特殊字符
    # 表格使用 | 作为列分隔符，Telegram Markdown 不支持表格语法
    has_table = '|' in message and '|' in message.split('\n')[0] if message else False
    
    if has_table:
        # 表格内容使用纯文本模式，但需要转义特殊字符避免解析错误
        use_markdown = False
        message = escape_markdown(message)
        logger.info("检测到表格格式，使用纯文本模式并转义特殊字符")
    
    # 拆分长消息
    chunks = split_telegram(message)
    if len(chunks) > 1:
        logger.info(f"消息长度 {len(message)} 字符，拆分为 {len(chunks)} 条发送")
    
    url = f"https://api.telegram.org/bot{config.telegram.bot_token}/sendMessage"
    
    success_count = 0
    for i, chunk in enumerate(chunks, 1):
        try:
            payload = {
                "chat_id": config.telegram.chat_id,
                "text": chunk
            }
            
            # 只有明确启用 Markdown 且没有表格时才添加 parse_mode
            if use_markdown and not has_table:
                payload["parse_mode"] = "Markdown"
            
            response = requests.post(
                url,
                json=payload,
                timeout=10,
                proxies={
                    "http": config.telegram.proxy,
                    "https": config.telegram.proxy
                }
            )
            response.raise_for_status()
            success_count += 1
            logger.info(f"Telegram 推送成功 ({i}/{len(chunks)})")
        except Exception as e:
            logger.error(f"Telegram 推送失败 ({i}/{len(chunks)})：{e}")
            # 继续发送后续分片，但记录失败
    
    # 所有分片都成功才返回 True
    return success_count == len(chunks)


def send_qq(message: str) -> bool:
    """
    推送到 QQ
    
    Args:
        message: 消息内容
    
    Returns:
        bool: 是否成功
    """
    try:
        subprocess.run(
            [
                "openclaw", "message", "send",
                "--channel", "qqbot",
                "--account", config.qq.account,
                "--target", config.qq.target,
                "--message", message
            ],
            check=True,
            capture_output=True
        )
        logger.info("QQ 推送成功")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"QQ 推送失败：{e.stderr.decode() if e.stderr else e}")
        return False
    except Exception as e:
        logger.error(f"QQ 推送失败：{e}")
        return False


def send_both(message: str) -> tuple[bool, bool]:
    """
    同时推送到 Telegram 和 QQ
    
    Args:
        message: 消息内容
    
    Returns:
        tuple[bool, bool]: (Telegram 是否成功，QQ 是否成功)
    """
    tg_ok = send_telegram(message)
    qq_ok = send_qq(message)
    return tg_ok, qq_ok


# ===== 测试函数 =====
def test_push():
    """测试推送功能"""
    test_message = "🧪 推送测试\n\n这是一条测试消息\n时间：2026-04-05"
    
    # 测试长消息拆分
    long_message = "🧪 长消息测试\n\n" + "测试行内容\n" * 500
    
    # 测试表格消息
    table_message = """🧪 表格测试

| 列1 | 列2 | 列3 |
|-----|-----|-----|
| A | B | C |
| D | E | F |
"""
    
    print("开始测试推送功能...")
    print(f"Telegram: {config.telegram.chat_id}")
    print(f"QQ: {config.qq.target}")
    print()
    
    # 测试 Telegram
    print("1. 测试 Telegram 推送（普通消息）...")
    tg_ok = send_telegram(test_message)
    print(f"   结果：{'✅ 成功' if tg_ok else '❌ 失败'}")
    print()
    
    # 测试长消息
    print("2. 测试 Telegram 推送（长消息拆分）...")
    tg_long_ok = send_telegram(long_message)
    print(f"   结果：{'✅ 成功' if tg_long_ok else '❌ 失败'}")
    print()
    
    # 测试表格消息
    print("3. 测试 Telegram 推送（表格消息）...")
    tg_table_ok = send_telegram(table_message)
    print(f"   结果：{'✅ 成功' if tg_table_ok else '❌ 失败'}")
    print()
    
    # 测试 QQ
    print("4. 测试 QQ 推送...")
    qq_ok = send_qq(test_message)
    print(f"   结果：{'✅ 成功' if qq_ok else '❌ 失败'}")
    print()
    
    # 测试同时推送
    print("5. 测试同时推送...")
    tg_ok2, qq_ok2 = send_both(test_message + "\n\n(同时推送)")
    print(f"   Telegram: {'✅ 成功' if tg_ok2 else '❌ 失败'}")
    print(f"   QQ: {'✅ 成功' if qq_ok2 else '❌ 失败'}")
    print()
    
    # 总结
    all_ok = tg_ok and tg_long_ok and tg_table_ok and qq_ok and tg_ok2 and qq_ok2
    print(f"总计：{'✅ 全部成功' if all_ok else '⚠️ 部分失败'}")
    return all_ok


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    test_push()