-- ============================================================================
-- AI Intent Flow 数据库建表 + 数据导出脚本
-- 包含：zb_ai_workflow、zb_conversation_nodes、zb_node_prompt、zb_node_prompt_ver_ctrl
-- ============================================================================

-- ----------------------------------------------------------------------------
-- DDL：AI 工作流表
-- ----------------------------------------------------------------------------
CREATE TABLE `zb_ai_workflow` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID，自增',
  `workflow_id` varchar(64) NOT NULL COMMENT '工作流id',
  `workflow_desc` varchar(256) DEFAULT NULL COMMENT '工作流描述',
  `entry_node_id` varchar(64) NOT NULL COMMENT '入口节点',
  `app_id` varchar(64) NOT NULL COMMENT '应用ID',
  `intent_classify_node_id` varchar(64) DEFAULT NULL COMMENT '意图识别节点，用于判断用户的话题是否在当前范围内，一般默认跟entry_node一致',
  `status` tinyint DEFAULT '1' COMMENT '工作流状态：0-不可用，1-可用',
  `enhance_intent_classify` tinyint DEFAULT '1' COMMENT '是否开启增强意图识别：0-不开启，1-开启',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_workflow_id` (`workflow_id`),
  KEY `idx_app_id` (`app_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI工作流表';

-- ----------------------------------------------------------------------------
-- DDL：对话流程节点表
-- ----------------------------------------------------------------------------
CREATE TABLE `zb_conversation_nodes` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID，自增',
  `node_id` varchar(64) NOT NULL COMMENT '节点ID',
  `node_name` varchar(128) NOT NULL COMMENT '节点名称',
  `node_type` varchar(64) NOT NULL COMMENT '节点类型：intent(意图识别), agent（智能体）,tool（执行工具）等',
  `node_description` varchar(512) DEFAULT NULL COMMENT '节点描述，描述该节点具体功能',
  `node_func_path` varchar(256) DEFAULT NULL COMMENT '节点功能实现的代码模块路径',
  `node_business_range` varchar(128) NOT NULL COMMENT '节点处理的业务范围，如：办公类业务、研发类业务、销售类业务等',
  `status` tinyint DEFAULT '1' COMMENT '节点状态：0-禁用，1-启用，默认启用',
  `parent_node_id` varchar(64) DEFAULT NULL COMMENT '上一级node_id',
  `model_id` varchar(64) DEFAULT NULL COMMENT '关联的模型ID，引用zb_node_model表',
  `model_ext_param` json DEFAULT NULL COMMENT '模型其他参数配置，JSON格式字符串，用于覆盖模型默认参数',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_id` (`node_id`),
  KEY `idx_model_id` (`model_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话流程节点表';

-- ----------------------------------------------------------------------------
-- DDL：节点提示词生效配置表
-- ----------------------------------------------------------------------------
CREATE TABLE `zb_node_prompt` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `node_id` varchar(64) NOT NULL COMMENT '节点id',
  `prompt_key` varchar(32) NOT NULL COMMENT '提示词的key，便于在代码中通过该key拿到提示词',
  `prompt_content` text COMMENT '提示词的实际内容',
  `model_id` varchar(64) DEFAULT NULL COMMENT '关联的模型ID，引用zb_llm_models表，不为空时覆盖节点级的模型配置',
  `model_ext_param` json DEFAULT NULL COMMENT '模型其他参数配置，JSON格式字符串，用于覆盖模型默认参数',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_prompt` (`node_id`, `prompt_key`),
  KEY `idx_node_id` (`node_id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点提示词配置表';

