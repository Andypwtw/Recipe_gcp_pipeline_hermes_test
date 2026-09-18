# Recipe Collections V11-T-2

V11-T-2 是 **V11 正式版的第二個測試版本**，用來驗證新增「每 100g 價格 → 食譜預估價格 → API / Hermes 顯示」功能。

本版本只供測試，不取代 V11，也不列入正式版版本演進。

## 測試架構

```text
已爬取 JSON
↓
資料清洗 / 正規化
↓
MySQL
↓
營養 / 重量 / Matching
↓
熱量 + 預估價格
↓
Flask API
↓
Hermes API
```

## 不包含

Crawler、Proxy、Kafka、Redpanda、MongoDB、Mongo Writer、Airflow、PostgreSQL、GCP production networking、Web frontend。

## 價格資料來源

`data/reference/food_nutrition_2025.xlsx`

新增欄位：

```text
每100g的價格
```

單位定義：**新台幣 / 100g**。

匯入後寫入：

```text
nutrition_source.price_per_100g
```

食譜價格公式：

```text
食材預估價格 = weight_g × price_per_100g ÷ 100
```

最後寫入：

```text
recipe_nutrition_summary.estimated_price
recipe_nutrition_summary.price_coverage_percent
recipe_nutrition_summary.price_status
```

`price_status`：

- `CALCULATED`：價格覆蓋率 100%
- `PARTIAL`：價格覆蓋率 >= 60% 且 < 100%
- `INSUFFICIENT`：價格覆蓋率 < 60% 或無可計算價格

## 第一次啟動

V11-T-2 提供測試專用非空預設密碼，所以即使沒有 `.env` 也可以啟動：

```bash
docker compose up -d --build
```

建議仍使用：

```bash
cp .env.example .env
docker compose up -d --build
```

如果之前同名測試 MySQL Volume 已用舊 Schema 建立，請先清除測試 Volume：

```bash
docker compose down -v
docker compose up -d --build
```

## 執行完整測試 Pipeline

```bash
docker compose exec python-test \
  uv run python scripts/10_pipeline.py
```

## API

Health：

```bash
curl http://localhost:5001/health
```

食譜詳細資料：

```bash
curl http://localhost:5001/api/v1/recipes/<SEQ>
```

價格功能加入後，API 可包含：

```json
{
  "energy_kcal": 520,
  "estimated_price": 135.50,
  "calorie_coverage_percent": 95.0,
  "price_coverage_percent": 80.0,
  "calorie_status": "CALCULATED",
  "price_status": "PARTIAL"
}
```

## 預設連線

- Flask API：`localhost:5001`
- MySQL Host：`127.0.0.1:3318`
- Docker 內 MySQL：`mysql-test:3306`

## 原始食譜測試資料

`data/raw/ytower_seq_recipes.json`
