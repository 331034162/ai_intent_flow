import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from ..core.logger import app_logger as logger
from sqlalchemy.engine.cursor import CursorResult
from ..core.config import settings

class AsyncMySQLConnection:
    def __init__(self, host='localhost', port=3306, user='root', password='123444', db='llm_db'):
        self.connection_string = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{db}"
        self.engine = None
        self.AsyncSessionFactory = None

    async def init_pool(self):
        """初始化连接池"""
        try:
            # 创建异步引擎，配置连接池参数
            self.engine = create_async_engine(
                self.connection_string,
                pool_pre_ping=True,  # 连接前验证连接有效性
                pool_recycle=settings.MYSQL_POOL_RECYCLE,   # 连接回收时间（秒）
                pool_timeout=settings.MYSQL_POOL_TIMEOUT,     # 获取连接的超时时间
                pool_size=settings.MYSQL_POOL_SIZE,   # 连接池大小
                max_overflow=settings.MYSQL_MAX_OVERFLOW,  # 超出pool_size后最多可创建的连接数
                echo=False            # 启用SQL日志输出
            )
            # 创建异步会话工厂
            self.AsyncSessionFactory = sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,  # 提交后对象不过期，可直接使用
                autoflush=False,  # 不自动flush，性能更好
                autocommit=False
            )
            logger.info(f"数据库连接池初始化成功，最小连接数: {settings.MYSQL_POOL_SIZE}, 最大连接数: {settings.MYSQL_POOL_SIZE+settings.MYSQL_MAX_OVERFLOW}")
        except Exception as e:
            logger.error(f"数据库连接池初始化失败: {e}")
            raise
    
    async def get_session(self):
        """获取一个数据库会话"""
        return self.AsyncSessionFactory()
    
    @staticmethod
    def one(result: CursorResult) -> dict | None:
        """获取单条记录"""
        rows = result.fetchall()
        if rows:
            return [dict(row._mapping) for row in rows][0]
        return None
    
    @staticmethod
    def all(result: CursorResult) -> list:
        """获取所有记录"""
        rows = result.fetchall()
        if rows:
            return [dict(row._mapping) for row in rows]
        return []


# 全局连接池实例
_global_db_instance = None
# 添加一个全局锁用于确保线程安全的初始化
_init_lock = asyncio.Lock()

async def get_async_pool_instance():
    """获取数据库连接池实例 - 单例模式"""
    global _global_db_instance
    # 使用锁确保只有一个协程可以初始化实例
    if _global_db_instance is None:
        async with _init_lock:
            if _global_db_instance is None:
                _global_db_instance = AsyncMySQLConnection(
                    host=settings.MYSQL_HOST,
                    port=settings.MYSQL_PORT,
                    user=settings.MYSQL_USER,
                    password=settings.MYSQL_PASSWORD,
                    db=settings.MYSQL_DB
                )
                # 初始化连接池
                await _global_db_instance.init_pool()
    return _global_db_instance