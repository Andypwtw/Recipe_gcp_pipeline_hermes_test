from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.normalization import (
    canonicalize_ingredient_name,
    clean_text,
    direct_weight_g,
    normalize_unit,
    parse_number,
    strip_material_group_prefix,
)

SRC = Path("/workspace/data/processed/recipes_clean.json")
OUT = Path("/workspace/data/processed/recipes_normalized.json")

LINE_SPLIT = re.compile(r"\s*\|\s*")

UNIT_PATTERN = (
    r"公斤|公克|毫升|公升|盎司|人份|量杯|"
    r"大匙|湯匙|小匙|茶匙|"
    r"小塊|大塊|小片|大片|小段|大段|大碗|小碗|中匙|"
    r"c\.c\.|C\.C\.|c\.c|C\.C|"
    r"mL|ML|ml|㏄|cc|CC|kg|lb|oz|"
    r"克|斤|兩|錢|钱|磅|g|L|l|"
    r"個|顆|朵|片|格|隻|尾|條|根|杯|碗|匙|"
    r"支|粒|塊|包|張|罐|盒|把|瓣|份|棵|枝|株|瓶|副|"
    r"段|球|葉|枚|串|束|卷|捲|袋|管|盤|鍋|桶"
)

NUMBER_ATOM = (
    r"(?:"
    r"\d+\s*又\s*\d+\s*/\s*\d+"
    r"|\d+\s+\d+\s*/\s*\d+"
    r"|\d+\s*/\s*\d+"
    r"|\d+(?:\.\d+)?"
    r")"
)

AMOUNT_RE = re.compile(
    # Greedy ingredient-name capture intentionally chooses the LAST valid
    # quantity token.  This preserves product names containing digits, e.g.
    # A1醬 1大匙 / 8吋戚風蛋糕 1個, instead of misreading the digit in the
    # ingredient name as the recipe quantity.
    rf"^(?P<name>.*)\s*(?:約\s*)?"
    rf"(?P<qty1>{NUMBER_ATOM})"
    rf"(?:\s*(?P<range_sep>~|-)\s*(?P<qty2>{NUMBER_ATOM}))?"
    rf"\s*(?P<unit>{UNIT_PATTERN})?(?P<trailing>.*)$"
)

QUALITATIVE_SUFFIX_RE = re.compile(
    r"^(?P<name>.*?)\s*(?P<qual>少許|適量|酌量|少量|些許)\s*$"
)
QUALITATIVE_PREFIX_RE = re.compile(
    r"^(?P<qual>少許|適量|酌量|少量|些許)\s*(?P<name>.+?)\s*$"
)


def split_original_materials(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def split_clean_materials(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return [
        part.strip()
        for part in LINE_SPLIT.split(clean_text(text))
        if part.strip()
    ]


def parse_material_line(clean_raw: str) -> dict:
    source = strip_material_group_prefix(clean_raw)

    # Qualitative amount can appear before or after the ingredient.
    qualitative_match = QUALITATIVE_SUFFIX_RE.match(source) or QUALITATIVE_PREFIX_RE.match(source)
    if qualitative_match:
        raw_name = clean_text(qualitative_match.group("name"))
        qualitative_unit = qualitative_match.group("qual")
        return {
            "raw_name": raw_name,
            "canonical_name": canonicalize_ingredient_name(raw_name),
            "quantity_min": None,
            "quantity_max": None,
            "quantity_value": None,
            "unit": qualitative_unit,
            "weight_g": None,
            "is_estimated": True,
        }

    amount_match = AMOUNT_RE.match(source)
    if amount_match:
        raw_name = clean_text(amount_match.group("name"))
        qty1 = parse_number(amount_match.group("qty1"))
        qty2 = parse_number(amount_match.group("qty2") or "")
        unit = normalize_unit(amount_match.group("unit") or "")
        trailing = clean_text(amount_match.group("trailing") or "")

        # Only accept a numeric token as a quantity when it has a recognized
        # unit, or when no product/model text remains after it.
        if unit or not trailing:
            quantity_min = qty1
            quantity_max = qty2 if qty2 is not None else qty1
            if qty1 is not None and qty2 is not None:
                quantity_value = (qty1 + qty2) / 2
                estimated = True
            else:
                quantity_value = qty1
                estimated = False

            return {
                "raw_name": raw_name,
                "canonical_name": canonicalize_ingredient_name(raw_name),
                "quantity_min": quantity_min,
                "quantity_max": quantity_max,
                "quantity_value": quantity_value,
                "unit": unit,
                "weight_g": direct_weight_g(quantity_value, unit),
                "is_estimated": estimated,
            }

    raw_name = source
    return {
        "raw_name": raw_name,
        "canonical_name": canonicalize_ingredient_name(raw_name),
        "quantity_min": None,
        "quantity_max": None,
        "quantity_value": None,
        "unit": "",
        "weight_g": None,
        "is_estimated": False,
    }


def parse_materials(cleaned_text: str, original_text: str):
    clean_items = split_clean_materials(cleaned_text)
    original_items = split_original_materials(original_text)
    result = []

    for idx, clean_raw in enumerate(clean_items, 1):
        display_raw = original_items[idx - 1] if idx <= len(original_items) else clean_raw
        result.append({"line_no": idx, "raw_text": display_raw, **parse_material_line(clean_raw)})
    return result


def main():
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        out.append(
            {
                "seq": r.get("SEQ"),
                "name": r.get("食譜名稱"),
                "published_date": r.get("上線日期"),
                "raw_keywords": r.get("關鍵字"),
                "source_url": r.get("食譜網址"),
                "steps": r.get("做法步驟"),
                "ingredients": parse_materials(
                    r.get("材料", ""),
                    r.get("材料_原始", r.get("材料", "")),
                ),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"normalized={len(out)}")


if __name__ == "__main__":
    main()
