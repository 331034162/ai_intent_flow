-- ai_intent_flow.checkpoint_blobs definition

CREATE TABLE `checkpoint_blobs` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `channel` varchar(150) NOT NULL,
  `version` varchar(150) NOT NULL,
  `type` varchar(150) NOT NULL,
  `blob` longblob,
  `checkpoint_ns_hash` binary(16) NOT NULL,
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`channel`,`version`),
  KEY `checkpoint_blobs_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- ai_intent_flow.checkpoint_migrations definition

CREATE TABLE `checkpoint_migrations` (
  `v` int NOT NULL,
  PRIMARY KEY (`v`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- ai_intent_flow.checkpoint_writes definition

CREATE TABLE `checkpoint_writes` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `checkpoint_id` varchar(150) NOT NULL,
  `task_id` varchar(150) NOT NULL,
  `idx` int NOT NULL,
  `channel` varchar(150) NOT NULL,
  `type` varchar(150) DEFAULT NULL,
  `blob` longblob NOT NULL,
  `checkpoint_ns_hash` binary(16) NOT NULL,
  `task_path` varchar(2000) NOT NULL DEFAULT '',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`,`task_id`,`idx`),
  KEY `checkpoint_writes_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- ai_intent_flow.checkpoints definition

CREATE TABLE `checkpoints` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `checkpoint_id` varchar(150) NOT NULL,
  `parent_checkpoint_id` varchar(150) DEFAULT NULL,
  `type` varchar(150) DEFAULT NULL,
  `checkpoint` json NOT NULL,
  `metadata` json NOT NULL DEFAULT (_utf8mb4'{}'),
  `checkpoint_ns_hash` binary(16) NOT NULL,
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`),
  KEY `checkpoints_thread_id_idx` (`thread_id`),
  KEY `checkpoints_checkpoint_id_idx` (`checkpoint_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- ai_intent_flow.zb_ai_workflow definition

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


-- ai_intent_flow.zb_conversation_business_state definition

CREATE TABLE `zb_conversation_business_state` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `conversation_id` varchar(64) NOT NULL COMMENT '会话ID',
  `node_id` varchar(64) NOT NULL COMMENT '节点ID（业务类型标识）',
  `thread_id` varchar(64) NOT NULL COMMENT 'LangGraph 线程ID',
  `business_state` varchar(32) NOT NULL DEFAULT 'processing' COMMENT '业务状态：processing-处理中, completed-已完成',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_conversation_node` (`conversation_id`,`node_id`),
  KEY `idx_conversation_node_state` (`conversation_id`,`node_id`,`business_state`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话业务状态表';


-- ai_intent_flow.zb_conversation_messages definition

CREATE TABLE `zb_conversation_messages` (
  `message_id` bigint NOT NULL AUTO_INCREMENT COMMENT '消息唯一标识，自增主键',
  `conversation_id` varchar(64) NOT NULL COMMENT '会话ID，关联到会话记录表',
  `seq_no` varchar(128) DEFAULT NULL COMMENT '对话流水号，唯一标识用户的每一次对话',
  `question` mediumtext COMMENT '消息问题',
  `answer` mediumtext COMMENT '消息回答',
  `message_status` tinyint DEFAULT '0' COMMENT '消息状态：0（处理中）、1（成功）、-1（失败）',
  `status_description` text COMMENT '状态描述，记录请求的实际状况，如错误信息或处理详情',
  `is_human_generated` tinyint(1) DEFAULT '0' COMMENT '当前信息是否为人类生成的：0-否，1-是',
  `model_name` varchar(128) DEFAULT NULL COMMENT '模型名称',
  `model_provider` varchar(128) DEFAULT 'zbank' COMMENT '模型提供商。默认为zbank，外部大模型请填写对应的模型提供商名称',
  `model_url` varchar(256) DEFAULT NULL COMMENT 'model的访问地址',
  `model_ext_param` json DEFAULT NULL COMMENT '模型其他参数配置，JSON格式字符串',
  `extra_info` json DEFAULT NULL COMMENT '额外信息，JSON格式，如客户端类型、设备IP等',
  `node_id` varchar(64) DEFAULT NULL COMMENT '对话处理的节点',
  `workflow_id` varchar(64) DEFAULT NULL COMMENT '对话处理的工作流节点',
  `file_id_list` text COMMENT '对话用到的file_id列表，用,分隔',
  `task_type` varchar(32) DEFAULT NULL COMMENT '任务类型: summary/report/outline/article/qa/compare/extract/translate/rewrite/speech/briefing/write_summary/normal',
  `thread_id` varchar(64) DEFAULT NULL COMMENT 'LangGraph 线程ID，用于会话状态管理',
  `interrupt_id` varchar(2048) DEFAULT NULL COMMENT '中断ID，用于人机协同中断恢复',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`message_id`),
  KEY `idx_conversation_id` (`conversation_id`),
  KEY `idx_create_at` (`created_at`),
  KEY `idx_seq_no` (`seq_no`)
) ENGINE=InnoDB AUTO_INCREMENT=38 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话消息表';


-- ai_intent_flow.zb_conversation_nodes definition

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
  `model_ext_param` json DEFAULT NULL COMMENT '模型其他参数配置，JSON格式字符串',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_id` (`node_id`),
  KEY `idx_model_id` (`model_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对话流程节点表';


-- ai_intent_flow.zb_conversation_upload_files definition

CREATE TABLE `zb_conversation_upload_files` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT '会话ID（来自 llm_db 版本，关联zb_conversations）',
  `seq_no` varchar(128) DEFAULT NULL COMMENT '对话流水号（来自 llm_db 版本）',
  `file_id` varchar(64) NOT NULL COMMENT '文件唯一标识',
  `user_id` varchar(64) NOT NULL COMMENT '用户ID',
  `file_name` varchar(128) NOT NULL COMMENT '原始文件名',
  `file_type` varchar(32) DEFAULT NULL COMMENT '文件类型(扩展名)',
  `file_size` bigint DEFAULT NULL COMMENT '文件大小(字节)',
  `file_path` varchar(1024) DEFAULT NULL COMMENT '文件存储路径',
  `file_content` mediumtext COMMENT '文件内容/解析后的文本(最大16MB)',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态: 1-正常, 0-删除',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_file_id` (`file_id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_seq_no` (`seq_no`),
  KEY `idx_conversation_user` (`conversation_id`,`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户上传文件信息表';


-- ai_intent_flow.zb_conversations definition

CREATE TABLE `zb_conversations` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID，自增',
  `conversation_id` varchar(64) NOT NULL COMMENT '会话唯一标识，使用UUID',
  `knowledge_conversation_id` varchar(128) DEFAULT NULL COMMENT '知识库会话id，由知识库提供的会话id',
  `conversation_name` varchar(256) NOT NULL DEFAULT '' COMMENT '会话名称，默认为该会话中第一个问题的前256个字符',
  `conversation_type` tinyint NOT NULL DEFAULT '1' COMMENT '会话类型：1-模型会话，2-知识库会话',
  `employee_id` varchar(256) NOT NULL COMMENT '员工编号',
  `user_name` varchar(100) DEFAULT NULL COMMENT '用户名称',
  `is_deleted` tinyint(1) DEFAULT '0' COMMENT '是否删除：0-未删除，1-已删除',
  `node_id` varchar(64) NOT NULL COMMENT '用户当前会话所处的节点。',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间,每次对话都更新，反映会话的最新动态',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_conversation_id` (`conversation_id`),
  KEY `idx_employee_updated` (`employee_id`,`updated_at`),
  KEY `idx_is_deleted` (`is_deleted`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话记录表';


-- ai_intent_flow.zb_llm_call_detail definition

CREATE TABLE `zb_llm_call_detail` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `node_id` varchar(64) DEFAULT NULL COMMENT '产生该调用的节点ID，关联 zb_conversation_nodes.node_id',
  `conversation_id` varchar(64) DEFAULT NULL COMMENT '会话ID，关联 zb_conversations.conversation_id',
  `employee_id` varchar(256) DEFAULT NULL COMMENT '员工编号',
  `user_name` varchar(100) DEFAULT NULL COMMENT '用户名称',
  `app_code` varchar(64) NOT NULL COMMENT '应用编号，对应application_info表',
  `agent_key` varchar(255) DEFAULT NULL COMMENT 'api_key,这里主要是指dify',
  `llm_url` varchar(255) DEFAULT NULL COMMENT '模型调用地址',
  `llm_using_type` varchar(20) DEFAULT NULL COMMENT '模型使用方式--dify-dify调用;direct-直连',
  `llm_type` varchar(20) DEFAULT NULL COMMENT '模型类型--zbank-行内;outside-行外',
  `llm_model_provider` varchar(64) NOT NULL COMMENT '模型提供商',
  `llm_model_name` varchar(64) NOT NULL COMMENT '模型名',
  `prompt_tokens` int NOT NULL DEFAULT '0' COMMENT '提示词 token 数',
  `prompt_unit_price` decimal(12,6) NOT NULL DEFAULT '0.000000' COMMENT '提示词单价(元/token)',
  `prompt_price` decimal(12,6) NOT NULL DEFAULT '0.000000' COMMENT '提示词费用(元)',
  `completion_tokens` int NOT NULL DEFAULT '0' COMMENT '生成 token 数',
  `completion_unit_price` decimal(12,6) NOT NULL DEFAULT '0.000000' COMMENT '生成内容单价(元/token)',
  `completion_price` decimal(12,6) NOT NULL DEFAULT '0.000000' COMMENT '生成费用(元)',
  `total_tokens` int NOT NULL DEFAULT '0' COMMENT '总 token 数',
  `total_price` decimal(12,6) NOT NULL DEFAULT '0.000000' COMMENT '总费用(元)',
  `currency` varchar(20) NOT NULL DEFAULT 'RMB' COMMENT '币种',
  `latency_ms` int NOT NULL DEFAULT '0' COMMENT '耗时(毫秒)',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '1成功 2失败',
  `error_msg` varchar(255) DEFAULT NULL COMMENT '错误信息',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `create_time` timestamp NOT NULL COMMENT '创建时间',
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `version_number` smallint NOT NULL DEFAULT '0' COMMENT '版本号',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_app_created` (`app_code`,`create_time`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=78 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='LLM 模型调用记录表';


-- ai_intent_flow.zb_llm_models definition

CREATE TABLE `zb_llm_models` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `model_id` varchar(128) NOT NULL COMMENT '模型唯一标识，如zb-qwen-plus、gpt-4',
  `model_name` varchar(128) NOT NULL COMMENT '模型显示名称',
  `description` text COMMENT '模型描述',
  `provider` varchar(64) NOT NULL COMMENT 'Provider类型：jiusuan、openai、anthropic等',
  `api_model_name` varchar(128) NOT NULL COMMENT '调用API时使用的模型名称',
  `base_url` varchar(512) NOT NULL COMMENT 'API基础URL',
  `api_key` varchar(256) NOT NULL COMMENT 'API密钥（建议加密存储）',
  `context_length` int NOT NULL DEFAULT '4096' COMMENT '上下文长度',
  `supports_streaming` tinyint(1) NOT NULL DEFAULT '1' COMMENT '是否支持流式输出',
  `supports_function_calling` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否支持函数调用',
  `supports_vision` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否支持视觉能力',
  `supports_search` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否支持联网搜索',
  `supports_json_mode` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否支持JSON模式',
  `input_price` decimal(10,6) NOT NULL DEFAULT '0.000000' COMMENT '输入token单价（元/千token）',
  `output_price` decimal(10,6) NOT NULL DEFAULT '0.000000' COMMENT '输出token单价（元/千token）',
  `currency` varchar(8) NOT NULL DEFAULT 'CNY' COMMENT '币种：CNY、USD',
  `is_enabled` tinyint(1) NOT NULL DEFAULT '1' COMMENT '是否启用：0-禁用，1-启用',
  `is_production_ready` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否可用于生产环境：0-否，1-是',
  `model_category` varchar(32) DEFAULT NULL COMMENT '模型分类：general、coding、math、reasoning、vision',
  `model_group` varchar(64) DEFAULT NULL COMMENT '模型分组，如：qwen、doubao、deepseek',
  `tags` json DEFAULT NULL COMMENT '模型标签，JSON数组格式',
  `rate_limit_rpm` int DEFAULT NULL COMMENT '每分钟请求数限制',
  `rate_limit_tpm` int DEFAULT NULL COMMENT '每分钟token数限制',
  `max_concurrent_requests` int DEFAULT NULL COMMENT '最大并发请求数',
  `default_temperature` decimal(3,2) DEFAULT '0.70' COMMENT '默认温度参数',
  `default_max_tokens` int DEFAULT '2000' COMMENT '默认最大token数',
  `api_parameters` json DEFAULT NULL COMMENT 'API默认参数，JSON格式',
  `custom_config` json DEFAULT NULL COMMENT '自定义配置，JSON格式',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `created_by` varchar(64) DEFAULT NULL COMMENT '创建人',
  `updated_by` varchar(64) DEFAULT NULL COMMENT '更新人',
  `version` int NOT NULL DEFAULT '1' COMMENT '版本号，用于乐观锁',
  PRIMARY KEY (`id`),
  UNIQUE KEY `model_id` (`model_id`),
  UNIQUE KEY `uk_model_name` (`model_name`),
  KEY `idx_model_id` (`model_id`),
  KEY `idx_provider` (`provider`),
  KEY `idx_enabled_production` (`is_enabled`,`is_production_ready`),
  KEY `idx_model_group` (`model_group`),
  KEY `idx_category` (`model_category`)
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM模型配置表';


-- ai_intent_flow.zb_node_prompt definition

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
  UNIQUE KEY `uk_node_prompt` (`node_id`,`prompt_key`),
  KEY `idx_node_id` (`node_id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点提示词配置表';


-- ai_intent_flow.zb_node_prompt_var definition

CREATE TABLE `zb_node_prompt_var` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `node_id` varchar(64) NOT NULL COMMENT '节点id',
  `prompt_key` varchar(32) NOT NULL COMMENT '提示词的key，关联node_prompt表',
  `prompt_var_name` varchar(32) NOT NULL COMMENT '提示词插值变量名，便于代码进行插值处理',
  `prompt_var_value` varchar(1024) DEFAULT NULL COMMENT '提示词插值变量值（来自 llm_db 版本）',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_prompt_var` (`node_id`,`prompt_key`,`prompt_var_name`),
  KEY `idx_node_prompt` (`node_id`,`prompt_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点提示词变量表';


-- ai_intent_flow.zb_node_prompt_ver_ctrl definition

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
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点提示词配置历史表';