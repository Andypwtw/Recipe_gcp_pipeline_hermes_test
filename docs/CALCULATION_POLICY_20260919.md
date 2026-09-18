# 熱量 / 主要食材價格計算政策

## 目的

舊版即使主要食材已有重量、熱量與價格，只要鹽、胡椒、醬油、香料等資料不足，仍可能降低 coverage 並造成 `INSUFFICIENT`。

本版將「熱量」和「價格」使用不同的計算母體。

## 熱量規則

1. `INCLUDE`
   - 主食材與高熱量調味料正常進入 kcal 加總與 coverage。
   - 例：油、糖、奶油、美乃滋、芝麻醬、沙茶醬。
2. `EXCLUDE`
   - 從 kcal 加總及 calorie coverage 分母完全排除。
   - 例：水、冰、鹽、味精、泡打粉等低影響項目。
3. `CONDITIONAL`
   - 使用 nutrition kcal；若 nutrition 缺少，規則的 `fallback_kcal_per_100g` 只用於「是否可忽略」判斷。
   - 單項估算 `<= 5 kcal`：排除。
   - `> 5 kcal`：保留為正式熱量計算項目；若缺 nutrition，仍會降低 calorie coverage，不會用 fallback kcal 冒充正式熱量。

## 價格規則

價格功能定義為「主要食材預估價格（不含調味料）」。

被辨識為下列類型者 `price_policy=EXCLUDE`：

- 鹽、味精、香辛料、調味粉
- 醬油、醋、魚露、味醂、料理酒
- 食用油、香油、麻油、奶油
- 糖、蜂蜜等甜味料
- 醬料/condiment
- 蔥、薑、蒜、辣椒、香草等被本專案視為辛香調味用途的項目

它們不會進入 `estimated_price`，也不會進入價格 coverage 分母。

## MySQL

新增：

```text
ingredient_calculation_rules
recipe_nutrition_summary.price_weight_line_coverage_percent
```

`ingredient_calculation_rules` 是衍生規則表。每次執行 `04a_import_reference_maps.py` 會依目前 `ingredients.canonical_name` 與 JSON 規則重新建立，避免舊分類殘留。

## API

價格欄位仍為：

```text
estimated_price
```

另外附加：

```text
price_scope = MAIN_INGREDIENTS_ONLY
price_note  = 不含調味料
```

因此前端或 Hermes 應將價格理解為「主要食材預估價格」，不是整道料理含所有調味料的完整成本。
