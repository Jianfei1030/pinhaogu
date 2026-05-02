# 港股实时监控系统 — 关键决策记录

## 2026-03-23 数据源选型
- **决策**: 使用腾讯财经API作为主数据源，放弃东方财富
- **原因**: 本机无法直连东方财富(push2his.eastmoney.com)，代理(10808端口)也不稳定。腾讯API直连可用，1分钟线数据完整。
- **影响**: 不需要代理配置，部署更简单。15分钟K线由腾讯1分钟线聚合而成，与东财有0.02以内的偏差（数据源差异，非bug）。

## 2026-03-23 K线聚合规则
- **决策**: 采用东财风格的结束时间对齐
- **说明**: 标签=bar结束时间，Close=标签分钟的1分钟线价格
- **示例**: "14:15" bar覆盖14:01~14:15，Close=14:15分钟的价格
- **验证**: 12:00→31.92, 14:30→31.76, 14:45→31.70 与东财一致

## 2026-03-23 技术方案
- **前端**: FastAPI + 原生 HTML/CSS/JS，不引入React/Vue等框架
- **K线图表**: Canvas 原生绘制，不依赖 echarts 等重型库
- **刷新策略**: 15秒轮询，平衡实时性与请求频率

---

# 新闻采集器重启报告

*2026-03-25 22:35 — 归档自 news_collector_restart_report.md*

## 问题
- 采集进程消失，数据停留在 1709 条（最新 21:41）
- 日志显示正常完成（21:42:00 新增 17 条），无报错
- 最后计划下次采集：21:52:00

## 根因
进程在 `time.sleep(600)` 期间被外部终止（stop_all.bat 或手动 kill）
代码本身无崩溃

## 修复措施
1. 重启采集器：`py -3 daily_news_collector.py --interval 600`
2. 启动后 17:30 和 21:30 自动触发数据补全（已集成到 monitor.py）
3. 统一使用 start_all.bat / stop_all.bat 管理服务

## 验证标准
| 检查项 | 状态 |
|--------|------|
| 进程在运行 | ✅ |
| 数据在更新 | ✅ |
| 下次采集已计划 | ✅ |

---

## thesis-ingest 决策

### 题材写入技能 — 决策记录

> 创建日期：2026-04-09
> 最后更新：2026-04-12

---

#### 2026-04-09 项目启动决策

##### 决策 1：工作目录位置

**决策**：在 stock-monitor 项目下新建 `thesis-ingest/` 专用目录

**原因**：
- 便于统一管理（与 stock-monitor 共享 workspace 结构）
- 未来可与 stock-monitor 的板块分析功能联动

---

##### 决策 2：数据库表结构 — 从扁平到树状

**初始方案 (v1)**：`thesis_list` + `thesis_stocks_{md5}`（261 张扁平表）

**问题**：
- 层级关系丢失，无法查询父/子题材
- MD5 哈希表名不透明
- 261 张表管理困难

**最终方案 (v2)**：每张原始截图 → `thesis_catalog` 一行 + `thesis_tree_{md5}` + `thesis_stocks_tree_{md5}`

**原因**：
- 树结构完整保留层级关系（parent_id + depth）
- 每张截图只产 2 张表，管理简单
- `full_path` 字段（如 "AI 硬件 / 光模块 / CPO"）可直接查询

---

##### 决策 3：切割方案 — 红色水平线检测 + 多模态命名

**决策**：OpenCV 检测红色水平线定位切割边界，多模态模型只负责识别名称

**原因**：
- 多模态模型对 y 坐标的估计偏差太大（最大偏差 1000px+）
- 红色水平线是 APP 内置的分隔线，像素级精确
- "定位"和"命名"拆成两个独立步骤，各司其职

**备选方案**：
- 纯多模态模型定位（已验证不可行，偏差太大）
- OCR 定位（Tesseract 作为 fallback 保留）

---

##### 决策 4：底部跳过参数 — 固定像素而非比例

