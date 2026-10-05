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

### Suspected alternate lines (DraftKings)

VegasInsider's DraftKings column sometimes shows an alternate line (on 10/5:
BOS o53.5 +150 and PHI o48.5 -200, when every other book was at 50.5-51.5).
Nothing in VI's HTML marks main vs alternate, and DraftKings' own API blocks us,
so the scraper can't confirm the main line. Instead, a DraftKings total that's
**2+ wins off the median of the other books** is:

- stored as missing (`-`) in `lines.json`, listed under `suspect_alt_lines`;
- printed after the coverage table, and shown on the page as `alt?` plus a banner;
- also ignored in older snapshots when working out "first tracked" lines.

To fill it in, check the DraftKings app and add an override, e.g.
`{"team": "BOS", "book": "draftkings", "total": 51.5, "over": -110}`.
An override's total replaces the `alt?` flag. Settings: `SUSPECT_ALT_BOOKS` /
`ALT_LINE_WINS` in `scraper/core.py`.

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
- **Best over / best under (model EV).** Ranking by total first would make
  o48.5 -200 beat o50.5 -105, which isn't better value. So each offer is priced
  with a simple model instead:
  - Final wins are assumed to be normal around a center `mu` with SD
    `SIGMA = 8` wins (`index.html`). **8 is an assumption** (a typical miss of
    preseason totals), not a fitted number.
  - `mu` comes from FanDuel's no-vig line (the only book with both prices): it's
    the center that makes P(over FD's total) equal FD's no-vig over %. Without
    both FD prices it falls back to the consensus median.
  - For each book/side: P(cash) (with continuity correction, and pushes on whole
    numbers), then EV = P(win) x profit - P(lose). Best = highest EV. When totals
    match, that's just the better price.
  - Example (BOS, mu about 50.5): o48.5 -200 has about 60% to cash and needs 66.7%,
    so about -10% EV. o50.5 -105 is about -2%, so the 50.5 wins.
  - Hover any O/U price for its P(cash) and EV.
- **Missing prices.** DK/MGM/CZR under prices aren't on VegasInsider, so those
  offers can't be EV-ranked and are left out of Best under. In the full view and
  drawer, a price that's missing while the book has a line shows as a faded `-`
  (explained once in the legend). There are no per-cell flags.
- Price movement only shows when the total hasn't moved. Otherwise the prices are
  on different numbers and can't be compared. ▲ on a price = that side got more
  expensive (higher implied probability).
- Missing data is always `-`, never 0 or an estimate.

## Page features

- **Compact view (default):** Team, Div, 25-26, Pyth W, consensus Line / Move /
  vs LY, Best over (line, price, book) + Market EV, Best under + Market EV,
  Expert W, Rec, Analysts, My pick. **Full view** adds every book's Tot / O / U /
  NV O, plus Proj. The header row and Team column are sticky, so you keep your place
  when scrolling sideways. Mobile cards always use the compact set.
- **Team drawer:** click a row (or tap a card) to open a side drawer (a bottom
  sheet on mobile) with every book's line, no-vig %, Market EV per side, your pick,
  analyst sources and expert win numbers. Esc, the X, or clicking outside closes it.
- **Market EV:** the EV of the best over/under, priced against FanDuel's no-vig
  center (see Calculations). Sortable. It's line-shopping value, not a forecast.
- **Sorting:** click any header; click again to reverse. Missing values always
  sort last. Works in Flat, Conference and Division views. On mobile the Sort
  dropdown + arrow use the same sort state, and list the compact columns.
- **My picks:** tap a Best over/under cell, or any price in the drawer or full
  view. Tap again to untag; tagging another side/book replaces it (one per team).
  The pick stores side, book, line and price *at tagging time*, and shows `now 49.5`
  if that book's line later moves. "My picks only" filters to tagged teams. Saved
  in this browser's localStorage (`nbawt-picks`); if storage is blocked, picks work
  until the page reloads.
- **Analysts:** tally of stated sides, one per analyst (their latest pick for that
  team), e.g. `Over 3-1`. Sorts by net lean (overs minus unders). Details and
  source links are in the drawer.
- **Proj:** projected wins / difference vs consensus (`52.1 / +2.6`). Full view and drawer.

## Analyst picks and projections (`scraper/analyst_scraper.py`)

Separate from the lines scraper; re-run as new episodes come out (most annual
win-total episodes drop mid-to-late October).

| File | What |
|---|---|
| `data/analyst_sources.json` | approved analysts, approved sources (URL, title, date, kind), show pages to watch |
| `data/analyst_picks.json` | one record per pick: analyst, team, side, line, source_url, title, date, timestamp, summary, basis |
| `data/picks_review_log.json` | excluded / ambiguous items, with the reason |
| `data/projections.json` | team, projected_wins, system, source, date |
| `analyst_cache/` | fetched transcripts / article text (gitignored, local only) |

A script can't reliably tell "I'm taking the over" from "I like them" without
guessing, so extraction is a human/Claude step between fetch and merge:

```
python scraper/analyst_scraper.py discover        # new over/under episodes on the watched show pages (prints only)
#   -> add the ones you want to data/analyst_sources.json
python scraper/analyst_scraper.py fetch           # cache text for any new sources
python scraper/analyst_scraper.py fetch --cookies-from-browser chrome   # YouTube bot check (see below)
#   -> ask Claude: "read analyst_cache/<id>.txt and write picks to new_picks.json"
python scraper/analyst_scraper.py merge new_picks.json --dry-run
python scraper/analyst_scraper.py merge new_picks.json
python scraper/analyst_scraper.py validate
python scraper/analyst_scraper.py projections     # ESPN BPI -> data/projections.json
```

`new_picks.json` looks like `{"picks": [...], "review": [...]}`. Rules enforced by `merge`:

- analyst must be approved and the source URL listed in `analyst_sources.json`;
- team is canonical, side is `over`/`under`, line is null or 10-70 in half-wins;
- video sources need a timestamp; summary is your own words, max 200 chars;
- `basis` is `stated`, or `derived_from_wl_prediction` (Andy Bailey's W-L
  predictions vs the line he quoted; labelled on the page);
- duplicates (same analyst + team + source URL) are skipped, so re-runs are safe;
  a duplicate with a *different* side or line stops the merge for you to resolve;
- nothing is written if any item fails.

Ambiguous items (no stated side) go in `review`, never in `picks`.

**YouTube:** YouTube currently answers anonymous requests with "confirm you're not a
bot". `--cookies-from-browser chrome|edge|firefox` lets yt-dlp use your logged-in
YouTube session cookies from that browser (read locally; nothing is uploaded).

**Projections:** `projections` refuses to write until ESPN's BPI API returns the
2026-27 season (it currently falls back to 2025-26). It checks for 30 teams,
W+L = 82, and a sum near 1230.

`update.py` already commits everything under `data/`, so new picks and
projections publish with the next `python update.py`.
