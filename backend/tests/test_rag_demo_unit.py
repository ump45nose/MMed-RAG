from langchain_core.documents import Document as LangchainDocument

from app.services.evaluation_metrics import ndcg_at_k, percentile, recall_at_k, reciprocal_rank
from app.services.metadata_service import MetadataSuggestionService
from app.services.query_router_service import QueryRouterService
from app.services.retrieval_service import ParentContextRetriever, RetrievalConfig, reciprocal_rank_fusion
from app.services.vector_store.milvus import build_milvus_filter_expr, build_milvus_jieba_analyzer_params


def test_parent_level_metrics():
    """Parent-level metrics count hits by parent_id instead of child chunk ID."""
    retrieved = ["p3", "p2", "p1"]
    relevant = ["p1", "p2"]

    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert ndcg_at_k(retrieved, relevant, 3) > 0.0
    assert percentile([10, 20, 30, 40], 95) == 40


def test_rrf_fuses_dense_and_lexical_ranks():
    """RRF boosts a child chunk that appears in both dense and lexical lists."""
    dense = [
        LangchainDocument(page_content="dense one", metadata={"chunk_id": "a"}),
        LangchainDocument(page_content="dense two", metadata={"chunk_id": "b"}),
    ]
    lexical = [
        LangchainDocument(page_content="lexical two", metadata={"chunk_id": "b"}),
        LangchainDocument(page_content="lexical three", metadata={"chunk_id": "c"}),
    ]

    fused = reciprocal_rank_fusion([dense, lexical], rank_constant=10)

    assert fused[0].metadata["chunk_id"] == "b"
    assert fused[0].metadata["rrf_score"] > fused[-1].metadata["rrf_score"]


def test_milvus_filter_expression_builder():
    """Milvus scalar filters support equality, membership, and date range operators."""
    expr = build_milvus_filter_expr({
        "kb_id": [1, 2],
        "doc_type": "规章制度",
        "effective_date": {"$gte": "2024-01-01"},
    })

    assert "kb_id in [1, 2]" in expr
    assert 'doc_type == "规章制度"' in expr
    assert 'effective_date >= "2024-01-01"' in expr


def test_milvus_jieba_analyzer_params():
    """BM25 analyzer uses jieba by default so Chinese terms are tokenized."""
    analyzer = build_milvus_jieba_analyzer_params()

    assert analyzer["tokenizer"] == "jieba"
    assert "lowercase" in analyzer["filter"]


def test_router_json_parser_maps_kb_names():
    """Structured router output maps KB display names to stable KB IDs."""
    decision = QueryRouterService.parse_router_json(
        '{"intent":"retrieval","domain":["医工"],"rewritten_query":"设备维修流程","candidate_kbs":["kb_医疗设备维修"]}',
        {"kb_医疗设备维修": 7},
        "原始问题",
    )

    assert decision.intent == "retrieval"
    assert decision.domain == ["医工"]
    assert decision.rewritten_query == "设备维修流程"
    assert decision.candidate_kbs == [7]


def test_parent_dedup_falls_back_to_single_parent_context():
    """Parent dedup returns one context when multiple children share a parent_id."""

    class EmptyQuery:
        """Minimal SQLAlchemy-like query object returning no parent rows."""

        def filter(self, *_args, **_kwargs):
            """Ignore filters because this fake DB has no stored parents."""
            return self

        def all(self):
            """Return an empty parent row result set."""
            return []

    class EmptyDb:
        """Minimal DB session fake used by ParentContextRetriever internals."""

        def query(self, *_args, **_kwargs):
            """Return an empty query for parent lookup."""
            return EmptyQuery()

    retriever = ParentContextRetriever(EmptyDb())
    children = [
        LangchainDocument(page_content="first child", metadata={"parent_id": "p1", "chunk_id": "c1"}),
        LangchainDocument(page_content="second child", metadata={"parent_id": "p1", "chunk_id": "c2"}),
        LangchainDocument(page_content="other parent", metadata={"parent_id": "p2", "chunk_id": "c3"}),
    ]

    parents = retriever._dedupe_to_parents(children, top_k=5)

    assert [doc.metadata["parent_id"] for doc in parents] == ["p1", "p2"]
    assert parents[0].metadata["child_ids"] == ["c1", "c2"]


def test_permission_filter_adds_allowed_departments():
    """Retriever appends backend-owned department permissions to scalar filters."""

    class EmptyDb:
        """Minimal DB session fake; this test only touches config rewriting."""

    class DemoUser:
        """Fake authenticated user with one allowed department."""

        is_superuser = False
        allowed_departments = ["医工"]

    retriever = ParentContextRetriever(EmptyDb())
    config = retriever._apply_user_permission_filter(
        config=RetrievalConfig(filters={"doc_type": "维修记录"}),
        user=DemoUser(),
    )

    assert config.filters["doc_type"] == "维修记录"
    assert config.filters["department"] == ["医工"]


def test_confidence_score_uses_rrf_for_refusal_gate():
    """RRF scores are normalized into a 0-1 confidence score."""

    class EmptyDb:
        """Minimal DB session fake; this test only calls score normalization."""

    retriever = ParentContextRetriever(EmptyDb())
    parent = LangchainDocument(page_content="parent", metadata={"parent_id": "p1"})
    child = LangchainDocument(page_content="child", metadata={"rrf_score": 1 / 61})
    config = RetrievalConfig(rrf_rank_constant=60)

    assert retriever._calculate_confidence([parent], [child], config) > 0.9


def test_metadata_heuristic_suggestion_for_hospital_logistics():
    """Metadata fallback identifies common hospital logistics document attributes."""
    suggestion = MetadataSuggestionService._heuristic_suggest(
        "智慧后勤运维管理平台操作手册.docx",
        "本文描述后勤报修工单、运维任务和操作流程。",
    )

    assert suggestion["doc_type"] == "维修记录"
    assert suggestion["department"] == "后勤"
    assert suggestion["title"] == "智慧后勤运维管理平台操作手册"
