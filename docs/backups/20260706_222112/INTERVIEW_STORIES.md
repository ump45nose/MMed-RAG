# 面试难点故事

每个故事都按“遇到什么问题 -> 试过什么方案 -> 为什么最终这样选 -> 效果”来讲，避免变成技术名词堆砌。

## 故事 1：1.3GB+ 医院资料不是简单调 chunk size

**遇到什么问题**

医院后勤资料里有操作手册、培训资料、问题整理、设备资料和压缩附件。单个 DOCX/PDF 可能很大，内容里有流程、表格、条款、页面标题。最开始如果按固定 chunk size 切，常见问题是：

- 报修流程被切成多段，答案漏掉“评价/回访闭环”。
- 表格行列关系被切断，字段解释对不上。
- 章节路径丢失，引用只能说来自某文件，不能说来自哪个章节。
- chunk 调大后上下文完整了，但召回粒度变粗，TopK 更容易被无关内容占掉。

**试过什么方案**

1. 只调大 chunk size 和 overlap。  
   结果是部分答案更完整，但召回质量下降，重复上下文变多。

2. 只保留小 chunk。  
   结果是专有词命中更好，但生成时上下文不够，尤其流程型问题容易漏步骤。

3. 用 parent/child 两层结构。  
   child 控制在更适合检索的粒度，parent 保留自然段落、标题、条款和表格上下文。

**为什么最终这样选**

医院资料问答真正需要的是“细粒度命中 + 完整证据”。所以最终把召回单元和生成单元拆开：

- `DocumentChunk` 是 child，写入向量库，带 parent_id、section_path、page、department 等 scalar metadata。
- `DocumentParentChunk` 是 parent，存在 MySQL，作为 LLM 上下文和引用证据。
- DOCX 解析时保留标题层级和表格，PDF 保留页码。
- 上传预览阶段展示 parent/child 数量和 metadata，让业务人员能提前发现切分是否离谱。

**效果**

在当前评测截图中，最终链路 Recall@5 达到 0.641，相比 baseline 0.328 提升约 95.4%。更重要的是，引用能落到 parent/child、页码和章节路径，面试时能解释“答案为什么可信”。

## 故事 2：医疗后勤专有词让纯 dense retrieval 不稳定

**遇到什么问题**

医院后勤和医工资料有大量专有词、缩写、设备型号和流程词，例如：

- 医废、暂存、交接签名、转运。
- 无人值守、设备异常告警。
- QX-9000、银行账号、初始密码等负例关键词。

纯 dense retrieval 对语义相近问题表现不错，但对这些词经常不稳定：有时召回的是“维修流程”泛化内容，而不是具体“医废交接”或“设备告警”段落。

**试过什么方案**

1. 只换 embedding 模型。  
   有改善，但对编号、型号、短关键词仍不够稳定。

2. 增加关键词 filter。  
   对个别问题有效，但规则维护成本高，也容易漏召回。

3. dense + sparse/BM25 + RRF。  
   dense 保留语义召回，sparse/BM25 补关键词和专有词，RRF 做排名融合。

**为什么最终这样选**

RRF 的好处是不用强行比较不同检索器分数。dense cosine、BM25、BGE-M3 sparse 的分数分布不同，直接加权容易调不稳；RRF 只看排名，换 Chroma/Milvus 或 sparse 实现时更稳。

Milvus 适配层里保留两类 sparse：

- BGE-M3 learned sparse，适合语义化稀疏表达。
- BM25 sparse 字段，配合 jieba analyzer 处理中文词法匹配。

如果 Milvus sparse 能力或依赖不可用，系统 fallback 到 SQL lexical search，演示不会中断。

**效果**

当前评测中，从 `+ 领域分块 + 父子检索` 到 `+ hybrid RRF`，Recall@5 从 0.328 提升到 0.438，MRR 从 0.234 提升到 0.328，nDCG@10 从 0.247 提升到 0.346。说明 sparse 分支确实补到了 dense 不稳定的部分。

## 故事 3：知识助手必须能拒答和追溯

**遇到什么问题**

医院后勤系统不是开放聊天机器人。用户可能问：

- 未上传合同中的供应商银行账号。
- 所有维修人员账号和初始密码。
- 量子发动机 QX-9000 的维修参数。
- 明天午餐菜单。

这些问题有的库里没有依据，有的涉及隐私或凭据，有的是未来信息或明显编造对象。如果只把召回结果交给 LLM，模型可能基于相似上下文硬答。

**试过什么方案**

1. 在 prompt 里写“没有依据就拒答”。  
   只能降低概率，不能保证，且无法量化。

2. 只看 Top1 分数。  
   不同检索器分数不可比，dense、RRF、rerank 的阈值含义不同。

3. 检索后、生成前加 answer_policy。  
   结合 confidence、query support、显式负例触发器、是否有 parent context 来决定是否进入 LLM。

**为什么最终这样选**

拒答应该发生在生成前，而不是交给 LLM 自觉。后端在 `ParentContextRetriever` 里计算：

- `confidence_score`
- `confidence_threshold`
- `query_support_score`
- `explicit_refusal_trigger`
- `should_refuse`
- `refusal_reason`

然后 Chat 流式首包把 `answer_policy` 和 `trace` 一起发给前端。这样用户不仅看到拒答，还能看到为什么拒答。

**效果**

当前评测截图中，最终链路负例拒答率达到 1.000，而 baseline、hybrid、reranker 在没有 refusal gate 时都是 0.000。这个指标能直接回应“医疗场景如何避免胡说”的问题。

## 30 秒总结

这三个故事可以串成一句话：我不是为了面试堆功能，而是从医院后勤资料的真实限制出发，分别解决“大文档怎么切和回填”“专有词怎么稳定召回”“没有证据怎么拒答和追溯”三个问题，并用 ablation 证明每一步的收益。
