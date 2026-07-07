# 架构设计

本系统围绕医院后勤与医工资料的“入库、检索、生成、评测、追溯”设计。核心原则是：检索链路必须可解释，生成答案必须有证据，缺少证据时必须拒答。

## 总体架构

```mermaid
flowchart TB
  subgraph FE[Next.js 前端]
    KB[知识库管理]
    Upload[上传与预览]
    Chat[聊天与引用]
    Test[检索测试]
    Eval[评测报告]
  end

  subgraph API[FastAPI 后端]
    KBA[Knowledge Base API]
    CHA[Chat Streaming API]
    EVA[Evaluation API]
    CHK[DomainDocumentChunker]
    META[MetadataSuggestionService]
    ROUTER[QueryRouterService]
    PROFILE[KBProfileService]
    RET[ParentContextRetriever]
    TRACE[RagTraceService]
  end

  subgraph STORE[存储]
    MYSQL[(MySQL\n文档/Parent/Child/Trace)]
    MINIO[(MinIO\n源文件)]
    VECTOR[(Chroma/Milvus/Qdrant\nChild 向量)]
  end

  KB --> KBA
  Upload --> KBA
  Chat --> CHA
  Test --> KBA
  Eval --> EVA

  KBA --> MINIO
  KBA --> CHK
  KBA --> META
  CHK --> MYSQL
  CHK --> VECTOR
  CHK --> PROFILE

  CHA --> RET
  EVA --> RET
  RET --> ROUTER
  RET --> PROFILE
  RET --> VECTOR
  RET --> MYSQL
  RET --> TRACE
  TRACE --> MYSQL
```

## 入库链路

```mermaid
sequenceDiagram
  participant User as 用户
  participant FE as 上传页
  participant API as 后端 API
  participant Obj as MinIO
  participant Chunk as 分块服务
  participant DB as MySQL
  participant Vec as 向量库

  User->>FE: 上传 DOCX/PDF/TXT/MD
  FE->>API: 上传文件
  API->>Obj: 保存源文件
  API->>Chunk: 解析标题、表格、页码、条款
  Chunk->>DB: 写 parent chunk
  Chunk->>DB: 写 child metadata
  Chunk->>Vec: 写 child vector
  API->>DB: 刷新 KB profile
```

### 为什么这样设计

| 设计 | 原因 |
| --- | --- |
| 源文件保存到 MinIO | 支持重试、重建索引、审计和后续解析优化 |
| parent/child 两层 chunk | child 适合召回，parent 适合生成和引用 |
| 标题、表格、条款边界保护 | 医院流程和制度文档不能被机械切断 |
| metadata 建议与确认 | department、doc_type、effective_date 会影响权限和过滤 |
| MySQL + 向量库双写 | MySQL 保存可审计上下文，向量库负责召回效率 |

## 检索链路

```mermaid
sequenceDiagram
  participant Q as Query
  participant R as Router
  participant P as KB Profile
  participant F as Filter
  participant D as Dense
  participant S as Sparse/BM25
  participant X as RRF
  participant E as Rerank
  participant C as Parent Context
  participant G as Refusal Gate

  Q->>R: 识别 intent/domain/rewrite/candidate_kbs
  R->>P: profile 兜底匹配
  P->>F: 生成 selected_kbs
  F->>D: dense child 检索
  F->>S: sparse/BM25 child 检索
  D->>X: dense 排名
  S->>X: sparse 排名
  X->>E: 融合候选
  E->>C: 精排后 parent 去重
  C->>G: 计算 confidence 与拒答策略
```

### 模块取舍

| 模块 | 选择原因 | 替代方案问题 |
| --- | --- | --- |
| Query Router | 多知识库下先收窄候选，降低噪声召回 | 全库检索容易把通用维修资料排到前面 |
| KB Profile | Router 失败时仍可用关键词和摘要兜底 | 完全依赖 LLM 路由会降低稳定性 |
| Dense + Sparse/BM25 | 兼顾语义召回与专有词、编号召回 | 单纯 dense 对短词、设备型号不稳定 |
| RRF | 不要求不同检索器分数可比 | 直接分数加权对模型和向量库敏感 |
| Rerank | 提升 TopK 排序质量 | 全量 rerank 成本和延迟不可控 |
| Parent 去重 | 避免多个 child 重复占用上下文 | 直接塞 child 会导致答案缺上下文或重复 |
| 拒答门禁 | 在生成前拦截无证据问题 | 只靠 prompt 约束无法稳定拒答 |
| Trace 落库 | 支持问题复盘、质量分析和审计 | 只保存最终答案无法解释错误来源 |

## 数据模型

```mermaid
erDiagram
  users ||--o{ knowledge_bases : owns
  knowledge_bases ||--o{ documents : contains
  documents ||--o{ document_parent_chunks : has
  document_parent_chunks ||--o{ document_chunks : contains
  users ||--o{ rag_traces : creates
  chats ||--o{ rag_traces : records
```

关键表：

| 表 | 作用 |
| --- | --- |
| `documents` | 源文档 metadata、部门、文档类型、设备型号、有效期 |
| `document_parent_chunks` | 生成上下文和引用证据 |
| `document_chunks` | 检索单元，保存 parent_id 与 scalar filter 字段 |
| `knowledge_bases` | KB profile、关键词、文档数量 |
| `rag_traces` | query、路由、候选、latency、confidence、拒答原因 |

数据库变更同时提供 Alembic migration 与 SQL 文件，分别位于 `backend/alembic/versions` 和 `backend/database`。

## 主要代码位置

| 文件 | 职责 |
| --- | --- |
| `backend/app/services/document_chunker.py` | 领域分块、parent/child 生成、章节路径保留 |
| `backend/app/services/metadata_service.py` | metadata 建议与确认合并 |
| `backend/app/services/query_router_service.py` | 结构化路由与启发式 fallback |
| `backend/app/services/kb_profile_service.py` | KB profile 构建与匹配 |
| `backend/app/services/retrieval_service.py` | 检索主链路、RRF、rerank、拒答 |
| `backend/app/services/vector_store/milvus.py` | Milvus dense/sparse/BM25/filter 适配 |
| `backend/app/services/evaluation_service.py` | ablation 评测 |
| `frontend/src/components/retrieval/retrieval-trace-panel.tsx` | 检索链路可视化 |

## 降级策略

- Milvus sparse/BM25 不可用时，回退到 SQL lexical search。
- Router 可关闭，关闭后使用用户选择的知识库范围。
- Metadata LLM 可关闭，关闭后使用启发式建议。
- Rerank 可关闭，保留 dense/hybrid 检索。
- 拒答阈值可配置，trace 中记录拒答原因。
