"""
AI工作流数据库操作工具类
用于加载和查询 zb_ai_workflow 表数据
"""
import asyncio
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List, Dict
from sqlalchemy import text
from .async_mysql_connection import get_async_pool_instance, AsyncMySQLConnection
from ..core.logger import app_logger
from ..core.config import settings


@dataclass
class ZbAiWorkflow:
    """AI工作流数据类"""
    id: int
    workflow_id: str
    workflow_desc: str
    entry_node_id: str
    app_id: str
    intent_classify_node_id: Optional[str] = None
    enhance_intent_classify: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ZbAiWorkflow':
        """从字典创建实例"""
        return cls(
            id=data.get('id', 0),
            workflow_id=data.get('workflow_id', ''),
            workflow_desc=data.get('workflow_desc', ''),
            entry_node_id=data.get('entry_node_id', ''),
            app_id=data.get('app_id', ''),
            intent_classify_node_id=data.get('intent_classify_node_id'),
            enhance_intent_classify=data.get('enhance_intent_classify', 0),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


class ZbAiWorkflowUtil:
    """AI工作流数据库操作助手"""
    
    @staticmethod
    async def load_all_workflows() -> List[ZbAiWorkflow]:
        """
        加载所有工作流记录
        
        Returns:
            List[ZbAiWorkflow]: 所有工作流列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_ai_workflow WHERE status = 1"
                    result = AsyncMySQLConnection.all(await session.execute(text(query)))
                    
                    workflows = [ZbAiWorkflow.from_dict(row) for row in result] if result else []
                
            app_logger.info(f"成功加载 {len(workflows)} 个工作流记录")
            return workflows
            
        except Exception as e:
            app_logger.error(f"加载工作流记录失败: {str(e)}\n{traceback.format_exc()}")
            return []
    
    @staticmethod
    async def load_workflow_by_id(workflow_id: str) -> Optional[ZbAiWorkflow]:
        """
        根据workflow_id加载单个工作流
        
        Args:
            workflow_id: 工作流ID
            
        Returns:
            ZbAiWorkflow 或 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_ai_workflow WHERE workflow_id = :workflow_id AND status = 1 LIMIT 1"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"workflow_id": workflow_id})
                    )
                    
                    if result and len(result) > 0:
                        workflow = ZbAiWorkflow.from_dict(result[0])
                        app_logger.info(f"成功加载工作流: workflow_id={workflow_id}")
                        return workflow
                        
            return None
            
        except Exception as e:
            app_logger.error(f"加载工作流记录失败: {str(e)}")
            return None
    
    @staticmethod
    async def load_workflow_by_app_id(app_id: str) -> Optional[ZbAiWorkflow]:
        """
        根据应用ID加载工作流
        
        Args:
            app_id: 应用ID
            
        Returns:
            ZbAiWorkflow 或 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_ai_workflow WHERE app_id = :app_id AND status = 1 LIMIT 1"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"app_id": app_id})
                    )
                    
                    if result and len(result) > 0:
                        workflow = ZbAiWorkflow.from_dict(result[0])
                        app_logger.info(f"成功加载工作流: app_id={app_id}")
                        return workflow
                        
            return None
            
        except Exception as e:
            app_logger.error(f"加载工作流记录失败: {str(e)}")
            return None
    
    @staticmethod
    async def load_workflows_by_entry_node(entry_node_id: str) -> List[ZbAiWorkflow]:
        """
        根据入口节点加载工作流列表
        
        Args:
            entry_node_id: 入口节点ID
            
        Returns:
            List[ZbAiWorkflow]: 工作流列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()
            
            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_ai_workflow WHERE entry_node_id = :entry_node_id AND status = 1"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"entry_node_id": entry_node_id})
                    )
                    
                    workflows = [ZbAiWorkflow.from_dict(row) for row in result] if result else []
                
            app_logger.info(f"成功加载 {len(workflows)} 个工作流记录, entry_node_id={entry_node_id}")
            return workflows
            
        except Exception as e:
            app_logger.error(f"加载工作流记录失败: {str(e)}\n{traceback.format_exc()}")
            return []


class _WorkflowCacheData:
    """内部缓存数据对象，包含所有索引，确保原子性更新"""
    __slots__ = ('workflow_map', 'app_id_map', 'entry_node_id_map')

    def __init__(self):
        self.workflow_map: Dict[str, ZbAiWorkflow] = {}
        self.app_id_map: Dict[str, ZbAiWorkflow] = {}
        self.entry_node_id_map: Dict[str, List[ZbAiWorkflow]] = {}


