#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Service 层集成验证测试 (T-R4.5)

测试目标：
- 验证所有 service 模块可导入
- 验证 runtime_state_service 的 monkeypatch 能力
- 验证 trading_calendar_service 的节假日判断逻辑
- 验证 push_service 在无副作用情况下的行为
- 验证 llm_service 在无真实网络情况下的行为

约束：
- 所有测试必须纯内存 / monkeypatch 驱动
- 不依赖真实网络、真实 openclaw CLI、真实 Telegram、真实 API key
"""
import os
import sys
from pathlib import Path

# 确保能导入 workspace 模块
WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(WORKSPACE_ROOT))

import pytest


# =============================================================================
# A. 导入与导出验证
# =============================================================================

class TestImports:
    """测试模块导入与导出"""
    
    def test_runtime_state_service_importable(self):
        """验证 runtime_state_service 可导入"""
        from services import runtime_state_service
        assert hasattr(runtime_state_service, 'is_dry_run')
        assert hasattr(runtime_state_service, 'is_notify_enabled')
        assert hasattr(runtime_state_service, 'get_runtime_flags')
    
    def test_trading_calendar_service_importable(self):
        """验证 trading_calendar_service 可导入"""
        from services import trading_calendar_service
        assert hasattr(trading_calendar_service, 'is_holiday')
        assert hasattr(trading_calendar_service, 'is_trading_day')
    
    def test_push_service_importable(self):
        """验证 push_service 可导入"""
        from services import push_service
        assert hasattr(push_service, 'send_telegram')
        assert hasattr(push_service, 'send_qq')
        assert hasattr(push_service, 'send_both')
    
    def test_llm_service_importable(self):
        """验证 llm_service 可导入"""
        from services import llm_service
        assert hasattr(llm_service, 'get_api_key')
        assert hasattr(llm_service, 'chat_completion')
        assert hasattr(llm_service, 'chat_completion_raw')
    
    def test_services_init_exports(self):
        """验证 services/__init__.py 导出正确"""
        from services import is_dry_run, is_notify_enabled, get_runtime_flags
        assert callable(is_dry_run)
        assert callable(is_notify_enabled)
        assert callable(get_runtime_flags)


# =============================================================================
# B. runtime_state_service 测试
# =============================================================================

class TestRuntimeStateService:
    """测试 runtime_state_service"""
    
    def test_is_dry_run_monkeypatch_true(self, monkeypatch):
        """验证 is_dry_run() 能反映 patched 值 (True)"""
        from services.runtime_state_service import config
        
        # Monkeypatch config
        monkeypatch.setattr(config.runtime, 'dry_run', True)
        
        from services.runtime_state_service import is_dry_run
        assert is_dry_run() is True
    
    def test_is_dry_run_monkeypatch_false(self, monkeypatch):
        """验证 is_dry_run() 能反映 patched 值 (False)"""
        from services.runtime_state_service import config
        
        # Monkeypatch Config
        monkeypatch.setattr(config.runtime, 'dry_run', False)
        
        # 需要重新导入以获取最新值
        import importlib
        from services import runtime_state_service
        importlib.reload(runtime_state_service)
        
        assert runtime_state_service.is_dry_run() is False
    
    def test_is_notify_enabled_monkeypatch(self, monkeypatch):
        """验证 is_notify_enabled() 能反映 patched 值"""
        from services.runtime_state_service import config
        
        monkeypatch.setattr(config.runtime, 'notify_enabled', True)
        
        import importlib
        from services import runtime_state_service
        importlib.reload(runtime_state_service)
        
        assert runtime_state_service.is_notify_enabled() is True
    
    def test_get_runtime_flags(self, monkeypatch):
        """验证 get_runtime_flags() 返回完整快照"""
        from services.runtime_state_service import config
        
        monkeypatch.setattr(config.runtime, 'dry_run', True)
        monkeypatch.setattr(config.runtime, 'notify_enabled', False)
        
        import importlib
        from services import runtime_state_service
        importlib.reload(runtime_state_service)
        
        flags = runtime_state_service.get_runtime_flags()
        assert flags == {
            "dry_run": True,
            "notify_enabled": False,
        }


# =============================================================================
# C. trading_calendar_service 测试
# =============================================================================

class TestTradingCalendarService:
    """测试 trading_calendar_service"""
    
    def test_is_trading_day_2026_04_06(self):
        """验证 2026-04-06 (清明调休) 为非交易日"""
        from services.trading_calendar_service import is_trading_day
        assert is_trading_day('2026-04-06') is False
    
    def test_is_trading_day_2026_04_07(self):
        """验证 2026-04-07 (普通周二) 为交易日"""
        from services.trading_calendar_service import is_trading_day
        assert is_trading_day('2026-04-07') is True
    
    def test_is_trading_day_weekend(self):
        """验证周末为非交易日 (2026-04-05 周日)"""
        from services.trading_calendar_service import is_trading_day
        # 2026-04-05 是周日
        assert is_trading_day('2026-04-05') is False
    
    def test_is_trading_day_saturday(self):
        """验证周六为非交易日 (2026-04-04)"""
        from services.trading_calendar_service import is_trading_day
        # 2026-04-04 是周六
        assert is_trading_day('2026-04-04') is False
    
    def test_is_holiday_2026_04_06(self):
        """验证 is_holiday('2026-04-06') 返回 True"""
        from services.trading_calendar_service import is_holiday
        assert is_holiday('2026-04-06') is True
    
    def test_is_holiday_2026_04_07(self):
        """验证 is_holiday('2026-04-07') 返回 False"""
        from services.trading_calendar_service import is_holiday
        assert is_holiday('2026-04-07') is False


# =============================================================================
# D. push_service 测试 (无副作用)
# =============================================================================

class TestPushService:
    """测试 push_service (使用 monkeypatch 避免真实网络调用)"""
    
    def test_send_telegram_success(self, monkeypatch):
        """验证 send_telegram 成功场景"""
        # Fake response with raise_for_status method
        class FakeResponse:
            def raise_for_status(self):
                pass  # 不抛异常表示成功
        
        def fake_post(*args, **kwargs):
            return FakeResponse()
        
        monkeypatch.setattr('requests.post', fake_post)
        
        from services.push_service import send_telegram
        result = send_telegram("测试消息")
        assert result is True
    
    def test_send_telegram_failure(self, monkeypatch):
        """验证 send_telegram 失败场景 (requests.post 抛异常)"""
        import requests
        
        def fake_post_raises(*args, **kwargs):
            raise requests.exceptions.RequestException("网络错误")
        
        monkeypatch.setattr('requests.post', fake_post_raises)
        
        from services.push_service import send_telegram
        result = send_telegram("测试消息")
        assert result is False
    
    def test_send_qq_success(self, monkeypatch):
        """验证 send_qq 成功场景"""
        import subprocess
        
        class FakeCompletedProcess:
            returncode = 0
            stdout = b""
            stderr = None
        
        def fake_run(*args, **kwargs):
            return FakeCompletedProcess()
        
        monkeypatch.setattr('subprocess.run', fake_run)
        
        from services.push_service import send_qq
        result = send_qq("测试消息")
        assert result is True
    
    def test_send_qq_failure(self, monkeypatch):
        """验证 send_qq 失败场景 (subprocess.run 抛异常)"""
        import subprocess
        
        def fake_run_raises(*args, **kwargs):
            raise subprocess.CalledProcessError(1, ['openclaw'], stderr=b"error")
        
        monkeypatch.setattr('subprocess.run', fake_run_raises)
        
        from services.push_service import send_qq
        result = send_qq("测试消息")
        assert result is False
    
    def test_send_both(self, monkeypatch):
        """验证 send_both 返回正确的 tuple"""
        from services.push_service import send_telegram, send_qq
        
        # Monkeypatch 两个函数本身
        monkeypatch.setattr('services.push_service.send_telegram', lambda msg: True)
        monkeypatch.setattr('services.push_service.send_qq', lambda msg: False)
        
        from services.push_service import send_both
        tg_result, qq_result = send_both("测试消息")
        assert tg_result is True
        assert qq_result is False
        assert isinstance((tg_result, qq_result), tuple)


# =============================================================================
# E. llm_service 测试 (无真实网络)
# =============================================================================

class TestLLMService:
    """测试 llm_service (使用 monkeypatch 避免真实网络调用)"""
    
    def test_get_api_key_exists(self, monkeypatch):
        """验证 get_api_key() 在环境变量存在时返回 key"""
        monkeypatch.setenv('BAILIAN_API_KEY', 'test-fake-api-key-12345')
        
        # 清除可能的缓存
        if 'services.llm_service' in sys.modules:
            import importlib
            import services.llm_service
            importlib.reload(services.llm_service)
        
        from services.llm_service import get_api_key
        key = get_api_key()
        assert key == 'test-fake-api-key-12345'
    
    def test_get_api_key_not_exists(self, monkeypatch):
        """验证 get_api_key() 在环境变量不存在时抛 RuntimeError"""
        # 移除环境变量
        monkeypatch.delenv('BAILIAN_API_KEY', raising=False)
        
        # 重新加载模块以读取新的环境变量
        if 'services.llm_service' in sys.modules:
            import importlib
            import services.llm_service
            importlib.reload(services.llm_service)
        
        from services.llm_service import get_api_key
        
        with pytest.raises(RuntimeError, match="API Key 未设置"):
            get_api_key()
    
    def test_chat_completion(self, monkeypatch):
        """验证 chat_completion() 返回正确的 string"""
        import json
        import urllib.request
        
        # Fake API key
        monkeypatch.setenv('BAILIAN_API_KEY', 'fake-key')
        
        # Fake opener
        class FakeResponse:
            def read(self):
                return json.dumps({
                    "choices": [{
                        "message": {
                            "content": "这是模拟的 LLM 响应"
                        }
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20
                    }
                }).encode('utf-8')
        
        class FakeOpener:
            def open(self, req, timeout=None):
                return FakeResponse()
        
        def fake_build_opener(*handlers):
            return FakeOpener()
        
        monkeypatch.setattr('urllib.request.build_opener', fake_build_opener)
        
        # 重新加载模块
        if 'services.llm_service' in sys.modules:
            import importlib
            import services.llm_service
            importlib.reload(services.llm_service)
        
        from services.llm_service import chat_completion
        
        result = chat_completion(
            system_prompt="你是助手",
            user_prompt="你好",
            verbose=False
        )
        
        assert result == "这是模拟的 LLM 响应"
        assert isinstance(result, str)
    
    def test_chat_completion_raw(self, monkeypatch):
        """验证 chat_completion_raw() 返回完整的 dict"""
        import json
        import urllib.request
        
        # Fake API key
        monkeypatch.setenv('BAILIAN_API_KEY', 'fake-key')
        
        expected_response = {
            "choices": [{
                "message": {
                    "content": "这是模拟的 LLM 响应"
                }
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20
            },
            "model": "qwen3.5-plus"
        }
        
        class FakeResponse:
            def read(self):
                return json.dumps(expected_response).encode('utf-8')
        
        class FakeOpener:
            def open(self, req, timeout=None):
                return FakeResponse()
        
        def fake_build_opener(*handlers):
            return FakeOpener()
        
        monkeypatch.setattr('urllib.request.build_opener', fake_build_opener)
        
        # 重新加载模块
        if 'services.llm_service' in sys.modules:
            import importlib
            import services.llm_service
            importlib.reload(services.llm_service)
        
        from services.llm_service import chat_completion_raw
        
        result = chat_completion_raw(
            messages=[
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "你好"}
            ],
            verbose=False
        )
        
        assert isinstance(result, dict)
        assert "choices" in result
        assert "usage" in result
        assert result["choices"][0]["message"]["content"] == "这是模拟的 LLM 响应"


# =============================================================================
# 主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
