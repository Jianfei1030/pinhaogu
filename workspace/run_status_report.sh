#!/bin/bash
cd "$(dirname "$0")"

# 校验 Python 版本
version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>&1 || echo "")
if [ "$version" != "3.10" ]; then
    echo "[错误] Python 版本不匹配：当前为 $version，需要 3.10"
    exit 1
fi

source .env 2>/dev/null || true

while true; do
    time_hm=$(date +%H%M)
    date_str=$(date +%Y-%m-%d)

    # 交易日判断：使用 utils.trading_calendar.is_trading_day()
    is_trading=$(python3 -c "from utils.trading_calendar import is_trading_day; print('1' if is_trading_day() else '0')" 2>&1)

    if [ "$is_trading" != "1" ]; then
        echo "[$date_str] 休市日，跳过状态巡检"
    elif [[ "$time_hm" > "0858" && "$time_hm" < "2102" ]]; then
        python3 status_report.py 2>&1 | tee -a logs/status_report.log
    fi
    sleep 3600
done
