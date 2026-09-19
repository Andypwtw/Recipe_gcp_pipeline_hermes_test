# V11-T-2 價格功能測試說明

## 目的

驗證新版 `food_nutrition_2025.xlsx` 的 `每100g的價格` 可以進入既有 Nutrition Matching 資料鏈，並由食材重量計算食譜預估價格。

## 修改點

1. `nutrition_source` 新增 `price_per_100g`。
2. `recipe_nutrition_summary` 新增：
   - `estimated_price`
   - `price_coverage_percent`
   - `price_status`
3. `05_import_nutrition_excel.py` 將 Excel 價格寫入 `nutrition_source.price_per_100g`。
4. `09_calculate_recipe_nutrition.py` 依 `weight_g × price_per_100g / 100` 計算價格。
5. API 與 Recommendation / Hermes item 增加價格相關欄位。
6. `009_recipe_price.sql` 供既有資料庫升級使用；全新測試 Volume 會直接由 `001_schema.sql` 建立新欄位。

## 不包含的正式基礎設施

Crawler、Kafka、Redpanda、MongoDB、Airflow、PostgreSQL、Proxy、Web frontend。
