# -*- coding: utf-8 -*-
"""数据源基础模块 - 异常类和基础配置"""
from __future__ import annotations

import requests
from typing import Any


class DataSourceError(RuntimeError):
    """数据源异常"""
    pass


# 共享会话（代理通过环境变量 HTTPS_PROXY / HTTP_PROXY 配置）
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0 Safari/537.36"
    }
)

# 超时配置
DEFAULT_TIMEOUT = 20
REALTIME_TIMEOUT = 5

# API URL 常量
TENCENT_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
TENCENT_DAILY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_REALTIME_URL = "https://qt.gtimg.cn/q={code}"
SINA_REALTIME_URL = "https://hq.sinajs.cn/list={code}"
