from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SRC = Path("/workspace/data/raw/ytower_seq_recipes.json")
OUT = Path("/workspace/data/processed/profile_report.json")

def main():
    rows = json.loads(SRC.read_text(encoding="utf-8"))

    fields = [
        "SEQ",
        "食譜名稱",
        "上線日期",
        "關鍵字",
        "食譜網址",
        "材料",
        "做法步驟",
    ]

    missing = Counter()

    for row in rows:
        for field in fields:
            if row.get(field) in (None, ""):
                missing[field] += 1

    report = {
        "source": "local_json_test",
        "input": str(SRC),
        "total_recipes": len(rows),
        "missing_fields": dict(missing),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
