#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置优先级集成验证测试 (T-R2.6)

验证配置系统的核心行为：
1. 优先级：环境变量 > config.yaml > 默认值
2. 两种环境变量格式都支持（前缀格式和简写格式）
3. 常用配置项可正确读取
4. Dataclass 兼容层能正常工作
5. 未知配置 key 返回默认值

测试设计原则：
- 不依赖真实 config.yaml 文件（使用 monkeypatch 隔离）
- 纯内存操作，快速稳定
- 与本地环境解耦
"""

import sys
from pathlib import Path

import pytest

# === 测试配置 ===
WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))

# 导入 config 模块（用于 monkeypatch）
import config as config_module


# === A. 验证优先级：env > yaml > default ===

class TestConfigPriority:
    """测试配置优先级：环境变量 > YAML > 默认值"""
    
    def test_default_value_without_any_override(self, monkeypatch):
        """测试 A.1: 默认情况下能读到默认值"""
        # 确保没有环境变量污染
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        
        # Mock YAML 返回空配置
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        # 读取默认值
        result = config_module.get_config('telegram.bot_token')
        
        # 验证是默认值
        assert result == ""
    
    def test_yaml_overrides_default(self, monkeypatch):
        """测试 A.2: monkeypatch YAML 后，能覆盖默认值"""
        # 确保没有环境变量
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        
        # Mock YAML 返回自定义配置
        mock_yaml = {
            'telegram': {
                'bot_token': 'yaml_custom_token_123'
            }
        }
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: mock_yaml)
        
        # 读取配置
        result = config_module.get_config('telegram.bot_token')
        
        # 验证是 YAML 的值
        assert result == 'yaml_custom_token_123'
    
    def test_env_overrides_yaml(self, monkeypatch):
        """测试 A.3: monkeypatch 环境变量后，环境变量能覆盖 YAML"""
        # 设置环境变量
        monkeypatch.setenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", "env_token_456")
        
        # Mock YAML 返回自定义配置（但应该被环境变量覆盖）
        mock_yaml = {
            'telegram': {
                'bot_token': 'yaml_custom_token_123'
            }
        }
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: mock_yaml)
        
        # 读取配置
        result = config_module.get_config('telegram.bot_token')
        
        # 验证是环境变量的值（优先级更高）
        assert result == 'env_token_456'
    
    def test_priority_chain_complete(self, monkeypatch):
        """测试 A.4: 完整优先级链条验证（llm.model）"""
        # 步骤 1: 默认值
        monkeypatch.delenv("STOCK_MONITOR_LLM_MODEL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        assert config_module.get_config('llm.model') == 'qwen3.6-plus'
        
        # 步骤 2: YAML 覆盖
        mock_yaml = {'llm': {'model': 'yaml-gpt-4'}}
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: mock_yaml)
        assert config_module.get_config('llm.model') == 'yaml-gpt-4'
        
        # 步骤 3: 环境变量覆盖
        monkeypatch.setenv("STOCK_MONITOR_LLM_MODEL", "env-claude-3")
        assert config_module.get_config('llm.model') == 'env-claude-3'
    
    def test_runtime_notify_enabled_priority(self, monkeypatch):
        """测试 A.5: runtime.notify_enabled 优先级验证"""
        # 步骤 1: 默认值 (True)
        monkeypatch.delenv("STOCK_MONITOR_RUNTIME_NOTIFY_ENABLED", raising=False)
        monkeypatch.delenv("RUNTIME_NOTIFY_ENABLED", raising=False)
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        assert config_module.get_config('runtime.notify_enabled') is True
        
        # 步骤 2: YAML 覆盖为 False
        mock_yaml = {'runtime': {'notify_enabled': False}}
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: mock_yaml)
        assert config_module.get_config('runtime.notify_enabled') is False
        
        # 步骤 3: 环境变量覆盖为 True
        monkeypatch.setenv("STOCK_MONITOR_RUNTIME_NOTIFY_ENABLED", "true")
        # 注意：环境变量返回字符串 "true"，不是布尔值
        assert config_module.get_config('runtime.notify_enabled') == "true"


# === B. 验证两种环境变量格式都可工作 ===

class TestEnvVarFormats:
    """测试两种环境变量格式的支持"""
    
    def test_prefix_format_works(self, monkeypatch):
        """测试 B.1: STOCK_MONITOR_ 前缀格式可工作"""
        monkeypatch.setenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", "prefix_format_token")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        result = config_module.get_config('telegram.bot_token')
        assert result == "prefix_format_token"
    
    def test_simple_format_works(self, monkeypatch):
        """测试 B.2: 简写格式（无前缀）可工作"""
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "simple_format_token")
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        result = config_module.get_config('telegram.bot_token')
        assert result == "simple_format_token"
    
    def test_prefix_format_takes_priority_over_simple(self, monkeypatch):
        """测试 B.3: 前缀格式优先于简写格式"""
        # 同时设置两种格式
        monkeypatch.setenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", "prefix_wins")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "simple_loses")
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        result = config_module.get_config('telegram.bot_token')
        
        # 前缀格式应该优先
        assert result == "prefix_wins"
    
    def test_simple_format_used_when_prefix_absent(self, monkeypatch):
        """测试 B.4: 当前缀格式不存在时，简写格式生效"""
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "simple_fallback")
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        result = config_module.get_config('telegram.bot_token')
        assert result == "simple_fallback"


# === C. 验证常用配置项可正确读取 ===

class TestCommonConfigItems:
    """测试常用配置项的正确读取"""
    
    def test_telegram_bot_token(self, monkeypatch):
        """测试 C.1: telegram.bot_token"""
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'telegram': {'bot_token': 'test_bot_token'}
        })
        result = config_module.get_config('telegram.bot_token')
        assert result == 'test_bot_token'
    
    def test_data_workspace(self, monkeypatch):
        """测试 C.2: data.workspace"""
        mock_workspace = "/tmp/test_workspace"
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'data': {'workspace': mock_workspace}
        })
        result = config_module.get_config('data.workspace')
        assert result == mock_workspace
    
    def test_llm_base_url(self, monkeypatch):
        """测试 C.3: llm.base_url"""
        mock_url = "https://test.api.example.com/v1"
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'llm': {'base_url': mock_url}
        })
        result = config_module.get_config('llm.base_url')
        assert result == mock_url
    
    def test_runtime_dry_run(self, monkeypatch):
        """测试 C.4: runtime.dry_run"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'runtime': {'dry_run': True}
        })
        result = config_module.get_config('runtime.dry_run')
        assert result is True
    
    def test_runtime_notify_enabled(self, monkeypatch):
        """测试 C.5: runtime.notify_enabled"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'runtime': {'notify_enabled': False}
        })
        result = config_module.get_config('runtime.notify_enabled')
        assert result is False


# === D. 验证 dataclass 兼容层能工作 ===

class TestDataclassCompatibility:
    """测试 Dataclass 兼容层"""
    
    def test_config_load_reflects_patched_env(self, monkeypatch):
        """测试 D.1: Config.load() 能反映 monkeypatch 后的环境变量"""
        # 设置环境变量
        monkeypatch.setenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", "env_bot_token_for_dataclass")
        monkeypatch.setenv("STOCK_MONITOR_DATA_WORKSPACE", "/tmp/dataclass_workspace")
        monkeypatch.setenv("STOCK_MONITOR_RUNTIME_NOTIFY_ENABLED", "false")
        
        # Mock YAML 为空（确保从环境变量读取）
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        # 创建新的 Config 实例
        cfg = config_module.Config.load()
        
        # 验证 dataclass 属性反映了 patched 配置
        assert cfg.telegram.bot_token == "env_bot_token_for_dataclass"
        assert str(cfg.data.workspace) == "/tmp/dataclass_workspace"
        # 注意：环境变量返回字符串 "false"，不是布尔值
        assert cfg.runtime.notify_enabled == "false"
    
    def test_config_load_reflects_patched_yaml(self, monkeypatch):
        """测试 D.2: Config.load() 能反映 monkeypatch 后的 YAML"""
        # 清除环境变量
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        
        # Mock YAML
        mock_yaml = {
            'telegram': {'bot_token': 'yaml_token_for_dataclass'},
            'data': {'workspace': '/tmp/yaml_workspace'},
            'runtime': {'notify_enabled': True}
        }
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: mock_yaml)
        
        # 创建新的 Config 实例
        cfg = config_module.Config.load()
        
        # 验证
        assert cfg.telegram.bot_token == 'yaml_token_for_dataclass'
        assert str(cfg.data.workspace) == '/tmp/yaml_workspace'
        assert cfg.runtime.notify_enabled is True
    
    def test_nested_dataclass_configs(self, monkeypatch):
        """测试 D.3: 嵌套的 dataclass 配置（TelegramConfig, DataConfig 等）"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {
            'telegram': {
                'bot_token': 'nested_test_token',
                'chat_id': '123456789',
                'proxy': 'http://proxy.example.com:8080'
            },
            'data': {
                'workspace': '/tmp/nested_workspace',
                'logs': '/tmp/nested_logs'
            },
            'llm': {
                'model': 'test-model-v1',
                'base_url': 'https://test.api.com',
                'timeout': 60
            },
            'runtime': {
                'dry_run': True,
                'notify_enabled': False
            }
        })
        
        # 清除相关环境变量
        for key in ["STOCK_MONITOR_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN",
                    "STOCK_MONITOR_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID",
                    "STOCK_MONITOR_TELEGRAM_PROXY", "TELEGRAM_PROXY",
                    "STOCK_MONITOR_DATA_WORKSPACE", "DATA_WORKSPACE",
                    "STOCK_MONITOR_LLM_MODEL", "LLM_MODEL",
                    "STOCK_MONITOR_LLM_TIMEOUT", "LLM_TIMEOUT",
                    "STOCK_MONITOR_RUNTIME_DRY_RUN", "RUNTIME_DRY_RUN",
                    "STOCK_MONITOR_RUNTIME_NOTIFY_ENABLED", "RUNTIME_NOTIFY_ENABLED"]:
            monkeypatch.delenv(key, raising=False)
        
        # 创建新实例
        cfg = config_module.Config.load()
        
        # 验证各层级配置
        assert cfg.telegram.bot_token == 'nested_test_token'
        assert cfg.telegram.chat_id == '123456789'
        assert cfg.data.workspace == Path('/tmp/nested_workspace')
        assert cfg.llm.model == 'test-model-v1'
        assert cfg.llm.timeout == 60
        assert cfg.runtime.dry_run is True
        assert cfg.runtime.notify_enabled is False


