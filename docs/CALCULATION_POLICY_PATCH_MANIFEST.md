# Full Integration / Changed-Only Patch Manifest

Changed-only comparison base:

```text
recipe_gcp_docker_compose.zip
```

也就是使用者原始上傳的 GCP production 專案。Changed-only ZIP 僅保留相對於該原始專案「有修改」或「新增」的檔案，不包含未修改檔案，也不包含 `.git` metadata。

## 整合內容

1. 前一階段正規化 / Nutrition coverage 修正：
   - 高信心 `qualitative_amount_rules`
   - 材料群組前綴與數字型食材解析修正
   - count-unit / density / qualitative weight estimation
   - Nutrition matching 強化
   - 重量型 calorie / price coverage
   - Hermes ingredient-intent / text-message 相容修正
2. 本階段 calculation policy：
   - 熱量：低影響項目可排除；高熱量調味料仍計算
   - 價格：所有被辨識為調味料/醬料/辛香料/油脂/糖/料理酒者排除
   - `estimated_price` 定義為「主要食材預估價格（不含調味料）」

## Modified files vs original upload

```text
README.md
V12_CHANGES.md
data/reference/README.md
docs/er_model.dbml
mysql/init/001_schema.sql
python/app/api.py
python/app/services/ingredient_intent.py
python/app/services/normalization.py
python/app/services/recommendation.py
python/scripts/03_normalize_recipes.py
python/scripts/03a_build_unit_weight_map.py
python/scripts/04a_import_reference_maps.py
python/scripts/04b_apply_weight_estimates.py
python/scripts/06_match_ingredient_nutrition.py
python/scripts/07_auto_review_nutrition.py
python/scripts/09_calculate_recipe_nutrition.py
```

## Added files vs original upload

```text
data/reference/ingredient_calculation_rules.json
data/reference/qualitative_amount_rules.json
data/reference/qualitative_amount_rules_high_confidence.xlsx
docs/CALCULATION_POLICY_20260919.md
docs/CALCULATION_POLICY_PATCH_MANIFEST.md
docs/CALCULATION_POLICY_VALIDATION.json
docs/INTEGRATION_VALIDATION.json
docs/NORMALIZATION_COVERAGE_CHANGES.md
docs/NORMALIZATION_COVERAGE_INTEGRATION.md
mysql/migrations/010_qualitative_rules_weighted_coverage.sql
mysql/migrations/011_ingredient_calculation_policy.sql
python/app/services/calculation_policy.py
```

Production topology remains unchanged: Airflow / Kafka / MongoDB / crawler / proxy / MySQL / Flask / Hermes / Redpanda services are retained.
