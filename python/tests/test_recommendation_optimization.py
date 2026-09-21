from app.services.recommendation_policy import (
    calculate_data_quality,
    calculate_recommendation_score,
    fallback_thresholds,
    ingredient_match_score,
)
from app.services.ingredient_intent import (
    detect_calorie_bounds,
    detect_excluded_ingredient_groups,
)


def test_fallback_up_to_three_attempts_for_five_or_less():
    assert fallback_thresholds(5) == [5, 4, 3]
    assert fallback_thresholds(3) == [3, 2, 1]
    assert fallback_thresholds(2) == [2, 1]


def test_fallback_up_to_five_attempts_for_more_than_five():
    assert fallback_thresholds(6) == [6, 5, 4, 3, 2]
    assert fallback_thresholds(8) == [8, 7, 6, 5, 4]


def test_weighted_name_matching():
    assert ingredient_match_score("雞肉", "雞肉") == 1.00
    assert ingredient_match_score("蕃茄", "番茄", ["蕃茄"]) == 0.98
    assert ingredient_match_score("雞肉", "雞胸肉") == 0.95
    assert ingredient_match_score("番茄", "牛番茄") == 0.90


def test_price_is_not_part_of_data_quality():
    row = {
        "calorie_coverage_percent": 90,
        "weight_coverage_percent": 80,
        "price_coverage_percent": 0,
    }
    assert calculate_data_quality(row) == 0.86


def test_score_has_no_price_or_cooking_time_component():
    assert calculate_recommendation_score(1.0, 0.0, 1.0) == 1.0
    assert calculate_recommendation_score(0.8, 0.6, 0.9) == 0.785


def test_conservative_natural_language_conditions():
    assert detect_excluded_ingredient_groups("我想吃雞肉，但不要牛肉") == ["牛肉"]
    assert detect_calorie_bounds("我想吃雞肉，600大卡以下") == (None, 600.0)
    assert detect_calorie_bounds("至少400 kcal") == (400.0, None)
