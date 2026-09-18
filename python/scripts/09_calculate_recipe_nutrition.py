from __future__ import annotations

import json
from pathlib import Path

from app.db import get_connection

ENERGY_SOURCE_COLUMN = "熱量(kcal)"
MIN_COVERAGE_PERCENT = 60.0
MIN_PRICE_COVERAGE_PERCENT = 60.0
MIN_WEIGHT_LINE_COVERAGE_PERCENT = 50.0

DIAGNOSTIC_OUT = Path("/workspace/data/processed/calorie_diagnostic.json")


def ensure_calculation_rules_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_calculation_rules (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          ingredient_id BIGINT NOT NULL,
          rule_key VARCHAR(100) NOT NULL,
          ingredient_category VARCHAR(60) NOT NULL DEFAULT 'FOOD',
          is_seasoning BOOLEAN NOT NULL DEFAULT FALSE,
          calorie_policy VARCHAR(20) NOT NULL DEFAULT 'INCLUDE',
          price_policy VARCHAR(20) NOT NULL DEFAULT 'INCLUDE',
          calorie_ignore_threshold_kcal DECIMAL(10,4) NOT NULL DEFAULT 5.0000,
          fallback_kcal_per_100g DECIMAL(12,4) NULL,
          confidence_score DECIMAL(6,2) NOT NULL DEFAULT 100.00,
          match_reason VARCHAR(255),
          source VARCHAR(255) NOT NULL DEFAULT 'ingredient_calculation_rules.json',
          note VARCHAR(1000),
          status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_icr_ingredient (ingredient_id),
          INDEX idx_icr_price_policy (price_policy,is_seasoning,status),
          INDEX idx_icr_calorie_policy (calorie_policy,status),
          CONSTRAINT fk_icr_ingredient
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
            ON DELETE CASCADE
        )
        """
    )


def ensure_summary_columns(cur):
    wanted = {
        "calorie_status": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN calorie_status VARCHAR(30)
            NOT NULL DEFAULT 'INSUFFICIENT'
            AFTER coverage_percent
        """,
        "estimated_price": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN estimated_price DECIMAL(18,2) NULL
            AFTER energy_kcal
        """,
        "price_coverage_percent": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN price_coverage_percent DECIMAL(8,2) NULL
            AFTER coverage_percent
        """,
        "weight_coverage_percent": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN weight_coverage_percent DECIMAL(8,2) NULL
            AFTER price_coverage_percent
        """,
        "price_weight_line_coverage_percent": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN price_weight_line_coverage_percent DECIMAL(8,2) NULL
            AFTER weight_coverage_percent
        """,
        "price_status": """
            ALTER TABLE recipe_nutrition_summary
            ADD COLUMN price_status VARCHAR(30)
            NOT NULL DEFAULT 'INSUFFICIENT'
            AFTER price_weight_line_coverage_percent
        """,
    }
    for column_name, ddl in wanted.items():
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'recipe_nutrition_summary'
              AND column_name = %s
            """,
            (column_name,),
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(ddl)


def line_source_sql() -> str:
    """One row per recipe ingredient with its effective calculation policy.

    Project policy:
    - price: every recognized seasoning/condiment is excluded;
    - calories: high-energy seasonings remain included;
    - low-impact seasonings can be EXCLUDE or CONDITIONAL;
    - CONDITIONAL is ignored only when its mapped/fallback energy contribution is
      <= calorie_ignore_threshold_kcal (default 5 kcal).
    """
    return """
        SELECT
          ri.recipe_id,
          ri.ingredient_id,
          i.canonical_name,
          ri.weight_g,
          energy.energy_kcal_per_100g,
          ns.price_per_100g,
          COALESCE(icr.is_seasoning, FALSE) AS is_seasoning,
          COALESCE(icr.calorie_policy, 'INCLUDE') AS calorie_policy,
          COALESCE(icr.price_policy, 'INCLUDE') AS price_policy,
          COALESCE(icr.calorie_ignore_threshold_kcal, 5.0) AS calorie_ignore_threshold_kcal,
          icr.fallback_kcal_per_100g,
          CASE
            WHEN COALESCE(icr.calorie_policy, 'INCLUDE') = 'EXCLUDE' THEN 1
            WHEN COALESCE(icr.calorie_policy, 'INCLUDE') = 'CONDITIONAL'
             AND ri.weight_g IS NOT NULL
             AND COALESCE(energy.energy_kcal_per_100g, icr.fallback_kcal_per_100g) IS NOT NULL
             AND COALESCE(energy.energy_kcal_per_100g, icr.fallback_kcal_per_100g)
                   * ri.weight_g / 100
                 <= COALESCE(icr.calorie_ignore_threshold_kcal, 5.0)
              THEN 1
            ELSE 0
          END AS calorie_excluded,
          CASE
            WHEN COALESCE(icr.price_policy, 'INCLUDE') = 'EXCLUDE' THEN 1
            ELSE 0
          END AS price_excluded
        FROM recipe_ingredients ri
        JOIN ingredients i
          ON i.id = ri.ingredient_id
        LEFT JOIN ingredient_calculation_rules icr
          ON icr.ingredient_id = ri.ingredient_id
         AND icr.status = 'ACTIVE'
        LEFT JOIN ingredient_nutrition_map inm
          ON inm.ingredient_id = ri.ingredient_id
         AND inm.status = 'APPROVED'
        LEFT JOIN nutrition_source ns
          ON ns.id = inm.nutrition_source_id
        LEFT JOIN (
          SELECT
            nv.nutrition_source_id,
            nv.value_numeric AS energy_kcal_per_100g
          FROM nutrition_values nv
          JOIN nutrient_definitions nd
            ON nd.id = nv.nutrient_id
          WHERE nd.source_column_name = %s
        ) energy
          ON energy.nutrition_source_id = inm.nutrition_source_id
    """


def main():
    DIAGNOSTIC_OUT.parent.mkdir(parents=True, exist_ok=True)
    line_sql = line_source_sql()

    with get_connection() as conn, conn.cursor() as cur:
        ensure_calculation_rules_table(cur)
        ensure_summary_columns(cur)
        cur.execute("DELETE FROM recipe_nutrition_summary")

        # coverage_percent = calorie weight coverage after excluding negligible
        # calorie items. price_coverage_percent = main-ingredient price weight
        # coverage after excluding all recognized seasonings/condiments.
        # weight_coverage_percent = calorie-relevant line weight coverage.
        # price_weight_line_coverage_percent = price-relevant line weight coverage.
        query = f"""
        INSERT INTO recipe_nutrition_summary
        (
          recipe_id,energy_kcal,estimated_price,
          coverage_percent,price_coverage_percent,weight_coverage_percent,
          price_weight_line_coverage_percent,
          calorie_status,price_status,calculated_at
        )
        SELECT
          calc.recipe_id,
          CASE
            WHEN calc.calorie_relevant_lines = 0 AND calc.calorie_excluded_lines > 0 THEN 0
            WHEN calc.calorie_known_weight_g <= 0 THEN NULL
            WHEN calc.weight_coverage_percent < {MIN_WEIGHT_LINE_COVERAGE_PERCENT} THEN NULL
            WHEN calc.coverage_percent < {MIN_COVERAGE_PERCENT} THEN NULL
            WHEN calc.raw_energy_kcal > 0 AND calc.raw_energy_kcal < 1 THEN NULL
            ELSE TRUNCATE(calc.raw_energy_kcal,0)
          END AS energy_kcal,
          CASE
            WHEN calc.price_relevant_lines <= 0 THEN NULL
            WHEN calc.price_denominator_g <= 0 THEN NULL
            WHEN calc.raw_estimated_price IS NULL THEN NULL
            WHEN calc.price_weight_line_coverage_percent < {MIN_WEIGHT_LINE_COVERAGE_PERCENT} THEN NULL
            WHEN calc.price_coverage_percent < {MIN_PRICE_COVERAGE_PERCENT} THEN NULL
            ELSE ROUND(calc.raw_estimated_price,2)
          END AS estimated_price,
          calc.coverage_percent,
          calc.price_coverage_percent,
          calc.weight_coverage_percent,
          calc.price_weight_line_coverage_percent,
          CASE
            WHEN calc.calorie_relevant_lines = 0 AND calc.calorie_excluded_lines > 0
              THEN 'TRUE_ZERO_SOURCE'
            WHEN calc.calorie_known_weight_g <= 0 THEN 'INSUFFICIENT'
            WHEN calc.weight_coverage_percent < {MIN_WEIGHT_LINE_COVERAGE_PERCENT} THEN 'INSUFFICIENT'
            WHEN calc.coverage_percent < {MIN_COVERAGE_PERCENT} THEN 'INSUFFICIENT'
            WHEN calc.raw_energy_kcal > 0 AND calc.raw_energy_kcal < 1 THEN 'BELOW_1_KCAL'
            WHEN calc.raw_energy_kcal = 0 THEN 'TRUE_ZERO_SOURCE'
            ELSE 'CALCULATED'
          END AS calorie_status,
          CASE
            WHEN calc.price_relevant_lines <= 0 THEN 'INSUFFICIENT'
            WHEN calc.price_denominator_g <= 0 THEN 'INSUFFICIENT'
            WHEN calc.raw_estimated_price IS NULL THEN 'INSUFFICIENT'
            WHEN calc.price_weight_line_coverage_percent < {MIN_WEIGHT_LINE_COVERAGE_PERCENT} THEN 'INSUFFICIENT'
            WHEN calc.price_coverage_percent < {MIN_PRICE_COVERAGE_PERCENT} THEN 'INSUFFICIENT'
            WHEN calc.price_coverage_percent < 99.5
              OR calc.price_weight_line_coverage_percent < 99.5
              THEN 'PARTIAL'
            ELSE 'CALCULATED'
          END AS price_status,
          NOW()
        FROM (
          SELECT
            base.recipe_id,
            base.raw_energy_kcal,
            base.raw_estimated_price,
            base.calorie_relevant_lines,
            base.calorie_excluded_lines,
            base.price_relevant_lines,
            base.calorie_known_weight_g,
            base.price_denominator_g,
            ROUND(
              100 * base.energy_covered_weight_g
              / NULLIF(base.calorie_known_weight_g,0), 2
            ) AS coverage_percent,
            ROUND(
              100 * base.price_covered_weight_g
              / NULLIF(base.price_denominator_g,0), 2
            ) AS price_coverage_percent,
            ROUND(
              100 * base.calorie_known_weight_lines
              / NULLIF(base.calorie_relevant_lines,0), 2
            ) AS weight_coverage_percent,
            ROUND(
              100 * base.price_known_weight_lines
              / NULLIF(base.price_relevant_lines,0), 2
            ) AS price_weight_line_coverage_percent
          FROM (
            SELECT
              line.recipe_id,

              SUM(CASE WHEN line.calorie_excluded = 0 THEN 1 ELSE 0 END)
                AS calorie_relevant_lines,
              SUM(CASE WHEN line.calorie_excluded = 1 THEN 1 ELSE 0 END)
                AS calorie_excluded_lines,
              SUM(CASE WHEN line.price_excluded = 0 THEN 1 ELSE 0 END)
                AS price_relevant_lines,

              SUM(
                CASE
                  WHEN line.calorie_excluded = 0 AND line.weight_g IS NOT NULL THEN 1
                  ELSE 0
                END
              ) AS calorie_known_weight_lines,
              SUM(
                CASE
                  WHEN line.price_excluded = 0 AND line.weight_g IS NOT NULL THEN 1
                  ELSE 0
                END
              ) AS price_known_weight_lines,

              SUM(
                CASE
                  WHEN line.calorie_excluded = 0 AND line.weight_g IS NOT NULL
                    THEN line.weight_g
                  ELSE 0
                END
              ) AS calorie_known_weight_g,
              SUM(
                CASE
                  WHEN line.price_excluded = 0 AND line.weight_g IS NOT NULL
                    THEN line.weight_g
                  ELSE 0
                END
              ) AS price_denominator_g,

              SUM(
                CASE
                  WHEN line.calorie_excluded = 0
                   AND line.weight_g IS NOT NULL
                   AND line.energy_kcal_per_100g IS NOT NULL
                    THEN line.energy_kcal_per_100g * line.weight_g / 100
                  WHEN line.calorie_excluded = 1 THEN 0
                  ELSE NULL
                END
              ) AS raw_energy_kcal,
              SUM(
                CASE
                  WHEN line.price_excluded = 0
                   AND line.weight_g IS NOT NULL
                   AND line.price_per_100g IS NOT NULL
                    THEN line.price_per_100g * line.weight_g / 100
                  ELSE NULL
                END
              ) AS raw_estimated_price,

              SUM(
                CASE
                  WHEN line.calorie_excluded = 0
                   AND line.weight_g IS NOT NULL
                   AND line.energy_kcal_per_100g IS NOT NULL
                    THEN line.weight_g
                  ELSE 0
                END
              ) AS energy_covered_weight_g,
              SUM(
                CASE
                  WHEN line.price_excluded = 0
                   AND line.weight_g IS NOT NULL
                   AND line.price_per_100g IS NOT NULL
                    THEN line.weight_g
                  ELSE 0
                END
              ) AS price_covered_weight_g

            FROM (
              {line_sql}
            ) line
            GROUP BY line.recipe_id
          ) base
        ) calc
        """
        cur.execute(query, (ENERGY_SOURCE_COLUMN,))

        cur.execute(
            """
            SELECT
              COUNT(*) AS recipe_count,
              SUM(calorie_status='CALCULATED') AS calorie_calculated_count,
              SUM(calorie_status='INSUFFICIENT') AS calorie_insufficient_count,
              SUM(calorie_status='BELOW_1_KCAL') AS below_1_kcal_count,
              SUM(calorie_status='TRUE_ZERO_SOURCE') AS true_zero_count,
              SUM(price_status='CALCULATED') AS price_calculated_count,
              SUM(price_status='PARTIAL') AS price_partial_count,
              SUM(price_status='INSUFFICIENT') AS price_insufficient_count,
              ROUND(AVG(coverage_percent),2) AS avg_calorie_weight_coverage,
              ROUND(AVG(price_coverage_percent),2) AS avg_price_weight_coverage,
              ROUND(AVG(weight_coverage_percent),2) AS avg_calorie_line_weight_coverage,
              ROUND(AVG(price_weight_line_coverage_percent),2)
                AS avg_price_line_weight_coverage
            FROM recipe_nutrition_summary
            """
        )
        summary = cur.fetchone()

        diagnostic_query = f"""
            SELECT
              r.seq,
              r.name,
              rns.energy_kcal,
              rns.estimated_price,
              rns.coverage_percent,
              rns.price_coverage_percent,
              rns.weight_coverage_percent,
              rns.price_weight_line_coverage_percent,
              rns.calorie_status,
              rns.price_status,
              COUNT(*) AS total_lines,
              SUM(line.calorie_excluded = 1) AS calorie_excluded_lines,
              SUM(line.price_excluded = 1) AS price_excluded_lines,
              SUM(line.calorie_excluded = 0 AND line.weight_g IS NULL)
                AS calorie_missing_weight_lines,
              SUM(line.price_excluded = 0 AND line.weight_g IS NULL)
                AS price_missing_weight_lines,
              SUM(
                line.calorie_excluded = 0
                AND line.weight_g IS NOT NULL
                AND line.energy_kcal_per_100g IS NULL
              ) AS missing_energy_lines,
              SUM(
                line.price_excluded = 0
                AND line.weight_g IS NOT NULL
                AND line.price_per_100g IS NULL
              ) AS missing_price_lines
            FROM recipes r
            JOIN (
              {line_sql}
            ) line
              ON line.recipe_id = r.id
            JOIN recipe_nutrition_summary rns
              ON rns.recipe_id = r.id
            WHERE rns.calorie_status <> 'CALCULATED'
               OR rns.price_status = 'INSUFFICIENT'
            GROUP BY
              r.id,r.seq,r.name,rns.energy_kcal,rns.estimated_price,
              rns.coverage_percent,rns.price_coverage_percent,
              rns.weight_coverage_percent,rns.price_weight_line_coverage_percent,
              rns.calorie_status,rns.price_status
            ORDER BY rns.calorie_status,rns.price_status,r.seq
        """
        cur.execute(diagnostic_query, (ENERGY_SOURCE_COLUMN,))
        diagnostic_rows = cur.fetchall()
        conn.commit()

    def safe(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    DIAGNOSTIC_OUT.write_text(
        json.dumps(
            {
                "coverage_method": "POLICY_AWARE_WEIGHT_BASED_WITH_SEPARATE_LINE_GUARDS",
                "energy_source_column": ENERGY_SOURCE_COLUMN,
                "price_source_column": "nutrition_source.price_per_100g",
                "price_scope": "MAIN_INGREDIENTS_ONLY_EXCLUDING_RECOGNIZED_SEASONINGS",
                "calorie_policy": "EXCLUDE_NEGLIGIBLE; CONDITIONAL<=5_KCAL; INCLUDE_HIGH_ENERGY_SEASONINGS",
                "minimum_calorie_weight_coverage_percent": MIN_COVERAGE_PERCENT,
                "minimum_price_weight_coverage_percent": MIN_PRICE_COVERAGE_PERCENT,
                "minimum_relevant_weight_line_coverage_percent": MIN_WEIGHT_LINE_COVERAGE_PERCENT,
                "summary": {k: safe(v) for k, v in summary.items()},
                "problem_recipes": [
                    {k: safe(v) for k, v in dict(row).items()}
                    for row in diagnostic_rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Recipe calorie + main-ingredient price summary calculated with policy-aware coverage.")
    print("Price excludes all recognized seasonings/condiments.")
    print(summary)
    print(f"Diagnostic report -> {DIAGNOSTIC_OUT}")


if __name__ == "__main__":
    main()
