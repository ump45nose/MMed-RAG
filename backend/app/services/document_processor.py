import logging
import os
import hashlib
import tempfile
import traceback
from datetime import datetime
from app.db.session import SessionLocal
from io import BytesIO
from typing import Optional, List, Dict, Set, Any
from fastapi import UploadFile
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    UnstructuredMarkdownLoader,
    TextLoader
)
try:
    # LangChain 新版将文本切分器拆到独立包，旧版仍保留在 langchain.text_splitter。
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LangchainDocument
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.minio import get_minio_client
from app.models.knowledge import ProcessingTask, Document, DocumentChunk, DocumentParentChunk
from app.services.chunk_record import ChunkRecord
import uuid
from langchain_community.document_loaders import UnstructuredFileLoader
from minio.error import MinioException
from minio import Minio
from minio.commonconfig import CopySource
from app.services.vector_store import VectorStoreFactory
from app.services.embedding.embedding_factory import EmbeddingsFactory
from app.services.document_chunker import DomainDocumentChunker, to_langchain_documents
from app.services.metadata_service import MetadataSuggestionService, merge_confirmed_metadata
from app.services.kb_profile_service import KnowledgeBaseProfileService

class UploadResult(BaseModel):
    file_path: str
    file_name: str
    file_size: int
    content_type: str
    file_hash: str

class TextChunk(BaseModel):
    content: str
    metadata: Optional[Dict] = None

class PreviewResult(BaseModel):
    chunks: List[TextChunk]
    total_chunks: int
    suggested_metadata: Optional[Dict[str, Any]] = None
    total_parent_chunks: int = 0

async def process_document(file_path: str, file_name: str, kb_id: int, document_id: int, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
    """Process document and store in vector database with incremental updates"""
    logger = logging.getLogger(__name__)
    
    try:
        preview_result = await preview_document(file_path, chunk_size, chunk_overlap)
        
        # Initialize embeddings
        logger.info("Initializing OpenAI embeddings...")
        embeddings = EmbeddingsFactory.create()
        
        logger.info(f"Initializing vector store with collection: kb_{kb_id}")
        vector_store = VectorStoreFactory.create(
            store_type=settings.VECTOR_STORE_TYPE,
            collection_name=f"kb_{kb_id}",
            embedding_function=embeddings,
        )
        
        # Initialize chunk record manager
        chunk_manager = ChunkRecord(kb_id)
        
        # Get existing chunk hashes for this file
        existing_hashes = chunk_manager.list_chunks(file_name)
        
        # Prepare new chunks
        new_chunks = []
        current_hashes = set()
        documents_to_update = []
        
        for chunk in preview_result.chunks:
            # Calculate chunk hash
            chunk_hash = hashlib.sha256(
                (chunk.content + str(chunk.metadata)).encode()
            ).hexdigest()
            current_hashes.add(chunk_hash)
            
            # Skip if chunk hasn't changed
            if chunk_hash in existing_hashes:
                continue
            
            # Create unique ID for the chunk
            chunk_id = hashlib.sha256(
                f"{kb_id}:{file_name}:{chunk_hash}".encode()
            ).hexdigest()
            
            # Prepare chunk record
            # Prepare metadata
            metadata = {
                **chunk.metadata,
                "chunk_id": chunk_id,
                "file_name": file_name,
                "kb_id": kb_id,
                "document_id": document_id
            }
            
            new_chunks.append({
                "id": chunk_id,
                "kb_id": kb_id,
                "document_id": document_id,
                "file_name": file_name,
                "metadata": metadata,
                "hash": chunk_hash
            })
            
            # Prepare document for vector store
            doc = LangchainDocument(
                page_content=chunk.content,
                metadata=metadata
            )
            documents_to_update.append(doc)
        
        # Add new chunks to database and vector store
        if new_chunks:
            logger.info(f"Adding {len(new_chunks)} new/updated chunks")
            chunk_manager.add_chunks(new_chunks)
            vector_store.add_documents(documents_to_update)
        
        # Delete removed chunks
        chunks_to_delete = chunk_manager.get_deleted_chunks(current_hashes, file_name)
        if chunks_to_delete:
            logger.info(f"Removing {len(chunks_to_delete)} deleted chunks")
            chunk_manager.delete_chunks(chunks_to_delete)
            vector_store.delete(chunks_to_delete)
        
        logger.info("Document processing completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        raise

async def upload_document(file: UploadFile, kb_id: int) -> UploadResult:
    """Step 1: Upload document to MinIO"""
    content = await file.read()
    file_size = len(content)
    
    file_hash = hashlib.sha256(content).hexdigest()
    
    # Clean and normalize filename
    file_name = "".join(c for c in file.filename if c.isalnum() or c in ('-', '_', '.')).strip()
    object_path = f"kb_{kb_id}/{file_name}"
    
    content_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".txt": "text/plain"
    }
    
    _, ext = os.path.splitext(file_name)
    content_type = content_types.get(ext.lower(), "application/octet-stream")
    
    # Upload to MinIO
    minio_client = get_minio_client()
    try:
        minio_client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=object_path,
            data=BytesIO(content),
            length=file_size,
            content_type=content_type
        )
    except Exception as e:
        logging.error(f"Failed to upload file to MinIO: {str(e)}")
        raise
        
    return UploadResult(
        file_path=object_path,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        file_hash=file_hash
    )

