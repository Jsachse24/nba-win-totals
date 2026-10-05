"""One-time pull of 2025-26 final regular season records from Basketball-Reference.

Writes data/last_season.json. Fails (and writes nothing) unless it finds all
30 teams and total wins == total losses == 1230.

    python scraper/fetch_last_season.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teams import ABBRS, normalize  # noqa: E402

URL = "https://www.basketball-reference.com/leagues/NBA_2026_standings.html"
OUT = Path(__file__).resolve().parent.parent / "data" / "last_season.json"
UA = "Mozilla/5.0 (compatible; nba-win-totals-portal/1.0; personal, manual runs)"


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
    if errors:
        sys.exit("FAIL:\n  " + "\n  ".join(errors))

    out = {
        "season": "2025-26",
        "source": URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": {a: records[a] for a in ABBRS},
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"OK: 30 teams, {tw} W / {tl} L -> {OUT}")


if __name__ == "__main__":
    main()
