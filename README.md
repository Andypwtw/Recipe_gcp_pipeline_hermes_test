# Recipe Collections V11

V11 是正式整合版：以 permission-safe Docker / crawler / proxy 架構為主，整合 V10 的正規化、MySQL ER Model、營養計算、Flask API 與 Hermes API。

## 正式資料流

```text
Airflow
  -> crawler_jobs (5 partitions)
  -> crawler-direct + 4 proxy workers
  -> ytower_recipe_results
  -> mongo-writer
  -> MongoDB recipe_ai.raw_recipes
  -> ETL 01~09 / 10_pipeline.py
  -> MySQL recipe_ai
  -> Flask API / Hermes
```

## V11 核心變更

- 單一 `crawler_jobs` Topic，5 partitions / 同一 crawler consumer group。
- 1 個 Direct Worker + 4 個動態 TW Proxy Workers。
- Result Topic 統一為 `ytower_recipe_results`。
- Mongo Writer 寫入 `recipe_ai.raw_recipes`，以 `SEQ` idempotent upsert。
- Docker runtime data 改用 named volumes，不再 chown Git source tree。
- MySQL / MongoDB application service 使用 application user，不使用 root。
- Airflow 拆為 init / webserver / scheduler，DAG 串完整 crawler -> MongoDB -> ETL -> MySQL。
- 修正 Direct Worker job failure offset 風險。
- `published_date` 正式匯入 MySQL。
- 食材 canonical name 移除尾端「約」。
- Direct crawler 補 Browser headers。
- `MAX_POLL_INTERVAL_MS` 預設提高為 16 小時。
- `HERMES_API_KEY` 設定後會實際驗證，原 `{items:[...]}` response 契約保持不變。
- 網頁端不包含在本專案；網頁由另一位組員透過 Flask API 獨立開發。

## 啟動

```bash
bash scripts/bootstrap-env.sh
bash scripts/first-start.sh
```

或自行：

```bash
cp .env.example .env
# 修改所有 CHANGE_ME_* secrets
docker compose --env-file .env up -d --build
```

## Docker 內部連線

- MySQL: `mysql:3306`
- MongoDB: `mongodb:27017`
- Kafka: `kafka:9092`
- PostgreSQL: `postgres:5432`

Host 預設：MySQL 3307、MongoDB 27018、Kafka 9094、Airflow 8080、Flask 5001。

## API

V10 已正式加入的 API 在 V11 全部保留：

- `GET /health`
- `GET /api/v1/recipes`
- `GET /api/v1/recipes/search`
- `GET /api/v1/recipes/random`
- `GET /api/v1/recipes/{seq}`
- `GET /api/v1/categories`
- `POST /api/v1/categories/resolve`
- `POST /api/v1/recommend`
- `POST /api/v1/hermes/recommend`

## 文件

- `docs/V11_ARCHITECTURE.md`
- `docs/V11_INTEGRATION_FIXES.md`
- `docs/V11_FORMAL_VALIDATION.json`
- `docs/er_model.dbml`

舊 V9 Multi-NIC / V10 crawler 元件已移入 `legacy/`，不再由 active compose 使用。

## Normalization / Nutrition Coverage Integration

此整合版以原本 GCP production stack 為主，保留 Airflow、Kafka、MongoDB、Crawler、Proxy、Redpanda、MySQL 與 Flask/Hermes 架構，並整合最新正規化與熱量/價格 coverage 修正。

主要新增：

- 高信心 `qualitative_amount_rules`（confidence >= 80）匯入與重量估算。
- `適量` 不再無依據固定換算克數。
- A-I / 甲乙 / 數字材料群組前綴正規化。
- `A1醬`、`8吋戚風蛋糕` 等數字型食材名稱解析修正。
- `ingredient + count unit` 明確克數資料導出 `ingredient_unit_weights`。
- Nutrition matching：exact / common-name / normalized variant / curated safe target / guarded fuzzy。
- 熱量與價格改為重量型 coverage，並保留已知重量食材列比例 guard。
- 新增 `recipe_nutrition_summary.weight_coverage_percent`。
- Hermes `text` / legacy `message` 相容，以及 ingredient-intent 推薦修正。

Production pipeline 仍使用 MongoDB：

```text
MongoDB raw_recipes
  -> 01_profile_mongodb.py
  -> 02_clean_recipes.py
  -> 03a_build_unit_weight_map.py
  -> 03_normalize_recipes.py
  -> 04_import_recipes_mysql.py
  -> 04c_build_recipe_categories.py
  -> 04a_import_reference_maps.py
  -> 04b_apply_weight_estimates.py
  -> 05_import_nutrition_excel.py
  -> 06_match_ingredient_nutrition.py
  -> 07_auto_review_nutrition.py
  -> 08_apply_manual_review.py
  -> 09_calculate_recipe_nutrition.py
```

若 MySQL 使用既有 named volume，`04a_import_reference_maps.py` 與 `09_calculate_recipe_nutrition.py` 都會自行補齊必要 table/column；`mysql/migrations/010_qualitative_rules_weighted_coverage.sql` 亦可人工執行。

## Calorie / Main-Ingredient Price Policy (2026-09-19)

本版新增 `ingredient_calculation_rules` 計算政策，目的為降低低影響調味料造成的 `INSUFFICIENT`，同時保留高熱量調味料的熱量影響。

### 熱量

- 主食材：正常計算。
- 高熱量調味料（油、糖、奶油、高熱量醬料）：仍計算熱量。
- 幾乎零熱量項目（水、冰、鹽、味精、部分加工助劑）：從熱量計算與 coverage 分母排除。
- `CONDITIONAL` 調味料：優先使用實際 nutrition kcal；沒有 nutrition 時可使用規則表中的 fallback kcal，只用於判斷是否可忽略。估計貢獻 `<= 5 kcal` 時排除，超過 5 kcal 時仍須納入正式熱量 coverage。

### 價格

- 價格定義改為「主要食材預估價格」。
- 所有被辨識為調味料/醬料/香辛料/油脂/糖類/料理酒的項目一律不列入價格總額，也不列入價格 coverage 分母。
- API 會附加：
  - `price_scope: MAIN_INGREDIENTS_ONLY`
  - `price_note: 不含調味料`

### 主要新增檔案

- `data/reference/ingredient_calculation_rules.json`
- `python/app/services/calculation_policy.py`
- `mysql/migrations/011_ingredient_calculation_policy.sql`
- `docs/CALCULATION_POLICY_20260919.md`

`04a_import_reference_maps.py` 會依當前 `ingredients` 重新建立 `ingredient_calculation_rules`；`09_calculate_recipe_nutrition.py` 再依政策分別計算熱量 coverage 與價格 coverage。
