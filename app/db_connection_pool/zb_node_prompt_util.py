"""
节点提示词数据库操作工具类
用于加载和查询 node_prompt 表数据
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
class NodePromptVar:
    """节点提示词变量数据类"""
    id: int
    node_id: str
    prompt_key: str
    prompt_var_name: str
    prompt_var_value: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'NodePromptVar':
        """从字典创建实例"""
        return cls(
            id=data.get('id', 0),
            node_id=data.get('node_id', ''),
            prompt_key=data.get('prompt_key', ''),
            prompt_var_name=data.get('prompt_var_name', ''),
            prompt_var_value=data.get('prompt_var_value'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


@dataclass
class NodePrompt:
    """节点提示词数据类"""
    id: int
    node_id: str
    prompt_key: str
    prompt_content: Optional[str] = None
    model_id: Optional[str] = None
    model_ext_param: Optional[Dict] = None
    prompt_var_names: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'NodePrompt':
        """从字典创建实例"""
        # model_ext_param 可能是 JSON 字符串或已解析的 dict
        ext_param = data.get('model_ext_param')
        if isinstance(ext_param, str) and ext_param:
            import json
            try:
                ext_param = json.loads(ext_param)
            except (json.JSONDecodeError, TypeError):
                ext_param = None
        return cls(
            id=data.get('id', 0),
            node_id=data.get('node_id', ''),
            prompt_key=data.get('prompt_key', ''),
            prompt_content=data.get('prompt_content'),
            model_id=data.get('model_id'),
            model_ext_param=ext_param,
            prompt_var_names=data.get('prompt_var_names'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


class NodePromptUtil:
    """节点提示词数据库操作助手"""

    @staticmethod
    async def load_all_prompts() -> List[NodePrompt]:
        """
        加载所有节点提示词记录

        Returns:
            List[NodePrompt]: 所有节点提示词列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_node_prompt"
                    result = AsyncMySQLConnection.all(await session.execute(text(query)))

                    prompts = [NodePrompt.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(prompts)} 条节点提示词记录")
            return prompts

        except Exception as e:
            app_logger.error(f"加载节点提示词记录失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def load_prompt(node_id: str, prompt_key: str) -> Optional[NodePrompt]:
        """
        根据node_id+prompt_key加载单个节点提示词

        Args:
            node_id: 节点ID
            prompt_key: 提示词key

        Returns:
            NodePrompt 或 None
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_node_prompt WHERE node_id = :node_id AND prompt_key = :prompt_key LIMIT 1"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"node_id": node_id, "prompt_key": prompt_key})
                    )

                    if result and len(result) > 0:
                        prompt = NodePrompt.from_dict(result[0])
                        app_logger.info(f"成功加载节点提示词: node_id={node_id}, prompt_key={prompt_key}")
                        return prompt

            return None

        except Exception as e:
            app_logger.error(f"加载节点提示词记录失败: {str(e)}")
            return None

    @staticmethod
    async def load_prompts_by_node_id(node_id: str) -> List[NodePrompt]:
        """
        根据节点ID加载提示词列表

        Args:
            node_id: 节点ID

        Returns:
            List[NodePrompt]: 提示词列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_node_prompt WHERE node_id = :node_id"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"node_id": node_id})
                    )

                    prompts = [NodePrompt.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(prompts)} 条节点提示词记录, node_id={node_id}")
            return prompts

        except Exception as e:
            app_logger.error(f"加载节点提示词记录失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def load_all_prompt_vars() -> List[NodePromptVar]:
        """
        加载所有节点提示词变量记录

        Returns:
            List[NodePromptVar]: 所有节点提示词变量列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_node_prompt_var"
                    result = AsyncMySQLConnection.all(await session.execute(text(query)))

                    prompt_vars = [NodePromptVar.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(prompt_vars)} 条节点提示词变量记录")
            return prompt_vars

        except Exception as e:
            app_logger.error(f"加载节点提示词变量记录失败: {str(e)}\n{traceback.format_exc()}")
            return []

    @staticmethod
    async def load_prompt_vars(node_id: str, prompt_key: str) -> List[NodePromptVar]:
        """
        根据node_id+prompt_key加载提示词变量列表

        Args:
            node_id: 节点ID
            prompt_key: 提示词key

        Returns:
            List[NodePromptVar]: 提示词变量列表
        """
        try:
            db_conn = await get_async_pool_instance()
            session = await db_conn.get_session()

            async with session:
                async with session.begin():
                    query = "SELECT * FROM zb_node_prompt_var WHERE node_id = :node_id AND prompt_key = :prompt_key"
                    result = AsyncMySQLConnection.all(
                        await session.execute(text(query), {"node_id": node_id, "prompt_key": prompt_key})
                    )

                    prompt_vars = [NodePromptVar.from_dict(row) for row in result] if result else []

            app_logger.info(f"成功加载 {len(prompt_vars)} 条提示词变量记录, node_id={node_id}, prompt_key={prompt_key}")
            return prompt_vars

        except Exception as e:
            app_logger.error(f"加载提示词变量记录失败: {str(e)}\n{traceback.format_exc()}")
            return []


class _PromptCacheData:
    """内部缓存数据对象，包含所有索引，确保原子性更新"""
    __slots__ = ('node_prompt_map', 'node_id_map', 'prompt_var_map', 'prompt_var_value_map')

    def __init__(self):
        # key: node_id+prompt_key, value: NodePrompt
        self.node_prompt_map: Dict[str, NodePrompt] = {}
        # key: node_id, value: List[NodePrompt]
        self.node_id_map: Dict[str, List[NodePrompt]] = {}
        # key: node_id+prompt_key, value: List[str] (prompt_var_name列表)
        self.prompt_var_map: Dict[str, List[str]] = {}
        # key: node_id+prompt_key, value: Dict[str, str] (prompt_var_name -> prompt_var_value)
        self.prompt_var_value_map: Dict[str, Dict[str, str]] = {}


class NodePromptCache:
    """
    节点提示词缓存类（单例模式）

    使用懒加载模式：每次访问时检查时间戳，超过刷新间隔则重新加载数据
    缓存索引：
      - node_prompt_map: key=node_id+prompt_key, value=NodePrompt
      - node_id_map: key=node_id, value=List[NodePrompt]
      - prompt_var_map: key=node_id+prompt_key, value=List[str] (prompt_var_name列表)
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
        self._cache: _PromptCacheData = _PromptCacheData()

        # 上次刷新时间，初始值设为一天前，确保首次访问时会刷新
        self._last_refresh_time: datetime = datetime.now() - timedelta(days=1)

    @classmethod
    def get_instance(cls) -> 'NodePromptCache':
        """获取单例实例"""
        return cls()

    @property
    def refresh_interval(self) -> int:
        """获取刷新间隔，优先从settings获取（支持Apollo热更新），失败则使用默认值"""
        interval = getattr(settings, 'AI_INTENT_FLOW_NODE_PROMPT_CACHE_REFRESH_INTERVAL', self._default_refresh_interval)
        app_logger.debug(f"[NodePromptCache] 当前刷新间隔: {interval}s")
        return interval

    async def _check_and_refresh(self) -> None:
        """检查是否需要刷新缓存，如果需要则刷新"""
        now = datetime.now()
        elapsed = (now - self._last_refresh_time).total_seconds()
        interval = self.refresh_interval
        app_logger.debug(f"[NodePromptCache] 距上次刷新已过 {elapsed:.1f}s，阈值 {interval}s")
        # 检查是否超过刷新间隔
        if elapsed >= interval:
            app_logger.info(f"[NodePromptCache] 触发缓存刷新，距上次 {elapsed:.1f}s >= {interval}s")
            async with self._lock:
                # 双重检查，避免并发刷新
                if (datetime.now() - self._last_refresh_time).total_seconds() >= interval:
                    await self._do_refresh()

    async def _do_refresh(self) -> None:
        """执行刷新缓存数据"""
        try:
            prompts = await NodePromptUtil.load_all_prompts()
            prompt_vars = await NodePromptUtil.load_all_prompt_vars()

            # 构建 node_id+prompt_key -> prompt_var_name 列表的映射
            prompt_var_map: Dict[str, List[str]] = {}
            # 构建 node_id+prompt_key -> {prompt_var_name: prompt_var_value} 的映射
            prompt_var_value_map: Dict[str, Dict[str, str]] = {}
            for pv in prompt_vars:
                key = f"{pv.node_id}+{pv.prompt_key}"
                if key not in prompt_var_map:
                    prompt_var_map[key] = []
                prompt_var_map[key].append(pv.prompt_var_name)
                # 只有 prompt_var_value 不为空时才加入值映射
                if pv.prompt_var_value is not None and pv.prompt_var_value != '':
                    if key not in prompt_var_value_map:
                        prompt_var_value_map[key] = {}
                    prompt_var_value_map[key][pv.prompt_var_name] = pv.prompt_var_value

            # 将 prompt_var_names 关联到 NodePrompt
            for prompt in prompts:
                key = f"{prompt.node_id}+{prompt.prompt_key}"
                prompt.prompt_var_names = prompt_var_map.get(key, [])

            # 先构建新的缓存对象
            new_cache = _PromptCacheData()
            # key: node_id+prompt_key
            new_cache.node_prompt_map = {
                f"{prompt.node_id}+{prompt.prompt_key}": prompt for prompt in prompts
            }
            # key: node_id
            for prompt in prompts:
                if prompt.node_id not in new_cache.node_id_map:
                    new_cache.node_id_map[prompt.node_id] = []
                new_cache.node_id_map[prompt.node_id].append(prompt)
            # key: node_id+prompt_key, value: prompt_var_name列表
            new_cache.prompt_var_map = prompt_var_map
            # key: node_id+prompt_key, value: {prompt_var_name -> prompt_var_value}
            new_cache.prompt_var_value_map = prompt_var_value_map

            # 一次性替换缓存对象（原子操作）
            self._cache = new_cache

            # 更新刷新时间
            self._last_refresh_time = datetime.now()
            app_logger.info(f"NodePromptCache 缓存已刷新，共 {len(prompts)} 条提示词记录，{len(prompt_vars)} 条变量记录")

        except Exception as e:
            app_logger.error(f"刷新缓存失败: {str(e)}\n{traceback.format_exc()}")

    async def force_refresh(self) -> None:
        """强制刷新缓存"""
        async with self._lock:
            await self._do_refresh()

    async def get_all_prompts(self) -> List[NodePrompt]:
        """获取所有节点提示词"""
        await self._check_and_refresh()
        return list(self._cache.node_prompt_map.values())

    async def get_prompt(self, node_id: str, prompt_key: str) -> Optional[NodePrompt]:
        """
        根据 node_id + prompt_key 获取提示词

        Args:
            node_id: 节点ID
            prompt_key: 提示词key

        Returns:
            NodePrompt 或 None
        """
        await self._check_and_refresh()
        return self._cache.node_prompt_map.get(f"{node_id}+{prompt_key}")

    async def get_prompts_by_node_id(self, node_id: str) -> List[NodePrompt]:
        """
        根据 node_id 获取提示词列表

        Args:
            node_id: 节点ID

        Returns:
            List[NodePrompt]: 提示词列表
        """
        await self._check_and_refresh()
        return self._cache.node_id_map.get(node_id, [])

    async def get_prompt_var_names(self, node_id: str, prompt_key: str) -> List[str]:
        """
        根据 node_id + prompt_key 获取提示词变量名列表

        Args:
            node_id: 节点ID
            prompt_key: 提示词key

        Returns:
            List[str]: prompt_var_name列表
        """
        await self._check_and_refresh()
        return self._cache.prompt_var_map.get(f"{node_id}+{prompt_key}", [])

    async def format_prompt(self, node_id: str, prompt_key: str, var_values: Dict[str, str]) -> Optional[str]:
        """
        根据node_id+prompt_key获取提示词模板，并使用变量值进行插值生成最终提示词

        取值优先级：zb_node_prompt_var 表的 prompt_var_value > 参数 var_values

        Args:
            node_id: 节点ID
            prompt_key: 提示词key
            var_values: 变量值字典，key为prompt_var_name，value为对应的值（作为兜底）

        Returns:
            str: 插值后的提示词内容，未找到时返回None
        """
        prompt = await self.get_prompt(node_id, prompt_key)
        if not prompt or not prompt.prompt_content:
            app_logger.warning(f"未找到提示词: node_id={node_id}, prompt_key={prompt_key}")
            return None

        # 1. 以 var_values 为基础（调用方传入的动态值）
        merged_values = dict(var_values) if var_values else {}

        # 2. 用数据库表中的 prompt_var_value 覆盖（数据库优先）
        cache_key = f"{node_id}+{prompt_key}"
        db_values = self._cache.prompt_var_value_map.get(cache_key, {})
        if db_values:
            app_logger.debug(
                f"[format_prompt] 从数据库加载变量值: node_id={node_id}, "
                f"prompt_key={prompt_key}, vars={list(db_values.keys())}"
            )
            merged_values.update(db_values)

        try:
            return prompt.prompt_content.format(**merged_values)
        except KeyError as e:
            app_logger.error(
                f"提示词插值失败，缺少变量: {e}, node_id={node_id}, prompt_key={prompt_key}, "
                f"可用变量: {list(merged_values.keys())}"
            )
            return None


# 全局默认缓存实例
_default_cache = NodePromptCache.get_instance()

"""
from app.db_connection_pool.zb_node_prompt_util import _default_cache

# 懒加载模式，首次访问时自动刷新
prompts = await _default_cache.get_all_prompts()
prompt = await _default_cache.get_prompt("node_001", "system_prompt")
prompts_by_node = await _default_cache.get_prompts_by_node_id("node_001")
# 获取提示词变量名列表
var_names = await _default_cache.get_prompt_var_names("node_001", "system_prompt")
# 或者直接从NodePrompt对象获取
prompt = await _default_cache.get_prompt("node_001", "system_prompt")
if prompt:
    var_names = prompt.prompt_var_names  # List[str]

# 使用插值生成提示词
# 假设 prompt_content = "你好，{user_name}，欢迎使用{service}"
result = await _default_cache.format_prompt("node_001", "system_prompt", {"user_name": "张三", "service": "智能客服"})
# result = "你好，张三，欢迎使用智能客服"

# 强制刷新缓存（可选）
await _default_cache.force_refresh()
"""