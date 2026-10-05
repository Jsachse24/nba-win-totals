"""Source parsers. Each returns {book: {abbr: {"total", "over", "under"}}}.

Missing values are None. Anything ambiguous raises rather than guessing.

  - FanDuel:      FanDuel's public sportsbook content API (plain JSON, no auth).
                  Gives total + over + under for all 30 teams.
  - VegasInsider: server-rendered win totals table. Gives DraftKings, BetMGM
                  and Caesars total + OVER price only (VI does not show the
                  under side), so their under prices come from overrides or
                  show as "-".

Neither source exposes opening lines, so movement is measured from the
earliest snapshot we captured ("since first tracked").
"""
import re

import requests
from bs4 import BeautifulSoup

from teams import normalize

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
TIMEOUT = 30

FANDUEL_STATE = "nj"
FANDUEL_URL = (
    f"https://sbapi.{FANDUEL_STATE}.sportsbook.fanduel.com/api/content-managed-page"
    "?page=CUSTOM&customPageId=nba&pbHorizontal=false&_ak=FhMFpcPWXMeyZxOx"
    "&timezone=America%2FNew_York&tab=regular-season-wins"
)
FANDUEL_PAGE = "https://sportsbook.fanduel.com/navigation/nba?tab=regular-season-wins"
FANDUEL_MARKET_TYPE = "NBA_REGULAR_SEASON_WINS_O/U"
FANDUEL_SEASON_PREFIX = "26-27 NBA "

VI_URL = "https://www.vegasinsider.com/nba/odds/win-totals/"
# VI column header label -> our book key. Other VI books are ignored.
VI_BOOKS = {"draftkings": "draftkings", "betmgm": "betmgm", "caesars": "caesars"}


class SourceError(Exception):
    pass


def parse_american(s):
    s = s.strip().upper()
    if s in ("EV", "EVEN"):
        return 100
    if not re.fullmatch(r"[+-]?\d{3,4}", s):
        raise SourceError(f"Unparseable American odds: {s!r}")
    return int(s)


def _get(url, **kw):
    resp = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=TIMEOUT, **kw)
    if resp.status_code != 200:
        raise SourceError(f"HTTP {resp.status_code} from {url}")
    return resp


# ---------------------------------------------------------------- FanDuel

_FD_RUNNER = re.compile(r"^(?P<team>.+?) (?P<side>Over|Under) (?P<total>\d+(?:\.\d+)?) Wins?$")


def fetch_fanduel():
    data = _get(FANDUEL_URL).json()
    markets = data.get("attachments", {}).get("markets", {})
    out = {}
    for m in markets.values():
        if m.get("marketType") != FANDUEL_MARKET_TYPE:
            continue
        name = m.get("marketName", "")
        if not name.startswith(FANDUEL_SEASON_PREFIX):
            raise SourceError(f"FanDuel market is not 2026-27: {name!r}")
        team_label = name[len(FANDUEL_SEASON_PREFIX):].removesuffix(" Regular Season Wins")
        abbr = normalize(team_label)
        if abbr in out:
            raise SourceError(f"FanDuel has two win-total markets for {abbr}; ambiguous")
        rec = {"total": None, "over": None, "under": None}
        open_market = m.get("marketStatus") == "OPEN"
        totals = set()
        for r in m.get("runners", []):
            mt = _FD_RUNNER.match(r.get("runnerName", ""))
            if not mt:
                raise SourceError(f"Unexpected FanDuel runner: {r.get('runnerName')!r}")
            if normalize(mt["team"]) != abbr:
                raise SourceError(f"FanDuel runner/market team mismatch: {r.get('runnerName')!r}")
            totals.add(float(mt["total"]))
            if not open_market or r.get("runnerStatus") != "ACTIVE":
                continue  # suspended side -> leave price missing
            price = r["winRunnerOdds"]["americanDisplayOdds"]["americanOddsInt"]
            rec["over" if mt["side"] == "Over" else "under"] = int(price)
        if len(totals) != 1:
            raise SourceError(f"FanDuel {abbr} over/under totals disagree: {sorted(totals)}")
        if open_market:
            rec["total"] = totals.pop()
        out[abbr] = rec
    if not out:
        raise SourceError("FanDuel returned no regular-season-wins markets")
    return {"fanduel": out}


# ----------------------------------------------------------- VegasInsider

def _vi_cell(td):
    """Return (side, total, price) from a VI odds cell, or None if blank."""
    vals = [s.get_text(strip=True) for s in td.select("span.data-value")]
    vals = [v for v in vals if v]
    if not vals:
        return None
    if len(vals) != 2:
        raise SourceError(f"Unexpected VI cell contents: {vals}")
    line, price = vals
    m = re.fullmatch(r"([ou])(\d+(?:\.\d+)?)", line.lower())
    if not m:
        raise SourceError(f"Unexpected VI line: {line!r}")
    return ("over" if m[1] == "o" else "under"), float(m[2]), parse_american(price)


def fetch_vegasinsider():
    soup = BeautifulSoup(_get(VI_URL).text, "html.parser")
    table = soup.find("table", id="table-total-wins")
    if table is None:
        raise SourceError("VI table #table-total-wins not found (page layout changed?)")

    headers = [th.get_text(" ", strip=True).lower() for th in table.select("thead tr th")]
    # headers[0] is the team column; the rest line up with each row's odds cells.
    col_book = {}
    for i, h in enumerate(headers[1:]):
        if h in VI_BOOKS:
            col_book[i] = VI_BOOKS[h]
    if set(col_book.values()) != set(VI_BOOKS.values()):
        raise SourceError(f"VI is missing expected book columns. Headers: {headers}")

    out = {b: {} for b in VI_BOOKS.values()}
    for row in table.select("tbody tr"):
        team_img = row.select_one(".team-plate img")
        if team_img is None:
            continue
        abbr = normalize(team_img.get("alt", ""))
        cells = row.select("td.game-odds")
        for i, book in col_book.items():
            if abbr in out[book]:
                raise SourceError(f"VI lists {abbr} twice")
            rec = {"total": None, "over": None, "under": None}
            parsed = _vi_cell(cells[i]) if i < len(cells) else None
            if parsed:
                side, total, price = parsed
                rec["total"] = total
                rec[side] = price
            out[book][abbr] = rec
    if not any(out.values()):
        raise SourceError("VI table had no team rows")
    return out


SOURCES = {
    "fanduel": {"fetch": fetch_fanduel, "url": FANDUEL_PAGE, "label": "FanDuel API"},
    "vegasinsider": {"fetch": fetch_vegasinsider, "url": VI_URL, "label": "VegasInsider"},
}
