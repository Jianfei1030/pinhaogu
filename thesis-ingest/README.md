# thesis-ingest

题材注入子模块 — 从开盘啦截图识别题材层级 + 成分股 → 写入 SQLite。

**完整文档**: 见 [stock-monitor/README.md → thesis-ingest 章节](../README.md#thesis-ingest-题材注入系统)

## 快速开始
```bash
python3 scripts/process_thesis_image.py --image input_images/光伏.png --db thesis.db
```

## 输出目录结构

每次运行按题材名归档，输出到 `output/{题材名}/`，文件名无时间戳，重复运行直接覆盖：

```
output/锂矿/
├── cut_plan.json              # Step 1: 切割方案
├── cut_plan.md
├── segments/                  # Step 2: segment 图片
│   ├── segment_01.png ~ N.png
│   ├── manifest.json
│   ├── manifest.md
│   └── manifest_contact.png
├── segment_parse.json         # Step 3: 多模态解析结果
├── segment_parse.md
├── ancestor_candidates.json   # Step 4: 祖先候选展开
├── ancestor_candidates.md
├── verify_report.md           # Step 6: 校验报告（含描述）
├── run_summary.json           # 运行摘要
└── run_summary.md
```
