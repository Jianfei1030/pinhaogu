# 港股实时监控系统 - 任务板

> 前端/UI 变更后必须用 OpenClaw managed browser 截图验证。

## 进度总览

| 模块 | 进度 | 状态 |
|------|------|------|
| Phase 1-16 (基础功能) | 16/16 | ✅ 已归档 |
| Phase 17-24.9 (历史 Phase) | 全部 | ✅ 已归档 |
| Phase 29 (概念板块列回填) | 0/1 | 📋 待开始 |
| Phase 30 (盘前优化+回填提速) | 4/5 | 🔄 T30.5 待补测试 |
| Phase R1-R5 (代码重构) | 17/17 | ✅ 已归档 |
| Phase 32-33 (前端+盘前盘后) | 15/15 | ✅ 已归档 |
| Phase 34 (盘前题材分析) | 14/14 | ✅ 全部完成 |
| Phase 35 (A股日线加固+三轮重试) | 7/7 | ✅ 全部完成 |
| Phase 36 (盘前题材分析v2: 子题材精筛) | 9/9 | ✅ 全部完成 |
| **Phase 37 (盘前新闻过滤优化)** | **10/10** | **✅ 全部完成** |
| **Phase 38 (A股日线新增市值字段)** | **3/3** | **✅ 全部完成** |
| **Phase 39 (thesis-ingest 图片裁剪+描述补全+文档合并)** | **8/8** | **✅ 全部完成** |
| **Phase 40 (thesis-ingest 输出目录归档+固定文件名)** | **7/7** | **✅ 全部完成** |
| **Phase 41 (成分股等权指数统一接入)** | **6/6** | **✅ 全部完成** |

### Phase 37 并行分组

| 并发组 | 任务 | 资源 | 并行策略 |
|--------|------|------|----------|
| **Group A** | T37.0-pre（环境检查） | 系统环境 | ✅ 独立，第一个跑 |
| **Group B** | T37.0（news_filter.py） | 新文件 | ✅ 独立 |
| **Group C** | T37.1→T37.2a→T37.2b→T37.2c→T37.2d | premarket_thesis_analysis.py | ❌ 全部串行，同文件 + 依赖链 |
| **Group D** | T37.3（全量回归） | 系统 | ❌ 必须等 Group C 全部完成 |
| **Group E** | T37.4（README + auto-add 验证） | 文档 + CLI | ✅ T37.3 完成后可跑 |

---

## 已完成 Phase 摘要（已归档）

### Phase 34: 盘前题材分析 ✅
- T34.0-T34.4: thesis 描述补充 + API 接口 + 脚本骨架 + 行情补全 + LLM Prompt 适配
- T34.5-T34.7: 报告推送适配 + dry-run 测试 21 个通过 + server.py 4 个端点
- T34.10-T34.13: LLM 模型替换 + 休市日优化 + Telegram 精简 + 北交所数据补全
- 交付：`workspace/premarket_thesis_analysis.py` (1015+ 行), `tests/test_premarket_thesis_analysis.py`

### Phase 35: A股日线数据源加固 + 三轮重试 ✅
- T35.1-T35.7: 腾讯 fallback + 代理禁用逻辑 + 单只重试 + 三轮循环 + 全量回归 5497 只 <1% 失败
- 交付：`data_sources/tencent.py`, `daily_incremental_backfill.py` 三轮重试

### Phase 36: 盘前题材分析优化 — 子题材精筛 ✅
- T36.0: 285/285 子题材 description 补充完成
- T36.1-T36.2: thesis_api.py 子题材树提取 + 成分股合并
- T36.3-T36.5: LLM 第二轮 Prompt + Step 2.5 接入 + 报告推送适配
- T36.6-T36.8: --auto-add 适配 + 回归验证 + README 更新
- 效果：AI 硬件 → 核心子题材：变压器/数据中心/燃气轮机/LPU/SOFC电池, 39→24→15 只

### Phase 30: 盘前优化 + 前置回填提速
- [x] T30.1-T30.4: DB 读取历史K线 + 限流配置化 + DB 筹码读取 + 报告字段补齐
- [ ] T30.5: 性能回归测试待补（需 test_premarket_optimization.py）

### Phase 29: 概念板块列回填
- [ ] T29.1: database.py 新增 concept_board 字段 + concept_board_backfill.py

### Phase 1-16 / 17-24.9 / 32-33 / R1-R5: 全部已归档 ✅

