#!/usr/bin/env python3
import json, os, sys, ssl, urllib.request, urllib.error
import numpy as np
from sklearn.cluster import KMeans

# ── 1. 加载新闻 ──
_news_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_data")
news_path = os.path.join(_news_dir, "financial_news_2026-03-27.json")
with open(news_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

# 过滤空标题
news = [item for item in raw if item.get("title") and item["title"].strip()]
news = news[:500]
print(f"加载新闻 {len(news)} 条 (过滤空标题后取前500)")

# ── 2. 生成 Embedding ──
EMBED_URL = "http://127.0.0.1:11434/api/embeddings"
headers_emb = {"Content-Type": "application/json"}

def get_embedding(text):
    payload = json.dumps({"model": "bge-m3", "prompt": text}).encode()
    req = urllib.request.Request(EMBED_URL, data=payload, headers=headers_emb)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    resp = urllib.request.urlopen(req, context=ctx, timeout=60)
    data = json.loads(resp.read())
    return data["embedding"]

print("生成 embeddings ...")
vectors = []
for i, item in enumerate(news):
    title = item["title"].strip()
    vec = get_embedding(title)
    vectors.append(vec)
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(news)}")

vectors = np.array(vectors)
print(f"Embeddings shape: {vectors.shape}")

# ── 3. K-Means 聚类 ──
n_clusters = 10
kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit(vectors)
labels = kmeans.labels_
print("聚类完成")

# ── 4. 算法 B: 最大间隔选代表 ──
def max_spread_indices(cluster_indices, vectors, centroid):
    vs = [vectors[i] for i in cluster_indices]
    selected = []
    
    # 第1条: 质心最近
    dists_center = [np.linalg.norm(v - centroid) for v in vs]
    selected.append(int(np.argmin(dists_center)))
    
    # 第2-10条
    for _ in range(min(9, len(vs) - 1)):
        avg_dists = []
        for j, v in enumerate(vs):
            if j in selected:
                avg_dists.append(float('inf'))
            else:
                avg_dists.append(np.mean([np.linalg.norm(v - vs[s]) for s in selected]))
        selected.append(int(np.argmax(avg_dists)))
    
    return [cluster_indices[i] for i in selected]

cluster_representatives = {}  # label -> list of news indices
for label in range(n_clusters):
    cluster_indices = list(np.where(labels == label)[0])
    centroid = kmeans.cluster_centers_[label]
    rep_indices = max_spread_indices(cluster_indices, vectors, centroid)
    cluster_representatives[label] = rep_indices

# ── 5. 构建 LLM Prompt ──
prompt_lines = ["你是资深市场分析师。请分析以下今日财经新闻（100条，来自10个聚类）。", ""]

for label in range(n_clusters):
    rep_indices = cluster_representatives[label]
    prompt_lines.append(f"[聚类{label} - {len(list(np.where(labels == label)[0]))}条] 候选新闻：")
    for idx in rep_indices:
        title = news[idx]["title"].replace("\n", " ").strip()
        source = news[idx].get("source", "")
        prompt_lines.append(f"  - {title} ({source})")
    prompt_lines.append("")

prompt_lines.append("""## 请从以下维度分析：

### 一、宏观经济形势判断（重点）
1. 全球经济：主要经济体（美国/欧洲/中国/新兴市场）状况
2. 地缘政治：当前局势对市场的影响
3. 货币政策：央行态度，利率走向
4. 大宗商品：供需格局，价格走势

### 二、市场机会与风险
- 列出当前最有价值的 3 个投资机会（附理由）
- 列出当前最需警惕的 3 个风险

### 三、聚类主题总结
- 为每个聚类（聚类0-聚类9）命名并简要描述其主题""")

user_prompt = "\n".join(prompt_lines)
print(f"Prompt 长度: {len(user_prompt)} 字符")

# ── 6. 调用 LLM ──
print("调用 LLM (qwen3.5-plus) ...")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

proxy = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
proxy_handler = urllib.request.ProxyHandler(proxy)
opener = urllib.request.build_opener(proxy_handler)

payload = json.dumps({
    "model": "qwen3.5-plus",
    "messages": [
        {"role": "system", "content": "你是资深市场分析师。请用中文详细分析，不要截断内容。"},
        {"role": "user", "content": user_prompt}
    ],
    "temperature": 0.7,
    "max_tokens": 16384
}).encode()

# 从环境变量读取 API Key
BAILIAN_API_KEY = os.environ.get("BAILIAN_API_KEY", "")
if not BAILIAN_API_KEY:
    print("ERROR: BAILIAN_API_KEY 未设置（阿里百炼 Coding Plan API）", file=sys.stderr)
    sys.exit(1)

req = urllib.request.Request(
    "https://coding.dashscope.aliyuncs.com/v1/chat/completions",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {BAILIAN_API_KEY}"}
)

resp = opener.open(req, timeout=180)
result = json.loads(resp.read())
llm_output = result["choices"][0]["message"]["content"]
print("LLM 返回完成")

# ── 7. 输出完整结果 ──
output = {"clusters": {}, "representatives": {}, "llm_analysis": llm_output}

print("\n" + "="*80)
print("【聚类分布】")
print("="*80)
for label in range(n_clusters):
    count = int(np.sum(labels == label))
    rep_indices = cluster_representatives[label]
    # 简短主题: 取第一条代表新闻标题
    first_title = news[rep_indices[0]]["title"][:30]
    output["clusters"][f"cluster_{label}"] = {"size": count, "representative_titles": [news[i]["title"] for i in rep_indices]}
    print(f"\n聚类{label} ({count}条) — 示例: {first_title}")
    print(f"  代表新闻:")
    for idx in rep_indices:
        print(f"    - {news[idx]['title'][:60]}")

print("\n" + "="*80)
print("【LLM 完整分析】")
print("="*80)
print(llm_output)

# 保存到文件
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cluster_analysis_result.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n结果已保存到: {output_path}")
