#!/bin/bash
#
# stock-monitor 一键启动脚本 (macOS)
# 启动后台三进程：server + monitor + daily_news_collector
# 同时检查 Ollama 依赖（端口 13145）是否可用
#
# 用法：cd workspace && ./start_all.sh
#

set -e

# 进入脚本所在目录
cd "$(dirname "$0")"

# 确保 logs 目录存在
mkdir -p logs

# 获取当前日期用于日志文件名
LOGDATE=$(date +%Y-%m-%d)

# 读取 server 端口配置（从 config.yaml 读取，默认 18805）
SERVER_PORT=$(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml')).get('web', {}).get('port', 18805))" 2>/dev/null || echo 18805)

echo "=========================================="
echo "  stock-monitor 启动脚本 (macOS)"
echo "  日期：$LOGDATE"
echo "  Server 端口：$SERVER_PORT"
echo "  说明：启动 server/monitor/news，检查 Ollama 依赖"
echo "=========================================="
echo ""

# 校验 Python 版本必须为 3.10
check_python_version() {
    local version
    version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>&1 || echo "")
    if [ "$version" != "3.10" ]; then
        echo "[错误] Python 版本不匹配：当前为 $version，需要 3.10"
        echo "请确保 python3 指向 Python 3.10"
        exit 1
    fi
    echo "[环境] Python 版本校验通过：$(python3 --version)"
}

# 检查进程是否已在运行
is_running() {
    local pattern="$1"
    if pgrep -f "$pattern" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 检查 Ollama 端口是否可用
check_ollama() {
    if nc -z 127.0.0.1 13145 > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 启动服务（如果未运行）
start_service() {
    local name="$1"
    local cmd="$2"
    local logfile="$3"
    
    if is_running "$name"; then
        echo "[跳过] $name 已在运行"
        return 0
    fi
    
    echo "[启动] $name..."
    nohup python3 -u $cmd >> "logs/$logfile" 2>&1 &
    local pid=$!
    echo "       PID: $pid, 日志：logs/$logfile"
    sleep 1
    
    # 检查进程是否成功启动
    if ps -p $pid > /dev/null 2>&1; then
        echo "[成功] $name 已启动"
    else
        echo "[失败] $name 启动失败，请检查日志：logs/$logfile"
        return 1
    fi
}

# 主流程
echo "[1/4] 校验 Python 版本..."
check_python_version
echo ""

echo "[2/4] 启动 server..."
start_service "server.py" "server.py" "server_${LOGDATE}.log"
sleep 2
echo ""

echo "[3/4] 启动 monitor..."
start_service "monitor.py" "monitor.py --config config.yaml --interval 60" "monitor_${LOGDATE}.log"
sleep 1
echo ""

echo "[4/4] 启动 news collector..."
start_service "daily_news_collector.py" "daily_news_collector.py --interval 600" "news_${LOGDATE}.log"
echo ""

echo "[5/4] 检查 Ollama 依赖..."
OLLAMA_OK=0
if check_ollama; then
    echo "[✓] Ollama 依赖正常 (端口 13145)"
else
    echo "[⚠] Ollama 未就绪 (端口 13145 不可达)"
    echo "    警告：Ollama 是新闻采集/embedding 去重的关键依赖"
    echo "    未就绪将影响新闻采集进度和去重效果"
    OLLAMA_OK=1
fi
echo ""

echo "=========================================="
echo "  所有服务已启动"
echo "=========================================="
echo ""
echo "  服务状态:"
echo "    • Server:  http://localhost:$SERVER_PORT"
echo "    • Monitor: 运行中 (60s 间隔)"
echo "    • News:    运行中 (600s 间隔)"
if [ $OLLAMA_OK -eq 0 ]; then
    echo "    • Ollama:  ✓ 依赖正常 (端口 13145)"
else
    echo "    • Ollama:  ⚠ 未就绪 (影响新闻采集/embedding 去重)"
fi
echo ""
echo "  日志文件:"
echo "    • logs/server_${LOGDATE}.log"
echo "    • logs/monitor_${LOGDATE}.log"
echo "    • logs/news_${LOGDATE}.log"
echo ""
echo "  查看进程:"
echo "    ps aux | grep -E 'server|monitor|daily_news'"
echo ""
echo "  健康检查:"
echo "    ./check_health.sh"
echo ""
echo "  状态监控:"
echo "    ./run_status_report.sh  # 后台状态检查 + 自动重启"
echo ""
