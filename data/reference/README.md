# Reference data

必備：

- `food_nutrition_2025.xlsx`：食品營養與每 100g 價格來源。
- `ingredient_density_map.json`：體積轉重量密度。
- `qualitative_amount_rules.json`：高信心「少許」等定性用量重量規則。
- `qualitative_amount_rules_high_confidence.xlsx`：高信心規則研究/人工檢查版本。
- `ingredient_calculation_rules.json`：熱量與價格計算政策。

`ingredient_calculation_rules.json` 的核心規則：

- 熱量：零/低影響項目可排除；油、糖、奶油、高熱量醬料仍計算。
- 價格：所有被辨識為調味料/醬料/香辛料/油脂/糖/料理酒者排除，價格代表「主要食材預估價格」。
