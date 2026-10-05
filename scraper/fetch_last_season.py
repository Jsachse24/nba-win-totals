"""One-time pull of 2025-26 final regular season records from Basketball-Reference.

Writes data/last_season.json: actual W-L (standings page) plus Pythagorean
W-L (league page, "Advanced Stats" table, PW / PL). Fails (and writes nothing)
unless it finds all 30 teams, total wins == total losses == 1230, every
Pythagorean W+L == 82, and Pythagorean wins sum to within PYTH_SUM_TOL of 1230.

    python scraper/fetch_last_season.py
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teams import ABBRS, normalize  # noqa: E402

URL = "https://www.basketball-reference.com/leagues/NBA_2026_standings.html"
PYTH_URL = "https://www.basketball-reference.com/leagues/NBA_2026.html"
PYTH_SUM_TOL = 15  # Pythagorean wins don't sum to exactly 1230, but should be close
CRAWL_DELAY = 3  # basketball-reference robots.txt
OUT = Path(__file__).resolve().parent.parent / "data" / "last_season.json"
UA = "Mozilla/5.0 (compatible; nba-win-totals-portal/1.0; personal, manual runs)"


def fetch_pyth():
    """{abbr: {"pw", "pl"}} from the league page's advanced-team table (it may sit inside an HTML comment)."""
    resp = requests.get(PYTH_URL, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", id="advanced-team")
    if table is None:
        for c in soup.find_all(string=lambda t: isinstance(t, Comment) and 'id="advanced-team"' in t):
            table = BeautifulSoup(c, "html.parser").find("table", id="advanced-team")
    if table is None:
        sys.exit(f"FAIL: table #advanced-team not found on {PYTH_URL}")
    out = {}
    for row in table.select("tbody tr"):
        link = row.select_one('[data-stat="team"] a')
        if link is None:
            continue
        abbr = normalize(link["href"].split("/")[2])
        if abbr in out:
            sys.exit(f"FAIL: {abbr} appears twice in #advanced-team")
        out[abbr] = {"pw": int(row.select_one('td[data-stat="wins_pyth"]').get_text(strip=True)),
                     "pl": int(row.select_one('td[data-stat="losses_pyth"]').get_text(strip=True))}
    return out


def main():
    resp = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    records = {}
    for table_id in ("confs_standings_E", "confs_standings_W"):
        table = soup.find("table", id=table_id)
        if table is None:
            sys.exit(f"FAIL: table #{table_id} not found on {URL}")
        for row in table.select("tbody tr"):
            link = row.select_one('th[data-stat="team_name"] a')
            if link is None:
                continue
            # href is /teams/XXX/2026.html
            abbr = normalize(link["href"].split("/")[2])
            wins = int(row.select_one('td[data-stat="wins"]').get_text(strip=True))
            losses = int(row.select_one('td[data-stat="losses"]').get_text(strip=True))
            if abbr in records:
                sys.exit(f"FAIL: {abbr} appears twice")
            records[abbr] = {"w": wins, "l": losses}

    time.sleep(CRAWL_DELAY)
    pyth = fetch_pyth()

    missing = sorted(set(ABBRS) - set(records))
    tw = sum(r["w"] for r in records.values())
    tl = sum(r["l"] for r in records.values())
    errors = []
    if len(records) != 30 or missing:
        errors.append(f"expected 30 teams, got {len(records)}; missing {missing}")
    if tw != 1230 or tl != 1230:
        errors.append(f"total wins {tw} / losses {tl}, expected 1230 / 1230")
    for abbr, r in records.items():
        if r["w"] + r["l"] != 82:
            errors.append(f"{abbr} played {r['w'] + r['l']} games, expected 82")
    pmissing = sorted(set(ABBRS) - set(pyth))
    if len(pyth) != 30 or pmissing:
        errors.append(f"Pythagorean: expected 30 teams, got {len(pyth)}; missing {pmissing}")
    for abbr, r in pyth.items():
        if r["pw"] + r["pl"] != 82:
            errors.append(f"{abbr} Pythagorean {r['pw']}-{r['pl']} doesn't add to 82")
    psum = sum(r["pw"] for r in pyth.values())
    if abs(psum - 1230) > PYTH_SUM_TOL:
        errors.append(f"Pythagorean wins sum to {psum}, more than {PYTH_SUM_TOL} off 1230")
    if errors:
        sys.exit("FAIL:\n  " + "\n  ".join(errors))
    for a in ABBRS:
        records[a].update(pyth[a])

    out = {
        "season": "2025-26",
        "source": URL,
        "pyth_source": PYTH_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": {a: records[a] for a in ABBRS},
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"OK: 30 teams, {tw} W / {tl} L; Pythagorean wins sum to {psum} -> {OUT}")
    print("Team  W   PW  Luck")
    for a in ABBRS:
        r = records[a]
        print(f"{a:<5} {r['w']:<3} {r['pw']:<3} {r['w'] - r['pw']:+d}")


if __name__ == "__main__":
    main()
