# V12 changes

- First successful crawl remains FULL: A01-I10, 1..MAX_SEQ_NUMBER.
- Added MongoDB `crawl_state` checkpoint. Checkpoint advances only after crawler queue, Mongo writer, ETL and MySQL validation succeed.
- Airflow checks daily and only runs when 7 days have elapsed since the last successful checkpoint.
- Incremental run uses `recipe-search.asp` with checkpoint minus one day overlap.
- Added Kafka `incremental_discovery` and `seq_list` job types.
- Added free TW proxy sources: Proxifly, HProxy, Proxmint, while preserving existing sources and validation.
- Added optional LumiProxy/Croxy endpoint environment variables; secrets remain outside Git in `.env`.
- Normalized shell scripts to LF line endings for GCP/Linux Bash.

## Normalization / Nutrition Coverage integration

- Added high-confidence `qualitative_amount_rules` reference data and MySQL table.
- Added MySQL migration `010_qualitative_rules_weighted_coverage.sql`.
- Strengthened material prefix cleanup and digit-containing ingredient parsing.
- Changed unsupported qualitative amounts such as generic `適量` to remain unresolved instead of forcing low-confidence grams.
- Added data-derived ingredient/count-unit weight map generation from explicit gram annotations.
- Strengthened nutrition matching with normalized variants, curated safe targets, and guarded fuzzy matching.
- Changed calorie/price coverage to weight-based coverage plus known-weight-line guard.
- Added `recipe_nutrition_summary.weight_coverage_percent`.
- Retained Hermes `text` / `message` compatibility and ingredient-intent recommendation filtering.
- Parser robustness fix: prevents `300公克` from being misread as `0g`, preserves product names such as `A1醬` / `8吋戚風蛋糕`, and keeps malformed zero-quantity rows unresolved.

## Calorie / price calculation policy fix

- Added `ingredient_calculation_rules` and JSON-driven ingredient policy classification.
- Calories exclude negligible items; high-energy seasonings remain included.
- Conditional seasonings are ignored only when their contribution is `<= 5 kcal`.
- All recognized seasonings/condiments are excluded from price calculation and price coverage.
- Added a separate `price_weight_line_coverage_percent` because calorie and price denominators are now different.
- API/Hermes results now expose `price_scope=MAIN_INGREDIENTS_ONLY` and `price_note=不含調味料`.
- Added migration `011_ingredient_calculation_policy.sql`.
