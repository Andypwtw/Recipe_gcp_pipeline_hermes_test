from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.db import get_connection
from app.services.category_resolver import resolve_categories_from_text
from app.services.ingredient_intent import (
    detect_ingredient_groups,
    excludes_for_group,
    patterns_for_group,
)
from app.services.recommendation_policy import (
    calculate_data_quality,
    calculate_recommendation_score,
    fallback_thresholds,
    ingredient_match_score,
)

CANDIDATE_LIMIT = 500


@dataclass(frozen=True)
class RecommendationContext:
    requested_ingredients: tuple[str, ...]
    required_ingredients: tuple[str, ...]
    preferred_ingredients: tuple[str, ...]
    excluded_ingredients: tuple[str, ...]
    category_ids: tuple[int, ...]


def _clean_terms(values: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        term = str(value or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def resolve_explicit_category_ids(categories: list[str]) -> list[int]:
    values = _clean_terms(categories)
    if not values:
        return []

    placeholders = ",".join(["%s"] * len(values))
    sql = f"""
        SELECT DISTINCT c.id AS category_id
        FROM category_aliases ca
        JOIN categories c ON c.id = ca.category_id
        WHERE ca.is_active = TRUE
          AND c.is_active = TRUE
          AND ca.alias_name IN ({placeholders})
    """

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(values))
        return [row["category_id"] for row in cur.fetchall()]


def _ingredient_exists_clause(
    patterns: list[str] | tuple[str, ...],
    excludes: list[str] | tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    positive = " OR ".join(["ix.canonical_name LIKE %s"] * len(patterns))
    params = list(patterns)
    exclude_sql = ""
    if excludes:
        exclude_sql = " AND " + " AND ".join(
            ["ix.canonical_name NOT LIKE %s"] * len(excludes)
        )
        params.extend(excludes)

    return (
        f"""
        EXISTS (
            SELECT 1
            FROM recipe_ingredients rix
            JOIN ingredients ix ON ix.id = rix.ingredient_id
            WHERE rix.recipe_id = r.id
              AND ({positive})
              {exclude_sql}
        )
        """,
        params,
    )


def _ingredient_not_exists_clause(term: str) -> tuple[str, list[str]]:
    group_patterns = patterns_for_group(term)
    if group_patterns:
        clause, params = _ingredient_exists_clause(
            group_patterns,
            excludes_for_group(term),
        )
    else:
        clause, params = _ingredient_exists_clause((f"%{term}%",))
    return f"NOT ({clause})", params


def _resolve_context(
    ingredients: list[str] | None = None,
    required_ingredients: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
    categories: list[str] | None = None,
    text: str | None = None,
) -> RecommendationContext:
    requested = _clean_terms(ingredients)
    required = _clean_terms(required_ingredients)
    preferred = _clean_terms(preferred_ingredients)
    excluded = _clean_terms(exclude_ingredients)

    text_matches = resolve_categories_from_text(text or "")
    text_groups = detect_ingredient_groups(text or "")
    category_ids: list[int] = []

    for row in text_matches:
        category_type = str(row.get("category_type") or "")
        category_name = str(row.get("category_name") or "").strip()
        if category_type == "ingredient_group" and patterns_for_group(category_name):
            if category_name not in text_groups:
                text_groups.append(category_name)
            continue
        category_id = row["category_id"]
        if category_id not in category_ids:
            category_ids.append(category_id)

    # Natural-language ingredient intent behaves like legacy `ingredients`:
    # strict on the first attempt, but eligible for bounded fallback.
    for group_name in text_groups:
        if group_name not in requested and group_name not in required:
            requested.append(group_name)

    for category_id in resolve_explicit_category_ids(categories or []):
        if category_id not in category_ids:
            category_ids.append(category_id)

    # Required wins over requested/preferred; excluded wins over preferred/requested.
    requested = [x for x in requested if x not in required and x not in excluded]
    preferred = [x for x in preferred if x not in required and x not in excluded]

    return RecommendationContext(
        requested_ingredients=tuple(requested),
        required_ingredients=tuple(required),
        preferred_ingredients=tuple(preferred),
        excluded_ingredients=tuple(excluded),
        category_ids=tuple(category_ids),
    )



def _best_term_score(term: str, ingredient_rows: list[dict]) -> float:
    best = 0.0
    for row in ingredient_rows:
        aliases = row.get("aliases") or []
        best = max(
            best,
            ingredient_match_score(term, row.get("canonical_name") or "", aliases),
        )
        if best >= 1.0:
            break
    return best


def calculate_data_quality(candidate: dict) -> float:
    """Quality score excludes price because V11-T-U price coverage is insufficient."""
    calorie_cov = float(candidate.get("calorie_coverage_percent") or 0.0) / 100.0
    weight_cov = float(candidate.get("weight_coverage_percent") or 0.0) / 100.0
    calorie_cov = min(max(calorie_cov, 0.0), 1.0)
    weight_cov = min(max(weight_cov, 0.0), 1.0)
    return round(0.60 * calorie_cov + 0.40 * weight_cov, 4)


def calculate_recommendation_score(
    ingredient_score: float,
    preferred_score: float,
    data_quality: float,
) -> float:
    """Score uses ingredients + quality only; price/time/cache are intentionally excluded."""
    ingredient_score = min(max(float(ingredient_score), 0.0), 1.0)
    preferred_score = min(max(float(preferred_score), 0.0), 1.0)
    data_quality = min(max(float(data_quality), 0.0), 1.0)

    if preferred_score > 0:
        score = 0.70 * ingredient_score + 0.15 * preferred_score + 0.15 * data_quality
    else:
        score = 0.80 * ingredient_score + 0.20 * data_quality
    return round(score, 4)


def _build_candidate_query(
    context: RecommendationContext,
    min_calories: float | None,
    max_calories: float | None,
) -> tuple[str, list[object]]:
    joins = [
        """
        LEFT JOIN recipe_nutrition_summary rns
          ON rns.recipe_id = r.id
        """
    ]
    where_parts: list[str] = []
    params: list[object] = []

    # Truly required ingredients are never relaxed.
    for term in context.required_ingredients:
        group_patterns = patterns_for_group(term)
        if group_patterns:
            clause, clause_params = _ingredient_exists_clause(
                group_patterns, excludes_for_group(term)
            )
        else:
            clause, clause_params = _ingredient_exists_clause((f"%{term}%",))
        where_parts.append(clause)
        params.extend(clause_params)

    # Legacy/requested ingredients need at least one hit in the candidate pool.
    if context.requested_ingredients:
        any_parts: list[str] = []
        any_params: list[object] = []
        for term in context.requested_ingredients:
            group_patterns = patterns_for_group(term)
            if group_patterns:
                clause, clause_params = _ingredient_exists_clause(
                    group_patterns, excludes_for_group(term)
                )
            else:
                clause, clause_params = _ingredient_exists_clause((f"%{term}%",))
            any_parts.append(clause)
            any_params.extend(clause_params)
        where_parts.append("(" + " OR ".join(any_parts) + ")")
        params.extend(any_params)

    # If the request only contains preferred ingredients, avoid scanning arbitrary recipes.
    if (
        not context.requested_ingredients
        and not context.required_ingredients
        and context.preferred_ingredients
    ):
        preferred_parts: list[str] = []
        preferred_params: list[object] = []
        for term in context.preferred_ingredients:
            group_patterns = patterns_for_group(term)
            if group_patterns:
                clause, clause_params = _ingredient_exists_clause(
                    group_patterns, excludes_for_group(term)
                )
            else:
                clause, clause_params = _ingredient_exists_clause((f"%{term}%",))
            preferred_parts.append(clause)
            preferred_params.extend(clause_params)
        where_parts.append("(" + " OR ".join(preferred_parts) + ")")
        params.extend(preferred_params)

    for term in context.excluded_ingredients:
        clause, clause_params = _ingredient_not_exists_clause(term)
        where_parts.append(clause)
        params.extend(clause_params)

    for category_id in context.category_ids:
        where_parts.append(
            """
            EXISTS (
                SELECT 1
                FROM recipe_categories rc
                WHERE rc.recipe_id = r.id
                  AND rc.category_id = %s
            )
            """
        )
        params.append(category_id)

    if min_calories is not None:
        where_parts.append("rns.energy_kcal IS NOT NULL AND rns.energy_kcal >= %s")
        params.append(float(min_calories))
    if max_calories is not None:
        where_parts.append("rns.energy_kcal IS NOT NULL AND rns.energy_kcal <= %s")
        params.append(float(max_calories))

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    sql = f"""
        SELECT
            r.id,
            r.seq,
            r.name,
            CAST(TRUNCATE(rns.energy_kcal, 0) AS SIGNED) AS energy_kcal,
            CAST(TRUNCATE(rns.ingredient_energy_kcal, 0) AS SIGNED) AS ingredient_energy_kcal,
            CAST(TRUNCATE(rns.seasoning_energy_kcal, 0) AS SIGNED) AS seasoning_energy_kcal,
            CAST(rns.estimated_price AS SIGNED) AS estimated_price,
            CASE WHEN rns.estimated_price IS NULL THEN '$無資料'
                 ELSE CONCAT('$', CAST(rns.estimated_price AS SIGNED)) END AS total_price_display,
            ROUND(rns.coverage_percent, 2) AS calorie_coverage_percent,
            ROUND(rns.price_coverage_percent, 2) AS price_coverage_percent,
            ROUND(rns.weight_coverage_percent, 2) AS weight_coverage_percent,
            rns.calorie_status,
            rns.price_status
        FROM recipes r
        {' '.join(joins)}
        WHERE {where_sql}
        ORDER BY r.seq
        LIMIT %s
    """
    params.append(CANDIDATE_LIMIT)
    return sql, params


def _fetch_candidate_ingredients(cur, recipe_ids: list[int]) -> dict[int, list[dict]]:
    if not recipe_ids:
        return {}
    placeholders = ",".join(["%s"] * len(recipe_ids))
    cur.execute(
        f"""
        SELECT
            ri.recipe_id,
            i.id AS ingredient_id,
            i.canonical_name,
            GROUP_CONCAT(DISTINCT ia.alias_name SEPARATOR '\\x1f') AS aliases_text
        FROM recipe_ingredients ri
        JOIN ingredients i ON i.id = ri.ingredient_id
        LEFT JOIN ingredient_aliases ia ON ia.ingredient_id = i.id
        WHERE ri.recipe_id IN ({placeholders})
        GROUP BY ri.recipe_id, i.id, i.canonical_name
        """,
        tuple(recipe_ids),
    )
    result: dict[int, list[dict]] = {recipe_id: [] for recipe_id in recipe_ids}
    for row in cur.fetchall():
        aliases_text = row.get("aliases_text") or ""
        result.setdefault(row["recipe_id"], []).append(
            {
                "canonical_name": row.get("canonical_name") or "",
                "aliases": [x for x in aliases_text.split("\x1f") if x],
            }
        )
    return result


def _score_candidates(candidates: list[dict], ingredients_by_recipe: dict[int, list[dict]], context: RecommendationContext) -> list[dict]:
    relaxable_count = len(context.requested_ingredients)
    target_terms = list(context.required_ingredients) + list(context.requested_ingredients)
    target_count = len(target_terms)
    preferred_count = len(context.preferred_ingredients)

    scored: list[dict] = []
    for candidate in candidates:
        recipe_ingredients = ingredients_by_recipe.get(candidate["id"], [])

        matched: list[str] = []
        missing: list[str] = []
        target_scores: list[float] = []
        relaxable_matched_count = 0
        for term in target_terms:
            score = _best_term_score(term, recipe_ingredients)
            target_scores.append(score)
            if score > 0:
                matched.append(term)
                if term in context.requested_ingredients:
                    relaxable_matched_count += 1
            else:
                missing.append(term)

        preferred_scores = [
            _best_term_score(term, recipe_ingredients)
            for term in context.preferred_ingredients
        ]
        matched_count = len(matched)
        match_ratio = (matched_count / target_count) if target_count else 1.0
        weighted_match = (
            sum(target_scores) / target_count if target_count else 1.0
        )
        preferred_score = (
            sum(preferred_scores) / preferred_count if preferred_count else 0.0
        )
        data_quality = calculate_data_quality(candidate)
        recommendation_score = calculate_recommendation_score(
            weighted_match, preferred_score, data_quality
        )

        item = dict(candidate)
        item.update(
            {
                "requested_ingredient_count": target_count,
                "required_ingredient_count": len(context.required_ingredients),
                "relaxable_ingredient_count": relaxable_count,
                "relaxable_matched_count": relaxable_matched_count,
                "matched_ingredient_count": matched_count,
                "matched_ingredients": matched,
                "missing_ingredients": missing,
                "missing_ingredient_count": len(missing),
                "ingredient_match_ratio": round(match_ratio, 4),
                "ingredient_match_score": round(weighted_match, 4),
                "preferred_ingredient_score": round(preferred_score, 4),
                "data_quality_score": data_quality,
                "recommendation_score": recommendation_score,
            }
        )
        scored.append(item)

    return scored


def _recommend_core(
    *,
    ingredients: list[str] | None = None,
    required_ingredients: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
    categories: list[str] | None = None,
    text: str | None = None,
    min_calories: float | None = None,
    max_calories: float | None = None,
) -> tuple[list[dict], dict]:
    context = _resolve_context(
        ingredients=ingredients,
        required_ingredients=required_ingredients,
        preferred_ingredients=preferred_ingredients,
        exclude_ingredients=exclude_ingredients,
        categories=categories,
        text=text,
    )

    has_any_condition = any(
        (
            context.requested_ingredients,
            context.required_ingredients,
            context.preferred_ingredients,
            context.excluded_ingredients,
            context.category_ids,
            min_calories is not None,
            max_calories is not None,
        )
    )
    if not has_any_condition:
        return [], {
            "fallback_applied": False,
            "attempts_used": 0,
            "max_attempts": 0,
            "requested_match_count": 0,
            "minimum_match_count": 0,
        }

    sql, params = _build_candidate_query(context, min_calories, max_calories)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        candidates = cur.fetchall()
        ingredients_by_recipe = _fetch_candidate_ingredients(
            cur, [row["id"] for row in candidates]
        )

    scored = _score_candidates(candidates, ingredients_by_recipe, context)

    requested_count = len(context.requested_ingredients)
    thresholds = fallback_thresholds(requested_count)
    selected: list[dict] = []
    selected_threshold = 0
    attempts_used = 0

    # If there are no relaxable ingredients, one pass is enough.
    if requested_count == 0:
        selected = scored
        selected_threshold = 0
        attempts_used = 1
    else:
        for threshold in thresholds:
            attempts_used += 1
            current = [
                row for row in scored if row["relaxable_matched_count"] >= threshold
            ]
            if current:
                selected = current
                selected_threshold = threshold
                break
        if not selected and thresholds:
            selected_threshold = thresholds[-1]

    selected.sort(
        key=lambda row: (
            -row["recommendation_score"],
            -row["matched_ingredient_count"],
            row["missing_ingredient_count"],
            row["seq"],
        )
    )

    metadata = {
        "fallback_applied": bool(requested_count and selected_threshold < requested_count and selected),
        "attempts_used": attempts_used,
        "max_attempts": len(thresholds) if requested_count else 1,
        "requested_match_count": requested_count,
        "minimum_match_count": selected_threshold,
        "price_used_for_ranking": False,
        "cooking_time_used": False,
        "cache_used": False,
    }
    return selected, metadata


def _strip_internal_id(items: list[dict]) -> list[dict]:
    output: list[dict] = []
    for item in items:
        row = dict(item)
        row.pop("id", None)
        output.append(row)
    return output


def recommend_recipes(
    ingredients: list[str] | None = None,
    limit: int = 10,
    categories: list[str] | None = None,
    text: str | None = None,
    required_ingredients: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
    min_calories: float | None = None,
    max_calories: float | None = None,
):
    """Hermes-compatible list; the endpoint path and `items` contract stay compatible."""
    items, _ = _recommend_core(
        ingredients=ingredients,
        required_ingredients=required_ingredients,
        preferred_ingredients=preferred_ingredients,
        exclude_ingredients=exclude_ingredients,
        categories=categories,
        text=text,
        min_calories=min_calories,
        max_calories=max_calories,
    )
    limit = min(max(int(limit), 1), 100)
    return _strip_internal_id(items[:limit])


def recommend_recipes_with_metadata(
    ingredients: list[str] | None = None,
    limit: int = 10,
    categories: list[str] | None = None,
    text: str | None = None,
    required_ingredients: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
    min_calories: float | None = None,
    max_calories: float | None = None,
) -> dict:
    items, metadata = _recommend_core(
        ingredients=ingredients,
        required_ingredients=required_ingredients,
        preferred_ingredients=preferred_ingredients,
        exclude_ingredients=exclude_ingredients,
        categories=categories,
        text=text,
        min_calories=min_calories,
        max_calories=max_calories,
    )
    limit = min(max(int(limit), 1), 100)
    return {"items": _strip_internal_id(items[:limit]), **metadata}


def recommend_recipes_page(
    ingredients: list[str] | None = None,
    categories: list[str] | None = None,
    text: str | None = None,
    page: int = 1,
    limit: int = 12,
    required_ingredients: list[str] | None = None,
    preferred_ingredients: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
    min_calories: float | None = None,
    max_calories: float | None = None,
) -> dict:
    """Stable paginated recommendation result for the web frontend."""
    page = max(int(page), 1)
    limit = min(max(int(limit), 1), 100)
    items, metadata = _recommend_core(
        ingredients=ingredients,
        required_ingredients=required_ingredients,
        preferred_ingredients=preferred_ingredients,
        exclude_ingredients=exclude_ingredients,
        categories=categories,
        text=text,
        min_calories=min_calories,
        max_calories=max_calories,
    )
    total = len(items)
    offset = (page - 1) * limit
    page_items = items[offset : offset + limit]
    total_pages = (total + limit - 1) // limit if total else 0
    return {
        "items": page_items,
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        **metadata,
    }


def recommend_by_ingredients(
    ingredients: list[str],
    limit: int = 10,
    categories: list[str] | None = None,
):
    return recommend_recipes(
        ingredients=ingredients,
        limit=limit,
        categories=categories,
    )