---

## 数据源策略

| 数据源 | 接口 | 风险 |
|--------|------|------|
| 同花顺 THS | `stock_board_concept_name_ths()` 375 板块 | ✅ |
| 东财 EM | `stock_board_concept_cons_em()` ~250 只/板块 | ⚠️ 可能被封 |
| 同花顺爬取 | `q.10jqka.com.cn` ~50 只/板块 | ✅ |

**策略**: 板块列表→同花顺 | 成份股→东财优先，被封 fallback 同花顺

---

## Phase 37: 盘前新闻过滤优化（P0）

> **背景**：当前 `load_premarket_news()`（`premarket_thesis_analysis.py`）加载约 1748 条新闻全塞给 LLM，
> 其中约 70% 是地缘冲突、外国选举、天气等对 A 股无直接影响的噪音。
> 第一轮 LLM 输入达 69000 tokens，贵且慢，噪音稀释有效信息。
>
> **方案**：用双参考向量 embedding（宏观 vs 产业）做新闻分类。
> - 宏观参考向量：`'地缘冲突 战争 中东 伊朗 以色列 军事 制裁 原油 黄金 政治选举 外交 央行 通胀 GDP'`
> - 产业参考向量：`'业绩预增 净利 涨停 资金 机构 政策 产业 技术突破 产品发布 合作 中标 研报 A股 港股'`
> - M > I → 宏观类；I >= M → 产业类
> - 实测 2762 条约 3.5 分钟完成，宏观 873 条 / 产业 1889 条
>
> **现有 embedding 代码参考**（`daily_news_collector.py`）：
> ```python
> OLLAMA_HOST = "http://localhost:13145"
> EMBEDDING_ENDPOINT = f"{OLLAMA_HOST}/api/embed"
> EMBEDDING_MODEL = "qwen3-embedding:4b"
> ```
> **注意**：`/api/embed` 的 `input` 字段支持字符串列表批量模式。

### T37.0-pre: 环境前置检查 `P0` `timeout:S` ✅
- ✅ Ollama 13145 端口可达，`qwen3-embedding:4b` 已拉取
- ✅ numpy 2.2.6 已安装
- ✅ `premarket_thesis_analysis.py` 可导入

---

### T37.0: 新闻 embedding 分类函数 `P0` `timeout:M`

**交付**：新建 `workspace/news_filter.py`

**函数签名**：
```python
def classify_news(news_items: list[dict], batch_size: int = 64) -> tuple[list[dict], list[dict]]:
    """
    用双参考向量 embedding 对新闻分类为宏观/产业两类。
    若 macro_sim > industry_sim → 宏观类；否则 → 产业类。
    """
```

**实现要点**：
1. 常量定义（文件顶部）：OLLAMA_HOST, EMBEDDING_ENDPOINT, EMBEDDING_MODEL, MACRO_REF_TEXT, INDUSTRY_REF_TEXT
2. `_get_batch_embeddings(texts)` → 调用 `/api/embed` 批量接口，失败时逐条 fallback，单条也失败返回零向量
3. `_cosine_sim(a, b)` → numpy 余弦相似度（复制 daily_news_collector.py 逻辑）
4. `classify_news()` 主函数：先算两个参考向量 embedding → 分批调用 → 计算相似度 → 分类 → 返回
5. 模块级缓存 `_ref_embeddings` 缓存参考向量
6. 进度打印：每 100 条 + 完成统计

**验收命令**：
```bash
cd workspace && python3 -m py_compile news_filter.py
# 功能验证（需 Ollama 运行）：
python3 -c "
from news_filter import classify_news
import json, glob
files = sorted(glob.glob('news_data/financial_news_*.json'))
news = []
for f in files[-3:]:
    with open(f) as fh: news.extend(json.load(fh))
macro, industry = classify_news(news)
print(f'宏观: {len(macro)} 条, 产业: {len(industry)} 条')
for n in macro[:5]: print(f'  [{n.get(\"source\",\"\")}] {n[\"title\"][:60]}')
for n in industry[:5]: print(f'  [{n.get(\"source\",\"\")}] {n[\"title\"][:60]}')
"
```

**验收标准**：
- `py_compile` 通过
- 宏观约占 30%，产业约占 70%
- 前 5 条宏观含地缘/宏观关键词，前 5 条产业含 A 股/行业关键词
- 耗时 < 5 分钟

