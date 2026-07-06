-- 初始化面试演示账号与知识库。
-- 文档、父块、子块与向量索引通过应用上传/处理接口生成，避免绕过业务处理链路。

SET NAMES utf8mb4;

SET @demo_username := 'interview_demo';
SET @demo_email := 'interview_demo@example.local';
SET @demo_password_hash := '$2b$12$9YYfk8tYNIsMRN28wXZrk.FdXVE.8jbRC6iXrmKw43x43K9qEOs9O';
SET @demo_kb_name := '面试演示-医院后勤RAG知识库';

INSERT INTO users (
    email,
    username,
    hashed_password,
    is_active,
    is_superuser,
    allowed_departments,
    created_at,
    updated_at
)
SELECT
    @demo_email,
    @demo_username,
    @demo_password_hash,
    1,
    1,
    JSON_ARRAY('后勤', '医工', '总务', '设备', '能源', '保洁', '运送', '医废'),
    NOW(),
    NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE username = @demo_username OR email = @demo_email
);

UPDATE users
SET
    hashed_password = @demo_password_hash,
    is_active = 1,
    is_superuser = 1,
    allowed_departments = JSON_ARRAY('后勤', '医工', '总务', '设备', '能源', '保洁', '运送', '医废'),
    updated_at = NOW()
WHERE username = @demo_username;

SET @demo_user_id := (
    SELECT id FROM users WHERE username = @demo_username LIMIT 1
);

UPDATE knowledge_bases
SET
    name = @demo_kb_name,
    description = '用于面试展示的医院后勤、医废、保洁、运送、医工设备与问题整理 RAG 评测知识库。',
    updated_at = NOW()
WHERE user_id = @demo_user_id
  AND HEX(name) = '3F3F3F3F2D3F3F3F3F5241473F3F3F'
  AND NOT EXISTS (
      SELECT 1
      FROM (
          SELECT id
          FROM knowledge_bases
          WHERE user_id = @demo_user_id AND name = @demo_kb_name
          LIMIT 1
      ) existing_kb
  );

INSERT INTO knowledge_bases (
    name,
    description,
    user_id,
    created_at,
    updated_at
)
SELECT
    @demo_kb_name,
    '用于面试展示的医院后勤、医废、保洁、运送、医工设备与问题整理 RAG 评测知识库。',
    @demo_user_id,
    NOW(),
    NOW()
WHERE NOT EXISTS (
    SELECT 1
    FROM knowledge_bases
    WHERE user_id = @demo_user_id AND name = @demo_kb_name
);
