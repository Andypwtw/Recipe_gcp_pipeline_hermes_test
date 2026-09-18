# V11-T JSON-only 測試架構

V11-T 是 V11 正式版的下游驗證版本，不包含正式資料蒐集與排程基礎設施。

```text
已爬取 JSON
  data/raw/ytower_seq_recipes.json
        ↓
資料清洗 / 去重
        ↓
食材與單位正規化
        ↓
MySQL recipe_ai
        ↓
營養 / 重量 / Matching / 熱量
        ↓
Flask API
        ↓
Hermes API
```

## 明確排除

- Crawler
- Proxy Manager / Proxy Worker
- Kafka
- Redpanda Console
- MongoDB
- Mongo Writer
- Airflow
- PostgreSQL
- GCP Multi-NIC / production deployment pieces
- Web frontend

## Docker services

- `mysql-test`
- `python-test`

## 測試入口

```bash
docker compose --env-file .env up -d --build

docker compose exec python-test \
  uv run python scripts/10_pipeline.py
```

API 預設：`http://localhost:5011`