---

### T37.1: 接入 `load_premarket_news()` — 输出宏观+产业两个列表 `P0` `timeout:M`

**交付**：修改 `workspace/premarket_thesis_analysis.py` 的 `load_premarket_news()` 函数

**改动**：
1. 新增 import: `from news_filter import classify_news`
2. 函数签名改为 `-> tuple[list[dict], list[dict]]`
3. 末尾替换 `return all_news` 为调用 `classify_news(all_news)` 后返回 `(macro_news, industry_news)`
4. 更新所有调用方：`run()` 内拆包，`llm_recommend_thesis()` 和 `llm_select_sub_themes()` 传 `industry_news`
5. **向后兼容处理**（如果 `premarket_analysis.py` 也调用）：
   - 先 `grep -n "load_premarket_news" premarket_analysis.py` 检查
   - 如果存在：方案 A 加 `compat=True` 参数返回旧格式 list；方案 B 同步修改调用方拆包后合并

**验收标准**：
- `py_compile` 通过
- 函数返回 `(macro_news, industry_news)` 两个列表
- premarket_analysis.py 如有调用需同步适配或 compat 参数正常工作

---

### T37.2a: 新增 llm_macro_analysis() + parse_macro_analysis() `P0` `timeout:M`

**交付**：修改 `workspace/premarket_thesis_analysis.py`，新增两个函数

**`llm_macro_analysis(macro_news, date, api_key)`**：
- 从 macro_news 最多取 50 条，格式化为 `[时间] [来源] 标题 | 详情摘要`
- system_prompt: "你是一位资深的 A 股宏观策略分析师..."
- user_prompt: 要求输出"形势判断 + 一句话摘要 + 关键信号 + 关注风险"
- 调用 `chat_completion`，model=LLM_MODEL, temperature=0.3, max_tokens=512
- 返回 LLM 原始输出

**`parse_macro_analysis(llm_output) -> dict`**：
- 正则提取 4 个字段 → `{"judgment": str, "summary": str, "signals": list, "risks": list}`

**验收**：`py_compile` 通过 + mock LLM 输出测试 parse 函数

---

### T37.2b: 重构 run() Step 结构（4 步→5 步） `P0` `timeout:L`

**交付**：修改 `workspace/premarket_thesis_analysis.py` 的 `run()` 函数

**前置依赖**：T37.1、T37.2a

**流程变更**：
```
Step 1 [1/5]: 拉取题材列表（不变）
Step 2 [2/5]: 新闻过滤 + 宏观分析 (load_premarket_news + llm_macro_analysis + parse)
Step 3 [3/5]: LLM 主题材选择（传 industry_news）
Step 3.5 [3.5/5]: 子题材精筛（传 industry_news + macro_parsed 背景参考）
Step 4 [4/5]: 行情补全 + 筛选
Step 5 [5/5]: 报告 + 推送
```

**验收**：
```bash
cd workspace && python3 -m py_compile premarket_thesis_analysis.py
python3 premarket_thesis_analysis.py --dry-run --date 2026-04-14
```
- 日志显示 `[1/5]` ~ `[5/5]` 完整流程
- 包含"宏观形势分析"和"形势判断: xxx"行

---

### T37.2c: llm_recommend_thesis() user_prompt 加宏观背景 `P0` `timeout:M`

**交付**：修改 `workspace/premarket_thesis_analysis.py` 的 `llm_recommend_thesis()` 函数

**改动**：
- 函数签名新增可选参数：`macro_judgment: str = "", macro_summary: str = ""`
- user_prompt 中新闻列表之后、题材选择指令之前，追加：
  ```
  宏观背景参考（仅供参考，不影响题材选择）：
  形势判断：{macro_judgment}
  摘要：{macro_summary}
  ```

**验收**：`py_compile` 通过 + mock 调用传参后 user_prompt 包含这两行

---

### T37.2d: 报告生成 + Telegram 消息加宏观判断 `P1` `timeout:M`

**交付**：修改报告生成和推送部分

**改动**：
1. `report_data` 新增 `macro_analysis` 字段（judgment/summary/signals/risks）
2. Telegram 消息头部增加：`🌍 宏观形势: {judgment} — {summary}`

**验收**：`py_compile` 通过 + `--dry-run` 报告 JSON 包含 `macro_analysis` + 消息预览含 `🌍 宏观形势:`

---