class ZbAiWorkflowCache:
    """
    AI工作流缓存类（单例模式）

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
        self._cache: _WorkflowCacheData = _WorkflowCacheData()

        # 上次刷新时间，初始值设为一天前，确保首次访问时会刷新
        self._last_refresh_time: datetime = datetime.now() - timedelta(days=1)

    @classmethod
    def get_instance(cls) -> 'ZbAiWorkflowCache':
        """获取单例实例"""
        return cls()

    @property
    def refresh_interval(self) -> int:
        """获取刷新间隔，优先从settings获取（支持Apollo热更新），失败则使用默认值"""
        interval = getattr(settings, 'AI_INTENT_FLOW_WORKFLOW_CACHE_REFRESH_INTERVAL', self._default_refresh_interval)
        app_logger.debug(f"[WorkflowCache] 当前刷新间隔: {interval}s")
        return interval

    async def _check_and_refresh(self) -> None:
        """检查是否需要刷新缓存，如果需要则刷新"""
        now = datetime.now()
        elapsed = (now - self._last_refresh_time).total_seconds()
        interval = self.refresh_interval
        app_logger.debug(f"[WorkflowCache] 距上次刷新已过 {elapsed:.1f}s，阈值 {interval}s")
        # 检查是否超过刷新间隔
        if elapsed >= interval:
            app_logger.info(f"[WorkflowCache] 触发缓存刷新，距上次 {elapsed:.1f}s >= {interval}s")
            async with self._lock:
                # 双重检查，避免并发刷新
                if (datetime.now() - self._last_refresh_time).total_seconds() >= interval:
                    await self._do_refresh()

    async def _do_refresh(self) -> None:
        """执行刷新缓存数据"""
        try:
            workflows = await ZbAiWorkflowUtil.load_all_workflows()

            # 先构建新的缓存对象
            new_cache = _WorkflowCacheData()
            new_cache.workflow_map = {workflow.workflow_id: workflow for workflow in workflows}
            new_cache.app_id_map = {workflow.app_id: workflow for workflow in workflows}
            for workflow in workflows:
                entry_node_id = workflow.entry_node_id
                if entry_node_id not in new_cache.entry_node_id_map:
                    new_cache.entry_node_id_map[entry_node_id] = []
                new_cache.entry_node_id_map[entry_node_id].append(workflow)

            # 一次性替换缓存对象（原子操作）
            self._cache = new_cache

            # 更新刷新时间
            self._last_refresh_time = datetime.now()
            app_logger.info(f"ZbAiWorkflowCache 缓存已刷新，共 {len(workflows)} 条记录")

        except Exception as e:
            app_logger.error(f"刷新缓存失败: {str(e)}\n{traceback.format_exc()}")

    async def force_refresh(self) -> None:
        """强制刷新缓存"""
        async with self._lock:
            await self._do_refresh()

    async def get_all_workflows(self) -> List[ZbAiWorkflow]:
        """获取所有工作流"""
        await self._check_and_refresh()
        return list(self._cache.workflow_map.values())

    async def get_workflow_by_id(self, workflow_id: str) -> Optional[ZbAiWorkflow]:
        """根据 workflow_id 获取工作流"""
        await self._check_and_refresh()
        return self._cache.workflow_map.get(workflow_id)

    async def get_workflow_by_app_id(self, app_id: str) -> Optional[ZbAiWorkflow]:
        """根据 app_id 获取工作流"""
        await self._check_and_refresh()
        return self._cache.app_id_map.get(app_id)

    async def get_workflows_by_entry_node_id(self, entry_node_id: str) -> List[ZbAiWorkflow]:
        """根据 entry_node_id 获取工作流列表"""
        await self._check_and_refresh()
        return self._cache.entry_node_id_map.get(entry_node_id, [])


# 全局默认缓存实例
_default_cache = ZbAiWorkflowCache.get_instance()

"""
from app.db_connection_pool.zb_ai_workflow_util import _default_cache

# 懒加载模式，首次访问时自动刷新
workflows = await _default_cache.get_all_workflows()
workflow = await _default_cache.get_workflow_by_id("workflow_001")
workflow_by_app = await _default_cache.get_workflow_by_app_id("app_001")
workflows_by_entry = await _default_cache.get_workflows_by_entry_node_id("intent_classification")

# 强制刷新缓存（可选）
await _default_cache.force_refresh()
"""