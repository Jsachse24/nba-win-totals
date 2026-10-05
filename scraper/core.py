"""Shared logic: override merge, validation, terminal summary.

index.html applies overrides with the same rules (see applyOverrides there),
so the portal still works off manual_overrides.json if the scraper breaks.
"""
import json
import statistics
from pathlib import Path

from teams import ABBRS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LINES = DATA / "lines.json"
OVERRIDES = DATA / "manual_overrides.json"
SNAPSHOTS = DATA / "snapshots"

BOOKS = ["draftkings", "fanduel", "betmgm", "caesars"]
BOOK_SHORT = {"draftkings": "DK", "fanduel": "FD", "betmgm": "MGM", "caesars": "CZR"}
FIELDS = ("total", "over", "under")

TOTAL_MIN, TOTAL_MAX = 10, 70
ODDS_MIN, ODDS_MAX = -400, 400
EXPECTED_SUM, SUM_TOLERANCE = 1230, 30
OUTLIER_WINS = 2  # warn when a book is this far from the team's median total
VI_STALE_MAD = 4  # VI vs FanDuel mean abs diff above this = VI page looks stale

# VegasInsider's DraftKings column sometimes shows an alternate line (e.g. BOS
# o53.5 +150 when every other book is at 50.5-51.5). Nothing in VI's HTML marks
# main vs alternate, so a scraped total this far from the other books' median
# is treated as a suspected alt line: stored as missing and reported, never
# guessed at. Enter the real main line via manual_overrides.json.
SUSPECT_ALT_BOOKS = ("draftkings",)
ALT_LINE_WINS = 2


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def empty_books():
    return {a: {b: {f: None for f in FIELDS} for b in BOOKS} for a in ABBRS}


def validate_overrides(ov):
    """Return a list of error strings for a malformed overrides file."""
    errors = []
    if ov is None:
        return errors
    entries = ov.get("overrides")
    if not isinstance(entries, list):
        return ["manual_overrides.json: 'overrides' must be a list"]
    seen = set()
    for i, e in enumerate(entries):
        where = f"manual_overrides.json entry {i}"
        if e.get("team") not in ABBRS:
            errors.append(f"{where}: unknown team {e.get('team')!r} (use one of {', '.join(ABBRS)})")
        if e.get("book") not in BOOKS:
            errors.append(f"{where}: unknown book {e.get('book')!r} (use one of {', '.join(BOOKS)})")
        if not any(f in e for f in FIELDS):
            errors.append(f"{where}: sets none of {FIELDS}")
        t = e.get("total")
        if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float))):
            errors.append(f"{where}: total must be a number or null, got {t!r}")
        for side in ("over", "under"):
            p = e.get(side)
            if p is not None and (isinstance(p, bool) or not isinstance(p, int)):
                errors.append(f"{where}: {side} must be an integer (American odds) or null, got {p!r}")
        key = (e.get("team"), e.get("book"))
        if key in seen:
            errors.append(f"{where}: duplicate override for {key}")
        seen.add(key)
    return errors


def apply_overrides(books, ov):
    """Return (merged, sources) where sources[abbr][book][field] = 'scraped'|'override'|None.

    Rules (mirrored in index.html):
      - Only keys present in an override entry are applied. A key set to null
        clears the scraped value (shows "-").
      - If an override changes the total but doesn't give a price for a side,
        the scraped price for that side is dropped -- it was quoted on a
        different number, so it no longer applies.
    """
    merged = json.loads(json.dumps(books))
    src = {a: {b: {f: ("scraped" if merged[a][b][f] is not None else None) for f in FIELDS} for b in BOOKS} for a in ABBRS}
    for e in (ov or {}).get("overrides", []):
        a, b = e["team"], e["book"]
        rec = merged[a][b]
        if "total" in e and e["total"] != rec["total"]:
            for side in ("over", "under"):
                if side not in e:
                    rec[side] = None
                    src[a][b][side] = None
        for f in FIELDS:
            if f in e:
                rec[f] = e[f]
                src[a][b][f] = "override" if e[f] is not None else None
    return merged, src


def flag_suspect_alt_lines(books):
    """Return (books, suspects). Suspected alt lines are replaced with an empty
    record in a copy of `books`; the original records are left untouched."""
    out = {a: dict(bs) for a, bs in books.items()}
    suspects = []
    for a in ABBRS:
        for b in SUSPECT_ALT_BOOKS:
            rec = books[a][b]
            t = rec.get("total")
            others = [books[a][o]["total"] for o in BOOKS if o != b and books[a][o].get("total") is not None]
            if t is None or len(others) < 2:
                continue
            med = statistics.median(others)
            if abs(t - med) >= ALT_LINE_WINS:
                out[a][b] = {f: None for f in FIELDS}
                suspects.append({"team": a, "book": b, **{f: rec.get(f) for f in FIELDS}, "others_median": med})
    return out, suspects