### T37.3: 完整回归验证（全量带推送） `P0` `timeout:M`

**交付**：无代码变更，纯验证

**执行命令**：`cd workspace && python3 premarket_thesis_analysis.py --date 2026-04-14`

**验收标准**：
1. **推送正常**：Telegram + QQ 推送成功
2. **消息内容**：含 `🌍 宏观形势:` 行 + 推荐题材 + 核心子题材 + 最终筛选成分股
3. **报告 JSON**：`macro_analysis` 字段存在且 judgment ∈ {偏乐观, 偏谨慎, 中性}
4. **性能基准对比**：
   - LLM 第一轮输入 token 从 ~69000 降至 ~48000（降幅 ~30%）
   - 全程耗时 vs 之前相近日期的总耗时（不应显著增加）
   - 新闻分类步骤耗时 < 5 分钟

---

### T37.4: README 更新 + `--auto-add` 适配验证 `P2` `timeout:S`

**交付**：修改 `README.md` + 验证 `--auto-add`

**Part A: README 更新**

更新执行流程表：
| 1/5 | 拉取题材列表 |
| 2/5 | 新闻过滤（embedding 分类）+ 宏观形势分析 |
| 3/5 | LLM 主题材选择（仅用产业类新闻） |
| 3.5/5 | 子题材精筛 |
| 4/5 | 行情补全 + 筛选 |
| 5/5 | 报告 + 推送（含宏观判断） |

新增「新闻过滤架构」小节：双参考向量 embedding 原理、参考向量定义、Ollama 批量接口、分类效果

**Part B: `--auto-add` 适配验证**
1. `grep -n "auto_add" premarket_thesis_analysis.py`
2. `cd workspace && python3 premarket_thesis_analysis.py --auto-add --dry-run --date 2026-04-14`

**验收**：README 可见新流程表 + 新闻过滤小节 + `--auto-add --dry-run` 正常执行

---

## Phase 35: A股日线加固（已归档摘要）

> T35.1-T35.7 全部完成 ✅ 腾讯 fallback + 三轮重试 + 全量回归 <1% 失败

---

---

## Phase 38: A股日线新增市值字段（P1）

> **背景**：当前 kline_1d 表缺少总市值/流通市值字段，选股和筛选时无法按市值过滤。
> **方案**：每日增量补全时，每只股票多调一次腾讯实时行情接口 `qt.gtimg.cn/q={code}`，从字段 [44] 取总市值、[45] 取流通市值（单位：亿元），写入 kline_1d 新增的 `total_mv` 和 `circ_mv` 列。

### T38.0: database.py 新增 total_mv/circ_mv 列 `P0` `timeout:M` ✅
- init_db() DDL 新增 total_mv REAL, circ_mv REAL
- _add_missing_columns() 自动 ALTER TABLE 兼容已有 DB
- upsert_kline() INSERT/UPDATE 支持两字段
- query_kline() optional_columns 包含 total_mv/circ_mv
- 验证：旧 DB 16列→18列 ✅，新 DB 18列 ✅，py_compile 通过 ✅

### T38.1: daily_incremental_backfill.py 新增市值抓取 `P0` `timeout:L` ✅
- _fetch_market_cap_from_tencent() 新增，调 qt.gtimg.cn/q={code}
- 解析 [44] 总市值 / [45] 流通市值（亿元）
- 集成到 _process_single_symbol()，写入前附带抓取
- 验证：平安银行 2175/2175亿 ✅，茅台 18377/18377亿 ✅，宁德 18347/19671亿 ✅

### T38.2: 全量回填 + 回归验证 `P0` `timeout:XL` ✅
- 等 16:30 增量补全自动触发时带上新字段，或手动触发 API POST /api/backfill/run
- 全量运行一次 daily_incremental_backfill，确认所有 kline_1d 都有 total_mv/circ_mv

---

## Phase 39: thesis-ingest 图片预裁剪 + 题材描述自动补全 `P0`

