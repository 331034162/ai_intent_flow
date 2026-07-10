"""
模拟 API /api/node-configs 查询，看实际返回了什么
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from app.db_connection_pool.async_mysql_connection import get_async_pool_instance
from sqlalchemy import text


async def main():
    db_conn = await get_async_pool_instance()
    session = await db_conn.get_session()

    node_where = ["1=1"]
    node_filter_sql = " AND ".join(node_where)
    child_filter_sql = ""
    all_params = {}
    page_size = 100
    offset = 0

    async with session:
        async with session.begin():
            # Step 1: Count
            count_sql = f"""
                SELECT COUNT(DISTINCT v.node_id) AS cnt
                FROM zb_node_prompt_ver_ctrl v
                LEFT JOIN zb_conversation_nodes cn ON cn.node_id = v.node_id
                WHERE {node_filter_sql} {child_filter_sql}
            """
            count_row = (await session.execute(text(count_sql), all_params)).fetchone()
            total = int(count_row[0]) if count_row else 0
            print(f"Step1 - total (DISTINCT node_id count): {total}")

            # Step 2: Get node ID list
            node_id_list_sql = f"""
                SELECT DISTINCT v.node_id
                FROM zb_node_prompt_ver_ctrl v
                LEFT JOIN zb_conversation_nodes cn ON cn.node_id = v.node_id
                WHERE {node_filter_sql} {child_filter_sql}
                ORDER BY v.node_id
                LIMIT {page_size} OFFSET {offset}
            """
            nids = [r[0] for r in (await session.execute(text(node_id_list_sql), all_params)).fetchall()]
            print(f"Step2 - node_ids: {nids} ({len(nids)}个)")

            if not nids:
                print("No nodes found!")
                return

            # Step 3: Get node rows with metadata
            nid_placeholders = ",".join([f":nid{i}" for i in range(len(nids))])
            nid_params = {f"nid{i}": nid for i, nid in enumerate(nids)}
            node_rows = [dict(r._mapping) for r in (await session.execute(
                text(f"""
                    SELECT cn.id, nd.node_id,
                           COALESCE(cn.node_name, nd.node_name) AS node_name,
                           cn.node_type, cn.node_business_range,
                           cn.node_description, cn.status, cn.parent_node_id,
                           cn.model_id, cn.created_at, cn.updated_at
                    FROM (
                        SELECT DISTINCT node_id, node_name
                        FROM zb_node_prompt_ver_ctrl
                        WHERE node_id IN ({nid_placeholders})
                    ) nd
                    LEFT JOIN zb_conversation_nodes cn ON cn.node_id = nd.node_id
                    ORDER BY nd.node_id DESC
                """),
                nid_params
            )).fetchall()]
            print(f"Step3 - node_rows: {len(node_rows)}个")
            for nr in node_rows:
                print(f"  node_id={nr['node_id']}, node_name={nr['node_name']}, node_type={nr['node_type']}")

            # Step 4: Get children
            child_qparams = {f"nid{i}": nid for i, nid in enumerate(nids)}
            child_rows = (await session.execute(
                text(f"""
                    SELECT id, node_id, node_name, prompt_key, prompt_content,
                           model_id, model_ext_param,
                           status, version_no, update_by, created_at, updated_at
                    FROM zb_node_prompt_ver_ctrl
                    WHERE node_id IN ({nid_placeholders})
                    ORDER BY id DESC
                """),
                child_qparams
            )).fetchall()
            print(f"\nStep4 - child_rows: {len(child_rows)}个")
            for cr in child_rows:
                d = dict(cr._mapping)
                print(f"  id={d['id']}, node_id={d['node_id']}, prompt_key={d['prompt_key']}, status={d['status']}")

            # Step 5: Group children by node_id
            children_by_node = {}
            for r in child_rows:
                d = dict(r._mapping)
                nid = d["node_id"]
                children_by_node.setdefault(nid, []).append(d)

            # Step 6: Final result
            result = []
            for nr in node_rows:
                nid = nr["node_id"]
                prompts = children_by_node.get(nid, [])
                result.append({
                    **nr,
                    "_children": prompts,
                    "_child_count": len(prompts),
                })

            print(f"\n=== 最终API返回 ===")
            print(f"data 长度: {len(result)}")
            print(f"total: {total}")
            for item in result:
                print(f"  node_id={item['node_id']}, child_count={item['_child_count']}")
                for ch in item['_children']:
                    print(f"    -> {ch['prompt_key']} (status={ch['status']})")

if __name__ == "__main__":
    asyncio.run(main())
