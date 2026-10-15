"""Pull final regular-season W-L for past seasons from Basketball-Reference,
for grading published win-total picks (scraper/grade_picks.py).

Writes data/final_records.json: {"seasons": {"2024-25": {"source", "teams": {abbr: {"w", "l"}}}, ...}}.
Fails (writes nothing) unless every season has all 30 teams, each W+L == 82,
and 1230 total wins and losses.

    python scraper/fetch_final_records.py
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teams import ABBRS, normalize  # noqa: E402

# Season label -> Basketball-Reference year (BBRef names a season by the year it ends)
SEASONS = {"2024-25": 2025, "2025-26": 2026}
URL = "https://www.basketball-reference.com/leagues/NBA_{year}_standings.html"
CRAWL_DELAY = 3  # basketball-reference robots.txt
OUT = Path(__file__).resolve().parent.parent / "data" / "final_records.json"
UA = "Mozilla/5.0 (compatible; nba-win-totals-portal/1.0; personal, manual runs)"


def fetch(year):
    url = URL.format(year=year)
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    records = {}
    for table_id in ("confs_standings_E", "confs_standings_W"):
        table = soup.find("table", id=table_id)
        if table is None:
            sys.exit(f"FAIL: table #{table_id} not found on {url}")
        for row in table.select("tbody tr"):
            link = row.select_one('th[data-stat="team_name"] a')
            if link is None:
                continue
            abbr = normalize(link["href"].split("/")[2])
            if abbr in records:
                sys.exit(f"FAIL: {abbr} appears twice on {url}")
            records[abbr] = {"w": int(row.select_one('td[data-stat="wins"]').get_text(strip=True)),
                             "l": int(row.select_one('td[data-stat="losses"]').get_text(strip=True))}
    return url, records


def check(label, records):
    errors = []
    missing = sorted(set(ABBRS) - set(records))
    if len(records) != 30 or missing:
        errors.append(f"{label}: expected 30 teams, got {len(records)}; missing {missing}")
    tw = sum(r["w"] for r in records.values())
    tl = sum(r["l"] for r in records.values())
    if tw != 1230 or tl != 1230:
        errors.append(f"{label}: total wins {tw} / losses {tl}, expected 1230 / 1230")
    errors += [f"{label}: {a} played {r['w'] + r['l']} games" for a, r in records.items() if r["w"] + r["l"] != 82]
    return errors


def main():
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seasons": {}}
    errors = []
    for i, (label, year) in enumerate(SEASONS.items()):
        if i:
            time.sleep(CRAWL_DELAY)
        url, records = fetch(year)
        errors += check(label, records)
        out["seasons"][label] = {"source": url, "teams": {a: records[a] for a in ABBRS if a in records}}
    if errors:
        sys.exit("FAIL:\n  " + "\n  ".join(errors))
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"OK: {', '.join(SEASONS)} -- 30 teams each, 1230 W / 1230 L -> {OUT}")


if __name__ == "__main__":
    main()