> **Part A — 图片预裁剪**：thesis-ingest 流水线（`scripts/process_thesis_image.py`）第 1 步 `plan_semantic_cuts.py` 直接拿原图做语义切割规划。如果原图带有手机状态栏/导航栏/footer 等冗余区域，会影响切割坐标准确性和 OCR 质量。
> 将已开发好的 `kpb_crop.py`（位于 `<your-path>/tools/kpb_crop.py`）集成到 thesis-ingest 流水线作为 **Step 0：图片预检 + 裁剪**。核心原则：检测不到冗余 = 不裁，绝不误切干净图。
> **Part B — 题材描述自动补全**：当前入库后 `thesis_catalog.description` 为空，需要手动跑 `supplement_thesis_description.py`。改为入库后自动调 LLM 生成描述，一条龙完成。
> **集成方式**：只在 `process_thesis_image.py` 入口和 `insert_thesis_tree.py` 收尾各改一处，下游步骤无感。

### T39.0: 复制 kpb_crop.py 到 thesis-ingest scripts/ 目录 `P0` `timeout:S`
- 将 `<your-path>/tools/kpb_crop.py` 复制到 `thesis-ingest/scripts/kpb_crop.py`
- 验证 import 可用：`cd thesis-ingest && python3 -c "from scripts.kpb_crop import crop_kpb_table, detect_redundancy; print('OK')"`
- **交付**：`thesis-ingest/scripts/kpb_crop.py`（与 tools/ 下同步）
- **验收**：import 通过，`detect_redundancy` 和 `crop_kpb_table` 可调用

### T39.1: process_thesis_image.py 新增 Step 0 — 图片预检+裁剪 `P0` `timeout:M`
- 修改 `scripts/process_thesis_image.py` 的 `main()` 函数
- 在原有 6 步之前插入 Step 0：
  1. 调用 `detect_redundancy(image_path)` 检测冗余
  2. 打印检测结果（顶部/底部冗余 px、是否需要裁剪）
  3. 如果 `needs_crop=True`：调用 `crop_kpb_table(image_path, output_path)`，将裁剪后的图保存到 `output/{stem}_cropped{ext}`，后续步骤用裁剪图
  4. 如果 `needs_crop=False`：跳过裁剪，后续步骤用原图
  5. 将裁剪信息写入 `run_summary`（`image_preprocess` 字段）
- total_steps 从 6 改为 7（快捷模式从 2 改为 3）
- `--image` 参数始终指向原始输入图，裁剪后的中间图自动选择
- **交付**：修改 `scripts/process_thesis_image.py`
- **验收**：
  ```bash
  cd thesis-ingest
  # 用一张已知有冗余的图测试
  python3 scripts/process_thesis_image.py --image input_images/光伏.png --db thesis.db
  # 日志应显示 Step 0 检测结果 + 裁剪信息
  # 后续步骤正常执行
  ```

### T39.2: 回归验证 — 干净图不误裁 `P0` `timeout:M`
- 用一张干净的题材图（无冗余区域）跑完整流水线
- 验证 Step 0 输出 `无需裁剪（内容完整）`，后续步骤正常工作
- **验收**：Step 0 检测 top_redundant_px=0 且 bottom_redundant_px=0，pipeline 正常完成

### T39.3: run_summary 增强 + 日志优化 `P1` `timeout:S`
- `run_summary` JSON 新增 `image_preprocess` 字段：
  ```json
  "image_preprocess": {
    "original_image": "光伏.png",
    "preprocessed_image": "光伏_cropped.png",  // 或 null（未裁剪）
    "top_cut_px": 452,
    "bottom_cut_px": 240,
    "needs_crop": true
  }
  ```
- 打印日志增加 emoji 区分：`🔍 Step 0: 图片预检 → ✅ 无需裁剪` 或 `✂️ 裁剪完成`
- **交付**：修改 `scripts/process_thesis_image.py` 的 run_summary 构建逻辑
- **验收**：run_summary JSON 包含 `image_preprocess` 字段

### T39.4: insert_thesis_tree.py 新增描述补全逻辑（根题材+子题材） `P0` `timeout:M`
- 在 `scripts/insert_thesis_tree.py` 的入库逻辑完成后（写入 thesis_catalog 后），追加描述补全：
  1. **根题材描述**（写入 `thesis_catalog.description`）：
     - 包含：题材定位（是什么）+ 核心子题材列表（包含哪些方向）
     - 格式示例："AI 硬件是人工智能基础设施核心环节，涵盖算力芯片、光模块、液冷散热、PCB、服务器整机等子题材，涉及国产替代与全球 AI 产业链共振。"
     - 长度 50-200 字
  2. **子题材描述**（写入 `thesis_tree_{suffix}.description`，first_level/second_level 节点）：
     - 包含：子题材定位（父题材下是什么方向）+ 涉及的下游/产品
     - 格式示例："光模块是 AI 算力网络的核心器件，涉及 CPO、硅光、800G/1.6T 高速模块等方向，标的涵盖中际旭创、新易盛等。"
     - 长度 30-120 字
  3. 调 `thesis_api.get_full_tree(image_name)` 拿完整树 → 构建根题材和各子节点的 prompt
  4. 调 LLM (qwen3.6-plus) 批量生成描述，返回 JSON 后批量 UPDATE
  5. 打印生成结果：`📝 自动生成根题材描述 + X 条子题材描述`
