import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeBase
from app.services.kb_profile_service import KnowledgeBaseProfileService, tokenize_profile_text

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """Structured query routing result used by retrieval and trace display."""

    intent: str
    domain: List[str]
    rewritten_query: str
    candidate_kbs: List[int]
    candidate_kb_names: List[str]
    source: str
    raw_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize route decision for API and trace output."""
        return asdict(self)


class QueryRouterService:
    """Route user queries to candidate KBs with optional LLM and deterministic fallback."""

    @staticmethod
    def route(
        db: Session,
        query: str,
        kb_ids: Sequence[int],
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> RouteDecision:
        """Route one query and return candidate KB ids plus rewritten query."""
        knowledge_bases = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.id.in_(list(kb_ids)))
            .order_by(KnowledgeBase.id.asc())
            .all()
        )
        for kb in knowledge_bases:
            if not kb.profile_summary:
                KnowledgeBaseProfileService.build_profile(db, kb.id)

        if settings.KB_ROUTER_LLM_ENABLED:
            try:
                return QueryRouterService._route_with_llm(db, query, knowledge_bases, chat_history or [])
            except Exception as exc:
                # LLM 路由失败时回退，避免检索主链路受外部模型可用性影响。
                logger.warning("LLM router failed, using heuristic router: %s", exc)

        return QueryRouterService._route_with_heuristic(query, knowledge_bases)

    @staticmethod
    def parse_router_json(text: str, kb_by_name: Dict[str, int], fallback_query: str) -> RouteDecision:
        """Parse LLM router JSON and map KB names to stable IDs."""
        json_text = QueryRouterService._extract_json_object(text)
        payload = json.loads(json_text)

        candidate_ids: List[int] = []
        candidate_names: List[str] = []
        for item in payload.get("candidate_kbs", []):
            name = str(item).strip()
            kb_id = QueryRouterService._resolve_kb_identifier(name, kb_by_name)
            if kb_id and kb_id not in candidate_ids:
                candidate_ids.append(kb_id)
                candidate_names.append(name)

        domain = payload.get("domain") or []
        if isinstance(domain, str):
            domain = [domain]

        intent = payload.get("intent") or "retrieval"
        if intent not in {"retrieval", "chitchat", "clarify"}:
            intent = "retrieval"

        return RouteDecision(
            intent=intent,
            domain=[str(item) for item in domain],
            rewritten_query=payload.get("rewritten_query") or fallback_query,
            candidate_kbs=candidate_ids,
            candidate_kb_names=candidate_names,
            source="llm",
            raw_response=text,
        )

    @staticmethod
    def _route_with_llm(
        db: Session,
        query: str,
        knowledge_bases: Sequence[KnowledgeBase],
        chat_history: List[Dict[str, str]],
    ) -> RouteDecision:
        """Call the configured LLM once to classify intent, rewrite query, and select KBs."""
        from app.services.llm.llm_factory import LLMFactory

        kb_lines = []
        kb_by_name: Dict[str, int] = {}
        for kb in knowledge_bases:
            profile = KnowledgeBaseProfileService.ensure_profile(db, kb.id)
            kb_name = f"kb_{kb.id}_{kb.name}"
            kb_by_name[kb_name] = kb.id
            kb_by_name[kb.name] = kb.id
            kb_lines.append(
                f"- {kb_name}\n  description: {kb.description or ''}\n  kb_profile: {(profile.get('summary') or '')[:900]}"
            )

        recent_history = "\n".join(
            f"{item.get('role')}: {item.get('content')}"
            for item in (chat_history or [])[-6:]
        )
        prompt = (
            "你是医院 RAG 系统的查询路由器。只输出 JSON，不要输出 Markdown。\n"
            "JSON 字段必须包含 intent、domain、rewritten_query、candidate_kbs。\n"
            "intent 只能是 retrieval、chitchat、clarify。\n"
            "domain 是数组，只能包含 医工、后勤 或 其他。\n"
            "candidate_kbs 使用下面给出的 kb 名称。\n\n"
            f"可用知识库：\n{chr(10).join(kb_lines)}\n\n"
            f"最近对话：\n{recent_history or '无'}\n\n"
            f"用户问题：{query}"
        )
        llm = LLMFactory.create()
        response = llm.invoke(prompt)
        content = getattr(response, "content", str(response))
        decision = QueryRouterService.parse_router_json(content, kb_by_name, query)
        if not decision.candidate_kbs:
            fallback = QueryRouterService._route_with_heuristic(query, knowledge_bases)
            decision.candidate_kbs = fallback.candidate_kbs
            decision.candidate_kb_names = fallback.candidate_kb_names
        return decision

    @staticmethod
    def _route_with_heuristic(query: str, knowledge_bases: Sequence[KnowledgeBase]) -> RouteDecision:
        """Use token overlap and domain keywords when LLM routing is disabled."""
        query_tokens = set(tokenize_profile_text(query))
        domain = QueryRouterService._infer_domain(query)
        scored: List[Dict[str, Any]] = []

        for kb in knowledge_bases:
            profile_text = " ".join([
                kb.name or "",
                kb.description or "",
                kb.profile_summary or "",
                " ".join(kb.profile_keywords or []),
            ])
            profile_tokens = set(tokenize_profile_text(profile_text))
            overlap = query_tokens & profile_tokens
            if overlap:
                scored.append({"kb": kb, "score": len(overlap), "overlap": overlap})

        scored.sort(key=lambda item: item["score"], reverse=True)
        # 业务逻辑：评测 Router 时需要真实收窄候选库，因此启发式路由只保留最高分知识库。
        selected = [scored[0]["kb"]] if scored else list(knowledge_bases[:1])
        intent = "chitchat" if QueryRouterService._looks_like_chitchat(query) else "retrieval"

        return RouteDecision(
            intent=intent,
            domain=domain,
            rewritten_query=query.strip(),
            candidate_kbs=[kb.id for kb in selected],
            candidate_kb_names=[kb.name for kb in selected],
            source="heuristic",
        )

    @staticmethod
    def _infer_domain(query: str) -> List[str]:
        """Infer coarse business domains from obvious department keywords."""
        domains: List[str] = []
        if re.search(r"医工|医疗设备|设备维修|外协|台账|无人值守|故障|报错", query):
            domains.append("医工")
        if re.search(r"后勤|保洁|运送|医废|巡检|能耗|报修|食堂|物业", query):
            domains.append("后勤")
        return domains or ["其他"]

    @staticmethod
    def _looks_like_chitchat(query: str) -> bool:
        """Detect short greetings that should not enter retrieval."""
        return bool(re.fullmatch(r"\s*(你好|您好|hello|hi|谢谢|thanks)[！!。.\s]*", query, re.IGNORECASE))

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """Extract the first JSON object from an LLM response."""
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        return match.group(0) if match else stripped

    @staticmethod
    def _resolve_kb_identifier(value: str, kb_by_name: Dict[str, int]) -> Optional[int]:
        """Resolve kb id from exact names, kb_<id> tokens, or display names."""
        if value in kb_by_name:
            return kb_by_name[value]
        id_match = re.search(r"kb[_-]?(\d+)", value, flags=re.IGNORECASE)
        if id_match:
            return int(id_match.group(1))
        for name, kb_id in kb_by_name.items():
            if name and name in value:
                return kb_id
        return None
