"use client";

import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { DocumentUploadSteps } from "@/components/knowledge-base/document-upload-steps";
import { DocumentList } from "@/components/knowledge-base/document-list";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { PlusIcon } from "lucide-react";
import DashboardLayout from "@/components/layout/dashboard-layout";

interface KnowledgeBaseProfile {
  name?: string;
  profile_summary?: string;
  profile_keywords?: string[];
  profile_document_count?: number;
  profile_updated_at?: string;
}

export default function KnowledgeBasePage() {
  const params = useParams();
  const knowledgeBaseId = parseInt(params.id as string);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBaseProfile | null>(null);

  const loadKnowledgeBase = useCallback(async () => {
    // 读取 KB profile 供路由透明化展示，失败时文档列表仍可独立工作。
    const data = await api.get(`/api/knowledge-base/${knowledgeBaseId}`);
    setKnowledgeBase(data);
  }, [knowledgeBaseId]);

  useEffect(() => {
    loadKnowledgeBase().catch(() => setKnowledgeBase(null));
  }, [loadKnowledgeBase, refreshKey]);

  const handleUploadComplete = useCallback(() => {
    setRefreshKey((prev) => prev + 1);
    setDialogOpen(false);
  }, []);

  const refreshProfile = async () => {
    const profile = await api.post(`/api/knowledge-base/${knowledgeBaseId}/profile/refresh`);
    setKnowledgeBase((prev) => ({
      ...(prev || {}),
      profile_summary: profile.summary,
      profile_keywords: profile.keywords,
      profile_document_count: profile.document_count,
      profile_updated_at: profile.updated_at,
    }));
  };

  return (
    <DashboardLayout>
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Knowledge Base</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <PlusIcon className="w-4 h-4 mr-2" />
              Add Document
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-4xl">
            <DialogHeader>
              <DialogTitle>Add Document</DialogTitle>
              <DialogDescription>
                Upload a document to your knowledge base. Supported formats:
                PDF, DOCX, Markdown, and Text files.
              </DialogDescription>
            </DialogHeader>
            <DocumentUploadSteps
              knowledgeBaseId={knowledgeBaseId}
              onComplete={handleUploadComplete}
            />
          </DialogContent>
        </Dialog>
      </div>

      <div className="mb-6 rounded-md border p-4">
        <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-lg font-semibold">{knowledgeBase?.name || "KB Profile"}</h2>
            <p className="text-sm text-muted-foreground">
              documents {knowledgeBase?.profile_document_count ?? 0}
              {knowledgeBase?.profile_updated_at ? ` / updated ${new Date(knowledgeBase.profile_updated_at).toLocaleString()}` : ""}
            </p>
          </div>
          <Button variant="secondary" onClick={refreshProfile}>
            Refresh Profile
          </Button>
        </div>
        <p className="line-clamp-5 whitespace-pre-wrap text-sm text-muted-foreground">
          {knowledgeBase?.profile_summary || "Profile has not been generated yet."}
        </p>
        {knowledgeBase?.profile_keywords?.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {knowledgeBase.profile_keywords.slice(0, 20).map((keyword) => (
              <Badge key={keyword} variant="outline">
                {keyword}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mt-8">
        <DocumentList key={refreshKey} knowledgeBaseId={knowledgeBaseId} />
      </div>
    </DashboardLayout>
  );
}