- LLM 调用策略：根题材一次调用 + 子题材分批调用（每批 20 个节点，避免上下文溢出）
- 复用现有依赖：`openai` SDK + 百炼 API
- 重试机制：LLM 调用失败重试 3 次，间隔 2/4/6 秒
- 安全原则：描述生成失败不终止流程，只打警告日志，入库本身不受影响
- **交付**：修改 `scripts/insert_thesis_tree.py` 或新建 `scripts/auto_generate_descriptions.py` 并在入库后调用
- **验收**：
  ```bash
  cd thesis-ingest
  python3 scripts/insert_thesis_tree.py --input /path/to/ancestor.json --db thesis.db --source-image 测试题材.jpg --root-name 测试题材
  # 验证：
  python3 -c "
import sqlite3; conn = sqlite3.connect('thesis.db')
r = conn.execute(\"SELECT description FROM thesis_catalog WHERE image_name='测试题材'\").fetchone()
print(f'根描述: {r[0] if r else \"未找到\"}')
# 验证子题材描述也填充了
r2 = conn.execute(\"SELECT COUNT(*) FROM thesis_tree_? WHERE description IS NOT NULL AND description != ''\").fetchone()
print(f'子题材有描述的节点: {r2[0]}')
conn.close()
"
  ```

### T39.5: 端到端验证 — 图片注入 → 裁剪 → 入库 → 描述补全 `P0` `timeout:L`
- 用 `process_thesis_image.py` 完整跑一次，验证全流程：
  ```bash
  cd thesis-ingest
  python3 scripts/process_thesis_image.py --image input_images/光伏.png --db thesis.db
  ```
- 验证点：
  1. Step 0 图片预检 ✅
  2. 原 6 步正常执行 ✅
  3. 入库后自动生成根题材描述 + 子题材描述 ✅
  4. run_summary 包含 image_preprocess + description 补全信息 ✅
  5. 数据库 thesis_catalog 和 thesis_tree 中描述字段已填充 ✅

### T39.6: thesis-ingest 文档合并到 stock-monitor `P1` `timeout:M`
- **背景**：thesis-ingest 之前作为独立子项目存在，有自己的 `DECISIONS.md`、`design.md`、`README.md`。现在作为 stock-monitor 的子模块，文档应统一到 stock-monitor 层级维护。
- **合并方案**：
  1. `thesis-ingest/README.md` → 内容合并到 `stock-monitor/README.md` 的「题材注入」章节下（如尚无此章节则新增），合并后删除 `thesis-ingest/README.md`
  2. `thesis-ingest/DECISIONS.md` → 追加到 `stock-monitor/DECISIONS.md` 末尾，标注来源，合并后删除 `thesis-ingest/DECISIONS.md`
  3. `thesis-ingest/design.md` → 追加到 `stock-monitor/design.md` 末尾的 thesis-ingest 章节，合并后删除 `thesis-ingest/design.md`
  4. `thesis-ingest/` 目录下保留：`scripts/`、`database/`、`output/`、`input_images/`、`thesis.db`、`merge_segments.py`、`run_test.sh`
  5. 在 `thesis-ingest/` 下放一个简短的 `README.md`（20 行以内），只写：目录用途 + 指向 stock-monitor/README.md 对应章节的引用
- **交付**：合并后的 3 个文档 + thesis-ingest/ 下的精简 README
- **验收**：
  - `stock-monitor/README.md` 包含 thesis-ingest 相关内容
  - `stock-monitor/DECISIONS.md` 包含 thesis-ingest 决策
  - `stock-monitor/design.md` 包含 thesis-ingest 设计
  - `thesis-ingest/` 下无重复的完整文档，只有精简 README

