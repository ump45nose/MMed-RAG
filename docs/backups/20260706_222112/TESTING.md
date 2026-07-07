# 评测体系

评测目标不是追求一个漂亮分数，而是证明每个增强点确实对应 naive RAG 的缺陷，并能在医院后勤/医工场景里被量化。

## 评测集

默认评测集：

- 路径：[backend/evaluation/datasets/interview_demo.jsonl](./backend/evaluation/datasets/interview_demo.jsonl)
- 数量：41 条
- 可答/负例：32 / 9
- 难度：easy 10、medium 21、hard 10
- 类型覆盖：事实型、流程型、跨文档型、医工设备类、路由型、拒答策略型、评测说明型、负例

问题不是通用 QA，而是来自医院后勤/医工资料的典型任务：

- 报修工单如何派单、接单、完工、评价闭环。
- 医废产生、收集、交接、转运、暂存如何衔接。
- 保洁质量检查或评分如何记录。
- 运送任务状态和执行节点如何追溯。
- 设备/资产台账维护哪些字段。
- 医疗设备无人值守系统如何处理异常告警。
- 售前资料、操作手册、问题整理之间如何跨文档对齐。
- 库中无依据、未来信息、隐私、账号密码、编造编号等负例如何拒答。

## 指标

| 指标 | 衡量什么 | 为什么需要 |
| --- | --- | --- |
| Recall@5 | Top5 parent 是否覆盖标注依据 | 证明“能不能找回来” |
| MRR | 第一个相关 parent 排名是否靠前 | 影响 LLM 最先看到的证据质量 |
| nDCG@10 | 排序整体质量 | 适合多依据、跨文档问题 |
| P95 latency | 95 分位检索耗时 | 面试 Demo 也要体现可用性 |
| negative_refusal_rate | 负例是否被拒答 | 医疗/后勤场景不能硬答 |

本项目按 parent_id 计分，而不是按 child chunk 计分。原因是生成阶段真正注入的是 parent context，child 只是召回单元；如果评测 child 命中，会高估可追溯回答质量。

## Ablation 配置

评测服务内置 5 组配置：

1. `baseline: dense only + 裸切分`
2. `+ 领域分块 + 父子检索`
3. `+ hybrid RRF`
4. `+ reranker`
5. `+ router + hybrid + reranker + refusal`

入口：

- 后端实现：[backend/app/services/evaluation_service.py](./backend/app/services/evaluation_service.py)
- 指标实现：[backend/app/services/evaluation_metrics.py](./backend/app/services/evaluation_metrics.py)
- 前端页面：[frontend/src/app/dashboard/evaluation/page.tsx](./frontend/src/app/dashboard/evaluation/page.tsx)

## 当前结果

当前报告截图：

![evaluation-report-router-refusal](./docs/images/evaluation-report-router-refusal.png)

| 配置 | Recall@5 | MRR | nDCG@10 | P95 延迟 | 负例拒答率 | 解释 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| baseline: dense only + 裸切分 | 0.328 | 0.234 | 0.247 | 79ms | 0.000 | dense 能召回部分语义相近内容，但专有词、流程节点和跨文档排序弱 |
| + 领域分块 + 父子检索 | 0.328 | 0.234 | 0.247 | 54ms | 0.000 | 本次标注集的 TopK 命中未变，但上下文完整性改善，延迟下降 |
| + hybrid RRF | 0.438 | 0.328 | 0.346 | 84ms | 0.000 | sparse/BM25 补上关键词、编号、业务术语，召回和排序提升 |
| + reranker | 0.641 | 0.544 | 0.547 | 80ms | 0.000 | 精排显著改善首个相关 parent 位置 |
| + router + hybrid + reranker + refusal | 0.641 | 0.544 | 0.547 | 55ms | 1.000 | 保持检索质量，候选库收敛降低延迟，负例拒答闭环 |

从 naive dense 到最终链路：

- Recall@5：0.328 -> 0.641，提升约 95.4%。
- MRR：0.234 -> 0.544，提升约 132.5%。
- nDCG@10：0.247 -> 0.547，提升约 121.5%。
- 负例拒答率：0.000 -> 1.000。
- P95 latency：79ms -> 55ms，下降约 30.4%。

## 每个选择的 trade-off

| 选择 | 收益 | 代价 | 当前控制方式 |
| --- | --- | --- | --- |
| 父子检索 | 召回粒度细，生成上下文完整 | 入库多一层 parent/child 表，重建索引复杂 | stable id、MySQL DocStore、child scalar metadata |
| hybrid RRF | 专有词和语义互补，分数不可比也能融合 | 多跑一路 sparse/lexical 检索 | RRF 只用 rank，Milvus 不可用时 fallback |
| reranker | 排序质量提升明显 | 增加模型调用成本和延迟 | 只对候选集 rerank，TopN 可配 |
| Router | 多知识库降低噪声，延迟可下降 | Router 可能选错库 | KB profile fallback、允许传入 KB 约束 |
| 拒答阈值 | 降低幻觉和敏感信息风险 | 阈值过高会误拒答 | confidence + query support + explicit trigger，并在 trace 中展示原因 |
| metadata 权限过滤 | 降低越权召回风险 | 依赖入库 metadata 质量 | 上传预览建议 + 人工确认 + confirm 后同步 parent/child |

## 如何复现评测

启动后端和前端后，在 UI 中打开：

```text
http://localhost:3000/dashboard/evaluation
```

或调用接口：

```bash
curl -X POST http://localhost:8000/api/evaluation/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"kb_ids\":[1]}"
```

运行单元测试：

```bash
py -m pytest backend/tests/test_rag_demo_unit.py -q
```

前端构建：

```bash
npm --prefix frontend run build
```

注意：如果默认构建目录被占用，先顺序重试；重试后仍占用时停止并排查并发构建，不切换构建目录污染仓库。

## 当前局限

- 评测集仍是面试级规模，不等价于生产验收集。
- 部分指标依赖 parent_id 标注质量；文档重新入库后需要检查标注是否仍一致。
- 当前负例覆盖了不存在实体、未来信息、隐私、凭据、编造和缺证据问题，但还可以扩展为医疗安全分级拒答集。
- Latency 是本地演示环境结果，生产环境需要按模型服务、Milvus 部署、并发量重新压测。
