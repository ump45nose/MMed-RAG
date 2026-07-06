# 发现与决策

## 需求
- 把 Demo 改成面试展示用 RAG 系统。
- 重点展示知识库级召回、chunk 级检索、LLM 前置路由、多知识库召回后统一重排。
- 增加评测集与指标，包括 Recall@k、MRR、nDCG，并支持 embedding、hybrid、reranker 对照。
- 增加 BM25 + dense + RRF 的混合检索链路。
- 模型配置要能支持 bge-m3 embedding 与 bge-reranker-v2-m3，并解释中文、dense/sparse/ColBERT 能力。
- 上传时补充 metadata，支持领域感知分块和大规模知识库构建场景说明。
- 调整全量注入上下文问题，只注入重排后的高质量上下文。

## 研究发现
- 仓库是 Python FastAPI 后端与 Next.js 前端结构。
- 初始 git 状态已有未提交改动：`.env.example` 删除，多个后端文件修改，新增 `rerank_service.py`、`pyproject.toml`、`uv.lock` 等。

## 技术决策
| 决策 | 理由 |
|------|------|
| 先阅读现有检索、上传、向量库和配置代码 | 确认能以最小改动落地需求 |
| 一期默认只处理 DOCX/PDF 主路径 | 原始目录中压缩包占主要体积，直接纳入会把一期变成解压/OCR/失败隔离工程 |
| Milvus 实装、Celery 预留 | 向量库切换是面试 demo 的核心生产信号，任务队列可作为二期生产化扩展 |
| Recall 按 parent_id 命中计算 | 父子检索下 child 只是召回单元，生成上下文和评测命中都应按 parent 判定 |

## 遇到的问题
| 问题 | 解决方案 |
|------|---------|
| 暂无 | 暂无 |

## 资源
- 本地仓库：`D:\work\github\rag-web-ui`
- 当前仓库：`P:\WorkSpace\rag-web-ui`
- 原始数据目录统计：DOCX 42 个约 490MB，PDF 2 个约 26MB，ZIP/RAR 约 760MB

## 视觉/浏览器发现
- 暂无

---
*每执行2次查看/浏览器/搜索操作后更新此文件*
*防止视觉信息丢失*
