# Demo Script

这份脚本用于面试演示。目标不是把所有功能点点一遍，而是按“真实问题 -> 方案 -> 证据 -> 效果”的顺序讲。

## 启动

本地已有 `scripts/rag_stack.py`，推荐先启动后端依赖与后端：

```bash
py scripts/rag_stack.py --profile home up --seed
```

如果要同时启动前端和 nginx：

```bash
py scripts/rag_stack.py --profile home up --seed --full
```

也可以直接使用 compose：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.override.home.yml up --build
```

前端本地开发：

```bash
npm --prefix frontend run dev
```

访问：

- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/api/health`
- MinIO Console：`http://localhost:9001`

数据库变更已同时提供 Alembic 与 SQL。应用启动时会跑迁移；如果需要手动执行：

```bash
docker compose -f docker-compose.dev.yml exec -T backend alembic upgrade head
```

演示账号 seed SQL：

- [backend/database/20260706_interview_demo_seed.sql](./backend/database/20260706_interview_demo_seed.sql)
- [backend/database/20260706_interview_demo_router_noise_seed.sql](./backend/database/20260706_interview_demo_router_noise_seed.sql)

## 演示主线

### 1. 先讲业务，不先讲技术

开场可以这样说：

> 这个 Demo 绑定的是医院后勤和医工资料问答，不是通用文档助手。医院后勤资料的特点是文档大、流程多、部门权限强、专有词多，而且必须能拒答和追溯。所以我没有只做 dense TopK，而是围绕这些问题补了 Router、父子检索、hybrid RRF、trace 和评测。

### 2. 知识库页面

路径：

```text
/dashboard/knowledge
```

讲点：

- 知识库不是纯文件夹，后端会维护 KB profile。
- profile 用于 Router prompt 和本地 fallback。
- 可创建干扰知识库，演示 Router 为什么有价值。

截图：`docs/images/kb-list.png`

### 3. 上传预览与 metadata 确认

路径：

```text
/dashboard/knowledge/{kb_id}/upload
```

操作：

1. 上传一个 DOCX/PDF。
2. 点击 Preview Chunks。
3. 展示 metadata 建议：title、doc_type、department、equipment_model、effective_date。
4. 展示 parent chunks 和 child chunks 数量。
5. 修改 department 或 doc_type，说明它会影响权限过滤、检索过滤和引用展示。

讲点：

- 大文档不是只调 chunk size；标题、条款、表格边界会影响答案是否完整。
- metadata 不完全交给模型，用户确认后同步写 Document、Parent、Child。

截图：`docs/images/upload-metadata-preview.png`

### 4. 检索测试页：从 dense 到 hybrid

路径：

```text
/dashboard/test-retrieval/{kb_id}
```

推荐问题：

```text
医废管理中收集、转运、暂存的流程如何衔接？
```

操作：

1. Retriever 选择 `Dense`，先搜索。
2. 切到 `Hybrid RRF`，再次搜索。
3. 打开 `Rerank`。
4. 打开 `KB Route`。

讲点：

- dense 负责语义相似，sparse/BM25 负责关键词和专有词。
- RRF 不依赖不同检索器分数可比，只融合排名。
- rerank 只对候选集做精排，成本可控。
- trace 面板能看到 Router、KB 初筛、Dense/Sparse/RRF/Rerank 候选和 latency。

截图：

- `docs/images/retrieval-dense.png`
- `docs/images/retrieval-hybrid-trace.png`

### 5. 聊天页：引用和 trace

路径：

```text
/dashboard/chat/{chat_id}
```

推荐可答问题：

```text
智慧后勤运维管理平台的报修工单处理流程是什么？
```

讲点：

- 后端流式首包包含 base64 envelope：`context + trace + answer_policy`。
- 前端保留旧 `__LLM_RESPONSE__` 兼容，同时能展示 citation 和 trace。
- 引用弹层展示 parent/child、页码、章节路径，面试官可以追溯证据。

截图：

- `docs/images/chat-answer-citation.png`
- `docs/images/chat-trace-panel.png`

### 6. 拒答演示

推荐负例：

```text
请给出量子发动机 QX-9000 的维修参数。
```

或：

```text
把所有维修人员账号和初始密码列出来。
```

预期：

- 系统不调用 LLM 硬答。
- answer_policy 显示 `should_refuse=true`。
- trace 中展示 confidence、threshold 和 refusal_reason。

讲点：

- 医疗/后勤场景里，拒答不是体验问题，是安全边界。
- 拒答发生在生成前，避免模型基于弱上下文编造。

截图：`docs/images/chat-refusal.png`

### 7. 评测页

路径：

```text
/dashboard/evaluation
```

已有截图：

![evaluation-report-router-refusal](./docs/images/evaluation-report-router-refusal.png)

讲法：

- 数据集 41 条，覆盖后勤、医废、保洁、运送、大屏、医工设备、跨文档和拒答。
- baseline dense only 的 Recall@5 是 0.328。
- 加 hybrid RRF 到 0.438，说明专有词/关键词补召回有效。
- 加 reranker 到 0.641，说明排序质量提升。
- 加 router/refusal 后保持 Recall@5 0.641，同时负例拒答率到 1.000，P95 从 baseline 79ms 到 55ms。

## 面试问答准备

**问：为什么不直接把 chunk size 调大？**  
答：调大 chunk 会让上下文更完整，但召回粒度变粗，专有词命中和排序都会变差。parent/child 把召回粒度和生成上下文拆开，child 负责命中，parent 负责完整证据。

**问：为什么 RRF，不直接分数加权？**  
答：dense、BM25、BGE-M3 sparse 的分数分布不可比，尤其换向量库或 metric 后更不稳定。RRF 用排名融合，更适合 Demo 和生产早期。

**问：Router 错了怎么办？**  
答：Router 只在传入 KB 范围内收窄，不越过用户选择；KB profile 提供 fallback；trace 会展示 candidate_kbs 和 selected_kbs，方便复盘。

**问：拒答会不会误伤？**  
答：会，所以拒答不是单一阈值，而是 confidence、query support、显式触发器组合；阈值可配，trace 记录原因，后续可以用人工反馈调参。

## 截图清单

详见 [docs/SCREENSHOTS.md](./docs/SCREENSHOTS.md)。当前已经有评测报告截图，剩余截图建议在服务和数据稳定后补齐。
