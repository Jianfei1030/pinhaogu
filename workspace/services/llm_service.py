#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Service - 统一大模型调用服务

封装阿里百炼 Coding Plan API 的调用逻辑，提供简洁的 chat_completion 接口。

用法:
    from services.llm_service import chat_completion
    
    response = chat_completion(
        system_prompt="你是一位助手",
        user_prompt="你好",
        model="qwen3.5-plus",
        temperature=0.3,
        max_tokens=2048
    )
"""
import json
import os
import ssl
import urllib.request
import urllib.error
from typing import Optional


# === 配置 ===
# 从环境变量或默认值读取配置
LLM_BASE_URL = os.environ.get(
    "STOCK_MONITOR_LLM_BASE_URL",
    "https://coding.dashscope.aliyuncs.com/v1"
)
LLM_MODEL = os.environ.get("STOCK_MONITOR_LLM_MODEL", "qwen3.6-plus")
LLM_PROXY = os.environ.get("STOCK_MONITOR_LLM_PROXY", "")
LLM_TIMEOUT = int(os.environ.get("STOCK_MONITOR_LLM_TIMEOUT", "120"))
API_KEY_ENV = os.environ.get("STOCK_MONITOR_LLM_API_KEY_ENV", "BAILIAN_API_KEY")


def get_api_key() -> str:
    """从环境变量读取 API Key"""
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        raise RuntimeError(f"API Key 未设置：请设置环境变量 {API_KEY_ENV}")
    return api_key


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: Optional[int] = None,
    verbose: bool = True,
) -> str:
    """
    调用 LLM 进行对话补全
    
    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        model: 模型名称（默认使用配置的 LLM_MODEL）
        temperature: 温度参数（默认 0.3）
        max_tokens: 最大输出 token 数（默认 2048）
        timeout: 请求超时秒数（默认使用配置的 LLM_TIMEOUT）
        verbose: 是否打印调用日志（默认 True）
    
    Returns:
        LLM 返回的文本内容
    
    Raises:
        RuntimeError: API Key 未设置或请求失败
        urllib.error.URLError: 网络错误
        json.JSONDecodeError: 响应解析失败
    """
    api_key = get_api_key()
    model = model or LLM_MODEL
    timeout = timeout or LLM_TIMEOUT
    
    # 构建请求 URL
    url = f"{LLM_BASE_URL}/chat/completions"
    
    # 构建请求体
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    
    # 配置 SSL 和代理
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    proxy_handler = urllib.request.ProxyHandler({
        "http": LLM_PROXY,
        "https": LLM_PROXY,
    })
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(proxy_handler, https_handler)
    
    # 构建请求
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    
    if verbose:
        print(f"  [LLM] 调用 {model} (Chat Completions) ...")
    
    # 发送请求（带 3 次重试，指数退避）
    import time
    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = opener.open(req, timeout=timeout)
            result = json.loads(resp.read())
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                if verbose:
                    print(f"  [LLM] 请求失败 (尝试 {attempt+1}/{max_retries}): {e}")
                    print(f"  [LLM] {wait}秒后重试...")
                time.sleep(wait)
            else:
                if verbose:
                    print(f"  [LLM] 请求失败，已达最大重试次数 {max_retries}: {e}")
                raise RuntimeError(f"LLM 请求失败（重试 {max_retries} 次后仍失败）: {e}") from e
    
    # 提取响应内容
    content = result["choices"][0]["message"]["content"].strip()
    usage = result.get("usage", {})
    tokens_in = usage.get("prompt_tokens", "?")
    tokens_out = usage.get("completion_tokens", "?")
    
    if verbose:
        print(f"  [LLM] Token: {tokens_in} in / {tokens_out} out")
    
    return content


def chat_completion_raw(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: Optional[int] = None,
    verbose: bool = True,
) -> dict:
    """
    调用 LLM 进行对话补全（原始接口，返回完整响应）
    
    Args:
        messages: 消息列表，每项为 {"role": "system"|"user"|"assistant", "content": "..."}
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        timeout: 请求超时秒数
        verbose: 是否打印调用日志
    
    Returns:
        完整响应字典（包含 choices、usage 等）
    """
    api_key = get_api_key()
    model = model or LLM_MODEL
    timeout = timeout or LLM_TIMEOUT
    
    url = f"{LLM_BASE_URL}/chat/completions"
    
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    proxy_handler = urllib.request.ProxyHandler({
        "http": LLM_PROXY,
        "https": LLM_PROXY,
    })
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(proxy_handler, https_handler)
    
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    
    if verbose:
        print(f"  [LLM] 调用 {model} (Chat Completions) ...")
    
    resp = opener.open(req, timeout=timeout)
    result = json.loads(resp.read())
    
    if verbose:
        usage = result.get("usage", {})
        tokens_in = usage.get("prompt_tokens", "?")
        tokens_out = usage.get("completion_tokens", "?")
        print(f"  [LLM] Token: {tokens_in} in / {tokens_out} out")
    
    return result
