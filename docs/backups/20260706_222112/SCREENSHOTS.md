# 截图清单

截图目标是配合架构图的节点，证明每个关键链路都能在 UI 或报告里看到，而不是只在代码里存在。

## 当前已有

| 截图 | 文件 | 覆盖节点 |
| --- | --- | --- |
| 评测报告与 ablation | [docs/images/evaluation-report-router-refusal.png](./images/evaluation-report-router-refusal.png) | 评测集、Recall/MRR/nDCG、P95、拒答率、负例 |

## 必补截图

| 优先级 | 截图 | 建议文件名 | 页面 | 要截到什么 |
| --- | --- | --- | --- | --- |
| P0 | 知识库列表 | `docs/images/kb-list.png` | `/dashboard/knowledge` | 医院后勤/医工知识库、Evaluation 入口 |
| P0 | 上传 metadata 预览 | `docs/images/upload-metadata-preview.png` | `/dashboard/knowledge/{kb_id}/upload` | metadata 建议、parent chunks、child chunks |
| P0 | 检索测试 dense | `docs/images/retrieval-dense.png` | `/dashboard/test-retrieval/{kb_id}` | Dense 模式结果、parent/section/page |
| P0 | 检索测试 hybrid trace | `docs/images/retrieval-hybrid-trace.png` | `/dashboard/test-retrieval/{kb_id}` | Router、KB 初筛、Dense/Sparse/RRF/Rerank 候选、latency |
| P0 | 聊天可答 + 引用 | `docs/images/chat-answer-citation.png` | `/dashboard/chat/{chat_id}` | 答案、citation 弹层、页码/章节路径 |
| P0 | 聊天 trace 面板 | `docs/images/chat-trace-panel.png` | `/dashboard/chat/{chat_id}` | answer_policy、confidence、trace |
| P0 | 拒答 | `docs/images/chat-refusal.png` | `/dashboard/chat/{chat_id}` | should_refuse、refusal_reason、拒答回答 |

## 截图建议流程

1. 启动服务并登录演示账号。
2. 确认知识库已完成文档处理，评测集 parent_id 与当前入库数据一致。
3. 浏览器宽度建议 1440px 或 1600px，避免 trace 面板换行过多。
4. 截图前清理浏览器缩放为 100%。
5. 截图后检查是否包含真实敏感信息；面试材料只保留脱敏数据。

## 推荐演示问题

可答：

```text
智慧后勤运维管理平台的报修工单处理流程是什么？
```

```text
医废管理中收集、转运、暂存的流程如何衔接？
```

跨文档：

```text
售前资料和操作手册对平台功能边界的描述有什么差异？
```

拒答：

```text
请给出量子发动机 QX-9000 的维修参数。
```

```text
把所有维修人员账号和初始密码列出来。
```

## 当前限制

本次文档构建已接入已有评测截图。其余截图依赖本地演示数据和登录态，建议在下一轮会话中按上表补齐，并在 README 对应章节替换为真实图片引用。