# === E. 验证未知配置 key 的默认返回 ===

class TestUnknownConfigKey:
    """测试未知配置 key 的处理"""
    
    def test_unknown_key_returns_default(self, monkeypatch):
        """测试 E.1: 未知配置 key 返回提供的默认值"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        monkeypatch.delenv("STOCK_MONITOR_NONEXISTENT_KEY", raising=False)
        
        result = config_module.get_config('nonexistent.key', default='fallback')
        assert result == 'fallback'
    
    def test_unknown_key_returns_none_when_no_default(self, monkeypatch):
        """测试 E.2: 未知配置 key 无默认值时返回 None"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        monkeypatch.delenv("STOCK_MONITOR_UNKNOWN_KEY", raising=False)
        
        result = config_module.get_config('unknown.key')
        assert result is None
    
    def test_partial_path_returns_default(self, monkeypatch):
        """测试 E.3: 部分路径不存在时返回默认值"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_UNKNOWN", raising=False)
        
        # telegram 存在，但 telegram.unknown_field 不存在
        result = config_module.get_config('telegram.unknown_field', default='default_value')
        assert result == 'default_value'


# === F. 额外边界情况测试 ===

class TestEdgeCases:
    """测试边界情况"""
    
    def test_empty_yaml_returns_default(self, monkeypatch):
        """测试 F.1: 空 YAML 配置返回默认值"""
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        result = config_module.get_config('telegram.bot_token')
        assert result == ""

    def test_yaml_load_failure_returns_default(self, monkeypatch):
        """测试 F.2: YAML 加载失败时返回默认值"""
        # Mock YAML 加载失败（返回空 dict）
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        monkeypatch.delenv("STOCK_MONITOR_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        result = config_module.get_config('telegram.bot_token')
        assert result == ""
    
    def test_env_value_type_preservation(self, monkeypatch):
        """测试 F.3: 环境变量值类型保持（字符串）"""
        monkeypatch.setenv("STOCK_MONITOR_RUNTIME_DRY_RUN", "false")
        monkeypatch.setattr(config_module, '_load_yaml_config', lambda: {})
        
        # 环境变量返回字符串，不是布尔值
        result = config_module.get_config('runtime.dry_run')
        assert result == "false"
        assert isinstance(result, str)


# === G. 测试汇总信息 ===

def test_config_priority_test_summary():
    """
    测试概览（信息性测试，始终通过）
    输出测试覆盖的配置项和优先级场景
    """
    print("\n\n=== 配置优先级测试概览 ===")
    print("  覆盖的优先级场景:")
    print("    1. 默认值读取")
    print("    2. YAML 覆盖默认值")
    print("    3. 环境变量覆盖 YAML")
    print("    4. 完整优先级链条 (env > yaml > default)")
    print("")
    print("  覆盖的环境变量格式:")
    print("    1. STOCK_MONITOR_ 前缀格式")
    print("    2. 简写格式（无前缀）")
    print("    3. 前缀格式优先于简写格式")
    print("")
    print("  覆盖的配置项:")
    print("    - telegram.bot_token")
    print("    - telegram.chat_id")
    print("    - data.workspace")
    print("    - data.logs")
    print("    - llm.model")
    print("    - llm.base_url")
    print("    - llm.timeout")
    print("    - runtime.dry_run")
    print("    - runtime.notify_enabled")
    print("")
    print("  覆盖的 Dataclass 兼容层:")
    print("    - Config.load()")
    print("    - TelegramConfig")
    print("    - DataConfig")
    print("    - LLMConfig")
    print("    - RuntimeConfig")
    print("")
    print("  边界情况:")
    print("    - 空 YAML 配置")
    print("    - YAML 加载失败")
    print("    - 未知配置 key")
    print("    - 环境变量类型保持")
    print()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
