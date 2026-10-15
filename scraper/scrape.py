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
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (BOOK_SHORT, BOOKS, FIELDS, LINES, OVERRIDES, SNAPSHOTS, apply_overrides,  # noqa: E402
                  empty_books, flag_suspect_alt_lines, load_json, print_summary, print_suspects,
                  validate, validate_overrides)
from sources import SOURCES, SourceError  # noqa: E402
from teams import ABBRS  # noqa: E402

CLOSING = LINES.parent / "closing_lines.json"
# 2026-27 opening night. Win totals usually come off the board around tip-off.
SEASON_START = date(2026, 10, 20)
MIN_TEAMS_ON_BOARD = 15  # fewer teams with any line than this = board pulled (or a parser broke)
OFF_BOARD_EXIT = 3       # update.py stops the scheduled job on this
UNCHANGED_MIN_HOURS = 12

# Which source supplies each book.
BOOK_SOURCE = {"fanduel": "fanduel", "draftkings": "vegasinsider", "betmgm": "vegasinsider", "caesars": "vegasinsider"}


def load_history():
    """Earlier snapshots as [(captured_at, raw books)], oldest first. Snapshots
    store suspected alt lines blanked, so their raw values are restored from
    the snapshot's suspect_alt_lines list."""
    history = []
    for p in sorted(SNAPSHOTS.glob("*.json")):
        snap = load_json(p)
        books = _complete(snap["teams"])
        for s in snap.get("suspect_alt_lines") or []:
            books[s["team"]][s["book"]] = {f: s.get(f) for f in FIELDS}
        history.append((snap["captured_at"], books))
    return history


def compute_opening(history, current_teams, now_iso):
    """Opening = earliest snapshot in which each team/book had a total.

    Neither source publishes opening lines, so this is "since first tracked".
    Suspected alt lines are dropped from older snapshots too (judged against
    the snapshots before each one), so an alt line captured before that check
    existed can't become a team's "opening" line.
    """
    full = history + [(now_iso, current_teams)]
    opening = {a: {b: None for b in BOOKS} for a in ABBRS}
    for i, (at, raw) in enumerate(full):
        teams, _, _ = flag_suspect_alt_lines(raw, full[:i])
        for a in ABBRS:
            for b in BOOKS:
                if opening[a][b] is not None:
                    continue
                rec = teams[a][b]
                if rec.get("total") is not None:
                    opening[a][b] = {**{f: rec.get(f) for f in FIELDS}, "at": at}
    return opening, full[0][0]


def _complete(teams):
    books = empty_books()
    for a in ABBRS:
        for b in BOOKS:
            rec = teams.get(a, {}).get(b) or {}
            books[a][b] = {f: rec.get(f) for f in FIELDS}
    return books


def unchanged_books(raw, history, now):
    """Books whose total/over/under match the latest snapshot at least
    UNCHANGED_MIN_HOURS old, for all 30 teams. A source serving a cached page
    looks exactly like this. (Runs minutes apart are expected to match.)"""
    older = [(at, b) for at, b in history if (now - datetime.fromisoformat(at)).total_seconds() >= UNCHANGED_MIN_HOURS * 3600]
    if not older:
        return [], None
    at, prev = older[-1]
    return [b for b in BOOKS
            if any(raw[a][b]["total"] is not None for a in ABBRS)
            and all(raw[a][b] == prev[a][b] for a in ABBRS)], at


def off_board(now, now_iso, on_board, failed, dry_run):
    """Too few teams have a line. Never overwrite lines.json with blanks. After
    opening night that means the board came down: mark lines.json and save it as
    closing_lines.json. Before then it's treated as a broken source."""
    msg = f"only {on_board}/30 teams have a line from any book" + (f" (failed: {', '.join(failed)})" if failed else "")
    if now.date() < SEASON_START:
        sys.exit(f"\nFAIL: {msg}, before opening night ({SEASON_START}). Looks like a source problem, "
                 "not the board coming down. lines.json NOT written.")
    print(f"\nOFF THE BOARD: {msg}. Keeping the last valid lines.")
    if dry_run:
        sys.exit(OFF_BOARD_EXIT)
    lines = load_json(LINES)
    if lines and not lines.get("off_board_since"):
        lines["off_board_since"] = now_iso
        LINES.write_text(json.dumps(lines, indent=1) + "\n", encoding="utf-8")
    if lines and not CLOSING.exists():
        closing = {**lines, "closing_basis": "last valid scrape before win totals came off the board"}
        CLOSING.write_text(json.dumps(closing, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {CLOSING.name} from the {lines['generated_at']} scrape.")
    sys.exit(OFF_BOARD_EXIT)


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

    on_board = sum(1 for a in ABBRS if any(books[a][b]["total"] is not None for b in BOOKS))
    if on_board < MIN_TEAMS_ON_BOARD:
        off_board(now, now_iso, on_board, failed, args.dry_run)

    if failed and not args.partial:
        sys.exit(f"\nFAIL: source(s) failed: {', '.join(failed)}. lines.json NOT written. "
                 "Re-run with --partial to publish without them, or fill gaps via manual_overrides.json.")

    raw = books
    history = load_history()
    books, suspects, stale = flag_suspect_alt_lines(raw, history)
    stale_books, compared_at = unchanged_books(raw, history, now)

    overrides = load_json(OVERRIDES, {"overrides": []})
    ov_errors = validate_overrides(overrides)
    merged, src = apply_overrides(books, overrides) if not ov_errors else (books, None)
    errors, warnings, total_sum = validate(merged, by_book)
    errors = ov_errors + errors

    if src is not None:
        print_summary(merged, src, total_sum)
    print_suspects(suspects, stale)
    print()
    for b in stale_books:
        warnings.append(f"{BOOK_SHORT[b]} numbers are identical to the {compared_at[:16]} snapshot for all 30 teams. "
                        "Kept, but flagged on the page as possibly stale")
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

    opening, first = compute_opening(history, raw, now_iso)
    out = {
        "season": "2026-27",
        "generated_at": now_iso,
        "opening_basis": "first_tracked",
        "first_tracked_at": first,
        "book_source": BOOK_SOURCE,
        "sources": source_status,
        "teams": books,
        "suspect_alt_lines": suspects,
        "stale_lines": stale,
        "possibly_stale_books": stale_books,
        "opening": opening,
    }
    LINES.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOTS / f"{now:%Y-%m-%d_%H%M}.json"
    snap = {"captured_at": now_iso, "sources": source_status, "teams": books, "suspect_alt_lines": suspects, "stale_lines": stale}
    snap_path.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    print(f"\nOK: wrote {LINES.relative_to(LINES.parent.parent)} and {snap_path.relative_to(LINES.parent.parent)}")


if __name__ == "__main__":
    main()
