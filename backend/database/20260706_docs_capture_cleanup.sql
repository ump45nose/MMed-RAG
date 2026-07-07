-- 清理文档截图过程中产生的临时验证数据。
-- 注意：不回滚知识库业务命名修正，仅删除截图自动化产生的用户、聊天、消息、trace 和临时上传记录。

SET NAMES utf8mb4;

DELETE FROM rag_traces
WHERE chat_id IN (
    SELECT id FROM chats WHERE title = '资料拒答验证'
);

DELETE FROM messages
WHERE chat_id IN (
    SELECT id FROM chats WHERE title = '资料拒答验证'
);

DELETE FROM chat_knowledge_bases
WHERE chat_id IN (
    SELECT id FROM chats WHERE title = '资料拒答验证'
);

DELETE FROM chats
WHERE title = '资料拒答验证';

DELETE FROM document_uploads
WHERE file_name = 'mmed_rag_upload_preview.txt'
  AND status = 'pending';

DELETE FROM users
WHERE username = 'docs_capture'
  AND email = 'docs.capture@example.com';
