#!/bin/bash
#
# pinhaogu 健康检查脚本 (macOS)
# 检查四件套运行状态（server/monitor/news/ollama）+ 端口监听 + 日志摘要
#
# 用法：cd workspace && ./check_health.sh
#

set -e

# 进入脚本所在目录
cd "$(dirname "$0")"

# 读取 server 端口配置（从 config.yaml 读取，默认 18805）
SERVER_PORT=$(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml')).get('web', {}).get('port', 18805))" 2>/dev/null || echo 18805)

echo "=========================================="
echo "  pinhaogu 健康检查"
echo "  时间：$(date '+%Y-%m-%d %H:%M:%S')"
echo "  Server 端口：$SERVER_PORT"
echo "=========================================="
echo ""

# 检查进程状态
check_process() {
    local name="$1"
    local pattern="$2"
    
    if pgrep -f "$pattern" > /dev/null 2>&1; then
        local pid=$(pgrep -f "$pattern" | head -1)
        echo "[✓] $name 运行中 (PID: $pid)"
        return 0
    else
        echo "[✗] $name 未运行"
        return 1
    fi
}

# 检查端口监听
check_port() {
    local port="$1"
    local service="$2"
    
    if lsof -i :$port > /dev/null 2>&1; then
        local info=$(lsof -i :$port | grep LISTEN | head -1)
        echo "[✓] 端口 $port 监听中 ($service)"
        echo "    $info"
        return 0
    else
        echo "[✗] 端口 $port 未监听 ($service)"
        return 1
    fi
}

# 显示最近日志
show_recent_logs() {
    local logfile="$1"
    local name="$2"
    
    if [ -f "$logfile" ]; then
        local size=$(du -h "$logfile" | cut -f1)
        local lines=$(wc -l < "$logfile")
        echo "[✓] $name 存在 ($size, $lines 行)"
        
        # 显示最后 3 行
        echo "    最近日志:"
        tail -n 3 "$logfile" | while read line; do
            echo "      $line"
        done
    else
        echo "[ ] $name 不存在"
    fi
}

# 检查 Ollama 端口
check_ollama() {
    if nc -z 127.0.0.1 13145 > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 主检查流程
echo "=== 进程状态 ==="
SERVER_OK=0
MONITOR_OK=0
NEWS_OK=0
OLLAMA_OK=0

check_process "server.py" "server.py" || SERVER_OK=1
check_process "monitor.py" "monitor.py --config config.yaml" || MONITOR_OK=1
check_process "daily_news_collector.py" "daily_news_collector.py" || NEWS_OK=1

# 检查 Ollama（端口 13145）
if check_ollama; then
    echo "[✓] Ollama 运行中 (端口 13145)"
else
    echo "[✗] Ollama 未运行 (端口 13145 未监听)"
    OLLAMA_OK=1
fi

echo ""
echo "=== 端口监听 ==="
PORT_OK=0
check_port "$SERVER_PORT" "server" || PORT_OK=1

echo ""
echo "=== 日志文件 ==="
LOGDATE=$(date +%Y-%m-%d)

# 查找最近的日志文件（可能是今天的，也可能是昨天的）
for prefix in server monitor news; do
    logfile=$(ls -t "logs/${prefix}_"*.log 2>/dev/null | head -1)
    if [ -n "$logfile" ] && [ -f "$logfile" ]; then
        show_recent_logs "$logfile" "$prefix"
    else
        echo "[ ] $prefix 日志文件未找到"
    fi
done

echo ""
echo "=== 状态摘要 ==="

# 统计结果
TOTAL_CHECKS=5
PASSED_CHECKS=0

[ $SERVER_OK -eq 0 ] && PASSED_CHECKS=$((PASSED_CHECKS + 1))
[ $MONITOR_OK -eq 0 ] && PASSED_CHECKS=$((PASSED_CHECKS + 1))
[ $NEWS_OK -eq 0 ] && PASSED_CHECKS=$((PASSED_CHECKS + 1))
[ $PORT_OK -eq 0 ] && PASSED_CHECKS=$((PASSED_CHECKS + 1))
[ $OLLAMA_OK -eq 0 ] && PASSED_CHECKS=$((PASSED_CHECKS + 1))

echo "检查项目：$TOTAL_CHECKS 项（server / monitor / news / ${SERVER_PORT}端口 / Ollama）"
echo "通过项目：$PASSED_CHECKS/$TOTAL_CHECKS"

if [ $PASSED_CHECKS -eq $TOTAL_CHECKS ]; then
    echo ""
    echo "✓ 所有服务运行正常（含 Ollama 依赖）"
    exit 0
else
    echo ""
    echo "⚠ 部分服务异常"
    
    if [ $SERVER_OK -ne 0 ]; then
        echo "  → 启动 server: ./start_all.sh"
    fi
    if [ $MONITOR_OK -ne 0 ] || [ $NEWS_OK -ne 0 ]; then
        echo "  → 启动后台服务：./start_all.sh"
    fi
    if [ $PORT_OK -ne 0 ]; then
        echo "  → 检查 server 日志：logs/server_*.log"
        echo "  → 当前配置端口：$SERVER_PORT"
    fi
    if [ $OLLAMA_OK -ne 0 ]; then
        echo "  → Ollama 未就绪将影响新闻采集/embedding 去重"
        echo "  → 请确保 Ollama 在后台运行（端口 13145）"
    fi
    
    exit 1
fi