**决策**：`bottom_skip_px=50`（固定 50 像素），替代原来的 `bottom_skip_ratio=0.05`

**原因**：
- 用户会对原始长截图进行裁切，裁切后图片高度差异大
- 比例方式在矮图上会过滤掉有效红线（如 5% of 11429px = 571px，误过滤了 y=11038 和 y=11268 的红线）
- 固定 50 像素只过滤底部 UI 按钮区域

---

##### 决策 5：多模态解析并发数 — 4 路

**决策**：`ThreadPoolExecutor(max_workers=4)`

**验证过程**：
- 8 路并发 → API 限流，部分 segment 返回空响应（segment 5、14 失败）
- 4 路并发 + 1 秒间隔 → 16 个 segment 全部成功

---

##### 决策 6：重试 + Fail-Fast

**决策**：每个 segment 最多 3 次尝试（含重试），全部失败则终止整个流程

**原因**：
- API 偶发无响应是正常的，不应直接丢弃数据
- 但如果某个 segment 确实无法解析，产出残缺数据比不产出更糟糕
- Fail-fast 让用户立即知道问题，而不是写入后才发现数据缺失

---

##### 决策 7：`--root-name` 参数

**决策**：`insert_thesis_tree.py` 增加 `--root-name` 参数

**问题**：每个 segment 的 `path_raw` 以一级题材名开头（如 `["CPU", "推理芯片"]`），`build_tree_from_items()` 按 `path_raw[0]` 分组，导致 16 个子题材各自成为独立根题材。

**解决方案**：指定 `--root-name` 时，所有 path 自动补上根题材前缀。`process_thesis_image.py` 从图片文件名自动推断。

---

##### 决策 8：执行器模型

**决策**：图片识别任务 → 百炼 coding plan 的 qwen3.6-plus

**API 配置**：
- Endpoint: `https://coding.dashscope.aliyuncs.com/v1`
- 模型: `qwen3.6-plus`（2026-04-12 从 qwen3.5-plus 升级）
- 通过 OpenAI SDK 兼容调用
- 函数名 `call_kimi_k25_image` 是历史遗留误名，实际调用的是 qwen3.6-plus

---

##### 决策 9：股票代码查找

**决策**：通过 `workspace/services/lookup_a_stock_code_by_name` 查找

**原因**：复用已有服务，无需新建股票代码映射逻辑

**查找策略**：精确匹配 → 空格变体 → 模糊匹配（编辑距离 ≤ 1）

**行为**：查不到的打印 `[WARN]` 到 stderr，不阻塞流程

---

##### 决策 10：Copilot gpt-5-mini 作为备选识图模型

**决策**：通过 `--model copilot` 参数支持 GitHub Copilot SDK 调用 gpt-5-mini

**原因**：
- Copilot 订阅免费，不受百炼额度限制
- 作为付费模型的备用方案，额度耗尽时可切换

**对比**：

| | qwen3.6-plus (百炼) | gpt-5-mini (Copilot) |
|---|---|---|
| 速度 | ~3-5 秒/segment | ~30-60 秒/segment |
| 费用 | 有额度限制 | 免费 |
| 识别质量 | 基准 | 通过 prompt 优化后基本持平 |

**Prompt 优化**：为使 copilot 识别质量接近 qwen，prompt 中增加了 7 条结构化规则（题材 vs 股票区分、股票名 ≤5 字、根题材名告知等）。

---

##### 决策 11：股票名模糊匹配

**决策**：`stock_lookup_service` 增加第三级查找策略 — Levenshtein 编辑距离 ≤ 1

**原因**：LLM 的 OCR 识别会产生近形字错误（骄→骐、新能→新能源），精确匹配找不到导致股票丢失

**约束**：仅对 2-5 字名称启用，最大编辑距离 ≤ 1，避免误匹配

**效果**：4 个 OCR 错误中修正了 3 个（五矿新能源→五矿新能、天华新能源→天华新能、骐成超声→骄成超声），1 个边界情况（蠡湖→盐湖）匹配到错误候选

