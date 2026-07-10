"""
对话流程节点数据库操作工具类
用于加载和查询 zb_conversation_nodes 表数据
"""
import asyncio
import importlib
import json
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Optional, List, Dict
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger
from ..core.config import settings


@dataclass
class ZbConversationNode:
    """对话流程节点数据类"""
    node_id: str
    node_name: str
    node_type: str
    node_description: Optional[str] = None
    node_func_path: Optional[str] = None
    node_business_range: Optional[str] = None
    status: int = 1
    parent_node_id: Optional[str] = None
    model_id: Optional[str] = None
    model_ext_param: Optional[Any] = None  # JSON类型，可能是dict或str
    # 模型配置信息（通过联表查询获取）
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    model_url: Optional[str] = None
    model_api_key: Optional[str] = None
    model_is_out: Optional[int] = None
    # 大模型实例（加载时初始化）
    llm: Optional[ChatOpenAI] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ZbConversationNode':
        """从字典创建实例，并初始化 llm 实例"""
        node = cls(
            node_id=data.get('node_id', ''),
            node_name=data.get('node_name', ''),
            node_type=data.get('node_type', ''),
            node_description=data.get('node_description'),
            node_func_path=data.get('node_func_path'),
            node_business_range=data.get('node_business_range'),
            status=data.get('status', 1),
            parent_node_id=data.get('parent_node_id'),
            model_id=data.get('model_id'),
            model_ext_param=data.get('model_ext_param'),
            model_provider=data.get('model_provider'),
            model_name=data.get('model_name'),
            model_url=data.get('model_url'),
            model_api_key=data.get('model_api_key'),
            model_is_out=data.get('model_is_out')
        )
        # 初始化 llm 实例
        node._init_llm()
        return node

    def _init_llm(self) -> None:
        """初始化 llm 实例"""
        # 检查必要的配置
        if not self.model_name or not self.model_url:
            return

        try:
            # 解析扩展参数
            ext_params = {}
            if self.model_ext_param:
                try:
                    # JSON类型字段从数据库读取时可能已经是dict，无需再解析
                    if isinstance(self.model_ext_param, dict):
                        ext_params = self.model_ext_param
                    else:
                        ext_params = json.loads(self.model_ext_param)
                    app_logger.info(f"节点 {self.node_id} 的 model_ext_param: {ext_params}")
                except (json.JSONDecodeError, TypeError) as e:
                    app_logger.error(f"节点 {self.node_id} 的 model_ext_param 解析失败: {e}")
                    ext_params = {}

            # 提取 extra_body 参数，其余作为标准参数
            extra_body = ext_params.pop('extra_body', None)

            # 创建ChatOpenAI实例
            self.llm = ChatOpenAI(
                model=self.model_name,
                base_url=self.model_url,
                api_key=self.model_api_key if self.model_api_key else None,
                extra_body=extra_body,
                **ext_params  # 标准参数
            )
            app_logger.info(f"节点 {self.node_id} 的 llm 实例初始化成功")

        except Exception as e:
            app_logger.error(f"初始化节点 {self.node_id} 的 llm 实例失败: {str(e)}\n{traceback.format_exc()}")


