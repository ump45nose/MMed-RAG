import React, {
  FC,
  useMemo,
  useEffect,
  useState,
  ClassAttributes,
} from "react";
import { AnchorHTMLAttributes } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Divider } from "@/components/ui/divider";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { api } from "@/lib/api";
import { FileIcon } from "react-file-icon";

// Debounce hook to prevent rapid state updates during streaming
const useDebouncedValue = <T,>(value: T, delay: number): T => {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
};

interface Citation {
  id: number;
  text: string;
  metadata: Record<string, any>;
}

interface MatchedChild {
  chunk_id?: string;
  text?: string;
  section_path?: string;
  page?: number;
  rerank_score?: number;
  rrf_score?: number;
}

interface KnowledgeBaseInfo {
  name: string;
}

interface DocumentInfo {
  file_name: string;
  knowledge_base: KnowledgeBaseInfo;
}

interface CitationInfo {
  knowledge_base: KnowledgeBaseInfo;
  document: DocumentInfo;
}

export const Answer: FC<{
  markdown: string;
  citations?: Citation[];
}> = ({ markdown, citations = [] }) => {
  const [citationInfoMap, setCitationInfoMap] = useState<
    Record<string, CitationInfo>
  >({});

  // Debounce citations to prevent rapid API calls during streaming
  const debouncedCitations = useDebouncedValue(citations, 300);

  const processedMarkdown = useMemo(() => {
    return markdown
      .replace(/<think>/g, "## 💭 深度思考\n```think")
      .replace(/<\/think>/g, "```");
  }, [markdown]);

  useEffect(() => {
    const fetchCitationInfo = async () => {
      const infoMap: Record<string, CitationInfo> = {};

      for (const citation of debouncedCitations) {
        const { kb_id, document_id } = citation.metadata;
        if (!kb_id || !document_id) continue;

        const key = `${kb_id}-${document_id}`;
        if (infoMap[key]) continue;

        try {
          const [kb, doc] = await Promise.all([
            api.get(`/api/knowledge-base/${kb_id}`),
            api.get(`/api/knowledge-base/${kb_id}/documents/${document_id}`),
          ]);

          infoMap[key] = {
            knowledge_base: {
              name: kb.name,
            },
            document: {
              file_name: doc.file_name,
              knowledge_base: {
                name: kb.name,
              },
            },
          };
        } catch (error) {
          console.error("Failed to fetch citation info:", error);
        }
      }

      setCitationInfoMap(infoMap);
    };

    if (debouncedCitations.length > 0) {
      fetchCitationInfo();
    }
  }, [debouncedCitations]);

  const CitationLink = useMemo(
    () =>
      (
        props: ClassAttributes<HTMLAnchorElement> &
          AnchorHTMLAttributes<HTMLAnchorElement>
      ) => {
        const citationId = props.href?.match(/^(\d+)$/)?.[1];
        const citation = citationId
          ? debouncedCitations[parseInt(citationId) - 1]
          : null;

        if (!citation) {
          return <a>[{props.href}]</a>;
        }

        const citationInfo =
          citationInfoMap[
            `${citation.metadata.kb_id}-${citation.metadata.document_id}`
          ];

        return (
          <Popover>
            <PopoverTrigger asChild>
              <a
                {...props}
                href="#"
                role="button"
                className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium text-blue-600 bg-blue-50 rounded hover:bg-blue-100 transition-colors relative"
              >
                <span className="absolute -top-3 -right-1">[{props.href}]</span>
              </a>
            </PopoverTrigger>
            <PopoverContent
              side="top"
              align="start"
              className="max-w-2xl w-[calc(100vw-100px)] p-4 rounded-lg shadow-lg"
            >
              <div className="text-sm space-y-3">
                {citationInfo && (
                  <div className="flex items-center gap-2 text-xs font-medium text-gray-700 bg-gray-50 p-2 rounded">
                    <div className="w-5 h-5 flex items-center justify-center">
                      <FileIcon
                        extension={
                          citationInfo.document.file_name.split(".").pop() || ""
                        }
                        color="#E2E8F0"
                        labelColor="#94A3B8"
                      />
                    </div>
                    <span className="truncate">
                      {citationInfo.knowledge_base.name} /{" "}
                      {citationInfo.document.file_name}
                    </span>
                  </div>
                )}
                <Divider />
                <div className="flex flex-wrap gap-2 text-xs text-gray-600">
                  {citation.metadata.page ? <span>Page {citation.metadata.page}</span> : null}
                  {citation.metadata.section_path ? <span>{citation.metadata.section_path}</span> : null}
                  {citation.metadata.parent_id ? <span>parent {String(citation.metadata.parent_id).slice(0, 12)}</span> : null}
                </div>
                {Array.isArray(citation.metadata.matched_children) && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-gray-500">Matched child chunks</div>
                    {(citation.metadata.matched_children as MatchedChild[])
                      .slice(0, 3)
                      .map((child, index) => (
                        <div key={child.chunk_id || index} className="border-l-2 border-blue-400 bg-blue-50 px-3 py-2 text-xs text-gray-700">
                          <div className="mb-1 flex flex-wrap gap-2 text-[11px] text-gray-500">
                            {child.page ? <span>p.{child.page}</span> : null}
                            {child.section_path ? <span>{child.section_path}</span> : null}
                            {child.rerank_score ? <span>rerank {Number(child.rerank_score).toFixed(4)}</span> : null}
                            {child.rrf_score ? <span>rrf {Number(child.rrf_score).toFixed(4)}</span> : null}
                          </div>
                          <p className="whitespace-pre-wrap">{child.text}</p>
                        </div>
                      ))}
                  </div>
                )}
                <Divider />
                <p className="text-gray-700 leading-relaxed">{citation.text}</p>
                <Divider />
                {Object.keys(citation.metadata).length > 0 && (
                  <div className="text-xs text-gray-500 bg-gray-50 p-2 rounded">
                    <div className="font-medium mb-2">Debug Info:</div>
                    <div className="space-y-1">
                      {Object.entries(citation.metadata).map(([key, value]) => (
                        <div key={key} className="flex">
                          <span className="font-medium min-w-[100px]">
                            {key}:
                          </span>
                          <span className="text-gray-600">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </PopoverContent>
          </Popover>
        );
      },
    [debouncedCitations, citationInfoMap]
  );

  if (!markdown) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="max-w-sm h-4 bg-zinc-200" />
        <Skeleton className="max-w-lg h-4 bg-zinc-200" />
        <Skeleton className="max-w-2xl h-4 bg-zinc-200" />
        <Skeleton className="max-w-lg h-4 bg-zinc-200" />
        <Skeleton className="max-w-xl h-4 bg-zinc-200" />
      </div>
    );
  }

  return (
    <div className="prose prose-sm max-w-full">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: CitationLink,
        }}
      >
        {processedMarkdown}
      </Markdown>
    </div>
  );
};