def print_suspects(suspects):
    if not suspects:
        return
    print()
    print(f"Suspected alternate lines excluded ({len(suspects)}) -- shown as '-'; add the main line via manual_overrides.json:")
    for s in suspects:
        o = "-" if s["over"] is None else f"{s['over']:+d}"
        print(f"  {s['team']:<4} {BOOK_SHORT[s['book']]:<4} o{s['total']:g} {o}  vs other books' median {s['others_median']:g}"
              f" ({s['total'] - s['others_median']:+g})")


def consensus(merged, abbr):
    totals = [merged[abbr][b]["total"] for b in BOOKS if merged[abbr][b]["total"] is not None]
    return statistics.median(totals) if totals else None


def validate(merged, scraped_by_book=None):
    """Return (errors, warnings). Errors block writing lines.json."""
    errors, warnings = [], []
    if sorted(merged) != sorted(ABBRS):
        errors.append(f"expected the 30 canonical teams, got {len(merged)}")
    for a in ABBRS:
        for b in BOOKS:
            rec = merged.get(a, {}).get(b, {})
            t = rec.get("total")
            if t is not None and not (TOTAL_MIN <= t <= TOTAL_MAX):
                errors.append(f"{a} {b}: total {t} outside {TOTAL_MIN}-{TOTAL_MAX}")
            for side in ("over", "under"):
                p = rec.get(side)
                if p is None:
                    continue
                if not isinstance(p, int) or not (ODDS_MIN <= p <= ODDS_MAX) or -100 < p < 100:
                    errors.append(f"{a} {b}: {side} price {p} invalid (must be {ODDS_MIN} to {ODDS_MAX}, |odds| >= 100)")
                if t is None:
                    errors.append(f"{a} {b}: has a {side} price but no total")

    cons = {a: consensus(merged, a) for a in ABBRS}
    have = [c for c in cons.values() if c is not None]
    total = sum(have)
    if len(have) < 30:
        warnings.append(f"only {len(have)}/30 teams have a consensus line; sum check is partial")
    elif abs(total - EXPECTED_SUM) > SUM_TOLERANCE:
        warnings.append(f"sum of consensus totals is {total:g}, more than {SUM_TOLERANCE} off {EXPECTED_SUM}")

    for a in ABBRS:
        c = cons[a]
        for b in BOOKS:
            t = merged[a][b]["total"]
            if c is not None and t is not None and abs(t - c) >= OUTLIER_WINS:
                rec = merged[a][b]
                warnings.append(
                    f"{a} {BOOK_SHORT[b]} {t:g} (o{rec['over']}/u{rec['under']}) is {t - c:+g} vs median {c:g}"
                    " -- check it's the main line, override if not"
                )

    # VegasInsider's page text still says 2024-25. Guard against it serving a
    # stale season by comparing its books to FanDuel's live API.
    if scraped_by_book and scraped_by_book.get("fanduel"):
        fd = scraped_by_book["fanduel"]
        for b in ("draftkings", "betmgm", "caesars"):
            vb = scraped_by_book.get(b) or {}
            diffs = [abs(vb[a]["total"] - fd[a]["total"]) for a in ABBRS
                     if a in vb and a in fd and vb[a]["total"] is not None and fd[a]["total"] is not None]
            if diffs and statistics.mean(diffs) > VI_STALE_MAD:
                errors.append(f"{b} (VegasInsider) averages {statistics.mean(diffs):.1f} wins off FanDuel -- VI may be serving a stale season")
    return errors, warnings, total


def print_summary(merged, src, total_sum):
    print()
    print("Book coverage (T=total, O=over, U=under; * = from override; - = missing)")
    print(f"{'Team':<5} " + " ".join(f"{BOOK_SHORT[b]:<6}" for b in BOOKS) + " Cons")
    for a in ABBRS:
        cells = []
        for b in BOOKS:
            s = ""
            for f, ch in (("total", "T"), ("over", "O"), ("under", "U")):
                s += "-" if merged[a][b][f] is None else ch + ("*" if src[a][b][f] == "override" else "")
            cells.append(f"{s:<6}")
        missing = [BOOK_SHORT[b] for b in BOOKS if merged[a][b]["total"] is None]
        c = consensus(merged, a)
        flag = f"  <- no line from {', '.join(missing)}" if missing else ""
        print(f"{a:<5} " + " ".join(cells) + f" {c if c is not None else '-'}{flag}")

    print()
    missing_any = [a for a in ABBRS if any(merged[a][b]["total"] is None for b in BOOKS)]
    print(f"Teams missing a line from at least one book: {len(missing_any)}/30")
    for b in BOOKS:
        no_total = [a for a in ABBRS if merged[a][b]["total"] is None]
        no_over = sum(merged[a][b]["over"] is None for a in ABBRS)
        no_under = sum(merged[a][b]["under"] is None for a in ABBRS)
        line = f"  {BOOK_SHORT[b]:<4} totals {30 - len(no_total)}/30, over {30 - no_over}/30, under {30 - no_under}/30"
        if no_total:
            line += f"  (no line: {', '.join(no_total)})"
        print(line)
    print(f"Sum of consensus totals: {total_sum:g} (expected ~{EXPECTED_SUM})")
