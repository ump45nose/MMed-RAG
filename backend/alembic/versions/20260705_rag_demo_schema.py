"""rag demo parent retrieval and metadata schema

Revision ID: 20260705ragdemo
Revises: 3580c0dcd005
Create Date: 2026-07-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = "20260705ragdemo"
down_revision: Union[str, None] = "3580c0dcd005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create production-demo metadata, parent chunk, and task progress columns."""
    op.add_column("documents", sa.Column("title", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("doc_type", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("department", sa.String(length=100), nullable=True))
    op.add_column("documents", sa.Column("equipment_model", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("effective_date", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("metadata_suggestion", sa.JSON(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("metadata_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column("document_uploads", sa.Column("metadata_suggestion", sa.JSON(), nullable=True))
    op.add_column("document_uploads", sa.Column("confirmed_metadata", sa.JSON(), nullable=True))

    op.add_column("processing_tasks", sa.Column("stage", sa.String(length=50), nullable=True))
    op.add_column("processing_tasks", sa.Column("progress", sa.Integer(), nullable=True))

    op.create_table(
        "document_parent_chunks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("parent_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content", mysql.LONGTEXT(), nullable=False),
        sa.Column("section_path", sa.String(length=2048), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("doc_type", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("effective_date", sa.String(length=32), nullable=True),
        sa.Column("parent_metadata", sa.JSON(), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_parent_kb_doc", "document_parent_chunks", ["kb_id", "document_id"])
    op.create_index("idx_parent_kb_file", "document_parent_chunks", ["kb_id", "file_name"])
    op.create_index(op.f("ix_document_parent_chunks_hash"), "document_parent_chunks", ["hash"])

    op.add_column("document_chunks", sa.Column("parent_id", sa.String(length=64), nullable=True))
    op.add_column("document_chunks", sa.Column("content", mysql.LONGTEXT(), nullable=True))
    op.add_column("document_chunks", sa.Column("child_index", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("section_path", sa.String(length=2048), nullable=True))
    op.add_column("document_chunks", sa.Column("page", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("doc_type", sa.String(length=100), nullable=True))
    op.add_column("document_chunks", sa.Column("department", sa.String(length=100), nullable=True))
    op.add_column("document_chunks", sa.Column("effective_date", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "document_chunks_parent_id_fkey",
        "document_chunks",
        "document_parent_chunks",
        ["parent_id"],
        ["id"],
    )
    op.create_index("idx_chunk_parent_id", "document_chunks", ["parent_id"])
    op.create_index(
        "idx_chunk_scalar_filter",
        "document_chunks",
        ["kb_id", "doc_type", "department", "effective_date"],
    )


def downgrade() -> None:
    """Remove production-demo schema additions."""
    op.drop_index("idx_chunk_scalar_filter", table_name="document_chunks")
    op.drop_index("idx_chunk_parent_id", table_name="document_chunks")
    op.drop_constraint("document_chunks_parent_id_fkey", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "effective_date")
    op.drop_column("document_chunks", "department")
    op.drop_column("document_chunks", "doc_type")
    op.drop_column("document_chunks", "page")
    op.drop_column("document_chunks", "section_path")
    op.drop_column("document_chunks", "child_index")
    op.drop_column("document_chunks", "content")
    op.drop_column("document_chunks", "parent_id")

    op.drop_index(op.f("ix_document_parent_chunks_hash"), table_name="document_parent_chunks")
    op.drop_index("idx_parent_kb_file", table_name="document_parent_chunks")
    op.drop_index("idx_parent_kb_doc", table_name="document_parent_chunks")
    op.drop_table("document_parent_chunks")

    op.drop_column("processing_tasks", "progress")
    op.drop_column("processing_tasks", "stage")
    op.drop_column("document_uploads", "confirmed_metadata")
    op.drop_column("document_uploads", "metadata_suggestion")
    op.drop_column("documents", "metadata_confirmed")
    op.drop_column("documents", "metadata_suggestion")
    op.drop_column("documents", "effective_date")
    op.drop_column("documents", "equipment_model")
    op.drop_column("documents", "department")
    op.drop_column("documents", "doc_type")
    op.drop_column("documents", "title")
