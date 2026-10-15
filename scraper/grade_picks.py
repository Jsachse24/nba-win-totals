"""Grade published past-season win-total picks against final records.

Input:  data/track_record_picks.json  -- picks collected from public archives
        data/final_records.json       -- final W-L (scraper/fetch_final_records.py)
Output: data/track_records.json       -- per person per season W-L-P, plus each graded pick

A pick only counts if it was published by that season's opening night (same day OK),
states a side, and the line is known (the person stated it, or line_disclosed
is false and `line` is the market line on the publish date from `line_source`).
Picks with no usable line are listed as ungraded, never guessed. A whole-number
line that lands exactly is a push (not counted in the win rate).

    python scraper/grade_picks.py            # validate, grade, write, print table
    python scraper/grade_picks.py --dry-run  # validate + print only
    python scraper/grade_picks.py --picks X.json --out Y.json   # e.g. candidates, kept out of data/ until approved
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import DATA, load_json  # noqa: E402
from teams import ABBRS  # noqa: E402

PICKS = DATA / "track_record_picks.json"
FINALS = DATA / "final_records.json"
OUT = DATA / "track_records.json"
OPENING_NIGHT = {"2024-25": date(2024, 10, 22), "2025-26": date(2025, 10, 21)}
NOISE_PICKS = 20  # fewer graded picks than this is noise, and labelled that way


def validate(picks):
    errs = []
    seen = set()
    for i, p in enumerate(picks):
        w = f"pick {i} ({p.get('person')} {p.get('season')} {p.get('team')})"
        if not p.get("person"):
            errs.append(f"{w}: no person")
        if p.get("season") not in OPENING_NIGHT:
            errs.append(f"{w}: season must be one of {list(OPENING_NIGHT)}")
            continue
        if p.get("team") not in ABBRS:
            errs.append(f"{w}: unknown team")
        if p.get("side") not in ("over", "under"):
            errs.append(f"{w}: side must be over/under")
        ln = p.get("line")
        if ln is not None and (not isinstance(ln, (int, float)) or not 10 <= ln <= 70 or (ln * 2) % 1):
            errs.append(f"{w}: bad line {ln!r}")
        if not isinstance(p.get("line_disclosed"), bool):
            errs.append(f"{w}: line_disclosed must be true/false")
        if ln is not None and not p["line_disclosed"] and not p.get("line_source"):
            errs.append(f"{w}: line not disclosed by the person, so line_source must say where the line came from")
        if not p.get("source_url", "").startswith("http"):
            errs.append(f"{w}: source_url required")
        try:
            d = date.fromisoformat(p.get("date") or "")
        except ValueError:
            errs.append(f"{w}: date must be YYYY-MM-DD")
        else:
            # Same-day pieces count (games tip in the evening); anything later doesn't
            if d > OPENING_NIGHT[p["season"]]:
                errs.append(f"{w}: published {d}, after opening night {OPENING_NIGHT[p['season']]}")
        key = (p.get("person"), p.get("season"), p.get("team"))
        if key in seen:
            errs.append(f"{w}: duplicate person/season/team (keep their final stated pick only)")
        seen.add(key)
    return errs


def grade(p, finals):
    if p.get("line") is None:
        return None, None
    wins = finals[p["season"]]["teams"][p["team"]]["w"]
    if wins == p["line"]:
        return wins, "push"
    over_hit = wins > p["line"]
    return wins, "win" if over_hit == (p["side"] == "over") else "loss"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--picks", type=Path, default=PICKS, help="input picks file (default data/track_record_picks.json)")
    ap.add_argument("--out", type=Path, default=OUT, help="output file (default data/track_records.json)")
    args = ap.parse_args()
    picks = (load_json(args.picks) or {}).get("picks", [])
    finals = (load_json(FINALS) or {}).get("seasons", {})
    errs = validate(picks)
    missing = sorted({p.get("season") for p in picks} - set(finals))
    if missing:
        errs.append(f"no final records for {missing}; run scraper/fetch_final_records.py")
    if errs:
        sys.exit("FAIL:\n  " + "\n  ".join(errs))

    graded, people = [], {}
    for p in picks:
        wins, res = grade(p, finals)
        graded.append({**p, "final_wins": wins, "result": res})
        s = people.setdefault(p["person"], {}).setdefault(p["season"], {"w": 0, "l": 0, "p": 0, "ungraded": 0, "n": 0, "lines_disclosed": 0})
        s["n"] += 1
        s["lines_disclosed"] += bool(p["line_disclosed"])
        s[{"win": "w", "loss": "l", "push": "p", None: "ungraded"}[res]] += 1
    for seasons in people.values():
        tot = {"w": 0, "l": 0, "p": 0, "ungraded": 0, "n": 0, "lines_disclosed": 0}
        for s in seasons.values():
            for k in tot:
                tot[k] += s[k]
        seasons["total"] = tot
        for s in seasons.values():
            dec = s["w"] + s["l"]
            s["win_rate"] = round(s["w"] / dec, 3) if dec else None
            s["sample"] = "noise" if s["w"] + s["l"] + s["p"] < NOISE_PICKS else "ok"

    print(f"{'Person':<24} {'Season':<8} {'W-L-P':<9} {'Win%':<6} {'Graded':<7} {'Lines disclosed':<16} Sample")
    for name in sorted(people):
        for season, s in people[name].items():
            wr = f"{s['win_rate'] * 100:.0f}%" if s["win_rate"] is not None else "-"
            print(f"{name:<24} {season:<8} {s['w']}-{s['l']}-{s['p']:<5} {wr:<6} {s['w'] + s['l'] + s['p']:<7} "
                  f"{s['lines_disclosed']}/{s['n']:<14} {'under ' + str(NOISE_PICKS) + ' = noise' if s['sample'] == 'noise' else ''}")
    if args.dry_run:
        print("\nDry run -- nothing written.")
        return
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "noise_below": NOISE_PICKS,
           "opening_night": {k: v.isoformat() for k, v in OPENING_NIGHT.items()}, "people": people, "graded": graded}
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nOK: wrote {args.out}")


if __name__ == "__main__":
    main()