class ZbConversationNodesUtil:
    """对话流程节点数据库操作助手"""
    
    @staticmethod
    async def load_all_nodes() -> List[ZbConversationNode]:
        """
        加载所有节点记录（联表查询包含模型信息）

        Returns:
            List[ZbConversationNode]: 所有节点列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT
                            n.node_id, n.node_name, n.node_type, n.node_description,
                            n.node_func_path, n.node_business_range, n.status, n.parent_node_id, n.model_id, n.model_ext_param,
                            m.provider AS model_provider,
                            m.api_model_name AS model_name,
                            m.base_url AS model_url,
                            m.api_key AS model_api_key,
                            (m.provider != 'zbank') AS model_is_out
                        FROM zb_conversation_nodes n
                        LEFT JOIN zb_llm_models m ON n.model_id = m.model_id AND m.is_enabled = 1
                        WHERE n.status = 1
                    """
                    result = AsyncMySQLConnection.all(await session.execute(text(query)))

                    nodes = [ZbConversationNode.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(nodes)} 个节点记录")
            return nodes

        except Exception as e:
            app_logger.error(f"加载节点记录失败: {str(e)}\n{traceback.format_exc()}")
            return []
    
    @staticmethod
    async def load_nodes_by_parent(parent_node_id: str) -> List[ZbConversationNode]:
        """
        根据父节点ID加载子节点列表（联表查询包含模型信息）

        Args:
            parent_node_id: 父节点ID

        Returns:
            List[ZbConversationNode]: 子节点列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT
                            n.node_id, n.node_name, n.node_type, n.node_description,
                            n.node_func_path, n.node_business_range, n.status, n.parent_node_id, n.model_id, n.model_ext_param,
                            m.provider AS model_provider,
                            m.api_model_name AS model_name,
                            m.base_url AS model_url,
                            m.api_key AS model_api_key,
                            (m.provider != 'zbank') AS model_is_out
                        FROM zb_conversation_nodes n
                        LEFT JOIN zb_llm_models m ON n.model_id = m.model_id AND m.is_enabled = 1
                        WHERE n.parent_node_id = :parent_node_id AND n.status = 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"parent_node_id": parent_node_id})
                    )

                    nodes = [ZbConversationNode.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(nodes)} 个子节点记录, parent_node_id={parent_node_id}")
            return nodes

        except Exception as e:
            app_logger.error(f"加载子节点记录失败: {str(e)}")
            return []
    
    @staticmethod
    async def load_node_by_id(node_id: str) -> Optional[ZbConversationNode]:
        """
        根据节点ID加载单个节点（联表查询包含模型信息）

        Args:
            node_id: 节点ID

        Returns:
            ZbConversationNode 或 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT
                            n.node_id, n.node_name, n.node_type, n.node_description,
                            n.node_func_path, n.node_business_range, n.status, n.parent_node_id, n.model_id, n.model_ext_param,
                            m.provider AS model_provider,
                            m.api_model_name AS model_name,
                            m.base_url AS model_url,
                            m.api_key AS model_api_key,
                            (m.provider != 'zbank') AS model_is_out
                        FROM zb_conversation_nodes n
                        LEFT JOIN zb_llm_models m ON n.model_id = m.model_id AND m.is_enabled = 1
                        WHERE n.node_id = :node_id AND n.status = 1
                        LIMIT 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"node_id": node_id})
                    )

                    if result and len(result) > 0:
                        node = ZbConversationNode.from_dict(result[0])
                        app_logger.info(f"成功加载节点: node_id={node_id}")
                        return node

            return None

        except Exception as e:
            app_logger.error(f"加载节点记录失败: {str(e)}")
            return None
    
    @staticmethod
    async def load_nodes_by_type(node_type: str) -> List[ZbConversationNode]:
        """
        根据节点类型加载节点列表（联表查询包含模型信息）

        Args:
            node_type: 节点类型 (intent, agent, tool等)

        Returns:
            List[ZbConversationNode]: 节点列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = """
                        SELECT
                            n.node_id, n.node_name, n.node_type, n.node_description,
                            n.node_func_path, n.node_business_range, n.status, n.parent_node_id, n.model_id, n.model_ext_param,
                            m.provider AS model_provider,
                            m.api_model_name AS model_name,
                            m.base_url AS model_url,
                            m.api_key AS model_api_key,
                            (m.provider != 'zbank') AS model_is_out
                        FROM zb_conversation_nodes n
                        LEFT JOIN zb_llm_models m ON n.model_id = m.model_id AND m.is_enabled = 1
                        WHERE n.node_type = :node_type AND n.status = 1
                    """
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"node_type": node_type})
                    )

                    nodes = [ZbConversationNode.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(nodes)} 个 {node_type} 类型节点记录")
            return nodes

        except Exception as e:
            app_logger.error(f"加载节点记录失败: {str(e)}\n{traceback.format_exc()}")
            return []


class _NodeCacheData:
    """内部缓存数据对象，包含所有节点索引，确保原子性更新"""
    __slots__ = ('nodes', 'node_map', 'children_map')

    def __init__(self):
        self.nodes: List[ZbConversationNode] = []
        self.node_map: Dict[str, ZbConversationNode] = {}
        self.children_map: Dict[str, List[ZbConversationNode]] = {}


class ZbConversationNodeCache:
    """
    对话流程节点缓存类（单例模式）

    使用懒加载模式：每次访问时检查时间戳，超过刷新间隔则重新加载数据
    """

    _instance = None
    _default_refresh_interval = 60  # 类级别默认值（秒）

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化缓存"""
        if self._initialized:
            return
        self._initialized = True

        # 使用 asyncio 锁
        self._lock = asyncio.Lock()

        # 统一的缓存数据对象
        self._cache: _NodeCacheData = _NodeCacheData()

        # 上次刷新时间，初始值设为一天前，确保首次访问时会刷新
        self._last_refresh_time: datetime = datetime.now() - timedelta(days=1)

    @classmethod
    def get_instance(cls) -> 'ZbConversationNodeCache':
        """获取单例实例"""
        return cls()

    @property
    def refresh_interval(self) -> int:
        """获取刷新间隔，优先从settings获取（支持Apollo热更新），失败则使用默认值"""
        interval = getattr(settings, 'AI_INTENT_FLOW_CONVERSATION_CACHE_REFRESH_INTERVAL', self._default_refresh_interval)
        app_logger.debug(f"[ConversationCache] 当前刷新间隔: {interval}s")
        return interval

    async def _check_and_refresh(self) -> None:
        """检查是否需要刷新缓存，如果需要则刷新"""
        now = datetime.now()
        elapsed = (now - self._last_refresh_time).total_seconds()
        interval = self.refresh_interval
        app_logger.debug(f"[ConversationCache] 距上次刷新已过 {elapsed:.1f}s，阈值 {interval}s")
        # 检查是否超过刷新间隔
        if elapsed >= interval:
            app_logger.info(f"[ConversationCache] 触发缓存刷新，距上次 {elapsed:.1f}s >= {interval}s")
            async with self._lock:
                # 双重检查，避免并发刷新
                if (datetime.now() - self._last_refresh_time).total_seconds() >= interval:
                    await self._do_refresh()

    async def _do_refresh(self) -> None:
        """执行刷新缓存数据"""
        try:
            nodes = await ZbConversationNodesUtil.load_all_nodes()

            # 先构建新的缓存对象
            new_cache = _NodeCacheData()
            new_cache.nodes = nodes
            new_cache.node_map = {node.node_id: node for node in nodes}
            for node in nodes:
                parent_id = node.parent_node_id or ""
                if parent_id not in new_cache.children_map:
                    new_cache.children_map[parent_id] = []
                new_cache.children_map[parent_id].append(node)

            # 一次性替换缓存对象（原子操作）
            self._cache = new_cache

            # 更新刷新时间
            self._last_refresh_time = datetime.now()
            app_logger.info(f"ZbConversationNodeCache 缓存已刷新，共 {len(nodes)} 条节点（节点包含 llm 实例）")

        except Exception as e:
            app_logger.error(f"刷新缓存失败: {str(e)}\n{traceback.format_exc()}")

    async def force_refresh(self) -> None:
        """强制刷新缓存"""
        async with self._lock:
            await self._do_refresh()

    async def get_all_nodes(self) -> List[ZbConversationNode]:
        """获取所有节点"""
        await self._check_and_refresh()
        return self._cache.nodes

    async def get_node_by_id(self, node_id: str) -> Optional[ZbConversationNode]:
        """根据 node_id 获取节点"""
        await self._check_and_refresh()
        return self._cache.node_map.get(node_id)

    async def get_children(self, parent_node_id: str) -> List[ZbConversationNode]:
        """根据 parent_node_id 获取子节点列表"""
        await self._check_and_refresh()
        return self._cache.children_map.get(parent_node_id, [])

    async def get_node_list(
        self,
        parent_node_id: str,
        node_type: str = None,
        is_recursive: bool = False
    ) -> List[ZbConversationNode]:
        """
        根据父节点ID获取子节点列表

        Args:
            parent_node_id: 父节点ID
            node_type: 节点类型过滤（可选），如 'tool', 'agent' 等
            is_recursive: 是否递归获取子节点的子节点，默认 False

        Returns:
            List[ZbConversationNode]: 子节点列表
        """
        await self._check_and_refresh()

        if is_recursive:
            # 递归模式：先收集所有子节点
            result = []
            self._collect_children_recursive(parent_node_id, result)
            # 最后统一根据 node_type 过滤
            if node_type:
                return [node for node in result if node.node_type == node_type]
            return result
        else:
            # 非递归模式：直接返回
            children = self._cache.children_map.get(parent_node_id, [])
            if node_type:
                return [node for node in children if node.node_type == node_type]
            return children

    def _collect_children_recursive(
        self,
        parent_node_id: str,
        result: List[ZbConversationNode]
    ) -> None:
        """
        内部方法：递归收集所有子节点（同步操作）

        Args:
            parent_node_id: 父节点ID
            result: 结果列表，直接修改此列表
        """
        children = self._cache.children_map.get(parent_node_id, [])
        for child in children:
            result.append(child)
            # 递归收集子节点的子节点
            self._collect_children_recursive(child.node_id, result)

    async def get_nodes_by_type(self, node_type: str) -> List[ZbConversationNode]:
        """根据节点类型获取节点列表"""
        await self._check_and_refresh()
        return [node for node in self._cache.nodes if node.node_type == node_type]

    async def get_node_desc_str(self, parent_node_id: str) -> str:
        """
        根据 parent_node_id 获取子节点的描述字符串
        
        Returns:
            str: 格式为 "node_id:node_description\n..." 的字符串
        """
        await self._check_and_refresh()
        children = self._cache.children_map.get(parent_node_id, [])
        lines = [f"{node.node_id}:{node.node_description}\n" for node in children if node.node_description]
        return "".join(lines)

    async def get_node_desc_str_by_type(self, node_type: str, parent_node_id: str = None) -> str:
        """
        根据 node_type 和可选的 parent_node_id 获取节点的描述字符串
        
        Args:
            node_type: 节点类型（intent/agent/tool）
            parent_node_id: 父节点ID，如果为None则不限制父节点
            
        Returns:
            str: 格式为 "node_description\n..." 的字符串
        """
        await self._check_and_refresh()
        lines = [
            f"{node.node_description}\n"
            for node in self._cache.nodes
            if node.node_type == node_type and (parent_node_id is None or parent_node_id == node.parent_node_id) and node.node_description
        ]
        return "".join(lines)

    async def instantiate_node(self, node_id: str, *args, **kwargs) -> Optional[Any]:
        """
        根据 node_id 实例化节点
        
        Args:
            node_id: 节点ID
            *args: 传递给节点类构造函数的位置参数
            **kwargs: 传递给节点类构造函数的关键字参数
            
        Returns:
            实例化的节点对象，如果 node_id 不存在或实例化失败则返回 None
        """
        await self._check_and_refresh()
        node = self._cache.node_map.get(node_id)
        
        if node is None:
            app_logger.error(f"节点不存在: {node_id}")
            return None
        
        if not node.node_func_path:
            app_logger.error(f"节点 {node_id} 未配置 node_func_path")
            return None
        
        try:
            # 动态导入模块
            app_logger.info(f"动态导入模块: {node.node_func_path}")
            module_path, class_name = node.node_func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)

            # 获取类并实例化
            cls = getattr(module, class_name)
            instance = cls(*args, **kwargs)

            app_logger.info(f"成功实例化节点: {node_id}")
            return instance

        except Exception as e:
            app_logger.error(f"实例化节点 {node_id} 失败: {str(e)}\n{traceback.format_exc()}")
            return None

    async def get_llm_by_node_id(self, node_id: str) -> Optional[ChatOpenAI]:
        """
        根据节点ID获取大模型实例

        Args:
            node_id: 节点ID

        Returns:
            ChatOpenAI实例，如果不存在则返回None
        """
        await self._check_and_refresh()

        # 获取节点信息
        node = self._cache.node_map.get(node_id)
        if not node:
            app_logger.error(f"节点不存在: {node_id}")
            return None

        # 直接返回节点中的 llm 实例
        return node.llm


# 全局默认缓存实例
_default_cache = ZbConversationNodeCache.get_instance()

"""
from app.db_connection_pool.zb_conversation_nodes_util import _default_cache

# 懒加载模式，首次访问时自动刷新
nodes = await _default_cache.get_all_nodes()
children = await _default_cache.get_children("intent_classification")
node = await _default_cache.get_node_by_id("agent_bangong")
desc = await _default_cache.get_node_desc_str("intent_classification")

# 强制刷新缓存（可选）
await _default_cache.force_refresh()
"""