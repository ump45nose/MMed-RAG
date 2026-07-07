# 截图清单

截图目标是配合架构图的节点，证明每个关键链路都能在 UI 或报告里看到，而不是只在代码里存在。

## 已完成截图

| 截图 | 文件 | 覆盖节点 |
| --- | --- | --- |
| 知识库列表 | [kb-list.png](./images/kb-list.png) | 主知识库、噪声知识库、文档入口 |
| 知识库文档详情 | [kb-detail-documents.png](./images/kb-detail-documents.png) | 文档列表、metadata、处理状态、索引状态 |
| 检索测试与 trace | [retrieval-dense.png](./images/retrieval-dense.png) | Router、KB 初筛、Dense/Rerank 候选、latency、parent 结果 |
| 聊天拒答 trace | [chat-refusal.png](./images/chat-refusal.png) | answer_policy、confidence、拒答链路 |
| 评测报告 | [evaluation-report-current.png](./images/evaluation-report-current.png) | 评测集、消融矩阵、拒答率 |
| 原始评测报告备份 | [evaluation-report-router-refusal.png](./images/evaluation-report-router-refusal.png) | 同一评测结果的历史截图 |
| 上传文件选择 | [upload-after-file.png](./images/upload-after-file.png) | 上传页文件选择状态 |

## 待补截图

| 优先级 | 截图 | 建议文件名 | 页面 | 当前状态 |
| --- | --- | --- | --- | --- |
| P0 | 上传 metadata 预览 | `docs/images/upload-metadata-preview.png` | `/dashboard/knowledge/{kb_id}/upload` | 前端自动上传触发 422，需修复上传状态后重截 |
| P1 | 聊天可答 + 引用弹层 | `docs/images/chat-answer-citation.png` | `/dashboard/chat/{chat_id}` | 需要稳定 LLM 生成链路后补 |
| P1 | Hybrid RRF 专项截图 | `docs/images/retrieval-hybrid-trace.png` | `/dashboard/test-retrieval/{kb_id}` | 当前已有检索 trace，后续可补 hybrid 开关状态 |

## 截图建议流程

1. 启动服务并登录本地验证账号。
2. 确认知识库已完成文档处理，评测集 parent_id 与当前入库数据一致。
3. 浏览器宽度建议 1440px 或 1600px，避免 trace 面板换行过多。
4. 截图前清理浏览器缩放为 100%。
5. 截图后检查是否包含真实敏感信息；对外材料只保留脱敏数据。

## 推荐验证问题

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

当前已接入知识库、检索链路、拒答和评测截图。上传 metadata 预览截图仍需在前端上传状态稳定后补齐。
