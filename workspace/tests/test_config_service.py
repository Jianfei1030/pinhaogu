# -*- coding: utf-8 -*-
"""
Config Service 独立单元测试

纯内存测试，不依赖 FastAPI，不依赖真实 config 文件。
使用 monkeypatch 隔离外部依赖。
"""
import os
import sys

# 添加工作区到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services import config_service
from services.config_service import (
    ConfigServiceError,
    get_analysis_model,
    build_config_payload,
)


# =============================================================================
# A. 基础接口与异常测试
# =============================================================================

def test_module_imports():
    """模块可导入"""
    assert config_service is not None
    assert ConfigServiceError is not None
    assert get_analysis_model is not None
    assert build_config_payload is not None


def test_config_service_error_exists():
    """ConfigServiceError 异常类存在"""
    assert issubclass(ConfigServiceError, Exception)


# =============================================================================
# B. get_analysis_model 测试
# =============================================================================

def test_get_analysis_model_import_success(monkeypatch):
    """正常导入 LLM_MODEL -> 返回模型名"""
    # 创建一个 fake 的 daily_sector_pipeline 模块
    fake_module = type(sys)('daily_sector_pipeline')
    fake_module.LLM_MODEL = 'qwen-plus'
    monkeypatch.setitem(sys.modules, 'daily_sector_pipeline', fake_module)
    
    result = get_analysis_model(default='unknown')
    
    assert result == 'qwen-plus'
    assert isinstance(result, str)


def test_get_analysis_model_import_error(monkeypatch):
    """ImportError -> 返回 default"""
    # 确保模块不存在
    monkeypatch.delitem(sys.modules, 'daily_sector_pipeline', raising=False)
    
    # 使用一个简单的 ImportError 模拟：直接让 from ... import 失败
    # 通过设置 sys.modules 为一个会抛 ImportError 的占位符
    class ImportFailingModule:
        def __getattr__(self, name):
            raise ImportError(f"cannot import name '{name}' from 'daily_sector_pipeline'")
    
    monkeypatch.setitem(sys.modules, 'daily_sector_pipeline', ImportFailingModule())
    
    result = get_analysis_model(default='my-default-model')
    
    assert result == 'my-default-model'


def test_get_analysis_model_other_exception(monkeypatch):
    """其他异常 -> 返回 default"""
    # 创建一个 fake 模块，但访问 LLM_MODEL 时会抛异常
    class FaultyModule:
        @property
        def LLM_MODEL(self):
            raise ValueError("Something went wrong")
    
    monkeypatch.setitem(sys.modules, 'daily_sector_pipeline', FaultyModule())
    
    result = get_analysis_model(default='fallback')
    
    assert result == 'fallback'


def test_get_analysis_model_default_parameter(monkeypatch):
    """默认参数为 'unknown'"""
    # 确保模块不存在，使用 monkeypatch 保证隔离
    monkeypatch.delitem(sys.modules, 'daily_sector_pipeline', raising=False)
    
    # 模拟一个会抛 ImportErrors 的模块占位符
    class ImportFailingModule:
        def __getattr__(self, name):
            raise ImportError(f"cannot import name '{name}' from 'daily_sector_pipeline'")
    
    monkeypatch.setitem(sys.modules, 'daily_sector_pipeline', ImportFailingModule())
    
    result = get_analysis_model()
    
    assert result == 'unknown'


def test_get_analysis_model_module_exists_no_llm_model(monkeypatch):
    """模块存在但 LLM_MODEL 不存在 -> 返回 default"""
    fake_module = type(sys)('daily_sector_pipeline')
    # 不设置 LLM_MODEL
    monkeypatch.setitem(sys.modules, 'daily_sector_pipeline', fake_module)
    
    result = get_analysis_model(default='unknown')
    
    assert result == 'unknown'


# =============================================================================
# C. build_config_payload 测试
# =============================================================================

