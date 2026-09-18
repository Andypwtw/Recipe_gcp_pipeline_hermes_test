# Recipe_gcp_pipeline_hermes_test — Normalization & Coverage Fix

這份測試專案以使用者上傳的 `Recipe_gcp_pipeline_hermes_test.zip` 為基礎，重點修正：

1. 食材名稱正規化不足，造成 Nutrition Matching 失敗。
2. `weight_g` 覆蓋率不足，造成熱量與價格大量 `INSUFFICIENT`。
3. 將高信心 `少許` 比對表正式納入 MySQL 與重量估算流程。
4. 熱量與價格 coverage 改為「重量型 coverage」，避免少量調味料與主要食材權重相同。
5. 保留安全門檻，不以降低門檻方式製造假精準結果。

## 測試架構

```text
已爬取 JSON
↓
01/02 清洗
↓
03a 建立 count-unit 候選重量表
↓
03 食材名稱 / 單位正規化
↓
04 匯入 MySQL
↓
04a 匯入重量 / 密度 / qualitative rules
↓
04b 補 weight_g
↓
05 匯入 Nutrition + 每100g價格
↓
06 Nutrition Matching
↓
07 自動審核
↓
08 套用審核結果
↓
09 熱量 + 價格（重量型 coverage）
↓
Flask API / Hermes
```

## 高信心 qualitative rules

專案已包含：

```text
data/reference/qualitative_amount_rules_high_confidence.xlsx
data/reference/qualitative_amount_rules.json
```

目前 JSON 只啟用 `少許` 的高信心規則，且：

```text
confidence_score >= 80
auto_convert = true
```

`適量` 不會被任意指定固定克數；沒有高信心規則時維持 `weight_g = NULL`。

## Coverage 新算法

### 熱量

```text
有熱量資料的已知重量
÷
全部已知重量
```

必須同時符合：

```text
calorie weight coverage >= 60%
known-weight line coverage >= 50%
```

### 價格

```text
有價格資料的可計價重量
÷
全部可計價已知重量
```

水 / 冰等不列入價格 coverage denominator。

## 第一次啟動

```bash
cp .env.example .env
docker compose up -d --build
```

預設：

```text
MySQL Host: 127.0.0.1:3319
Flask API:  http://127.0.0.1:5001
```

若舊測試 volume 的 schema 需要完全重建，而且資料可以刪除：

```bash
docker compose down -v
docker compose up -d --build
```

注意：`down -v` 只應用在這份可重建的測試環境，不要拿去正式資料庫環境執行。

## 執行完整 Pipeline

```bash
docker compose exec python-test \
  uv run python scripts/10_pipeline.py
```

## API 健康檢查

```bash
curl http://127.0.0.1:5001/health
```

Hermes：

```text
POST /api/v1/hermes/recommend
```

## Pipeline 完成後檢查成功率

```sql
SELECT calorie_status, COUNT(*)
FROM recipe_nutrition_summary
GROUP BY calorie_status;

SELECT price_status, COUNT(*)
FROM recipe_nutrition_summary
GROUP BY price_status;

SELECT
  ROUND(AVG(coverage_percent),2) AS avg_calorie_weight_coverage,
  ROUND(AVG(price_coverage_percent),2) AS avg_price_weight_coverage,
  ROUND(AVG(weight_coverage_percent),2) AS avg_known_weight_line_coverage
FROM recipe_nutrition_summary;
```

## 驗證限制

已做 Python syntax、Compose YAML、JSON、正規化離線測試與 SQL 結構靜態檢查。

目前工作環境沒有 Docker daemon / MySQL runtime，因此沒有宣稱完成實際 Docker + MySQL E2E。最終的 CALCULATED / PARTIAL / INSUFFICIENT 數量，必須在 GCP 跑完整 pipeline 後確認。
