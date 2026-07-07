-- 将本地展示数据从临时命名改为业务命名。
-- 作用：页面截图和对外文档统一呈现为医院后勤/医工知识库场景。

SET NAMES utf8mb4;

UPDATE knowledge_bases
SET
    name = '医院后勤与医工资料知识库',
    description = '覆盖医院后勤、医废、保洁、运送、医工设备与问题整理资料，用于知识检索、引用追溯和拒答评测。',
    updated_at = NOW()
WHERE id = 1;

UPDATE knowledge_bases
SET
    name = '通用维修噪声知识库',
    description = '包含通用维修、公告、能耗和非核心后勤材料，用于验证知识库路由对噪声资料的抑制效果。',
    profile_summary = '知识库名称：通用维修噪声知识库
描述：通用维修、公告、能耗、空间和人员管理等干扰材料，用于测试全库检索误召回。',
    profile_keywords = JSON_ARRAY('通用维修', '公告', '能耗', '空间', '人员', '干扰', '噪声'),
    updated_at = NOW()
WHERE id = 2;
