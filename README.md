# NBA Win Totals 2026-27

Preseason over/under win totals for all 30 teams across DraftKings, FanDuel,
BetMGM and Caesars. It's a static page (`index.html`) that reads JSON from `data/`.

## Where the numbers come from

| Book | Source | Total | Over | Under |
|---|---|---|---|---|
| FanDuel | FanDuel's public sportsbook API (`sbapi.nj.sportsbook.fanduel.com`) | yes | yes | yes |
| DraftKings, BetMGM, Caesars | [VegasInsider win totals table](https://www.vegasinsider.com/nba/odds/win-totals/) | yes | yes | **no** |

- VegasInsider only publishes the over side, so DK/MGM/Caesars under prices
  (and their no-vig %) show `-` unless you add them in `manual_overrides.json`.
- Neither source has opening lines. "Movement" is measured from the earliest
  snapshot we captured, labelled "since first tracked".
- VegasInsider's page text still says 2024-25. The table is current, but the
  scraper fails if VI's numbers average more than 4 wins off FanDuel's, in
  case it ever starts serving a stale season.
- DraftKings and Caesars block direct API requests (Akamai/CloudFront 403s),
  which is why they come through VegasInsider.
- 2025-26 records come from Basketball-Reference (`scraper/fetch_last_season.py`,
  a one-time pull, verified 30 teams / 1230 W / 1230 L).

## Setup

```
pip install -r requirements.txt
```

## Running the scraper

```
python scraper/scrape.py             # scrape, validate, write data/lines.json + data/snapshots/<time>.json
python scraper/scrape.py --dry-run   # same, writes nothing
python scraper/scrape.py --partial   # write even if one source failed (its books show "-")
```

It prints a coverage table (T/O/U per book, `*` = override, `-` = missing)
and warnings. **Nothing is written if validation fails:**

- exactly the 30 canonical teams; every source label must map to one
- totals 10-70, odds -400..+400 (and |odds| >= 100)
- a price without a total is an error
- any source failing is an error unless `--partial`

Warnings (don't block): the sum of consensus lines is more than 30 off 1230,
or one book is 2+ wins off the team's median (possibly an alt line, so check it).

## Overrides

`data/manual_overrides.json` beats scraped data for a team/book. The page applies
it too, so if the scraper breaks you can edit this file and publish.

```json
{
  "overrides": [
    {"team": "BOS", "book": "caesars", "total": 50.5, "over": -115, "under": -105, "note": "Caesars app 10/5"},
    {"team": "PHI", "book": "draftkings", "under": -120},
    {"team": "TOR", "book": "betmgm", "total": null}
  ]
}
```

- `team` is the abbreviation (BOS, BKN, NYK, PHI, TOR, CHI, CLE, DET, IND, MIL,
  ATL, CHA, MIA, ORL, WAS, DEN, MIN, OKC, POR, UTA, GSW, LAC, LAL, PHX, SAC,
  DAL, HOU, MEM, NOP, SAS).
- `book` is one of `draftkings`, `fanduel`, `betmgm`, `caesars`.
- Only the keys you include apply. `null` clears a value (shows `-`).
- If you change `total` without giving a price for a side, the scraped price for
  that side is dropped, since it was quoted on a different number.
- Override cells get a yellow dot on the page.

Check overrides without scraping: `python scraper/validate.py`.

## Publishing

```
python update.py                 # scrape -> validate -> git commit -> git push
python update.py --skip-scrape   # overrides-only change: validate -> commit -> push
python update.py --no-push       # commit locally only
```

GitHub Pages serves the repo root from `main`. One-time setup:
Settings -> Pages -> Source "Deploy from a branch", branch `main`, folder `/ (root)`.

## Viewing locally

Browsers block `fetch()` from `file://`, so serve the folder:

```
python -m http.server 8000      # then open http://localhost:8000
```

## Calculations

- Implied prob: `-A/(-A+100)` for negative odds, `100/(A+100)` for positive.
- No-vig: over and under implied probabilities normalized to sum to 100%
  (needs both prices).
- Consensus: median total across the books that have a line. The page shows a
  book count when fewer than 4 have one.
- Delta vs last season: consensus minus 2025-26 wins.
- Best over: lowest total, then best over price. Best under: highest total,
  then best under price. A book with a total but no price for that side still
  qualifies on the number; at equal totals a known price ranks ahead of a missing one.
- Price movement only shows when the total hasn't moved. Otherwise the prices are
  on different numbers and can't be compared. ▲ on a price = that side got more
  expensive (higher implied probability).
- Missing data is always `-`, never 0 or an estimate.