### T39.7: thesis-ingest tasks.md 并入主 tasks.md `P1` `timeout:S`
- **背景**：之前 `tasks.md` 底部有一个「题材写入技能 — 任务板（thesis-ingest）」独立段落。
- 确认当前 tasks.md 中 Phase 39 已覆盖 thesis-ingest 的全部功能需求后，移除底部独立的「题材写入技能 — 任务板」段落，避免维护两套任务列表。
- **交付**：清理 `stock-monitor/tasks.md` 底部的独立 thesis-ingest 任务板
- **验收**：tasks.md 中只有 Phase 编号结构化的任务，无独立的 thesis-ingest 任务板

### T39.8: 最终回归验证 — stock-monitor 主项目 + thesis-ingest 子模块 `P0` `timeout:L`
- 合并文档后，验证 stock-monitor 主项目和 thesis-ingest 子模块都能正常运行：
  1. `cd stock-monitor && python3 workspace/premarket_thesis_analysis.py --dry-run --date 2026-04-14` ✅
  2. `cd stock-monitor/thesis-ingest && python3 scripts/process_thesis_image.py --image input_images/光伏.png --db thesis.db` ✅
  3. 主项目 stock-monitor server.py 健康检查 ✅
  4. thesis-ingest 所有脚本 import 路径未因文档合并而破坏 ✅

## Phase 40: thesis-ingest 输出目录归档 + 固定文件名（P1）

> **背景**：流水线每步生成带时间戳的文件，14+ 文件散落在 `output/` 平目录，难以管理和查找。
> **方案**：按题材名创建 `output/{题材名}/` 子目录，每次运行清空重建，所有文件使用固定名称。

### T40.0: 子脚本新增 --fixed-name 参数 `P0` `timeout:M` ✅
- `plan_semantic_cuts.py`：`--fixed-name` → `cut_plan.json/.md`
- `split_by_path_plan.py`：`--fixed-name` → `segments/` + `manifest.*`
- `parse_path_segments_mm.py`：`--fixed-name` → `segment_parse.json/.md`，跳过 run record
- `expand_path_ancestors.py`：`--fixed-name` → `ancestor_candidates.json/.md`，跳过 run record
- `verify_thesis_report.py`：`--fixed-name` → `verify_report.md`

### T40.1: orchestrator 输出目录归档 `P0` `timeout:M` ✅
- `process_thesis_image.py`：`theme_name = image_path.stem` → `output/{theme_name}/`
- 每次运行前 `shutil.rmtree` 清空 + `mkdir` 重建
- 所有子脚本调用传入 `--fixed-name`
- `run_step` 新增 `fixed_output_name` 参数，精确查找输出文件
- `run_summary.json/.md` 使用固定文件名

### T40.2: manifest 查找适配 `P0` `timeout:S` ✅
- Step 3 查找 manifest 时优先检查 `manifest.json`（fixed-name 模式），fallback 到 `path_segments_manifest_*.json`

### T40.3: 全量回归验证 `P0` `timeout:L` ✅
- 用 `锂矿.png` 跑完整 6 步管道
- 验证 `output/锂矿/` 下 15 个文件，结构符合预期
- Step 6 报告含 3 个一级题材、4 个二级题材、28 只股票、全部节点描述

### T40.4: 文档更新 `P1` `timeout:S` ✅
- `README.md`：更新管道流程图、运行示例、输出说明
- `thesis-ingest/README.md`：新增输出目录结构说明
- `DECISIONS.md`：新增决策 13（输出目录按题材名归档）
- `design.md`：更新架构图中的文件名

### T40.5: CLAUDE.md 更新 `P1` `timeout:S` ✅
- 更新 thesis-ingest 输出路径说明

### T40.6: tasks.md 清理 `P1` `timeout:S` ✅
- Phase 40 任务板记录

---

## Phase 41: 成分股等权指数统一接入

> **背景**：盘前分析、盘前题材分析、盘后复盘当前用板块指数衡量推荐效果，但板块指数与实际推荐成分股不匹配，导致失真（实测板块+3.20% vs 成分股等权-1.77%）。需要统一使用成分股等权指数。
> **核心公式**：指数 = (1/N) × Σ(个股收盘价 / 基期价格 × 1000)
> **设计文档**：`spec_component_index.md`

