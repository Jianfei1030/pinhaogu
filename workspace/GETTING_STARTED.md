# 快速开始

本文档指导你如何在本地环境搭建并运行 pinhaogu（A 股概念板块监控系统）。

## 前置要求

| 依赖 | 说明 |
|------|------|
| **Python 3.10** | 本项目使用 Python 3.10，建议使用 pyenv 或 homebrew 安装 |
| **阿里百炼 API Key** | 用于 LLM 分析，申请地址：https://bailian.console.aliyun.com/ |
| **（可选）Telegram Bot** | 用于推送告警，非必需 |
| **（可选）Ollama** | 用于新闻 embedding 去重，本地运行 `ollama run qwen3-embedding:4b` |

## 1. 克隆项目

```bash
git clone https://github.com/Jianfei1030/pinhaogu.git
cd pinhaogu
```

## 2. 安装依赖

```bash
cd workspace
pip install -r requirements.txt
```

## 3. 配置

复制 `.env.example` 为 `.env` 并填写你的配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# Telegram Bot 配置（可选）
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_PROXY=

# QQ Bot 配置（可选）
QQ_TARGET=

# LLM API Key (必需)
BAILIAN_API_KEY=your_api_key_here

# LLM 模型与端点（可选，覆盖 config.yaml 默认值）
# LLM_MODEL=qwen-plus
# LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

> **注意**：`.env` 文件包含敏感信息，已被 `.gitignore` 排除，不会被提交到版本库。

## 4. 运行

### 方式一：一键启动（推荐）

```bash
cd workspace
./start_all.sh
```

这会同时启动三个后台进程：
- **Server**（Web 仪表盘）：访问 `http://localhost:18805`
- **Monitor**（实时监控）：每 60 秒拉取行情并评估告警
- **News Collector**（新闻采集）：每 600 秒采集财经新闻

### 方式二：单独运行

```bash
cd workspace

# Web 服务器
python3 server.py

# 实时监控（60 秒间隔）
python3 monitor.py --config config.yaml --interval 60

# 新闻采集（600 秒间隔）
python3 daily_news_collector.py --interval 600
```

### 方式三：定时任务

```bash
# 盘前分析（交易日盘前运行）
python3 premarket_analysis.py --dry-run  # 先测试
python3 premarket_analysis.py             # 正式运行

# 盘后复盘（交易日收盘后运行）
python3 postmarket_review.py --dry-run    # 先测试
python3 postmarket_review.py              # 正式运行

# 盘后数据补全（收盘后自动触发，也可手动运行）
python3 daily_incremental_backfill.py --date 2026-05-02 --dry-run
```

## 5. 健康检查

```bash
cd workspace
./check_health.sh
```

检查四项服务运行状态：Server、Monitor、News、Ollama。

## 6. 运行测试

```bash
cd workspace
pytest tests/ -v
```

## 目录结构

```
workspace/
├── config.py              # 配置系统（环境变量 > config.yaml > 默认值）
├── config.yaml            # 主配置文件（监控股、告警规则、交易时间等）
├── .env.example           # 环境变量模板
├── server.py              # Web 服务器（FastAPI）
├── monitor.py             # 实时监控引擎
├── premarket_analysis.py  # 盘前分析
├── postmarket_review.py   # 盘后复盘
├── daily_news_collector.py # 新闻采集
├── services/              # 业务逻辑层
├── data_sources/          # 数据源适配（腾讯、新浪、akshare、yfinance）
├── indicators/            # 技术指标插件（MACD、KDJ）
├── screener/              # 选股引擎
├── static/                # Web 前端
└── tests/                 # 测试套件
```

## 常见问题

### 为什么推荐 Python 3.10？

项目在 Python 3.10 下经过完整测试。其他版本可能存在兼容性问题。

### 如何更换 LLM 模型？

在 `.env` 中设置：
```env
LLM_MODEL=qwen-max
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

支持所有兼容 OpenAI API 格式的大模型服务。

### Ollama 是必须的吗？

不是。Ollama 仅用于新闻 embedding 去重功能。如果未安装 Ollama，新闻采集仍能运行，但不会进行去重处理。

### 如何配置告警推送？

在 `config.yaml` 的 `alerts` 部分定义告警规则，在 `.env` 中配置 Telegram 或 QQ 推送凭证。

### 数据源是否稳定？

项目使用腾讯、新浪的公开行情接口。这些是非官方接口，可能存在被限流或变更的风险。生产环境建议添加 akshare 作为备选数据源。
