"""Validate the current data/lines.json + data/manual_overrides.json without scraping.

Use after hand-editing overrides (update.py --skip-scrape runs this).
Exits non-zero if validation fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (BOOKS, FIELDS, LINES, OVERRIDES, apply_overrides, empty_books,  # noqa: E402
                  load_json, print_summary, validate, validate_overrides)
from teams import ABBRS  # noqa: E402


def main():
    lines = load_json(LINES, {})
    books = empty_books()
    for a in ABBRS:
        for b in BOOKS:
            rec = (lines.get("teams") or {}).get(a, {}).get(b) or {}
            books[a][b] = {f: rec.get(f) for f in FIELDS}
    overrides = load_json(OVERRIDES, {"overrides": []})
    errors = validate_overrides(overrides)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit("\nFAIL: manual_overrides.json is invalid.")
    merged, src = apply_overrides(books, overrides)
    by_book = {b: {a: books[a][b] for a in ABBRS} for b in BOOKS}
    errors, warnings, total_sum = validate(merged, by_book)
    print_summary(merged, src, total_sum)
    print()
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit("\nFAIL: validation failed.")
    print("\nValidation OK.")


if __name__ == "__main__":
    main()