async def preview_document(file_path: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> PreviewResult:
    """Step 2: Generate domain-aware preview chunks and metadata suggestions."""
    # Get file from MinIO
    minio_client = get_minio_client()
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    file_name = os.path.basename(file_path)
    
    # Download to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        minio_client.fget_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=file_path,
            file_path=temp_file.name
        )
        temp_path = temp_file.name
    
    try:
        # Use the same domain-aware chunking logic as ingestion, with placeholder IDs for preview only.
        chunker = DomainDocumentChunker(
            parent_size=max(chunk_size, 800),
            child_size=max(200, min(chunk_size, 500)),
            child_overlap=min(chunk_overlap, 120),
        )
        chunking_result = chunker.split_file(
            file_path=temp_path,
            file_name=file_name,
            kb_id=0,
            document_id=0,
            metadata={}
        )
        suggested_metadata = MetadataSuggestionService.suggest(file_name, chunking_result.sample_text)
        
        # Convert to preview format
        preview_chunks = [
            TextChunk(
                content=chunk.content,
                metadata=chunk.metadata
            )
            for chunk in chunking_result.children
        ]
        
        return PreviewResult(
            chunks=preview_chunks,
            total_chunks=len(preview_chunks),
            suggested_metadata=suggested_metadata,
            total_parent_chunks=len(chunking_result.parents)
        )
    finally:
        os.unlink(temp_path)

