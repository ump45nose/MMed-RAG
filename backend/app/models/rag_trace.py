from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class RagTrace(Base, TimestampMixin):
    """RAG 问答链路追踪记录，用于面试 Demo 展示每次问答的可观测信息。"""

    __tablename__ = "rag_traces"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=True, index=True)
    query = Column(Text, nullable=False)
    rewritten_query = Column(Text, nullable=True)
    intent = Column(String(50), nullable=True)
    domains = Column(JSON, nullable=True)
    candidate_kbs = Column(JSON, nullable=True)
    selected_kbs = Column(JSON, nullable=True)
    retrieval_trace = Column(JSON, nullable=True)
    answer_policy = Column(JSON, nullable=True)
    latency_breakdown = Column(JSON, nullable=True)
    total_latency_ms = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    refused = Column(Boolean, nullable=False, default=False)
    refusal_reason = Column(String(255), nullable=True)

    # 关联用户和会话，便于 API 层按用户隔离 trace。
    user = relationship("User")
    chat = relationship("Chat")
