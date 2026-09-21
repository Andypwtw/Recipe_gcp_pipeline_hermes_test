# V11-T-U-2 推薦邏輯優化測試版

基底版本：V11-T-U (`recipe_gcp_docker_compose_UPDATED_FULL.zip`)

## 本版範圍

本版只優化推薦與 API 條件處理；不修改 Crawler、Kafka、MongoDB、Airflow、既有 ETL、營養 Matching、價格 Matching、熱量/價格計算政策與 docker-compose.yml。

### 已加入

- 多食材實際符合率 (`ingredient_match_ratio`)
- 缺少食材清單與數量
- 決定式食材 Matching 權重：canonical exact / alias exact / ingredient group / substring
- `required_ingredients`、`preferred_ingredients`、`exclude_ingredients`
- `min_calories`、`max_calories` 條件
- 資料品質分數：只使用熱量 coverage 與 weight coverage
- 綜合 `recommendation_score`
- Hermes / Web 共用 `_recommend_core()`
- 0 筆結果 bounded fallback
  - 1~5 個可放寬食材：最多 3 次條件比對
  - >5 個可放寬食材：最多 5 次條件比對
  - 每次只降低 1 個最低符合食材數，最低不低於 1
- 回傳 fallback metadata

### 明確不加入

- 預算推薦
- 價格排序與 PriceScore
- 烹飪時間推估/排序
- API cache / Redis / in-memory cache
- K-means 分群

## 為什麼暫不使用價格排序

目前價格 coverage 不足，因此價格繼續顯示，但不參與候選篩選、Recommendation Score 或排序，避免資料缺失造成排名偏誤。

## 烹飪時間可信度評估

對 YTower 原始 29,597 筆食譜做文字檢查，17,911 筆（約 60.5%）的做法步驟至少出現一個明確的「秒/分鐘/小時」時間表達。但這不等於可可靠取得總烹飪時間：時間可能只描述醃漬、燉煮或單一步驟，其他步驟沒有時間，而且不同步驟可能重疊。因此本版不產生總分鐘數，也不將時間放入排序。

## 0 筆 fallback

例如 3 種食材：

1. 3/3
2. 2/3
3. 1/3

三次仍為 0 筆才回 0 筆。

例如 7 種食材：

1. 7/7
2. 6/7
3. 5/7
4. 4/7
5. 3/7

五次仍為 0 筆才回 0 筆。

`required_ingredients` 不參與放寬，始終必須存在；legacy `ingredients` / 從 text 偵測到的 ingredient group 才使用 bounded fallback。

## Recommendation Score

未指定 preferred ingredient：

- 80% Ingredient Match Score
- 20% Data Quality

有 preferred ingredient：

- 70% Ingredient Match Score
- 15% Preferred Ingredient Score
- 15% Data Quality

Data Quality：

- 60% calorie coverage
- 40% weight coverage

價格 coverage 不納入。

## API 相容性

保留：

- `POST /api/v1/hermes/recommend`
- `POST /api/v1/recommend`

舊 `ingredients`、`text/message`、`categories`、`limit` 仍可使用。
新增可選欄位：

- `required_ingredients`
- `preferred_ingredients`
- `exclude_ingredients`
- `min_calories`
- `max_calories`

回傳新增：

- `ingredient_match_ratio`
- `ingredient_match_score`
- `matched_ingredients`
- `missing_ingredients`
- `missing_ingredient_count`
- `data_quality_score`
- `recommendation_score`
- `fallback_applied`
- `attempts_used`
- `max_attempts`
- `requested_match_count`
- `minimum_match_count`

## 測試

- Python compileall：PASS
- 原熱量/價格政策 + 新推薦 policy：17 tests PASS
- docker-compose.yml：未修改，SHA256 與 V11-T-U 基底相同
- YAML parse：PASS
- MySQL runtime / Docker stack：此環境未執行
