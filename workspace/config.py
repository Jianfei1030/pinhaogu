#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置管理模块

配置优先级：环境变量 > config.yaml > 代码默认值

用法:
    from config import config, get_config
    
    # 方式 1: 对象属性访问（向后兼容）
    config.telegram.bot_token
    config.telegram.chat_id
    config.qq.target
    config.data.a_stock_list
    
    # 方式 2: 统一接口（推荐新用法）
    get_config('telegram.bot_token')
    get_config('qq.target')
    get_config('data.workspace')
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional
import yaml

# Load .env file for local development (secrets are not committed to repo)
try:
    from dotenv import load_dotenv
    # Try workspace/.env first, then parent directory
    _env_path = Path(__file__).parent / ".env"
    if not _env_path.exists():
        _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed, rely on environment variables


# ===== 配置加载核心逻辑 =====

def _load_yaml_config() -> dict:
    """从 config.yaml 加载配置"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _get_env_value(key: str) -> Optional[str]:
    """从环境变量获取值"""
    return os.environ.get(key)


def _merge_configs(defaults: dict, yaml_config: dict) -> dict:
    """
    合并配置：yaml 覆盖默认值
    支持嵌套字典的浅合并
    """
    result = defaults.copy()
    for key, value in yaml_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def get_config(key: str, default: Any = None) -> Any:
    """
    统一配置读取接口
    
    优先级：环境变量 > config.yaml > 默认值
    
    Args:
        key: 配置键，支持点号分隔（如 'telegram.bot_token'）
        default: 默认值（当配置不存在时返回）
    
    Returns:
        配置值
    
    Examples:
        get_config('telegram.bot_token')
        get_config('qq.target', default='default_target')
        get_config('data.workspace')
    """
    keys = key.split('.')
    
    # 1. 先尝试环境变量（支持两种格式）
    # 格式 1: STOCK_MONITOR_TELEGRAM_BOT_TOKEN
    env_key_upper = f"STOCK_MONITOR_{'_'.join(keys).upper()}"
    env_value = _get_env_value(env_key_upper)
    if env_value is not None:
        return env_value
    
    # 格式 2: 直接匹配（如 TELEGRAM_BOT_TOKEN）
    env_key_simple = '_'.join(keys).upper()
    env_value = _get_env_value(env_key_simple)
    if env_value is not None:
        return env_value
    
    # 2. 从 yaml 配置读取
    yaml_config = _load_yaml_config()
    value = yaml_config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            value = None
            break
    if value is not None:
        return value
    
    # 3. 从默认配置读取
    default_config = _get_default_config()
    value = default_config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


def _get_default_config() -> dict:
    """获取默认配置字典"""
    return {
        'web': {
            'port': 18805,
        },
        'telegram': {
            'bot_token': "",
            'chat_id': "",
            'proxy': None,
        },
        'qq': {
            'target': "",
            'account': "guzi",
        },
        'data': {
            'a_stock_list': "data/a_stock_list.json",
            'workspace': str(Path(__file__).parent),
            'logs': str(Path(__file__).parent / "logs"),
            'root': "data",  # 数据根目录（相对 workspace）
            'board_db': "data/board",  # 板块数据库目录
            'reports': "reports",  # 报告输出目录
            'news': "news_data",  # 新闻数据目录
        },
        'llm': {
            # 阿里百炼 Coding Plan API 配置
            'model': "qwen3.6-plus",
            'base_url': "https://coding.dashscope.aliyuncs.com/v1",
            'api_key_env': "BAILIAN_API_KEY",  # 环境变量名称
            'proxy': None,
            'timeout': 120,
        },
        'runtime': {
            # 全局运行时开关
            'dry_run': False,  # 默认关闭 dry-run（生产环境正常保存/推送）
            'notify_enabled': True,  # 默认开启推送
        },
    }


# ===== Dataclass 风格配置（向后兼容） =====

@dataclass
class TelegramConfig:
    """Telegram 配置"""
    bot_token: str = field(default_factory=lambda: get_config('telegram.bot_token'))
    chat_id: str = field(default_factory=lambda: get_config('telegram.chat_id'))
    proxy: str = field(default_factory=lambda: get_config('telegram.proxy'))


@dataclass
class QQConfig:
    """QQ 推送配置"""
    target: str = field(default_factory=lambda: get_config('qq.target'))
    account: str = field(default_factory=lambda: get_config('qq.account'))


@dataclass
class DataConfig:
    """数据路径配置"""
    a_stock_list: str = field(default_factory=lambda: get_config('data.a_stock_list'))
    workspace: Path = field(default_factory=lambda: Path(get_config('data.workspace', str(Path(__file__).parent))))
    logs: Path = field(default_factory=lambda: Path(get_config('data.logs', str(Path(__file__).parent / "logs"))))
    root: str = field(default_factory=lambda: get_config('data.root', "data"))
    board_db: str = field(default_factory=lambda: get_config('data.board_db', "data/board"))
    reports: str = field(default_factory=lambda: get_config('data.reports', "reports"))
    news: str = field(default_factory=lambda: get_config('data.news', "news_data"))
    
    @property
    def a_stock_list_path(self) -> Path:
        return self.workspace / self.a_stock_list
    
    @property
    def data_root(self) -> Path:
        """数据根目录"""
        return self.workspace / self.root
    
    @property
    def board_db_dir(self) -> Path:
        """板块数据库目录"""
        return self.workspace / self.board_db
    
    @property
    def reports_dir(self) -> Path:
        """报告输出目录"""
        return self.workspace / self.reports
    
    @property
    def news_dir(self) -> Path:
        """新闻数据目录"""
        return self.workspace / self.news


@dataclass
class LLMConfig:
    """LLM 配置（阿里百炼 Coding Plan API）"""
    model: str = field(default_factory=lambda: get_config('llm.model'))
    base_url: str = field(default_factory=lambda: get_config('llm.base_url'))
    api_key_env: str = field(default_factory=lambda: get_config('llm.api_key_env'))
    proxy: str = field(default_factory=lambda: get_config('llm.proxy'))
    timeout: int = field(default_factory=lambda: get_config('llm.timeout', 120))
    
    @property
    def api_key(self) -> str:
        """从环境变量读取 API Key"""
        import os
        return os.environ.get(self.api_key_env, "")
    
    @property
    def proxy_dict(self) -> dict:
        """代理字典格式"""
        return {"http": self.proxy, "https": self.proxy}


@dataclass
class RuntimeConfig:
    """运行时配置（全局开关）"""
    dry_run: bool = field(default_factory=lambda: get_config('runtime.dry_run', False))
    notify_enabled: bool = field(default_factory=lambda: get_config('runtime.notify_enabled', True))


@dataclass
class WatchlistConfig:
    """监控股配置"""
    market: str = ""
    symbol: str = ""
    name: str = ""


@dataclass
class Config:
    """全局配置"""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    qq: QQConfig = field(default_factory=QQConfig)
    data: DataConfig = field(default_factory=DataConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    watchlist: list = field(default_factory=lambda: get_config('watchlist', []))
    
    @classmethod
    def load(cls) -> 'Config':
        """加载配置（单例模式）"""
        return cls()


# 全局配置实例
config = Config.load()


# ===== 向后兼容：保留旧的全局变量 =====
# 旧代码可以直接使用这些变量，无需修改

TELEGRAM_BOT_TOKEN = config.telegram.bot_token
TELEGRAM_CHAT_ID = config.telegram.chat_id
TELEGRAM_PROXY = {"http": config.telegram.proxy, "https": config.telegram.proxy}

QQ_TARGET = config.qq.target
QQ_ACCOUNT = config.qq.account

A_STOCK_LIST = config.data.a_stock_list
WORKSPACE = config.data.workspace
LOGS_DIR = config.data.logs

# LLM 配置（阿里百炼 Coding Plan API）
LLM_MODEL = config.llm.model
LLM_BASE_URL = config.llm.base_url
LLM_PROXY = config.llm.proxy_dict
LLM_TIMEOUT = config.llm.timeout
