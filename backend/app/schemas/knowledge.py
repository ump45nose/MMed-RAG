from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    profile_summary: Optional[str] = None
    profile_keywords: Optional[List[str]] = None
    profile_document_count: Optional[int] = None
    profile_updated_at: Optional[datetime] = None

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBaseUpdate(KnowledgeBaseBase):
    pass

class DocumentBase(BaseModel):
    file_name: str
    file_path: str
    file_hash: str
    file_size: int
    content_type: str
    title: Optional[str] = None
    doc_type: Optional[str] = None
    department: Optional[str] = None
    equipment_model: Optional[str] = None
    effective_date: Optional[str] = None
    metadata_suggestion: Optional[Dict[str, Any]] = None
    metadata_confirmed: bool = False

class DocumentCreate(DocumentBase):
    knowledge_base_id: int

class DocumentUploadBase(BaseModel):
    file_name: str
    file_hash: str
    file_size: int
    content_type: str
    temp_path: str
    metadata_suggestion: Optional[Dict[str, Any]] = None
    confirmed_metadata: Optional[Dict[str, Any]] = None
    status: str = "pending"
    error_message: Optional[str] = None

class DocumentUploadCreate(DocumentUploadBase):
    knowledge_base_id: int

class DocumentUploadResponse(DocumentUploadBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ProcessingTaskBase(BaseModel):
    status: str
    stage: Optional[str] = None
    progress: Optional[int] = None
    error_message: Optional[str] = None

class ProcessingTaskCreate(ProcessingTaskBase):
    document_id: int
    knowledge_base_id: int

class ProcessingTask(ProcessingTaskBase):
    id: int
    document_id: int
    knowledge_base_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DocumentResponse(DocumentBase):
    id: int
    knowledge_base_id: int
    created_at: datetime
    updated_at: datetime
    processing_tasks: List[ProcessingTask] = []

    class Config:
        from_attributes = True

class KnowledgeBaseResponse(KnowledgeBaseBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentResponse] = []

    class Config:
        from_attributes = True

class PreviewRequest(BaseModel):
    document_ids: List[int]
    chunk_size: int = 1000
    chunk_overlap: int = 200

class DocumentMetadataConfirm(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    department: Optional[str] = None
    equipment_model: Optional[str] = None
    effective_date: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

class MetadataSuggestRequest(BaseModel):
    document_id: Optional[int] = None
    upload_id: Optional[int] = None
    file_name: Optional[str] = None
    sample_text: Optional[str] = None
