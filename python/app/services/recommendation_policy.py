from __future__ import annotations

from typing import Iterable

from app.services.ingredient_intent import excludes_for_group, patterns_for_group


def fallback_thresholds(requested_count: int) -> list[int]:
    """Bounded zero-result relaxation thresholds.

    <= 5 requested ingredients: at most 3 attempts.
    > 5 requested ingredients: at most 5 attempts.
    Each attempt relaxes by one matched ingredient and never drops below 1.
    """
    if requested_count <= 0:
        return [0]
    max_attempts = 5 if requested_count > 5 else 3
    return [
        requested_count - step
        for step in range(min(max_attempts, requested_count))
        if requested_count - step >= 1
    ]


def _sql_like_to_fragment(pattern: str) -> str:
    return str(pattern or "").replace("%", "").strip()


def _matches_group(canonical_name: str, group_name: str) -> bool:
    value = canonical_name or ""
    patterns = patterns_for_group(group_name)
    if not patterns:
        return False
    if any(
        fragment and fragment in value
        for fragment in (_sql_like_to_fragment(p) for p in patterns)
    ):
        excludes = excludes_for_group(group_name)
        return not any(
            fragment and fragment in value
            for fragment in (_sql_like_to_fragment(p) for p in excludes)
        )
    return False


def ingredient_match_score(
    query: str,
    canonical_name: str,
    aliases: Iterable[str] | None = None,
) -> float:
    """Deterministic weighted matching without fuzzy/ML inference."""
    q = str(query or "").strip()
    canonical = str(canonical_name or "").strip()
    alias_values = [str(a or "").strip() for a in aliases or [] if str(a or "").strip()]
    if not q or not canonical:
        return 0.0
    if canonical == q:
        return 1.0
    if q in alias_values:
        return 0.98
    if _matches_group(canonical, q):
        return 0.95
    if q in canonical or canonical in q:
        return 0.90
    if any(q in alias or alias in q for alias in alias_values):
        return 0.85
    return 0.0


def calculate_data_quality(candidate: dict) -> float:
    """Quality excludes price because current price coverage is insufficient."""
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
    """Ranking intentionally excludes price, cooking time and cache state."""
    ingredient_score = min(max(float(ingredient_score), 0.0), 1.0)
    preferred_score = min(max(float(preferred_score), 0.0), 1.0)
    data_quality = min(max(float(data_quality), 0.0), 1.0)

    if preferred_score > 0:
        score = 0.70 * ingredient_score + 0.15 * preferred_score + 0.15 * data_quality
    else:
        score = 0.80 * ingredient_score + 0.20 * data_quality
    return round(score, 4)
