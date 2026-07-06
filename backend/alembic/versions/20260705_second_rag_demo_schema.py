"""second rag demo routing, profile, permission, and trace schema

Revision ID: 20260705ragdemo2
Revises: 20260705ragdemo
Create Date: 2026-07-05 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "20260705ragdemo2"
down_revision: Union[str, None] = "20260705ragdemo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add profile, permission, and trace tables used by the second RAG demo pass."""
    # KB profile 让路由 LLM 和兜底匹配都能用同一份知识库摘要。
    op.add_column("knowledge_bases", sa.Column("profile_summary", mysql.LONGTEXT(), nullable=True))
    op.add_column("knowledge_bases", sa.Column("profile_keywords", sa.JSON(), nullable=True))
    op.add_column("knowledge_bases", sa.Column("profile_document_count", sa.Integer(), nullable=True))
    op.add_column("knowledge_bases", sa.Column("profile_updated_at", sa.DateTime(), nullable=True))

    # 用户部门白名单是后端权限过滤的唯一可信输入，前端传参只作为检索条件补充。
    op.add_column("users", sa.Column("allowed_departments", sa.JSON(), nullable=True))

    # 自建 trace 表记录 RAG 链路，避免面试 Demo 依赖外部 Langfuse 服务。
    op.create_table(
        "rag_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("domains", sa.JSON(), nullable=True),
        sa.Column("candidate_kbs", sa.JSON(), nullable=True),
        sa.Column("selected_kbs", sa.JSON(), nullable=True),
        sa.Column("retrieval_trace", sa.JSON(), nullable=True),
        sa.Column("answer_policy", sa.JSON(), nullable=True),
        sa.Column("latency_breakdown", sa.JSON(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("refusal_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rag_traces_id"), "rag_traces", ["id"])
    op.create_index(op.f("ix_rag_traces_user_id"), "rag_traces", ["user_id"])
    op.create_index(op.f("ix_rag_traces_chat_id"), "rag_traces", ["chat_id"])


def downgrade() -> None:
    """Remove second-pass RAG demo schema additions."""
    op.drop_index(op.f("ix_rag_traces_chat_id"), table_name="rag_traces")
    op.drop_index(op.f("ix_rag_traces_user_id"), table_name="rag_traces")
    op.drop_index(op.f("ix_rag_traces_id"), table_name="rag_traces")
    op.drop_table("rag_traces")
    op.drop_column("users", "allowed_departments")
    op.drop_column("knowledge_bases", "profile_updated_at")
    op.drop_column("knowledge_bases", "profile_document_count")
    op.drop_column("knowledge_bases", "profile_keywords")
    op.drop_column("knowledge_bases", "profile_summary")