async def process_document_background(
    temp_path: str,
    file_name: str,
    kb_id: int,
    task_id: int,
    db: Session = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> None:
    """Process document in background"""
    logger = logging.getLogger(__name__)
    logger.info(f"Starting background processing for task {task_id}, file: {file_name}")

    # if we don't pass in db, create a new database session
    if db is None:
        db = SessionLocal()
        should_close_db = True
    else:
        should_close_db = False
    
    task = db.query(ProcessingTask).get(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return
    
    try:
        logger.info(f"Task {task_id}: Setting status to processing")
        task.status = "processing"
        db.commit()
        
        # 1. 从临时目录下载文件
        minio_client = get_minio_client()
        try:
            local_temp_path = f"/tmp/temp_{task_id}_{file_name}"  # 使用系统临时目录
            logger.info(f"Task {task_id}: Downloading file from MinIO: {temp_path} to {local_temp_path}")
            minio_client.fget_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=temp_path,
                file_path=local_temp_path
            )
            logger.info(f"Task {task_id}: File downloaded successfully")
        except MinioException as e:
            error_msg = f"Failed to download temp file: {str(e)}"
            logger.error(f"Task {task_id}: {error_msg}")
            raise Exception(error_msg)
        
        try:
            # 2. 初始化向量存储，后续同名文件重建索引时需要先删除旧 child 向量。
            logger.info(f"Task {task_id}: Initializing vector store")
            task.stage = "embedding"
            task.progress = 20
            db.commit()
            embeddings = EmbeddingsFactory.create()
            
            vector_store = VectorStoreFactory.create(
                store_type=settings.VECTOR_STORE_TYPE,
                collection_name=f"kb_{kb_id}",
                embedding_function=embeddings,
            )
            vector_store.ensure_collection()
            
            # 3. 将临时文件移动到永久目录，保证数据库记录指向稳定对象路径。
            permanent_path = f"kb_{kb_id}/{file_name}"
            try:
                logger.info(f"Task {task_id}: Moving file to permanent storage")
                # 复制到永久目录
                source = CopySource(settings.MINIO_BUCKET_NAME, temp_path)
                minio_client.copy_object(
                    bucket_name=settings.MINIO_BUCKET_NAME,
                    object_name=permanent_path,
                    source=source
                )
                logger.info(f"Task {task_id}: File moved to permanent storage")
                
                # 删除临时文件
                logger.info(f"Task {task_id}: Removing temporary file from MinIO")
                minio_client.remove_object(
                    bucket_name=settings.MINIO_BUCKET_NAME,
                    object_name=temp_path
                )
                logger.info(f"Task {task_id}: Temporary file removed")
            except MinioException as e:
                error_msg = f"Failed to move file to permanent storage: {str(e)}"
                logger.error(f"Task {task_id}: {error_msg}")
                raise Exception(error_msg)
            
            # 4. 创建或复用文档记录。同名文件重新处理时清理旧 parent/child，保持检索结果幂等。
            logger.info(f"Task {task_id}: Creating or updating document record")
            task.stage = "parsing"
            task.progress = 30
            db.commit()
            upload = task.document_upload
            existing_document = db.query(Document).filter(
                Document.knowledge_base_id == kb_id,
                Document.file_name == file_name
            ).first()

            if existing_document:
                old_chunk_ids = [
                    row[0]
                    for row in db.query(DocumentChunk.id)
                    .filter(DocumentChunk.document_id == existing_document.id)
                    .all()
                ]
                if old_chunk_ids:
                    vector_store.delete(old_chunk_ids)
                db.query(DocumentChunk).filter(DocumentChunk.document_id == existing_document.id).delete(synchronize_session=False)
                db.query(DocumentParentChunk).filter(DocumentParentChunk.document_id == existing_document.id).delete(synchronize_session=False)
                document = existing_document
                document.file_path = permanent_path
                document.file_hash = upload.file_hash
                document.file_size = upload.file_size
                document.content_type = upload.content_type
            else:
                document = Document(
                    file_name=file_name,
                    file_path=permanent_path,
                    file_hash=upload.file_hash,
                    file_size=upload.file_size,
                    content_type=upload.content_type,
                    knowledge_base_id=kb_id
                )
                db.add(document)
            db.commit()
            db.refresh(document)
            logger.info(f"Task {task_id}: Document record created with ID {document.id}")

            # 5. 领域感知分块。metadata 先用上传阶段确认值，解析出正文样本后再补充建议值。
            logger.info(f"Task {task_id}: Domain-aware chunking")
            task.stage = "chunking"
            task.progress = 45
            db.commit()
            initial_metadata = merge_confirmed_metadata(
                upload.metadata_suggestion if upload else None,
                upload.confirmed_metadata if upload else None,
            )
            if not initial_metadata:
                initial_metadata = MetadataSuggestionService.suggest(file_name, "")

            chunker = DomainDocumentChunker(
                parent_size=max(chunk_size, 800),
                child_size=max(200, min(chunk_size, 500)),
                child_overlap=min(chunk_overlap, 120),
            )
            chunking_result = chunker.split_file(
                file_path=local_temp_path,
                file_name=file_name,
                kb_id=kb_id,
                document_id=document.id,
                metadata=initial_metadata,
            )

            metadata_suggestion = upload.metadata_suggestion if upload else None
            if not metadata_suggestion:
                metadata_suggestion = MetadataSuggestionService.suggest(file_name, chunking_result.sample_text)
                if upload:
                    upload.metadata_suggestion = metadata_suggestion
            final_metadata = merge_confirmed_metadata(
                metadata_suggestion,
                upload.confirmed_metadata if upload else None,
            )

            # 业务 metadata 同步到文档表，便于管理界面、审计和面试时解释三层存储。
            document.title = final_metadata.get("title")
            document.doc_type = final_metadata.get("doc_type")
            document.department = final_metadata.get("department")
            document.equipment_model = final_metadata.get("equipment_model")
            document.effective_date = final_metadata.get("effective_date")
            document.metadata_suggestion = metadata_suggestion
            document.metadata_confirmed = bool(upload and upload.confirmed_metadata)
            db.commit()
            
            # 6. Parent 存 MySQL DocStore，Child 同步 MySQL metadata 与向量库 scalar 字段。
            logger.info(
                "Task %s: Storing %s parent chunks and %s child chunks",
                task_id,
                len(chunking_result.parents),
                len(chunking_result.children),
            )
            task.progress = 65
            db.commit()
            for parent in chunking_result.parents:
                parent.metadata.update(final_metadata)
                parent_row = DocumentParentChunk(
                    id=parent.id,
                    kb_id=kb_id,
                    document_id=document.id,
                    file_name=file_name,
                    parent_index=parent.metadata.get("parent_index", 0),
                    content=parent.content,
                    section_path=parent.section_path,
                    page=parent.page,
                    doc_type=final_metadata.get("doc_type"),
                    department=final_metadata.get("department"),
                    effective_date=final_metadata.get("effective_date"),
                    parent_metadata=parent.metadata,
                    hash=hashlib.sha256(parent.content.encode("utf-8")).hexdigest(),
                )
                db.merge(parent_row)

            for i, child in enumerate(chunking_result.children):
                child.metadata.update(final_metadata)
                child.metadata["source"] = file_name
                child.metadata["file_name"] = file_name
                child.metadata["page_content"] = child.content
                child.metadata["doc_type"] = final_metadata.get("doc_type")
                child.metadata["department"] = final_metadata.get("department")
                child.metadata["effective_date"] = final_metadata.get("effective_date")
                doc_chunk = DocumentChunk(
                    id=child.id,
                    document_id=document.id,
                    parent_id=child.parent_id,
                    kb_id=kb_id,
                    file_name=file_name,
                    content=child.content,
                    child_index=child.metadata.get("child_index", i),
                    section_path=child.section_path,
                    page=child.page,
                    doc_type=final_metadata.get("doc_type"),
                    department=final_metadata.get("department"),
                    effective_date=final_metadata.get("effective_date"),
                    chunk_metadata=child.metadata,
                    hash=hashlib.sha256((child.content + str(child.metadata)).encode("utf-8")).hexdigest()
                )
                db.merge(doc_chunk)
                if i > 0 and i % 100 == 0:
                    logger.info(f"Task {task_id}: Stored {i} child chunks")
                    db.commit()
            
            # 7. Child chunk 入向量库，parent_id/doc_type/department 等作为 scalar metadata 支持过滤。
            logger.info(f"Task {task_id}: Adding child chunks to vector store")
            task.stage = "embedding"
            task.progress = 80
            db.commit()
            vector_documents = to_langchain_documents(chunking_result.children)
            vector_store.add_documents(vector_documents, ids=[child.id for child in chunking_result.children])
            logger.info(f"Task {task_id}: Chunks added to vector store")
            
            # 8. 更新任务状态
            logger.info(f"Task {task_id}: Updating task status to completed")
            task.status = "completed"
            task.stage = "indexed"
            task.progress = 100
            task.document_id = document.id  # 更新为新创建的文档ID
            
            # 9. 更新上传记录状态
            if upload:
                logger.info(f"Task {task_id}: Updating upload record status to completed")
                upload.status = "completed"
            
            db.commit()
            # 文档入库后刷新 KB profile，供 Router Prompt 和 profile 向量兜底匹配使用。
            try:
                KnowledgeBaseProfileService.build_profile(db, kb_id)
            except Exception as profile_error:
                logger.warning("Task %s: Failed to refresh KB profile: %s", task_id, profile_error)
            logger.info(f"Task {task_id}: Processing completed successfully")
            
        finally:
            # 清理本地临时文件
            try:
                if os.path.exists(local_temp_path):
                    logger.info(f"Task {task_id}: Cleaning up local temp file")
                    os.remove(local_temp_path)
                    logger.info(f"Task {task_id}: Local temp file cleaned up")
            except Exception as e:
                logger.warning(f"Task {task_id}: Failed to clean up local temp file: {str(e)}")
        
    except Exception as e:
        logger.error(f"Task {task_id}: Error processing document: {str(e)}")
        logger.error(f"Task {task_id}: Stack trace: {traceback.format_exc()}")
        task.status = "failed"
        task.stage = "failed"
        task.error_message = str(e)
        db.commit()
        
        # 清理临时文件
        try:
            logger.info(f"Task {task_id}: Cleaning up temporary file after error")
            minio_client.remove_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=temp_path
            )
            logger.info(f"Task {task_id}: Temporary file cleaned up after error")
        except:
            logger.warning(f"Task {task_id}: Failed to clean up temporary file after error")
    finally:
        # if we create the db session, we need to close it
        if should_close_db and db:
            db.close()