### T41.0: 新建共享工具模块 `utils/component_index.py` `P0` `timeout:M` [x] <!-- sha:$(git -C <your-path>/stock-monitor rev-parse --short HEAD) -->
- 交付：`workspace/utils/component_index.py`
- 验收：py_compile 通过；mock 计算正确；fetch_prev_close 腾讯 fallback 成功
- 创建 `workspace/utils/component_index.py`，提供两个函数：
  - `calc_equal_weight_index(stocks_with_prices: list[dict], base_prices: dict[str, float]) → dict` — 输入成分股列表（含当日收盘价）和基期价格字典（股票代码→前一日收盘价），返回 {index_value, avg_change_pct, n_stocks, best_stock, worst_stock}
  - `fetch_prev_close(codes: list[str], market: str) → dict[str, float]` — 批量获取前一交易日收盘价（A 股用 akshare/腾讯 fallback，港股用 yfinance）
- 不修改任何现有脚本，只建工具模块
- 交付：`workspace/utils/component_index.py` + 简单测试（python3 -c 调用验证）
- 验收：py_compile 通过；给定 mock 数据返回正确指数值

### T41.1: `premarket_analysis.py` 接入等权指数 `P0` `timeout:M` [x]
- 在 report JSON 中新增 `component_index` 字段：含 index_value、avg_change_pct、base_date、best/worst_stock
- Telegram 消息在板块涨跌信息之后新增一行成分股等权指数展示（格式：📊 成分股指数: XXXX.XX (N 只等权 ±X.XX%)）
- 只改 `premarket_analysis.py`，不改其他文件
- 验收：py_compile 通过；dry-run 输出 JSON 含 component_index 字段

### T41.2: `premarket_thesis_analysis.py` 接入等权指数 `P0` `timeout:M` [x]
- 同上，在 report JSON 和 Telegram 消息中新增成分股等权指数
- 使用 `final_stocks` 列表计算（已通过筹码筛选的最终成分股）
- 基期价格：使用本地 DB 中 `kline_1d` 表的前一交易日收盘数据
- 只改 `premarket_thesis_analysis.py`
- 验收：py_compile 通过；dry-run 输出 JSON 含 component_index 字段

### T41.3: `postmarket_review.py` 用等权指数替代板块指数 `P0` `timeout:M` [x]
- 复盘分析中用成分股等权指数替代当前的 `sector_change_pct`
- 需要：读取盘前报告中的成分股列表 → 获取当日收盘价 → 计算等权指数 → 与盘前基线指数对比
- 报告 JSON 新增 `component_index_change_pct` 字段，替代或补充 `post_recommend_return`
- Telegram 消息中展示：📊 盘前成分股指数: XXXX → 📊 复盘成分股指数: XXXX → 📈 指数涨跌: ±X.XX%
- 只改 `postmarket_review.py`
- 验收：py_compile 通过；dry-run 输出含等权指数对比

### T41.4: 全量回归验证 `P0` `timeout:L` [x]
- 三个脚本分别 `python3 -m py_compile` 验证 ✅
- component_index 模块导入验证 ✅
- 验证三个脚本互不影响，可独立运行 ✅

### T41.5: 文档更新 `P1` `timeout:S` [x]
- `README.md`：Cron 任务表更新，说明盘前/盘后使用成分股等权指数
- 变更记录写入 tasks.md

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-04-18 | Phase 41 全部完成 ✅：成分股等权指数统一接入（T41.0-T41.5）— premarket_analysis.py / premarket_thesis_analysis.py / postmarket_review.py 三个脚本全部接入等权指数，替代板块指数 |
| 2026-04-17 | Phase 40 全部完成 ✅：输出目录按题材名归档 + 固定文件名（T40.0-T40.6） |
| 2026-04-15 | Phase 37 全部完成 ✅：新闻过滤 + 宏观分析 + Step 重构 + README 更新 |
| 2026-04-16 | Phase 39 全部完成 ✅：图片预裁剪 (T39.0-T39.3) + 描述自动补全 (T39.4-T39.5) + 文档合并 (T39.6) + 清理任务板 (T39.7) + 回归验证 (T39.8) |
| 2026-04-15 | Phase 38 全部完成 ✅：A 股日线新增 total_mv/circ_mv 市值字段（腾讯接口）+ database.py 自动 ALTER TABLE 兼容 + daily_incremental_backfill.py 集成抓取 |
| 2026-04-14 | Phase 36 全部完成 ✅ |
| 2026-04-13 | Phase 34 全部完成 ✅ |
| 2026-04-10 | thesis-ingest T4.5 一键入口收口 ✅ |