def test_build_config_payload_basic():
    """fake config_loader 返回 dict -> 保留原字段并补 analysisModel"""
    def fake_loader():
        return {
            'watchlist': ['000001.SZ', '600519.SH'],
            'periods': ['5m', '15m', '1h']
        }
    
    result = build_config_payload(fake_loader)
    
    assert isinstance(result, dict)
    assert 'watchlist' in result
    assert 'periods' in result
    assert 'analysisModel' in result
    assert result['watchlist'] == ['000001.SZ', '600519.SH']
    assert result['periods'] == ['5m', '15m', '1h']


def test_build_config_payload_complex_structure():
    """config_loader 返回复杂结构时，结构不丢失"""
    def fake_loader():
        return {
            'watchlist': ['000001.SZ'],
            'periods': ['5m'],
            'alerts': [
                {'id': 1, 'condition': {'indicator': 'macd', 'op': '>', 'value': 0}},
                {'id': 2, 'condition': {'indicator': 'rsi', 'op': '<', 'value': 30}}
            ],
            'settings': {
                'notify': True,
                'channel': 'telegram'
            }
        }
    
    result = build_config_payload(fake_loader)
    
    assert isinstance(result, dict)
    assert 'watchlist' in result
    assert 'periods' in result
    assert 'alerts' in result
    assert 'settings' in result
    assert 'analysisModel' in result
    assert len(result['alerts']) == 2
    assert result['settings']['notify'] is True
    assert result['settings']['channel'] == 'telegram'


def test_build_config_payload_analysis_model_field():
    """analysisModel 字段存在且为字符串"""
    def fake_loader():
        return {'foo': 'bar'}
    
    result = build_config_payload(fake_loader)
    
    assert 'analysisModel' in result
    assert isinstance(result['analysisModel'], str)


def test_build_config_payload_does_not_overwrite():
    """analysisModel 被补进来而不是覆盖其它字段"""
    def fake_loader():
        return {
            'existing_field': 'existing_value',
            'another_field': {'nested': 'data'}
        }
    
    result = build_config_payload(fake_loader)
    
    assert result['existing_field'] == 'existing_value'
    assert result['another_field'] == {'nested': 'data'}
    assert 'analysisModel' in result
    assert len(result) == 3  # existing_field + another_field + analysisModel


def test_build_config_payload_loader_raises(monkeypatch):
    """config_loader 抛异常时，异常向上传播"""
    def fake_loader():
        raise ValueError("Config loading failed")
    
    with pytest.raises(ValueError, match="Config loading failed"):
        build_config_payload(fake_loader)


def test_build_config_payload_empty_config():
    """config_loader 返回空 dict 也能正常工作"""
    def fake_loader():
        return {}
    
    result = build_config_payload(fake_loader)
    
    assert isinstance(result, dict)
    assert 'analysisModel' in result
    assert len(result) == 1


# =============================================================================
# D. 兼容性测试
# =============================================================================

def test_return_type_is_dict():
    """返回值始终是 dict"""
    def fake_loader():
        return {'test': 'data'}
    
    result = build_config_payload(fake_loader)
    assert isinstance(result, dict)


def test_original_config_preserved():
    """原始 config 内容仍在"""
    original = {
        'key1': 'value1',
        'key2': ['list', 'of', 'values'],
        'key3': {'nested': 'dict'}
    }
    
    def fake_loader():
        return original.copy()
    
    result = build_config_payload(fake_loader)
    
    assert result['key1'] == 'value1'
    assert result['key2'] == ['list', 'of', 'values']
    assert result['key3'] == {'nested': 'dict'}


def test_analysis_model_appended_not_replacing():
    """analysisModel 被追加而不是替换"""
    def fake_loader():
        return {'field1': 'val1', 'field2': 'val2'}
    
    result = build_config_payload(fake_loader)
    
    assert 'field1' in result
    assert 'field2' in result
    assert 'analysisModel' in result
    assert len(result) == 3
