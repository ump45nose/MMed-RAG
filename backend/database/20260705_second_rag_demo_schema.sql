-- 面试版生产化 RAG Demo 二期 schema 变更。
-- 作用：补充 KB profile、用户部门访问白名单、自建 RAG trace 落库。

ALTER TABLE knowledge_bases
  ADD COLUMN profile_summary LONGTEXT NULL,
  ADD COLUMN profile_keywords JSON NULL,
  ADD COLUMN profile_document_count INT NULL,
  ADD COLUMN profile_updated_at DATETIME NULL;

ALTER TABLE users
  ADD COLUMN allowed_departments JSON NULL;

CREATE TABLE rag_traces (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  chat_id INT NULL,
  query TEXT NOT NULL,
  rewritten_query TEXT NULL,
  intent VARCHAR(50) NULL,
  domains JSON NULL,
  candidate_kbs JSON NULL,
  selected_kbs JSON NULL,
  retrieval_trace JSON NULL,
  answer_policy JSON NULL,
  latency_breakdown JSON NULL,
  total_latency_ms FLOAT NULL,
  confidence_score FLOAT NULL,
  refused TINYINT(1) NOT NULL DEFAULT 0,
  refusal_reason VARCHAR(255) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT rag_traces_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT rag_traces_chat_id_fkey FOREIGN KEY (chat_id) REFERENCES chats(id)
);

CREATE INDEX ix_rag_traces_user_id ON rag_traces (user_id);
CREATE INDEX ix_rag_traces_chat_id ON rag_traces (chat_id);
