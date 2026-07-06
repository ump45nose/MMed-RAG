-- 初始化面试演示用干扰知识库，用于展示 KB Router 相比全库检索的收益。
-- 文档内容仍通过上传接口导入，SQL 只负责创建知识库元数据。

SET NAMES utf8mb4;

SET @demo_username := 'interview_demo';
SET @noise_kb_name := '面试演示-通用维修噪声知识库';
SET @demo_user_id := (
    SELECT id FROM users WHERE username = @demo_username LIMIT 1
);

INSERT INTO knowledge_bases (
    name,
    description,
    user_id,
    created_at,
    updated_at,
    profile_summary,
    profile_keywords,
    profile_document_count,
    profile_updated_at
)
SELECT
    @noise_kb_name,
    '用于评测 KB Router 的干扰知识库，包含通用维修、公告、能耗和非核心后勤材料。',
    @demo_user_id,
    NOW(),
    NOW(),
    '知识库名称：面试演示-通用维修噪声知识库\n描述：通用维修、公告、能耗、空间和人员管理等干扰材料，用于测试全库检索误召回。',
    JSON_ARRAY('通用维修', '公告', '能耗', '空间', '人员', '干扰', '噪声'),
    0,
    NOW()
WHERE NOT EXISTS (
    SELECT 1
    FROM knowledge_bases
    WHERE user_id = @demo_user_id AND name = @noise_kb_name
);
