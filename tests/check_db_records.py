"""
查询 zb_node_prompt、zb_node_prompt_ver_ctrl、zb_conversation_nodes 三张表的实际数据
"""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import text

# 加载项目根目录 .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# 动态创建异步引擎
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "ai_intent_flow")

DATABASE_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # 1. zb_node_prompt（生效表）
            print("=" * 80)
            print("1. zb_node_prompt（生效表）")
            print("=" * 80)
            rows = (await session.execute(
                text("SELECT id, node_id, prompt_key, model_id FROM zb_node_prompt ORDER BY id")
            )).fetchall()
            print(f"总记录数: {len(rows)}")
            for r in rows:
                d = dict(r._mapping)
                print(f"  id={d['id']}, node_id={d['node_id']}, prompt_key={d['prompt_key']}, model_id={d['model_id']}")

            # 2. zb_node_prompt_ver_ctrl（版本控制表）
            print()
            print("=" * 80)
            print("2. zb_node_prompt_ver_ctrl（版本控制表）")
            print("=" * 80)
            rows = (await session.execute(
                text("SELECT id, node_id, node_name, prompt_key, status, version_no, update_by FROM zb_node_prompt_ver_ctrl ORDER BY id")
            )).fetchall()
            print(f"总记录数: {len(rows)}")
            for r in rows:
                d = dict(r._mapping)
                print(f"  id={d['id']}, node_id={d['node_id']}, node_name={d['node_name']}, prompt_key={d['prompt_key']}, status={d['status']}, version_no={d['version_no']}, update_by={d['update_by']}")

            # 3. zb_conversation_nodes（会话节点表）
            print()
            print("=" * 80)
            print("3. zb_conversation_nodes（会话节点表）")
            print("=" * 80)
            rows = (await session.execute(
                text("SELECT id, node_id, node_name, node_type, status FROM zb_conversation_nodes ORDER BY id")
            )).fetchall()
            print(f"总记录数: {len(rows)}")
            for r in rows:
                d = dict(r._mapping)
                print(f"  id={d['id']}, node_id={d['node_id']}, node_name={d['node_name']}, node_type={d['node_type']}, status={d['status']}")

            # 4. 对比分析
            print()
            print("=" * 80)
            print("4. 对比分析")
            print("=" * 80)

            # zb_node_prompt 中有但 zb_node_prompt_ver_ctrl 中没有的
            np_rows = (await session.execute(
                text("SELECT node_id, prompt_key FROM zb_node_prompt")
            )).fetchall()
            vc_rows = (await session.execute(
                text("SELECT node_id, prompt_key FROM zb_node_prompt_ver_ctrl")
            )).fetchall()

            np_set = {(r[0], r[1]) for r in np_rows}
            vc_set = {(r[0], r[1]) for r in vc_rows}

            missing_in_vc = np_set - vc_set
            extra_in_vc = vc_set - np_set

            if missing_in_vc:
                print(f"\nzb_node_prompt 有但 zb_node_prompt_ver_ctrl 没有的记录 ({len(missing_in_vc)} 条):")
                for node_id, prompt_key in missing_in_vc:
                    print(f"  node_id={node_id}, prompt_key={prompt_key}")
            else:
                print("\n版本表包含生效表的全部记录")

            if extra_in_vc:
                print(f"\nzb_node_prompt_ver_ctrl 有但 zb_node_prompt 没有的记录 ({len(extra_in_vc)} 条):")
                for node_id, prompt_key in extra_in_vc:
                    print(f"  node_id={node_id}, prompt_key={prompt_key}")
            else:
                print("生效表包含版本表的全部记录")

            # 5. 模拟当前 API 的查询逻辑（不加任何过滤条件）
            print()
            print("=" * 80)
            print("5. 模拟 API /api/node-configs 查询（无过滤条件，page_size=100）")
            print("=" * 80)
            rows = (await session.execute(
                text("""
                    SELECT DISTINCT v.node_id
                    FROM zb_node_prompt_ver_ctrl v
                    LEFT JOIN zb_conversation_nodes cn ON cn.node_id = v.node_id
                    ORDER BY v.node_id
                """)
            )).fetchall()
            nids = [r[0] for r in rows]
            print(f"从 zb_node_prompt_ver_ctrl 查到的 DISTINCT node_id ({len(nids)} 个):")
            for nid in nids:
                print(f"  {nid}")

            if nids:
                nid_placeholders = ",".join([f":nid{i}" for i in range(len(nids))])
                nid_params = {f"nid{i}": nid for i, nid in enumerate(nids)}
                node_rows = (await session.execute(
                    text(f"""
                        SELECT nd.node_id, COALESCE(cn.node_name, nd.node_name) AS node_name
                        FROM (
                            SELECT DISTINCT node_id, node_name
                            FROM zb_node_prompt_ver_ctrl
                            WHERE node_id IN ({nid_placeholders})
                        ) nd
                        LEFT JOIN zb_conversation_nodes cn ON cn.node_id = nd.node_id
                        ORDER BY nd.node_id DESC
                    """),
                    nid_params
                )).fetchall()
                print(f"\n最终返回的节点行 ({len(node_rows)} 个):")
                for r in node_rows:
                    d = dict(r._mapping)
                    print(f"  node_id={d['node_id']}, node_name={d['node_name']}")

    await engine.dispose()
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
