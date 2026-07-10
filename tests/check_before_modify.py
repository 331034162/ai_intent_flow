"""检查 zb_node_prompt_ver_ctrl 中哪些记录有 prompt_content_before_modify"""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def main():
    db_url = f"mysql+aiomysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}@{os.getenv('MYSQL_HOST')}:{os.getenv('MYSQL_PORT')}/{os.getenv('MYSQL_DB')}?charset=utf8mb4"
    engine = create_async_engine(db_url, echo=False)
    Sess = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Sess() as sess:
        async with sess.begin():
            rows = (await sess.execute(
                text("SELECT id, node_id, prompt_key, status, version_no, CASE WHEN prompt_content_before_modify IS NULL THEN 'NULL' ELSE CONCAT('有内容(', CHAR_LENGTH(prompt_content_before_modify), '字符)') END AS has_before FROM zb_node_prompt_ver_ctrl ORDER BY id")
            )).fetchall()
            print(f"总记录数: {len(rows)}")
            for r in rows:
                d = dict(r._mapping)
                print(f"  id={d['id']}, node_id={d['node_id']}, prompt_key={d['prompt_key']}, status={d['status']}, v{d['version_no']}, before_modify={d['has_before']}")
    await engine.dispose()

asyncio.run(main())
