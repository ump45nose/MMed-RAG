# 面试话术与答题稿

本文件只用于个人准备，不在 README 中引用。

## 30 秒项目总结

我把基础 RAG 链路改造成了一个医院后勤与医工资料检索系统。场景里有长文档、多知识库、部门权限、专有词和拒答要求，所以我做了结构化 Router、KB profile、父子检索、hybrid RRF、rerank、RAG trace 和拒答门禁。当前 41 条业务评测集上，最终链路 Recall@5 0.641、MRR 0.544、nDCG@10 0.547，负例拒答率 1.000。

## 为什么不是套壳 RAG

回答要点：

- 不是单纯上传文档后 dense TopK。
- 业务问题来自医院后勤、医废、保洁、运送、医工设备等资料。
- 每个增强点都对应真实限制：长文档要父子检索，专有词要 sparse/BM25，多知识库要 Router，医疗场景要权限和拒答。
- 有 trace 和 ablation，不只展示最终答案。

## 难点 1：大文档切分

**问题**：DOCX/PDF 中有标题、流程、表格和条款，固定 chunk size 容易切断流程或表格。

**试过**：

- 调大 chunk：上下文完整但召回变粗。
- 小 chunk：召回细但生成上下文不足。

**最终方案**：

- child chunk 入向量库负责召回。
- parent chunk 存 MySQL 负责生成和引用。
- 保留 section_path、page、table markdown、条款边界。

**效果**：

- 引用能定位 parent/child、页码和章节路径。
- 最终链路 Recall@5 从 0.328 提升到 0.641。

## 难点 2：专有词检索

**问题**：纯 dense 对“医废交接签名”“无人值守告警”“设备型号/编号”不稳定。

**试过**：

- 只换 embedding，有改善但不稳定。
- 只做关键词规则，维护成本高。

**最终方案**：

- Dense 负责语义召回。
- BGE-M3 sparse / BM25 负责关键词、编号和中文术语。
- RRF 用 rank 融合，避免不同检索器分数不可比。

**效果**：

- hybrid RRF 后 Recall@5 从 0.328 提升到 0.438。
- rerank 后 Recall@5 到 0.641，MRR 到 0.544。

## 难点 3：拒答与追溯

**问题**：库里没有答案时，LLM 可能基于弱上下文硬答；医疗后勤场景不能暴露隐私、账号密码或编造信息。

**方案**：

- 检索后、生成前计算 answer_policy。
- 使用 confidence、query support、显式风险触发器和 parent context 判断是否拒答。
- trace 记录拒答原因、候选、latency 和 confidence。

**效果**：

- 最终链路负例拒答率 1.000。
- 拒答发生在调用 LLM 生成前，减少幻觉和敏感泄露风险。

## 高频问题

**为什么不用直接调大 chunk size？**  
调大 chunk 会提升上下文完整度，但召回粒度变粗，TopK 更容易被无关内容占掉。父子检索把召回粒度和生成上下文拆开。

**为什么用 RRF？**  
Dense、BM25、BGE-M3 sparse 的分数分布不可比。RRF 只用排名，跨模型和向量库更稳。

**Router 错了怎么办？**  
Router 只在用户可用 KB 范围内收窄，不越权；KB profile 提供 fallback；trace 会展示 candidate_kbs 和 selected_kbs，便于复盘。

**拒答会不会误伤？**  
会，所以拒答不是单一阈值，而是 confidence、query support 和显式风险触发器组合；阈值可配置，trace 记录原因。

**怎么证明有效？**  
看 ablation：dense only -> hybrid RRF -> rerank -> router/refusal。最终 Recall@5 0.641、MRR 0.544、nDCG@10 0.547、负例拒答率 1.000。
