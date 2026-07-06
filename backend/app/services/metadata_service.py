import json
import logging
import os
import re
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.llm.llm_factory import LLMFactory

logger = logging.getLogger(__name__)


class MetadataSuggestionService:
    """Suggest document metadata for user confirmation during ingestion."""

    @staticmethod
    def suggest(file_name: str, sample_text: str = "") -> Dict[str, Any]:
        """Suggest metadata with optional LLM enrichment and deterministic fallback.

        Args:
            file_name: Original document file name.
            sample_text: Extracted text sample used for metadata inference.

        Returns:
            A metadata dictionary safe to show to users and store for audit.
        """
        fallback = MetadataSuggestionService._heuristic_suggest(file_name, sample_text)
        if not settings.METADATA_LLM_ENABLED:
            return fallback

        try:
            llm_suggestion = MetadataSuggestionService._llm_suggest(file_name, sample_text)
            return {**fallback, **{key: value for key, value in llm_suggestion.items() if value}}
        except Exception as exc:
            # Metadata extraction is a convenience step; ingestion should continue with fallback values.
            logger.warning("Metadata LLM suggestion failed, using heuristic fallback: %s", exc)
            return fallback

    @staticmethod
    def _heuristic_suggest(file_name: str, sample_text: str) -> Dict[str, Any]:
        """Infer metadata from file name and text keywords without external services."""
        base_name = os.path.splitext(os.path.basename(file_name))[0]
        normalized = f"{file_name}\n{sample_text[:3000]}"

        doc_type = "其他"
        type_rules = [
            ("维修记录", ["维修", "报修", "工单", "故障"]),
            ("采购合同", ["采购", "合同", "招标", "报价"]),
            ("规章制度", ["制度", "规章", "管理办法", "第", "条"]),
            ("设备手册", ["手册", "操作", "说明书", "培训"]),
        ]
        for candidate, keywords in type_rules:
            if any(keyword in normalized for keyword in keywords):
                doc_type = candidate
                break

        department = None
        if "医工" in normalized or "设备科" in normalized:
            department = "医工"
        elif "后勤" in normalized or "运维" in normalized or "保洁" in normalized or "医废" in normalized:
            department = "后勤"

        model_match = re.search(r"([A-Z]{1,6}[-_ ]?\d{2,6}[A-Z0-9-]*)", normalized)
        date_match = re.search(r"(20\d{2})[-年./](\d{1,2})(?:[-月./](\d{1,2}))?", normalized)
        effective_date = None
        if date_match:
            year, month, day = date_match.group(1), date_match.group(2), date_match.group(3) or "01"
            effective_date = f"{year}-{int(month):02d}-{int(day):02d}"

        return {
            "title": base_name,
            "doc_type": doc_type,
            "department": department,
            "equipment_model": model_match.group(1).replace(" ", "") if model_match else None,
            "effective_date": effective_date,
            "source": "heuristic",
        }

    @staticmethod
    def _llm_suggest(file_name: str, sample_text: str) -> Dict[str, Any]:
        """Ask the configured LLM to produce strict JSON metadata."""
        llm = LLMFactory.create(streaming=False, temperature=0)
        prompt = (
            "请从文档文件名和正文片段中抽取 RAG 入库 metadata，只返回 JSON。"
            "字段包括 title, doc_type, department, equipment_model, effective_date。"
            "doc_type 只能是 设备手册、维修记录、采购合同、规章制度、其他。"
            "department 只能是 医工、后勤、其他 或 null。"
            f"\n文件名: {file_name}\n正文片段:\n{sample_text[:4000]}"
        )
        response = llm.invoke(prompt)
        content = getattr(response, "content", response)
        parsed = json.loads(str(content).strip().strip("`"))
        parsed["source"] = "llm"
        return parsed


def merge_confirmed_metadata(
    suggestion: Optional[Dict[str, Any]],
    confirmed: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge suggested metadata with user-confirmed overrides for ingestion."""
    base = dict(suggestion or {})
    for key, value in (confirmed or {}).items():
        # Empty override values should not erase usable suggestions during ingestion.
        if value is not None and value != "":
            base[key] = value
    return base
