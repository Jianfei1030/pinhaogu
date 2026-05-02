#!/bin/bash
# 批量更新筹码分布数据

cd "$(dirname "$0")"

# 测试单只股票
echo "测试 300548..."
python3 batch_update_chip_data.py --symbols 300548 --timeout 300

# 运行全部
echo "运行全部股票..."
python3 batch_update_chip_data.py --timeout 1800
