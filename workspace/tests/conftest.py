# -*- coding: utf-8 -*-
"""
Pytest 配置文件

自动添加 workspace 目录到 Python 路径，使测试可以导入 workspace 模块
"""
import os
import sys
from pathlib import Path

# 添加 workspace 目录到 Python 路径
_workspace_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_workspace_dir))

# 设置环境变量
os.environ.setdefault("PYTHONPATH", str(_workspace_dir))
