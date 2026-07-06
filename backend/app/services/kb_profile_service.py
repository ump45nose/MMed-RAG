import re
from datetime import datetime
from typing import Any, Dict, List, Sequence

from sqlalchemy.orm import Session

from app.models.knowledge import Document, DocumentParentChunk, KnowledgeBase


def tokenize_profile_text(text: str) -> List[str]:
    """Tokenize Chinese and mixed technical text for KB profile matching."""
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_-]{1,}", text or "")
    expanded: List[str] = []
    for term in terms:
        expanded.append(term.lower())
        # 中文长词增加二字滑窗，解决短 query 与长 profile 粒度不一致的问题。
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term):
            expanded.extend(term[index:index + 2] for index in range(0, len(term) - 1))
    return list(dict.fromkeys(expanded))


class KnowledgeBaseProfileService:
    """Build and match lightweight KB profiles for routing fallback and cross-checking."""

    @staticmethod
    def build_profile(db: Session, kb_id: int) -> Dict[str, Any]:
        """Regenerate one KB profile from document titles and sampled parent chunks."""
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise ValueError(f"Knowledge base {kb_id} not found")

        documents = (
            db.query(Document)
            .filter(Document.knowledge_base_id == kb_id)
            .order_by(Document.id.asc())
            .all()
        )
        parent_samples = (
            db.query(DocumentParentChunk)
            .filter(DocumentParentChunk.kb_id == kb_id)
            .order_by(DocumentParentChunk.document_id.asc(), DocumentParentChunk.parent_index.asc())
            .limit(16)
            .all()
        )

        titles = [doc.title or doc.file_name for doc in documents]
        departments = sorted({doc.department for doc in documents if doc.department})
        doc_types = sorted({doc.doc_type for doc in documents if doc.doc_type})
        sample_text = "\n".join((row.content or "")[:300] for row in parent_samples)

        # profile 摘要控制在短文本内，便于注入 Router Prompt 和前端展示。
        summary_parts = [
            f"知识库名称：{kb.name}",
            f"描述：{kb.description or '无'}",
            f"文档数：{len(documents)}",
            f"部门：{'、'.join(departments) if departments else '未标注'}",
            f"文档类型：{'、'.join(doc_types) if doc_types else '未标注'}",
            f"代表文档：{'；'.join(titles[:12]) if titles else '暂无文档'}",
        ]
        if sample_text:
            summary_parts.append(f"抽样内容：{sample_text[:1200]}")
        summary = "\n".join(summary_parts)

        keywords = KnowledgeBaseProfileService._top_keywords(
            " ".join([kb.name or "", kb.description or "", " ".join(titles), sample_text]),
            limit=40,
        )

        kb.profile_summary = summary
        kb.profile_keywords = keywords
        kb.profile_document_count = len(documents)
        kb.profile_updated_at = datetime.utcnow()
        db.add(kb)
        db.commit()
        db.refresh(kb)

        return KnowledgeBaseProfileService.profile_to_dict(kb)

    @staticmethod
    def ensure_profile(db: Session, kb_id: int) -> Dict[str, Any]:
        """Return an existing profile or build it when the KB has not been profiled."""
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise ValueError(f"Knowledge base {kb_id} not found")
        if not kb.profile_summary:
            return KnowledgeBaseProfileService.build_profile(db, kb_id)
        return KnowledgeBaseProfileService.profile_to_dict(kb)

    @staticmethod
    def match_profiles(
        db: Session,
        query: str,
        kb_ids: Sequence[int],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Match query against KB profiles using deterministic token overlap."""
        query_tokens = set(tokenize_profile_text(query))
        if not query_tokens or not kb_ids:
            return []

        matches: List[Dict[str, Any]] = []
        knowledge_bases = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(list(kb_ids))).all()
        for kb in knowledge_bases:
            if not kb.profile_summary:
                KnowledgeBaseProfileService.build_profile(db, kb.id)
                db.refresh(kb)

            profile_text = " ".join([
                kb.name or "",
                kb.description or "",
                kb.profile_summary or "",
                " ".join(kb.profile_keywords or []),
            ])
            profile_tokens = set(tokenize_profile_text(profile_text))
            overlap = sorted(query_tokens & profile_tokens)
            score = len(overlap) / max(len(query_tokens), 1)
            if score > 0:
                matches.append({
                    "kb_id": kb.id,
                    "kb_name": kb.name,
                    "score": round(score, 4),
                    "matched_terms": overlap[:12],
                    "source": "kb_profile",
                })

        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:top_k]

    @staticmethod
    def profile_to_dict(kb: KnowledgeBase) -> Dict[str, Any]:
        """Serialize profile fields for API and trace payloads."""
        return {
            "kb_id": kb.id,
            "kb_name": kb.name,
            "summary": kb.profile_summary,
            "keywords": kb.profile_keywords or [],
            "document_count": kb.profile_document_count or 0,
            "updated_at": kb.profile_updated_at.isoformat() if kb.profile_updated_at else None,
        }

    @staticmethod
    def _top_keywords(text: str, limit: int = 40) -> List[str]:
        """Extract frequent business terms for lightweight profile matching."""
        stop_words = {"管理", "系统", "平台", "操作", "手册", "文档", "进行", "支持", "功能"}
        counts: Dict[str, int] = {}
        for token in tokenize_profile_text(text):
            if token in stop_words or len(token) < 2:
                continue
            counts[token] = counts.get(token, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [token for token, _count in ranked[:limit]]
