-- 清理面试演示知识库中失败的导入记录，便于重新走上传、分块、向量化流程。
-- 仅作用于 interview_demo 用户名下的演示知识库。

SET NAMES utf8mb4;

SET @demo_username := 'interview_demo';
SET @demo_kb_name := '面试演示-医院后勤RAG知识库';
SET @demo_user_id := (
    SELECT id FROM users WHERE username = @demo_username LIMIT 1
);
SET @demo_kb_id := (
    SELECT id
    FROM knowledge_bases
    WHERE user_id = @demo_user_id AND name = @demo_kb_name
    LIMIT 1
);

DELETE FROM document_chunks
WHERE kb_id = @demo_kb_id;

DELETE FROM document_parent_chunks
WHERE kb_id = @demo_kb_id;

DELETE FROM processing_tasks
WHERE knowledge_base_id = @demo_kb_id;

DELETE FROM document_uploads
WHERE knowledge_base_id = @demo_kb_id;

DELETE FROM documents
WHERE knowledge_base_id = @demo_kb_id;