---

##### 已解决的技术问题

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 04-11 | 红线检测遗漏底部子题材 | `bottom_skip_ratio=0.05` 在矮图上过滤范围过大 | 改为 `bottom_skip_px=50` |
| 04-11 | Step 3 超时（300s 不够） | 16 个 LLM 调用串行执行 | 并发 4 路 + 超时改为 600s |
| 04-11 | 8 路并发部分 segment 失败 | API 限流 | 降为 4 路 + 1 秒间隔 |
| 04-11 | 16 个子题材各自成为独立根题材 | `path_raw[0]` 缺少根题材前缀 | 增加 `--root-name` 参数 |
| 04-11 | Step 4 拿到空数据 | `get_latest_file` 匹配到 `*_run_*.json` | 排除 `*_run_*` 文件 |
| 04-12 | 商业航天迁移后路径碎片化 | 旧数据 path 缺少根题材前缀 | `normalize_path()` 自动补前缀 |
| 04-11 | Copilot 识图把股票名当题材节点 | prompt 未区分题材 vs 股票 | 增加 7 条结构化规则 + 股票名 ≤5 字约束 |
| 04-11 | LLM OCR 近形字错误（骄→骐） | 模型视觉识别偏差 | `stock_lookup_service` 增加模糊匹配 fallback |

---

##### 决策 12：校验报告 — Step 6 自动输出

**决策**：Step 5 写入数据库后，自动执行 Step 6 生成 Markdown 校验报告

**原因**：
- 写入后无回校验步骤，用户需要对照原始图片确认解析结果
- 结构化文本输出（层级缩进 + 股票名代码）比直接查数据库直观
- 失败不终止流程（仅报告），避免辅助功能阻塞主流程

**实现**：独立脚本 `verify_thesis_report.py`，复用 `thesis_api.get_full_tree()` 读取数据

---

##### 决策 13：输出目录按题材名归档

**决策**：每次运行清空 `output/{题材名}/` 目录，所有文件使用固定名称（无时间戳）

**原因**：
- 原来每个步骤生成独立时间戳文件（`path_cut_plan_20260417_120000.json`），14+ 文件散落在 `output/` 平目录，难以管理
- 按题材名归档后，`output/锂矿/` 下一目了然，重复运行直接覆盖

**实现**：
- orchestrator (`process_thesis_image.py`) 从 `image_path.stem` 提取题材名，创建 `output/{题材名}/` 子目录
- 每次运行前 `shutil.rmtree` 清空目录
- 每个子脚本新增 `--fixed-name` 参数，启用时写固定文件名
- 文件名映射：`cut_plan.json`, `segments/`, `segment_parse.json`, `ancestor_candidates.json`, `verify_report.md`

**文件名映射**：

| 步骤 | 原文件名（时间戳） | 新文件名（固定） |
|------|-------------------|-----------------|
| Step 1 | `path_cut_plan_{ts}.json/.md` | `cut_plan.json/.md` |
| Step 2 | `path_segments_{ts}/` + `path_segments_manifest_{ts}.*` | `segments/` + `manifest.*` |
| Step 3 | `path_segment_parse_{ts}.json/.md` | `segment_parse.json/.md` |
| Step 4 | `path_ancestor_candidates_{ts}.json/.md` | `ancestor_candidates.json/.md` |
| Step 6 | `verify_report_{ts}.md` | `verify_report.md` |
| Summary | `run_summary_{ts}.json/.md` | `run_summary.json/.md` |

---

##### 待决策事项

###### 待定 1：数据库备份策略

**问题**：是否需要定期备份数据库？

**建议**：暂不需要（数据可从原始图片重新生成）

###### 待定 2：二级以下题材支持

**问题**：当前 `node_type` CHECK 约束只允许 'root' / 'first_level' / 'second_level'。如果出现三级题材怎么办？

**建议**：目前所有测试图片最多二级，出现时再扩展 CHECK 约束。

---

*最后更新：2026-04-17*