-- ----------------------------------------------------------------------------
-- DDL：节点提示词版本控制表
-- ----------------------------------------------------------------------------
CREATE TABLE `zb_node_prompt_ver_ctrl` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `node_id` varchar(64) NOT NULL COMMENT '节点id',
  `node_name` varchar(200) NOT NULL,
  `prompt_key` varchar(32) NOT NULL COMMENT '提示词的key，便于在代码中通过该key拿到提示词',
  `prompt_content` text COMMENT '提示词的实际内容',
  `model_id` varchar(64) DEFAULT NULL COMMENT '关联的模型ID，引用zb_llm_models表，不为空时覆盖节点级的模型配置',
  `model_ext_param` json DEFAULT NULL COMMENT '模型其他参数配置，JSON格式字符串，用于覆盖模型默认参数（如temperature、top_p等）',
  `status` tinyint DEFAULT NULL COMMENT '当前的提示词状态。0、暂存。1、发布。每一个node_id、prompt_key只有一个发布状态的提示词',
  `prompt_content_before_modify` text COMMENT '修改前的提示词的实际内容',
  `version_no` int NOT NULL COMMENT '版本号',
  `parent_id` bigint DEFAULT NULL COMMENT '当前版本的上一来源记录ID，用于版本溯源',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `update_by` varchar(64) NOT NULL COMMENT '修改人',
  PRIMARY KEY (`id`),
  KEY `idx_node_id` (`node_id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点提示词配置历史表';


-- ============================================================================
-- 以下为数据导出（共 22 条）
-- ============================================================================

-- ----------------------------------------------------------------------------
-- DATA：zb_ai_workflow（3 条）
-- ----------------------------------------------------------------------------
INSERT INTO `zb_ai_workflow` (`id`, `workflow_id`, `workflow_desc`, `entry_node_id`, `app_id`, `intent_classify_node_id`, `status`, `enhance_intent_classify`, `created_at`, `updated_at`) VALUES (1, 'xiaobang_all', '小智全能助手', 'intent_classification', 'xiaobang', 'intent_classification', 1, 1, '2026-07-07 16:10:04', '2026-07-09 16:53:40');
INSERT INTO `zb_ai_workflow` (`id`, `workflow_id`, `workflow_desc`, `entry_node_id`, `app_id`, `intent_classify_node_id`, `status`, `enhance_intent_classify`, `created_at`, `updated_at`) VALUES (2, 'xiaobang_book_meeting_room', '小智会议室管理员', 'tool_meeting_room', 'xiaobang', 'tool_meeting_room', 1, 1, '2026-07-07 16:10:04', '2026-07-09 16:53:40');
INSERT INTO `zb_ai_workflow` (`id`, `workflow_id`, `workflow_desc`, `entry_node_id`, `app_id`, `intent_classify_node_id`, `status`, `enhance_intent_classify`, `created_at`, `updated_at`) VALUES (3, 'xiaobang_bangong', '小智办公助手', 'agent_bangong', 'xiaobang', 'agent_bangong', 1, 1, '2026-07-07 16:10:04', '2026-07-09 16:53:41');

-- ----------------------------------------------------------------------------
-- DATA：zb_conversation_nodes（3 条）
-- ----------------------------------------------------------------------------
INSERT INTO `zb_conversation_nodes` (`id`, `node_id`, `node_name`, `node_type`, `node_description`, `node_func_path`, `node_business_range`, `status`, `parent_node_id`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (1, 'intent_classification', '小智全能助手', 'intent', '识别业务属于哪个智能体', 'app.intent.intent_classifier.IntentClassifier', '全部业务', 1, NULL, 'zb-qwen3.5-plus', '{"max_tokens": 65536, "temperature": 0.7}', '2026-02-26 17:06:31', '2026-07-09 16:53:22');
INSERT INTO `zb_conversation_nodes` (`id`, `node_id`, `node_name`, `node_type`, `node_description`, `node_func_path`, `node_business_range`, `status`, `parent_node_id`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (2, 'agent_bangong', '小智办公助手', 'agent', '办公类业务意图识别智能体', 'app.agent.agent_bangong.AgentBanGong', '办公类业务', 1, 'intent_classification', 'zb-qwen3.5-plus', '{"max_tokens": 65536, "temperature": 0.1}', '2026-02-26 17:06:33', '2026-07-09 16:53:23');
INSERT INTO `zb_conversation_nodes` (`id`, `node_id`, `node_name`, `node_type`, `node_description`, `node_func_path`, `node_business_range`, `status`, `parent_node_id`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (3, 'tool_meeting_room', '小智会议室助手', 'tool', '会议室预定/查询 - 查询会议室使用情况、预定会议室、查询会议室（可用的、空闲的、使用中的会议室等）', 'app.tool.xb_bangong.tool_book_meeting_room.ToolBookMeetingRoom', '会议室类业务', 1, 'agent_bangong', 'zb-qwen3.5-plus', '{"max_tokens": 65536, "temperature": 0.1}', '2026-02-26 17:06:34', '2026-07-09 16:53:23');

-- ----------------------------------------------------------------------------
-- DATA：zb_node_prompt（7 条）
-- ----------------------------------------------------------------------------
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (1, 'intent_classification', 'classification_prompt', '你是一个智能意图分类助手，负责将用户的输入分类到合适的业务类别。

当前你可处理的业务类别共有 {children_count} 个：
{classify_desc}

请根据用户的输入，判断用户想要办理哪个业务类别，并以 JSON 格式返回结果：
{{"intent": "<业务类别对应的 node_id>", "confidence": <0.0~1.0 置信度>}}

注意：
1. 如果用户输入属于已有业务类别，intent 填对应 node_id
2. 如果用户是寒暄、闲聊、问候等无关内容，intent 填 "__unknown"
3. confidence 为 0.0~1.0 的浮点数
', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (2, 'intent_classification', 'friendly_response_prompt', '你是 {node_name}，一个友好、专业的智能助手。

你服务的业务范围包括：
{classify_desc}

请用友好、自然的语气回复用户的寒暄、问候或闲聊内容，并简要介绍你可以帮助用户办理哪些业务。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (3, 'agent_bangong', 'classification_prompt', '你是小灰机办公助手，负责将用户的办公类需求分类到具体的工具。<br><br>当前你可处理的工具共有 {tool_count} 个：<br>{func_desc_str}<br><br>请根据用户的输入，判断用户想要使用哪个工具，并以 JSON 格式返回结果：<br>{{"intent": "&lt;工具对应的 node_id&gt;", "confidence": &lt;0.0~1.0 置信度&gt;}}<br><br>注意：如果用户输入无法匹配到任何工具，intent 填 "__unknown"', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-09 17:02:27');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (4, 'agent_bangong', 'friendly_response_prompt', '你是 {node_name}，一个专业友好的办公助手。

你可以帮助用户处理以下办公类业务：
{func_desc_str}

请用友好、自然的语气回复用户的寒暄、问候或闲聊内容。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (5, 'tool_meeting_room', 'prompt_tool_call', '你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。
当前用户：{user_name}
当前时间：{current_time}

你可以使用以下工具：
1. get_meeting_room_available_time_periods - 查询指定时间段内会议室的空闲时间段
2. book_meeting_room - 预订指定的会议室（需用户确认）

工作流程：
- 如果用户想查看会议室空闲情况，先调用查询工具
- 如果用户想预订会议室，需要先确认会议室名称、开始时间和结束时间
- 5001 会议室不可预订，请提醒用户选择其他会议室

注意事项：
- 预订时间不能跨天，不能超过1小时
- 不能预订已经过去的时间段
- 会议室开放时间为每天 08:00-20:00
', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (6, 'tool_meeting_room', 'prompt_friendly_response', '你是 {node_name}，一个帮助用户预订会议室的智能助手。
请用友好、自然的语气回复用户的寒暄或闲聊，并引导用户说明会议室预订需求。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');
INSERT INTO `zb_node_prompt` (`id`, `node_id`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `created_at`, `updated_at`) VALUES (7, 'tool_meeting_room', 'prompt_intent_analysis', '你是一个意图分析助手，用于判断用户输入的意图类型。

背景：用户当前正在使用会议室预订服务。请根据用户最新输入，判断其意图属于以下哪种类型：

1. {INTENT_CONTINUE_BUSINESS}：用户想继续办理会议室预订相关业务
2. {INTENT_FRIENDLY_RESPONSE}：用户只是在闲聊、寒暄、问候或询问与你相关的问题
3. {INTENT_CHANGE_TOPIC}：用户想切换到其他业务话题
4. {INTENT_END_BUSINESS}：用户想结束当前业务

请以 JSON 格式返回结果：
{{"intent_type": "<意图类型>", "friendly_response": "<切换话题时的友好回应文本，其他情况为空字符串>"}}

注意：仅在 intent_type 为 {INTENT_CHANGE_TOPIC} 时需要填写友好的回应文本。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', '2026-07-08 10:38:26', '2026-07-08 11:52:28');

-- ----------------------------------------------------------------------------
-- DATA：zb_node_prompt_ver_ctrl（9 条）
-- ----------------------------------------------------------------------------
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (1, 'intent_classification', '小邦全能助手', 'classification_prompt', '你是一个智能意图分类助手，负责将用户的输入分类到合适的业务类别。

当前你可处理的业务类别共有 {children_count} 个：
{classify_desc}

请根据用户的输入，判断用户想要办理哪个业务类别，并以 JSON 格式返回结果：
{{"intent": "<业务类别对应的 node_id>", "confidence": <0.0~1.0 置信度>}}

注意：
1. 如果用户输入属于已有业务类别，intent 填对应 node_id
2. 如果用户是寒暄、闲聊、问候等无关内容，intent 填 "__unknown"
3. confidence 为 0.0~1.0 的浮点数
', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (2, 'intent_classification', '小邦全能助手', 'friendly_response_prompt', '你是 {node_name}，一个友好、专业的智能助手。

你服务的业务范围包括：
{classify_desc}

请用友好、自然的语气回复用户的寒暄、问候或闲聊内容，并简要介绍你可以帮助用户办理哪些业务。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (3, 'agent_bangong', '小智办公助手', 'classification_prompt', '你是小灰机办公助手，负责将用户的办公类需求分类到具体的工具。<br><br>当前你可处理的工具共有 {tool_count} 个：<br>{func_desc_str}<br><br>请根据用户的输入，判断用户想要使用哪个工具，并以 JSON 格式返回结果：<br>{{"intent": "&lt;工具对应的 node_id&gt;", "confidence": &lt;0.0~1.0 置信度&gt;}}<br><br>注意：如果用户输入无法匹配到任何工具，intent 填 "__unknown"', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, '你是小灰灰办公助手，负责将用户的办公类需求分类到具体的工具。<br><br>当前你可处理的工具共有 {tool_count} 个：<br>{func_desc_str}<br><br>请根据用户的输入，判断用户想要使用哪个工具，并以 JSON 格式返回结果：<br>{{"intent": "&lt;工具对应的 node_id&gt;", "confidence": &lt;0.0~1.0 置信度&gt;}}<br><br>注意：如果用户输入无法匹配到任何工具，intent 填 "__unknown"', 1, NULL, '2026-07-09 10:26:11', '2026-07-09 17:02:27', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (4, 'agent_bangong', '小邦办公助手', 'friendly_response_prompt', '你是 {node_name}，一个专业友好的办公助手。

你可以帮助用户处理以下办公类业务：
{func_desc_str}

请用友好、自然的语气回复用户的寒暄、问候或闲聊内容。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (5, 'tool_meeting_room', '小邦会议室助手', 'prompt_friendly_response', '你是 {node_name}，一个帮助用户预订会议室的智能助手。
请用友好、自然的语气回复用户的寒暄或闲聊，并引导用户说明会议室预订需求。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (6, 'tool_meeting_room', '小邦会议室助手', 'prompt_intent_analysis', '你是一个意图分析助手，用于判断用户输入的意图类型。

背景：用户当前正在使用会议室预订服务。请根据用户最新输入，判断其意图属于以下哪种类型：

1. {INTENT_CONTINUE_BUSINESS}：用户想继续办理会议室预订相关业务
2. {INTENT_FRIENDLY_RESPONSE}：用户只是在闲聊、寒暄、问候或询问与你相关的问题
3. {INTENT_CHANGE_TOPIC}：用户想切换到其他业务话题
4. {INTENT_END_BUSINESS}：用户想结束当前业务

请以 JSON 格式返回结果：
{{"intent_type": "<意图类型>", "friendly_response": "<切换话题时的友好回应文本，其他情况为空字符串>"}}

注意：仅在 intent_type 为 {INTENT_CHANGE_TOPIC} 时需要填写友好的回应文本。', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (7, 'tool_meeting_room', '小邦会议室助手', 'prompt_tool_call', '你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。
当前用户：{user_name}
当前时间：{current_time}

你可以使用以下工具：
1. get_meeting_room_available_time_periods - 查询指定时间段内会议室的空闲时间段
2. book_meeting_room - 预订指定的会议室（需用户确认）

工作流程：
- 如果用户想查看会议室空闲情况，先调用查询工具
- 如果用户想预订会议室，需要先确认会议室名称、开始时间和结束时间
- 5001 会议室不可预订，请提醒用户选择其他会议室

注意事项：
- 预订时间不能跨天，不能超过1小时
- 不能预订已经过去的时间段
- 会议室开放时间为每天 08:00-20:00
', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 1, NULL, 1, NULL, '2026-07-09 10:26:11', '2026-07-09 10:26:11', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (8, 'tool_meeting_room', '小邦会议室助手', 'prompt_tool_call', '你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。<br>当前用户：{user_name}<br>当前时间：{current_time}<br><br>你可以使用以下工具：<br>1. get_meeting_room_available_time_periods - 查询指定时间段内会议室的空闲时间段<br>2. book_meeting_room - 预订指定的会议室（需用户确认）<br><br>工作流程：<br>- 如果用户想查看会议室空闲情况，先调用查询工具<br>- 如果用户想预订会议室，需要先确认会议室名称、开始时间和结束时间<br>- 5001 会议室不可预订，请提醒用户选择其他会议室<br><br>注意事项：<br>- 预订时间不能跨天，不能超过1小时<br>- 不能预订已经过去的时间段<br>- 会议室开放时间为每天 08:00-20:00<br>', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.2}', 0, '你是 {node_name}，专门帮助用户查询和预订会议室的智能助手。
当前用户：{user_name}
当前时间：{current_time}

你可以使用以下工具：
1. get_meeting_room_available_time_periods - 查询指定时间段内会议室的空闲时间段
2. book_meeting_room - 预订指定的会议室（需用户确认）

工作流程：
- 如果用户想查看会议室空闲情况，先调用查询工具
- 如果用户想预订会议室，需要先确认会议室名称、开始时间和结束时间
- 5001 会议室不可预订，请提醒用户选择其他会议室

注意事项：
- 预订时间不能跨天，不能超过1小时
- 不能预订已经过去的时间段
- 会议室开放时间为每天 08:00-20:00
', 2, 7, '2026-07-09 16:31:12', '2026-07-09 16:31:12', 'system');
INSERT INTO `zb_node_prompt_ver_ctrl` (`id`, `node_id`, `node_name`, `prompt_key`, `prompt_content`, `model_id`, `model_ext_param`, `status`, `prompt_content_before_modify`, `version_no`, `parent_id`, `created_at`, `updated_at`, `update_by`) VALUES (9, 'agent_bangong', '小邦办公助手', 'classification_prompt', '你是小智办公助手，负责将用户的办公类需求分类到具体的工具。<br><br>当前你可处理的工具共有 {tool_count} 个：<br>{func_desc_str}<br><br>请根据用户的输入，判断用户想要使用哪个工具，并以 JSON 格式返回结果：<br>{{"intent": "&lt;工具对应的 node_id&gt;", "confidence": &lt;0.0~1.0 置信度&gt;}}<br><br>注意：如果用户输入无法匹配到任何工具，intent 填 "__unknown"', 'zb_deep_seek_chat', '{"max_tokens": 65536, "temperature": 0.1}', 0, '你是小邦办公助手，负责将用户的办公类需求分类到具体的工具。

当前你可处理的工具共有 {tool_count} 个：
{func_desc_str}

请根据用户的输入，判断用户想要使用哪个工具，并以 JSON 格式返回结果：
{{"intent": "<工具对应的 node_id>", "confidence": <0.0~1.0 置信度>}}

注意：如果用户输入无法匹配到任何工具，intent 填 "__unknown"', 2, 3, '2026-07-09 16:55:19', '2026-07-09 17:02:27', 'system');


-- ----------------------------------------------------------------------------
-- DATA：zb_llm_models（1 条）
-- ----------------------------------------------------------------------------
INSERT INTO `zb_llm_models` (`id`, `model_id`, `model_name`, `description`, `provider`, `api_model_name`, `base_url`, `api_key`, `context_length`, `supports_streaming`, `supports_function_calling`, `supports_vision`, `supports_search`, `supports_json_mode`, `input_price`, `output_price`, `currency`, `is_enabled`, `is_production_ready`, `model_category`, `model_group`, `tags`, `rate_limit_rpm`, `rate_limit_tpm`, `max_concurrent_requests`, `default_temperature`, `default_max_tokens`, `api_parameters`, `custom_config`, `created_at`, `updated_at`, `created_by`, `updated_by`, `version`) VALUES (21, 'zb_deep_seek_chat', 'DeepSeek Chat', 'DeepSeek Chat 模型，直连 DeepSeek 官方 API', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com', 'sk-xxxxxxxxxxxxxxxx', 64000, 1, 1, 0, 0, 1, 0.010000, 0.010000, 'CNY', 1, 1, 'general', 'deepseek', '["deepseek", "direct"]', NULL, NULL, NULL, 0.70, 2000, NULL, NULL, '2026-07-08 11:05:19', '2026-07-08 11:05:19', NULL, NULL, 1);

