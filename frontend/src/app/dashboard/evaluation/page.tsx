"use client";

import { useEffect, useMemo, useState } from "react";
import DashboardLayout from "@/components/layout/dashboard-layout";
import { api, ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/use-toast";
import {
  BarChart3,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Loader2,
  RefreshCw,
  Route,
  ShieldCheck,
  Square,
  Target,
  Zap,
} from "lucide-react";

interface KnowledgeBase {
  id: number;
  name: string;
  description?: string;
}

interface DatasetSummary {
  query_count: number;
  answerable_query_count: number;
  negative_query_count: number;
  labeled_query_count: number;
  unlabeled_query_count: number;
  labeled_answerable_query_count: number;
  unlabeled_answerable_query_count: number;
  label_coverage: number;
  answerable_label_coverage: number;
  type_counts: Record<string, number>;
  difficulty_counts: Record<string, number>;
}

interface DatasetQuery {
  query: string;
  type: string;
  kb_ids: number[];
  relevant_parent_ids: string[];
  answerable: boolean;
  labeled: boolean;
  expected_answer: string;
  evidence_keywords: string[];
  difficulty: string;
  notes: string;
}

interface AblationRow {
  config: string;
  recall_at_5: number;
  mrr: number;
  ndcg_at_10: number;
  p95_latency_ms: number;
  negative_refusal_rate: number;
  labeled_answerable_query_count?: number;
  queries: Array<Record<string, any>>;
}

interface EvaluationReport {
  dataset_path: string;
  query_count: number;
  dataset_summary?: DatasetSummary;
  ablation: AblationRow[];
}

interface DatasetResponse {
  dataset_path: string;
  query_count: number;
  dataset_summary: DatasetSummary;
  queries: DatasetQuery[];
}

const ABLATION_CONFIGS = [
  "baseline: dense only + 裸切分",
  "+ 领域分块 + 父子检索",
  "+ hybrid RRF",
  "+ reranker",
  "+ router + hybrid + reranker + refusal",
];

const HIGHLIGHTS = [
  { label: "父子检索", value: "长上下文回填", icon: Database },
  { label: "Hybrid RRF", value: "稠密与词法融合", icon: Zap },
  { label: "Reranker", value: "TopK 精排", icon: Target },
  { label: "KB 路由", value: "跨库候选收敛", icon: Route },
  { label: "拒答门禁", value: "低置信度拦截", icon: ShieldCheck },
];

const FALLBACK_DATASET_SUMMARY: DatasetSummary = {
  query_count: 41,
  answerable_query_count: 33,
  negative_query_count: 8,
  labeled_query_count: 8,
  unlabeled_query_count: 33,
  labeled_answerable_query_count: 0,
  unlabeled_answerable_query_count: 33,
  label_coverage: 8 / 41,
  answerable_label_coverage: 0,
  type_counts: {
    "事实型": 12,
    "流程型": 10,
    "跨文档型": 5,
    "医工设备类": 3,
    "负例": 8,
    "路由型": 1,
    "拒答策略型": 1,
    "评测说明型": 1,
  },
  difficulty_counts: {
    easy: 10,
    medium: 21,
    hard: 10,
  },
};

const FALLBACK_DATASET_QUERIES: DatasetQuery[] = [
  {
    query: "智慧后勤运维管理平台的报修工单处理流程是什么？",
    type: "流程型",
    kb_ids: [1],
    relevant_parent_ids: ["TODO_PARENT_REPAIR_FLOW_001"],
    answerable: true,
    labeled: false,
    expected_answer: "应覆盖报修提交、受理派单、维修人员接单处理、完工反馈、评价或回访闭环。",
    evidence_keywords: ["报修", "派单", "接单", "完工", "评价"],
    difficulty: "easy",
    notes: "入库后替换为报修流程章节对应 parent_id",
  },
  {
    query: "医废管理模块的核心操作步骤有哪些？",
    type: "流程型",
    kb_ids: [1],
    relevant_parent_ids: ["TODO_PARENT_MEDICAL_WASTE_001"],
    answerable: true,
    labeled: false,
    expected_answer: "应覆盖医废产生登记、收集、交接、转运、暂存、出库或处置追踪。",
    evidence_keywords: ["医废", "登记", "收集", "交接", "转运"],
    difficulty: "easy",
    notes: "标注智慧医废管理操作手册章节",
  },
  {
    query: "售前资料和操作手册对平台功能边界的描述有什么差异？",
    type: "跨文档型",
    kb_ids: [1],
    relevant_parent_ids: ["TODO_PARENT_PRESALE_SCOPE_001", "TODO_PARENT_MANUAL_SCOPE_001"],
    answerable: true,
    labeled: false,
    expected_answer: "应比较售前资料偏价值和模块范围，操作手册偏具体页面、流程和操作限制。",
    evidence_keywords: ["售前资料", "操作手册", "功能边界", "价值"],
    difficulty: "hard",
    notes: "标注售前资料与操作手册的范围描述",
  },
  {
    query: "医疗设备无人值守管理系统的设备异常告警如何处理？",
    type: "医工设备类",
    kb_ids: [1],
    relevant_parent_ids: ["TODO_PARENT_MEDICAL_DEVICE_ALERT_001"],
    answerable: true,
    labeled: false,
    expected_answer: "应说明告警产生、告警列表查看、确认或派工处理、处理结果记录和状态关闭。",
    evidence_keywords: ["设备异常", "告警", "确认", "派工", "关闭"],
    difficulty: "medium",
    notes: "标注医疗设备无人值守管理系统操作手册中的告警处理章节",
  },
  {
    query: "请给出量子发动机 QX-9000 的维修参数。",
    type: "负例",
    kb_ids: [1],
    relevant_parent_ids: [],
    answerable: false,
    labeled: true,
    expected_answer: "应拒答，说明知识库没有量子发动机 QX-9000 的维修参数。",
    evidence_keywords: ["量子发动机", "QX-9000"],
    difficulty: "easy",
    notes: "库中无答案，测试拒答",
  },
];

/** 将比例转换成百分比字符串，用于摘要卡片和报告表格。 */
function formatPercent(value?: number) {
  return `${((value || 0) * 100).toFixed(0)}%`;
}

/** 将评测指标转换成固定三位小数，未运行时由调用方显示占位。 */
function formatMetric(value?: number) {
  return typeof value === "number" ? value.toFixed(3) : "-";
}

/** 根据后端返回结果合并默认消融配置，保证未运行时也能展示完整矩阵。 */
function buildAblationRows(report: EvaluationReport | null) {
  return ABLATION_CONFIGS.map((config) => {
    const matched = report?.ablation?.find((row) => row.config === config);
    return {
      config,
      row: matched,
    };
  });
}

export default function EvaluationPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string>("");
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [dataset, setDataset] = useState<DatasetResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    /** 拉取知识库、最近一次评测和默认评测集，让页面打开后就是完整报告。 */
    const loadInitialData = async () => {
      try {
        const [kbs, latest, defaultDataset] = await Promise.all([
          api.get("/api/knowledge-base"),
          api.get("/api/evaluation/latest"),
          api.get("/api/evaluation/dataset/default"),
        ]);
        setKnowledgeBases(kbs);
        setReport(latest);
        setDataset(defaultDataset);
        if (kbs.length > 0) {
          setSelectedKbId(String(kbs[0].id));
        }
      } catch (error) {
        toast({
          title: "评测报告加载失败",
          description: error instanceof ApiError ? error.message : "未知错误",
          variant: "destructive",
        });
      }
    };

    loadInitialData();
  }, [toast]);

  const summary = dataset?.dataset_summary || report?.dataset_summary || FALLBACK_DATASET_SUMMARY;
  const displayQueries = dataset?.queries || FALLBACK_DATASET_QUERIES;
  const ablationRows = useMemo(() => buildAblationRows(report), [report]);
  const canScoreAnswerable = summary.labeled_answerable_query_count > 0;

  /** 使用当前知识库执行消融评测，并把结果直接回填到报告矩阵。 */
  const runEvaluation = async () => {
    if (!selectedKbId) {
      toast({
        title: "请选择知识库",
        description: "运行评测前需要至少一个已入库知识库。",
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    try {
      const result = await api.post("/api/evaluation/run", {
        kb_ids: [parseInt(selectedKbId)],
      });
      setReport(result);
    } catch (error) {
      toast({
        title: "评测运行失败",
        description: error instanceof ApiError ? error.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 border-b pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <Badge variant="outline" className="w-fit">
              面试演示评测集
            </Badge>
            <h1 className="text-3xl font-bold tracking-tight">RAG 评测报告</h1>
            <p className="max-w-3xl text-sm text-muted-foreground">
              覆盖后勤、医废、保洁、运送、大屏、医工设备、跨文档和拒答场景。
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="space-y-2">
              <Label>知识库</Label>
              <Select value={selectedKbId} onValueChange={setSelectedKbId}>
                <SelectTrigger className="w-[260px]">
                  <SelectValue placeholder="选择知识库" />
                </SelectTrigger>
                <SelectContent>
                  {knowledgeBases.map((kb) => (
                    <SelectItem key={kb.id} value={String(kb.id)}>
                      {kb.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={runEvaluation} disabled={loading || !selectedKbId}>
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              运行评测
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-md border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">问题总数</span>
              <FileText className="h-4 w-4 text-cyan-600" />
            </div>
            <div className="mt-3 text-3xl font-semibold">{summary.query_count}</div>
          </div>
          <div className="rounded-md border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">可答 / 负例</span>
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
            </div>
            <div className="mt-3 text-3xl font-semibold">
              {summary.answerable_query_count} / {summary.negative_query_count}
            </div>
          </div>
          <div className="rounded-md border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">可计分标注</span>
              <Target className="h-4 w-4 text-amber-600" />
            </div>
            <div className="mt-3 text-3xl font-semibold">
              {summary.labeled_answerable_query_count}
            </div>
            <Progress className="mt-3 h-2" value={summary.answerable_label_coverage * 100} />
          </div>
          <div className="rounded-md border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">数据集路径</span>
              <Clock3 className="h-4 w-4 text-rose-600" />
            </div>
            <div className="mt-3 truncate text-sm font-medium">
              {dataset?.dataset_path || report?.dataset_path || "-"}
            </div>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-5">
          {HIGHLIGHTS.map((item) => (
            <div key={item.label} className="rounded-md border p-4">
              <item.icon className="mb-3 h-5 w-5 text-primary" />
              <div className="text-sm font-semibold">{item.label}</div>
              <div className="mt-1 text-xs text-muted-foreground">{item.value}</div>
            </div>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-md border">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div>
                <h2 className="font-semibold">消融矩阵</h2>
                <p className="text-xs text-muted-foreground">
                  {canScoreAnswerable ? "指标来自已绑定 parent_id 的可答样本" : "可答样本待绑定真实 parent_id"}
                </p>
              </div>
              <BarChart3 className="h-5 w-5 text-muted-foreground" />
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[260px]">配置</TableHead>
                  <TableHead>Recall@5</TableHead>
                  <TableHead>MRR</TableHead>
                  <TableHead>nDCG@10</TableHead>
                  <TableHead>P95 延迟</TableHead>
                  <TableHead>负例拒答率</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ablationRows.map(({ config, row }) => (
                  <TableRow key={config}>
                    <TableCell className="font-medium">{config}</TableCell>
                    <TableCell>{row && canScoreAnswerable ? formatMetric(row.recall_at_5) : "待标注"}</TableCell>
                    <TableCell>{row && canScoreAnswerable ? formatMetric(row.mrr) : "待标注"}</TableCell>
                    <TableCell>{row && canScoreAnswerable ? formatMetric(row.ndcg_at_10) : "待标注"}</TableCell>
                    <TableCell>{row ? `${row.p95_latency_ms.toFixed(0)} ms` : "待运行"}</TableCell>
                    <TableCell>{row ? formatMetric(row.negative_refusal_rate) : "待运行"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="rounded-md border">
            <div className="border-b px-4 py-3">
              <h2 className="font-semibold">覆盖分布</h2>
              <p className="text-xs text-muted-foreground">
                可答标注覆盖 {formatPercent(summary.answerable_label_coverage)}
              </p>
            </div>
            <div className="space-y-4 p-4">
              {Object.entries(summary.type_counts).map(([type, count]) => {
                const width = summary.query_count ? (count / summary.query_count) * 100 : 0;
                return (
                  <div key={type} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span>{type}</span>
                      <span className="font-mono text-xs">{count}</span>
                    </div>
                    <Progress className="h-2" value={width} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="rounded-md border">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <h2 className="font-semibold">评测集明细</h2>
              <p className="text-xs text-muted-foreground">
                待绑定样本会在文档入库后替换为真实父块 ID。
              </p>
            </div>
            <Badge variant="secondary">
              {dataset?.queries.length || summary.query_count} 条
            </Badge>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[34%]">问题</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>难度</TableHead>
                <TableHead>标注</TableHead>
                <TableHead className="w-[32%]">证据关键词 / 预期答案</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayQueries.map((item) => (
                <TableRow key={item.query}>
                  <TableCell className="align-top">
                    <div className="font-medium leading-6">{item.query}</div>
                  </TableCell>
                  <TableCell className="align-top">
                    <Badge variant={item.answerable ? "secondary" : "outline"}>{item.type}</Badge>
                  </TableCell>
                  <TableCell className="align-top text-sm">{item.difficulty}</TableCell>
                  <TableCell className="align-top">
                    <div className="flex items-center gap-2 text-sm">
                      {!item.answerable ? (
                        <ShieldCheck className="h-4 w-4 text-cyan-600" />
                      ) : item.labeled ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      ) : (
                        <Square className="h-4 w-4 text-amber-600" />
                      )}
                      {!item.answerable ? "负例" : item.labeled ? "已绑定" : "待绑定"}
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-wrap gap-1">
                      {item.evidence_keywords.slice(0, 5).map((keyword) => (
                        <Badge key={`${item.query}-${keyword}`} variant="outline">
                          {keyword}
                        </Badge>
                      ))}
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                      {item.expected_answer}
                    </p>
                  </TableCell>
                </TableRow>
              ))}
              {!displayQueries.length && (
                <TableRow>
                  <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                    暂无评测集数据。
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </DashboardLayout>
  );
}
