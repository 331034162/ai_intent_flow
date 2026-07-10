"""导出指定表的数据为 INSERT 脚本"""
import pymysql
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

conn = pymysql.connect(
    host=os.getenv('MYSQL_HOST', '127.0.0.1'),
    port=int(os.getenv('MYSQL_PORT', 3306)),
    user=os.getenv('MYSQL_USER', 'root'),
    password=os.getenv('MYSQL_PASSWORD', ''),
    database=os.getenv('MYSQL_DB', 'ai_intent_flow'),
    charset='utf8mb4'
)

TABLES = [
    'zb_ai_workflow',
    'zb_conversation_nodes',
    'zb_node_prompt',
    'zb_node_prompt_ver_ctrl',
]

output_lines = []
output_lines.append("-- ============================================================================")
output_lines.append("-- AI Intent Flow 数据导出脚本")
output_lines.append(f"-- 导出表：{', '.join(TABLES)}")
output_lines.append("-- ============================================================================")

for table in TABLES:
    output_lines.append("")
    output_lines.append(f"-- ----------------------------------------------------------------------------")
    output_lines.append(f"-- 表：{table}")
    output_lines.append(f"-- ----------------------------------------------------------------------------")

    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM `{table}`")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        output_lines.append(f"-- (空表，无数据)")
        cursor.close()
        continue

    col_str = '`, `'.join(columns)
    for row in rows:
        vals = []
        for val in row:
            if val is None:
                vals.append('NULL')
            elif isinstance(val, (int, float)):
                vals.append(str(val))
            elif isinstance(val, bytes):
                vals.append(f"'{val.decode('utf8', errors='replace').replace(chr(92), chr(92)+chr(92)).replace(chr(39), chr(92)+chr(39))}'")
            elif isinstance(val, str):
                escaped = val.replace(chr(92), chr(92)+chr(92)).replace(chr(39), chr(92)+chr(39))
                vals.append(f"'{escaped}'")
            else:
                escaped = str(val).replace(chr(92), chr(92)+chr(92)).replace(chr(39), chr(92)+chr(39))
                vals.append(f"'{escaped}'")
        output_lines.append(f"INSERT INTO `{table}` (`{col_str}`) VALUES ({', '.join(vals)});")

    cursor.close()

output_lines.append("")

output_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'db_scripts', 'schema_unified.sql')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

conn.close()
print(f"导出完成，共 {sum(1 for l in output_lines if l.startswith('INSERT'))} 条 INSERT 语句")
print(f"写入：{output_path}")
