from pathlib import Path
from app.db import get_connection

raw_json = Path('/workspace/data/raw/ytower_seq_recipes.json')
print('raw_json_exists:', raw_json.exists())
print('raw_json:', raw_json)

conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute('SELECT 1 AS ok')
        print('mysql:', cur.fetchone())
finally:
    conn.close()
