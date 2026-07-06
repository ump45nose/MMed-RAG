-- 面试版生产化 RAG Demo 一期 schema 变更。
-- 作用：补充文档 metadata、父子检索 parent 存储、child 标量过滤字段与任务进度字段。

ALTER TABLE documents
  ADD COLUMN title VARCHAR(512) NULL,
  ADD COLUMN doc_type VARCHAR(100) NULL,
  ADD COLUMN department VARCHAR(100) NULL,
  ADD COLUMN equipment_model VARCHAR(255) NULL,
  ADD COLUMN effective_date VARCHAR(32) NULL,
  ADD COLUMN metadata_suggestion JSON NULL,
  ADD COLUMN metadata_confirmed TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE document_uploads
  ADD COLUMN metadata_suggestion JSON NULL,
  ADD COLUMN confirmed_metadata JSON NULL;

ALTER TABLE processing_tasks
  ADD COLUMN stage VARCHAR(50) NULL,
  ADD COLUMN progress INT NULL;

CREATE TABLE document_parent_chunks (
  id VARCHAR(64) NOT NULL,
  kb_id INT NOT NULL,
  document_id INT NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  parent_index INT NOT NULL DEFAULT 0,
  content LONGTEXT NOT NULL,
  section_path VARCHAR(2048) NULL,
  page INT NULL,
  doc_type VARCHAR(100) NULL,
  department VARCHAR(100) NULL,
  effective_date VARCHAR(32) NULL,
  parent_metadata JSON NULL,
  hash VARCHAR(64) NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT document_parent_chunks_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id),
  CONSTRAINT document_parent_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE INDEX idx_parent_kb_doc ON document_parent_chunks (kb_id, document_id);
CREATE INDEX idx_parent_kb_file ON document_parent_chunks (kb_id, file_name);
CREATE INDEX ix_document_parent_chunks_hash ON document_parent_chunks (hash);

ALTER TABLE document_chunks
  ADD COLUMN parent_id VARCHAR(64) NULL,
  ADD COLUMN content LONGTEXT NULL,
  ADD COLUMN child_index INT NULL,
  ADD COLUMN section_path VARCHAR(2048) NULL,
  ADD COLUMN page INT NULL,
  ADD COLUMN doc_type VARCHAR(100) NULL,
  ADD COLUMN department VARCHAR(100) NULL,
  ADD COLUMN effective_date VARCHAR(32) NULL,
  ADD CONSTRAINT document_chunks_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES document_parent_chunks(id);

CREATE INDEX idx_chunk_parent_id ON document_chunks (parent_id);
CREATE INDEX idx_chunk_scalar_filter ON document_chunks (kb_id, doc_type, department, effective_date);
