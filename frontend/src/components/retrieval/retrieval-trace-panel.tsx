"use client";

import { Badge } from "@/components/ui/badge";
import { ChevronRight, GitBranch, Search, ShieldAlert, Timer } from "lucide-react";

interface TraceCandidate {
  rank?: number;
  kb_id?: number;
  file_name?: string;
  section_path?: string;
  page?: number;
  retrieval_source?: string;
  dense_score?: number;
  sparse_score?: number;
  rrf_score?: number;
  rerank_score?: number;
  preview?: string;
}

interface RetrievalTracePanelProps {
  trace?: Record<string, any>;
  answerPolicy?: Record<string, any>;
}

function formatScore(value: unknown) {
  // 分数来源不同，统一收敛到短小展示，避免面板横向撑开。
  return typeof value === "number" ? value.toFixed(4) : "-";
}

function CandidateList({
  title,
  items,
}: {
  title: string;
  items?: TraceCandidate[];
}) {
  const rows = (items || []).slice(0, 5);

  return (
    <div className="rounded-md border">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="text-sm font-medium">{title}</div>
        <Badge variant="outline">{items?.length || 0}</Badge>
      </div>
      <div className="divide-y">
        {rows.length ? (
          rows.map((item, index) => (
            <div key={`${title}-${item.rank || index}`} className="px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant="secondary">#{item.rank || index + 1}</Badge>
                {item.retrieval_source && <Badge variant="outline">{item.retrieval_source}</Badge>}
                {item.file_name && <span className="font-medium">{item.file_name}</span>}
                {item.page ? <span className="text-muted-foreground">p.{item.page}</span> : null}
                {item.section_path ? <span className="text-muted-foreground">{item.section_path}</span> : null}
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <span>dense {formatScore(item.dense_score)}</span>
                <span>sparse {formatScore(item.sparse_score)}</span>
                <span>rrf {formatScore(item.rrf_score)}</span>
                <span>rerank {formatScore(item.rerank_score)}</span>
              </div>
              {item.preview ? (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.preview}</p>
              ) : null}
            </div>
          ))
        ) : (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">No candidates</div>
        )}
      </div>
    </div>
  );
}

export function RetrievalTracePanel({ trace, answerPolicy }: RetrievalTracePanelProps) {
  if (!trace) return null;

  const router = trace.router || {};
  const confidence = trace.confidence || answerPolicy || {};
  const latency = trace.latency_ms || {};
  const profileMatches = trace.profile_matches || [];

  return (
    <div className="mt-3 space-y-3 rounded-md border bg-muted/20 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-medium">
          <GitBranch className="h-4 w-4" />
          检索链路
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={confidence.should_refuse ? "destructive" : "secondary"}>
            confidence {formatScore(confidence.score ?? confidence.confidence_score)}
          </Badge>
          <Badge variant="outline">threshold {formatScore(confidence.threshold ?? confidence.confidence_threshold)}</Badge>
          <Badge variant="outline">
            <Timer className="mr-1 h-3 w-3" />
            {formatScore(latency.total)} ms
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="rounded-md border bg-background px-3 py-2">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <ChevronRight className="h-3 w-3" />
            Router
          </div>
          <div className="space-y-1 text-xs">
            <div>intent: {router.intent || "-"}</div>
            <div>domain: {(router.domain || []).join("、") || "-"}</div>
            <div>source: {router.source || "-"}</div>
            <div className="line-clamp-2">rewrite: {router.rewritten_query || trace.query || "-"}</div>
          </div>
        </div>
        <div className="rounded-md border bg-background px-3 py-2">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Search className="h-3 w-3" />
            KB 初筛
          </div>
          <div className="space-y-1 text-xs">
            <div>router: {(router.candidate_kb_names || router.candidate_kbs || []).join("、") || "-"}</div>
            <div>profile: {profileMatches.map((item: any) => `${item.kb_name || item.kb_id}:${formatScore(item.score)}`).join("、") || "-"}</div>
            <div>selected: {(trace.selected_kbs || []).join("、") || "-"}</div>
          </div>
        </div>
        <div className="rounded-md border bg-background px-3 py-2">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <ShieldAlert className="h-3 w-3" />
            拒答策略
          </div>
          <div className="space-y-1 text-xs">
            <div>refuse: {String(confidence.should_refuse ?? answerPolicy?.should_refuse ?? false)}</div>
            <div className="line-clamp-2">reason: {confidence.reason || answerPolicy?.refusal_reason || "-"}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-4">
        <CandidateList title="Dense" items={trace.dense_candidates} />
        <CandidateList title="Sparse/BM25" items={trace.sparse_candidates} />
        <CandidateList title="RRF" items={trace.rrf_candidates} />
        <CandidateList title="Rerank 后" items={trace.rerank_after || trace.final_context} />
      </div>
    </div>
  );
}
