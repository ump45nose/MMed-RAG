# 操作与验证脚本

本文档用于本地启动、页面验证和质量检查。

## 启动服务

后端依赖与后端服务：

```bash
py scripts/rag_stack.py --profile home up --seed
```

启动完整栈：

```bash
py scripts/rag_stack.py --profile home up --seed --full
```

前端开发服务：

```bash
npm --prefix frontend run dev
```

访问地址：

- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/api/health`
- MinIO：`http://localhost:9001`

## 数据库

应用启动时会执行 Alembic migration。需要手动迁移时：

```bash
docker compose -f docker-compose.dev.yml exec -T backend alembic upgrade head
```

展示数据命名修正脚本：

```text
backend/database/20260706_business_kb_display_names.sql
```

执行 SQL 时应避免 PowerShell 管道导致中文转码，推荐复制到 MySQL 容器内执行：

```bash
docker cp backend/database/20260706_business_kb_display_names.sql rag-web-ui-db-1:/tmp/20260706_business_kb_display_names.sql
docker exec rag-web-ui-db-1 mysql -uragwebui -pragwebui --default-character-set=utf8mb4 ragwebui -e "source /tmp/20260706_business_kb_display_names.sql"
```

## 页面验证路径

### 1. 知识库

路径：

```text
/dashboard/knowledge
```

验证点：

- 主知识库包含医院后勤、医废、保洁、运送、医工设备资料。
- 噪声知识库存在，用于验证 Router 抑制无关资料。
- 文档列表展示文件、metadata、处理状态和索引状态。

截图：

```text
docs/images/kb-list.png
docs/images/kb-detail-documents.png
```

### 2. 文档上传与预览

路径：

```text
/dashboard/knowledge/{kb_id}/upload
```

验证点：

- 支持 PDF、DOCX、TXT、MD。
- 上传后进入预览阶段。
- 预览应展示 metadata 建议、parent chunk 数和 child chunk 内容。

当前自动截图只覆盖到文件选择状态；metadata 预览截图需要在上传接口和前端状态稳定后补齐。

### 3. 检索测试

路径：

```text
/dashboard/test-retrieval/{kb_id}
```

推荐查询：

```text
医废管理中收集、转运、暂存的流程如何衔接？
```

验证点：

- Dense 候选、Sparse/BM25 候选、RRF 候选、Rerank 后候选。
- Router intent、domain、query rewrite、selected KB。
- confidence、threshold、latency。
- parent_id、section_path、page、child_ids。

截图：

```text
docs/images/retrieval-dense.png
```

### 4. 聊天与拒答

路径：

```text
/dashboard/chat/{chat_id}
```

推荐拒答问题：

```text
请给出量子发动机 QX-9000 的维修参数。
```

验证点：

- answer_policy 中 `should_refuse=true`。
- trace 中展示拒答原因。
- 生成前停止硬答。

截图：

```text
docs/images/chat-refusal.png
```

### 5. 评测报告

路径：

```text
/dashboard/evaluation
```

验证点：

- 数据集统计：41 条问题、32 条可答、9 条负例。
- 消融矩阵展示 Recall@5、MRR、nDCG@10、P95 延迟、负例拒答率。
- 最终链路负例拒答率为 1.000。

截图：

```text
docs/images/evaluation-report-current.png
```

## API 验证

健康检查：

```bash
curl http://localhost:8000/api/health
```

运行评测：

```bash
curl -X POST http://localhost:8000/api/evaluation/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"kb_ids\":[1]}"
```

检索测试：

```bash
curl -X POST http://localhost:8000/api/knowledge-base/test-retrieval \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"医废管理中收集、转运、暂存的流程如何衔接？\",\"kb_id\":1,\"top_k\":3,\"retriever\":\"hybrid_rrf\",\"rerank_enabled\":true,\"kb_router_enabled\":true}"
```
