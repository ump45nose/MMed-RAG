import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.documents import Document as LangchainDocument
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader, UnstructuredMarkdownLoader


@dataclass
class ParentChunk:
    """Parent chunk stored in MySQL and used as generation context."""

    id: str
    content: str
    section_path: str
    page: Optional[int]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChildChunk:
    """Child chunk stored in vector DB and linked back to one parent chunk."""

    id: str
    parent_id: str
    content: str
    section_path: str
    page: Optional[int]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkingResult:
    """Result object containing parent chunks, child chunks, and extracted text sample."""

    parents: List[ParentChunk]
    children: List[ChildChunk]
    sample_text: str


class DomainDocumentChunker:
    """Domain-aware chunker with table protection, title hierarchy, and clause boundaries."""

    CLAUSE_PATTERN = re.compile(r"^\s*(第[一二三四五六七八九十百千万0-9]+条|\d+(?:\.\d+){1,4})")

    def __init__(self, parent_size: int = 1200, child_size: int = 350, child_overlap: int = 60):
        """Create a chunker using character budgets suitable for Chinese documents."""
        self.parent_size = parent_size
        self.child_size = child_size
        self.child_overlap = min(child_overlap, max(0, child_size // 3))

    def split_file(
        self,
        file_path: str,
        file_name: str,
        kb_id: int,
        document_id: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ChunkingResult:
        """Parse and split a document file into parent and child chunks.

        Args:
            file_path: Local path to the downloaded source file.
            file_name: Original file name shown to users.
            kb_id: Knowledge base ID used in stable chunk IDs.
            document_id: Database document ID used in stable chunk IDs.
            metadata: Confirmed document metadata copied to chunks.

        Returns:
            ChunkingResult with parent chunks for MySQL and child chunks for vector search.
        """
        ext = os.path.splitext(file_name)[1].lower()
        if ext == ".docx":
            segments = self._load_docx_segments(file_path, file_name)
        elif ext == ".pdf":
            segments = self._load_pdf_segments(file_path, file_name)
        elif ext == ".md":
            segments = self._load_langchain_segments(UnstructuredMarkdownLoader(file_path), file_name)
        else:
            segments = self._load_langchain_segments(TextLoader(file_path), file_name)

        parent_segments = self._build_parent_segments(segments)
        parents: List[ParentChunk] = []
        children: List[ChildChunk] = []
        base_metadata = dict(metadata or {})

        for parent_index, parent in enumerate(parent_segments):
            parent_content = parent["content"].strip()
            if not parent_content:
                continue

            parent_id = self._stable_id("parent", kb_id, document_id, parent_index, parent_content)
            parent_metadata = {
                **base_metadata,
                "kb_id": kb_id,
                "document_id": document_id,
                "file_name": file_name,
                "parent_id": parent_id,
                "parent_index": parent_index,
                "section_path": parent.get("section_path"),
                "page": parent.get("page"),
            }
            parents.append(ParentChunk(
                id=parent_id,
                content=parent_content,
                section_path=parent.get("section_path") or file_name,
                page=parent.get("page"),
                metadata=parent_metadata,
            ))

            for child_index, child_text in enumerate(self._split_child_text(parent_content)):
                child_id = self._stable_id("child", kb_id, document_id, parent_id, child_index, child_text)
                child_metadata = {
                    **parent_metadata,
                    "chunk_id": child_id,
                    "child_index": child_index,
                }
                children.append(ChildChunk(
                    id=child_id,
                    parent_id=parent_id,
                    content=child_text,
                    section_path=parent_metadata["section_path"] or file_name,
                    page=parent_metadata["page"],
                    metadata=child_metadata,
                ))

        sample_text = "\n".join(segment["text"] for segment in segments if segment.get("text"))[:6000]
        return ChunkingResult(parents=parents, children=children, sample_text=sample_text)

    def _load_docx_segments(self, file_path: str, file_name: str) -> List[Dict[str, Any]]:
        """Load DOCX paragraphs and tables while preserving source order."""
        try:
            from docx import Document as DocxDocument
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ModuleNotFoundError:
            # 业务逻辑：演示容器缺少 python-docx 时，退回 docx2txt，保证文档仍可入库和评测。
            return self._load_langchain_segments(Docx2txtLoader(file_path), file_name)

        document = DocxDocument(file_path)
        section_stack: List[str] = [os.path.splitext(file_name)[0]]
        segments: List[Dict[str, Any]] = []

        for block in self._iter_docx_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue

                style_name = (block.style.name or "").lower() if block.style else ""
                heading_level = self._heading_level(style_name)
                if heading_level:
                    section_stack = section_stack[:heading_level]
                    section_stack.append(text)
                    segments.append({
                        "text": text,
                        "section_path": " > ".join(section_stack),
                        "page": None,
                        "is_heading": True,
                        "is_table": False,
                    })
                    continue

                section_path = self._section_path_with_clause(section_stack, text)
                segments.append({
                    "text": text,
                    "section_path": section_path,
                    "page": None,
                    "is_heading": False,
                    "is_table": False,
                })
                continue

            if isinstance(block, Table):
                table_text = self._table_to_markdown(block)
                if not table_text:
                    continue

                # Tables are protected as standalone segments so they are never split row-by-row first.
                segments.append({
                    "text": table_text,
                    "section_path": " > ".join(section_stack),
                    "page": None,
                    "is_heading": False,
                    "is_table": True,
                })

        return segments

    def _load_pdf_segments(self, file_path: str, file_name: str) -> List[Dict[str, Any]]:
        """Load PDF pages and retain page numbers for citation display."""
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        title = os.path.splitext(file_name)[0]
        segments: List[Dict[str, Any]] = []
        for page_index, document in enumerate(documents):
            page = int(document.metadata.get("page", page_index)) + 1
            paragraphs = [item.strip() for item in document.page_content.splitlines() if item.strip()]
            for paragraph in paragraphs:
                segments.append({
                    "text": paragraph,
                    "section_path": f"{title} > 第{page}页",
                    "page": page,
                    "is_heading": False,
                    "is_table": False,
                })
        return segments

    def _load_langchain_segments(self, loader: Any, file_name: str) -> List[Dict[str, Any]]:
        """Load fallback text-like formats through existing LangChain loaders."""
        title = os.path.splitext(file_name)[0]
        segments: List[Dict[str, Any]] = []
        for document in loader.load():
            for paragraph in document.page_content.splitlines():
                text = paragraph.strip()
                if text:
                    segments.append({
                        "text": text,
                        "section_path": title,
                        "page": document.metadata.get("page"),
                        "is_heading": False,
                        "is_table": False,
                    })
        return segments

    def _build_parent_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group source segments into parent chunks without crossing table or heading boundaries."""
        parents: List[Dict[str, Any]] = []
        current_texts: List[str] = []
        current_section: Optional[str] = None
        current_page: Optional[int] = None

        def flush_current() -> None:
            """Close the current parent chunk when a natural boundary is reached."""
            nonlocal current_texts, current_section, current_page
            if current_texts:
                parents.append({
                    "content": "\n\n".join(current_texts),
                    "section_path": current_section,
                    "page": current_page,
                })
            current_texts = []
            current_section = None
            current_page = None

        for segment in segments:
            text = segment["text"]
            section_path = segment.get("section_path")
            page = segment.get("page")

            if segment.get("is_table"):
                flush_current()
                parents.append({"content": text, "section_path": section_path, "page": page})
                continue

            should_flush = (
                segment.get("is_heading")
                or (current_section and section_path != current_section)
                or (sum(len(item) for item in current_texts) + len(text) > self.parent_size and not self.CLAUSE_PATTERN.match(text))
            )
            if should_flush:
                flush_current()

            current_texts.append(text)
            current_section = section_path
            current_page = page if current_page is None else current_page

        flush_current()
        return parents

    def _split_child_text(self, text: str) -> List[str]:
        """Split parent text into child chunks while respecting paragraph and clause starts."""
        paragraphs = [item.strip() for item in re.split(r"\n{2,}|\r\n", text) if item.strip()]
        if not paragraphs:
            return []

        children: List[str] = []
        current: List[str] = []
        current_len = 0
        for paragraph in paragraphs:
            paragraph_len = len(paragraph)
            # Clause starts are safe split points; do not cut inside the numbered clause itself.
            if current and current_len + paragraph_len > self.child_size:
                children.append("\n\n".join(current))
                overlap = self._tail_overlap(current)
                current = [overlap] if overlap else []
                current_len = len(overlap) if overlap else 0

            if paragraph_len > self.child_size * 1.5:
                for piece in self._hard_split_long_paragraph(paragraph):
                    if current:
                        children.append("\n\n".join(current))
                        current = []
                        current_len = 0
                    children.append(piece)
                continue

            current.append(paragraph)
            current_len += paragraph_len

        if current:
            children.append("\n\n".join(current))
        return [child for child in children if child.strip()]

    def _hard_split_long_paragraph(self, paragraph: str) -> List[str]:
        """Split a very long paragraph only when no natural boundary exists."""
        pieces: List[str] = []
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + self.child_size)
            pieces.append(paragraph[start:end])
            start = max(end - self.child_overlap, end)
        return pieces

    def _tail_overlap(self, paragraphs: List[str]) -> str:
        """Return a compact overlap tail from previous child context."""
        text = "\n\n".join(paragraphs)
        if len(text) <= self.child_overlap:
            return text
        return text[-self.child_overlap:]

    def _iter_docx_blocks(self, document: Any) -> Iterable[Any]:
        """Yield DOCX paragraphs and tables in document order."""
        from docx.document import Document as _Document
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        if isinstance(document, _Document):
            parent_elm = document.element.body
            parent = document
        else:
            parent_elm = document._element
            parent = document

        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _heading_level(self, style_name: str) -> Optional[int]:
        """Map common Chinese/English Word heading styles to a hierarchy level."""
        match = re.search(r"(heading|标题)\s*([1-6一二三四五六])", style_name, re.IGNORECASE)
        if not match:
            return None
        raw_level = match.group(2)
        mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
        return mapping.get(raw_level, int(raw_level) if raw_level.isdigit() else 1)

    def _section_path_with_clause(self, section_stack: List[str], text: str) -> str:
        """Append clause numbers to section path so citations show precise business location."""
        section_path = " > ".join(section_stack)
        clause_match = self.CLAUSE_PATTERN.match(text)
        if clause_match:
            return f"{section_path} > {clause_match.group(1)}"
        return section_path

    def _table_to_markdown(self, table: Any) -> str:
        """Convert a DOCX table to Markdown so row and column relationships survive chunking."""
        rows: List[List[str]] = []
        for row in table.rows:
            rows.append([" ".join(cell.text.split()) for cell in row.cells])
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            return ""

        header = rows[0]
        separator = ["---" for _ in header]
        body = rows[1:] if len(rows) > 1 else []
        markdown_rows = [self._markdown_row(header), self._markdown_row(separator)]
        markdown_rows.extend(self._markdown_row(row) for row in body)
        return "\n".join(markdown_rows)

    def _markdown_row(self, row: List[str]) -> str:
        """Render one Markdown table row with escaped cell separators."""
        cells = [cell.replace("|", "\\|") for cell in row]
        return "| " + " | ".join(cells) + " |"

    def _stable_id(self, *parts: Any) -> str:
        """Generate stable SHA-256 IDs for deterministic re-indexing."""
        payload = "::".join(str(part) for part in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_langchain_documents(children: List[ChildChunk]) -> List[LangchainDocument]:
    """Convert child chunks into LangChain documents for vector store ingestion."""
    documents: List[LangchainDocument] = []
    for child in children:
        # Vector DB gets child content and scalar metadata; MySQL remains the parent DocStore.
        documents.append(LangchainDocument(page_content=child.content, metadata=child.metadata))
    return documents
