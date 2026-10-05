"""Scrape 2026-27 NBA win totals, validate, write data/lines.json + a snapshot.

    python scraper/scrape.py             # strict: any source failure aborts
    python scraper/scrape.py --partial   # write even if a source failed (its books show "-")
    python scraper/scrape.py --dry-run   # scrape + validate + summary, write nothing

Nothing is written if validation fails.
"""
import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (BOOKS, FIELDS, LINES, OVERRIDES, SNAPSHOTS, apply_overrides,  # noqa: E402
                  empty_books, load_json, print_summary, validate, validate_overrides)
from sources import SOURCES, SourceError  # noqa: E402
from teams import ABBRS  # noqa: E402

# Which source supplies each book.
BOOK_SOURCE = {"fanduel": "fanduel", "draftkings": "vegasinsider", "betmgm": "vegasinsider", "caesars": "vegasinsider"}


def compute_opening(current_teams, now_iso):
    """Opening = earliest snapshot in which each team/book had a total.

    Neither source publishes opening lines, so this is "since first tracked".
    """
    snaps = sorted(SNAPSHOTS.glob("*.json"))
    history = [load_json(p) for p in snaps] + [{"captured_at": now_iso, "teams": current_teams}]
    opening = {a: {b: None for b in BOOKS} for a in ABBRS}
    for snap in history:
        for a in ABBRS:
            for b in BOOKS:
                if opening[a][b] is not None:
                    continue
                rec = snap["teams"].get(a, {}).get(b)
                if rec and rec.get("total") is not None:
                    opening[a][b] = {**{f: rec.get(f) for f in FIELDS}, "at": snap["captured_at"]}
    first = history[0]["captured_at"]
    return opening, first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partial", action="store_true", help="write even if a source failed")
    ap.add_argument("--dry-run", action="store_true", help="don't write anything")
    args = ap.parse_args()

    now = datetime.now().astimezone()
    now_iso = now.isoformat(timespec="seconds")

    books = empty_books()
    by_book = {}
    source_status = {}
    failed = []
    for key, s in SOURCES.items():
        try:
            result = s["fetch"]()
        except Exception as e:  # noqa: BLE001 -- report every failure the same way
            failed.append(key)
            source_status[key] = {"ok": False, "error": f"{type(e).__name__}: {e}", "url": s["url"], "fetched_at": now_iso}
            print(f"SOURCE FAILED: {s['label']}: {e}", file=sys.stderr)
            if not isinstance(e, (SourceError, ValueError)):
                traceback.print_exc()
            continue
        source_status[key] = {"ok": True, "url": s["url"], "fetched_at": now_iso, "books": sorted(result)}
        for book, teams in result.items():
            if BOOK_SOURCE.get(book) != key:
                continue
            by_book[book] = teams
            for abbr, rec in teams.items():
                books[abbr][book] = rec

    if failed and not args.partial:
        sys.exit(f"\nFAIL: source(s) failed: {', '.join(failed)}. lines.json NOT written. "
                 "Re-run with --partial to publish without them, or fill gaps via manual_overrides.json.")

    overrides = load_json(OVERRIDES, {"overrides": []})
    ov_errors = validate_overrides(overrides)
    merged, src = apply_overrides(books, overrides) if not ov_errors else (books, None)
    errors, warnings, total_sum = validate(merged, by_book)
    errors = ov_errors + errors

    if src is not None:
        print_summary(merged, src, total_sum)
    print()
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        print()
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit("\nFAIL: validation failed. lines.json NOT written.")

    if args.dry_run:
        print("\nDry run OK -- nothing written.")
        return

    opening, first = compute_opening(books, now_iso)
    out = {
        "season": "2026-27",
        "generated_at": now_iso,
        "opening_basis": "first_tracked",
        "first_tracked_at": first,
        "book_source": BOOK_SOURCE,
        "sources": source_status,
        "teams": books,
        "opening": opening,
    }
    LINES.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOTS / f"{now:%Y-%m-%d_%H%M}.json"
    snap = {"captured_at": now_iso, "sources": source_status, "teams": books}
    snap_path.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    print(f"\nOK: wrote {LINES.relative_to(LINES.parent.parent)} and {snap_path.relative_to(LINES.parent.parent)}")


if __name__ == "__main__":
    main()
