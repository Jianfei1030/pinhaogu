# 架构重构规划 (2026-Q2)

> 文档目标：指导 stock-monitor 项目从"脚本集合"向"模块化单体"演进
> 原则：低风险、先收益大、每步验证、不重写框架

---

## 一、当前架构的主要问题

### 1.1 顶层脚本臃肿
- `monitor.py` (37KB): 数据获取、指标计算、告警检测、推送、数据补全全部混在一起
- `premarket_analysis.py` (27KB) / `postmarket_review.py` (17KB): 业务逻辑 + CLI 参数 + 推送逻辑耦合
- 新成员难以理解执行流程

### 1.2 配置分散
- `config.yaml`: 部分配置
- 环境变量：部分配置
- 脚本内部硬编码：部分配置（如 LLM 模型、推送目标、数据路径）
- **问题**: 修改一个配置需要改多个地方，容易遗漏

### 1.3 横切能力重复
- 推送逻辑：5+ 个脚本各自实现 `_send_telegram()` / `_send_qq()`
- LLM 调用：多个脚本各自调用 Ollama API
- 交易日判断：多个地方重复实现
- **问题**: 修复一个 bug 需要改多个文件

### 1.4 任务脚本形态不一致
- `monitor.py`: 无限循环 + tick 处理
- `premarket_analysis.py`: 一次性执行 + cron 调用
- `daily_incremental_backfill.py`: 一次性执行 + monitor.py 内调用
- **问题**: 难以统一测试、难以复用

### 1.5 Server.py 职责不清
- FastAPI router + 业务逻辑混在一起
- endpoint 函数动辄 100+ 行
- **问题**: 修改 API 需要理解业务细节，容易引入 bug

---

## 二、推荐目标形态

### 2.1 架构原则
- **模块化单体**: 继续单一进程，不上微服务
- **分层清晰**: 顶层脚本 → Job Runner → Service 层 → 数据层
- **配置统一**: env > yaml > default 三级优先级
- **横切收敛**: 推送/LLM/日历/状态 收成独立服务

### 2.2 目标分层

```
顶层脚本 (Thin Wrappers)
├── monitor.py           # CLI 参数解析 → JobRunner.run()
├── premarket_analysis.py
├── postmarket_review.py
├── daily_sector_pipeline.py
└── daily_incremental_backfill.py

Job Runner 层 (统一形态)
├── run(date, dry_run, notify) -> Result
└── 所有脚本统一接口

Service 层 (横切能力)
├── push_service.py      # Telegram + QQ 推送
├── llm_service.py       # Ollama / 百炼调用
├── trading_calendar_service.py  # 交易日判断
├── runtime_state_service.py     # 进程状态/去重记录
└── config_service.py    # 配置读取 (env > yaml > default)

数据层 (保持不变)
├── data_source.py       # 数据获取
├── database.py          # SQLite 操作
└── indicators/          # 指标计算
```

### 2.3 配置层级

```
优先级：env > yaml > default

1. env (最高优先级)
   - OPENCLAW_MESSAGE_API
   - QQ_PUSH_TARGET
   - TELEGRAM_BOT_TOKEN
   - DATA_ROOT

2. config.yaml (中优先级)
   - watchlist
   - alert_rules
   - llm.model
   - push.telegram.chat_id

3. 代码默认值 (最低优先级)
   - 默认端口
   - 默认日志路径
   - 默认超时时间
```

---

## 三、拆分优先级

### Phase R1: Job Runner 统一 (P0)
**目标**: 5 个核心脚本统一成 `run(date, dry_run, notify)` 接口
**收益**: 易于测试、易于复用
**风险**: 中（需要改脚本入口）
**状态**: tasks.md 已定义

### Phase R2: 配置层统一 (P0)
**目标**: 所有配置从一个地方读取，优先级清晰
**收益**: 后续重构的基础，降低配置错误风险
**风险**: 低（只读不改）
**状态**: tasks.md 已定义

### Phase R3: Server.py 拆分 (P1)
**目标**: router + service 分离
**收益**: API 逻辑清晰，易于维护
**风险**: 中（需要测试 API）
**状态**: tasks.md 已定义

### Phase R4: 横切服务收敛 (P1)
**目标**: 推送/LLM/日历/状态 收成独立服务
**收益**: 减少重复代码，统一修复 bug
**风险**: 低（向后兼容）
**状态**: tasks.md 已定义

### Phase R5: 顶层脚本软迁移 (P2)
**目标**: 顶层脚本变成薄 wrapper，逻辑沉到模块
**收益**: 新成员易于理解
**风险**: 低（逐步迁移）
**状态**: tasks.md 已定义

---

## 四、哪些先不动

### 4.1 暂不重构
- **数据库结构**: SQLite + 按日期分文件，当前设计合理
- **数据源策略**: 东财主源 + 同花顺 fallback，已验证稳定
- **指标计算**: indicators/ 目录结构清晰
- **前端**: 当前功能满足需求

### 4.2 暂不引入
- **微服务**: 当前规模不需要
- **消息队列**: 单进程足够
- **ORM**: SQLite 直接操作更灵活
- **复杂依赖注入**: 简单函数调用即可

---

## 五、验证策略

每个 Phase 完成后必须验证：

### 基础验证
- [ ] `python3 -m py_compile` 全部通过
- [ ] 核心模块 import 成功
- [ ] config 读取正常

### 功能验证
- [ ] 三件套能启动 (monitor / server / news_collector)
- [ ] 关键 API 正常 (/api/kline, /api/quote)
- [ ] dry-run 正常
- [ ] 节假日保护正常

### 推送验证
- [ ] Telegram 推送正常
- [ ] QQ 推送正常

### 数据验证
- [ ] DB 写入正常
- [ ] 数据补全正常

---

## 六、任务组织原则

### 6.1 任务粒度
- 每个任务修改文件 ≤ 5 个
- 每个任务可在 1-2 小时内完成
- 每个任务有明确验收标准

### 6.2 依赖关系
- Phase 内任务尽量独立
- Phase 间按优先级顺序
- 验证任务独立列出

### 6.3 风险控制
- 先读后写：先实现配置读取，不改原有逻辑
- 向后兼容：新服务先存在，旧代码逐步迁移
- 每步验证：每个任务完成后立即验证

---

*最后更新：2026-04-10*
