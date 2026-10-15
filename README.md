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
- Since about 10/15, VegasInsider's win-totals table also holds a second market
  (30 rows of bare prices like OKC +120, which look like title odds). Rows with no
  o/u line are skipped and counted in the output. A team listed twice with a
  win-total line still fails the scrape.
- DraftKings and Caesars block direct API requests (Akamai/CloudFront 403s),
  which is why they come through VegasInsider.
- 2025-26 records come from Basketball-Reference (`scraper/fetch_last_season.py`,
  a one-time pull, verified 30 teams / 1230 W / 1230 L). The same script pulls
  2025-26 **Pythagorean W-L** (league page, Advanced Stats table: PW/PL) and
  fails unless all 30 teams are present, each PW+PL = 82, and the PW total is
  within 15 of 1230 (it was 1239 on 10/5).

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

**Unless it's a lagging main line.** Before excluding it, the scraper checks the
snapshot history: if DraftKings matched the other books (within 2 wins) in an earlier
snapshot, hasn't changed its number since, and the other books' median has moved
**1.5+ wins** (`STALE_MOVE_WINS`) from that point, DK is just slow to move. That line is:

- kept in the table (it counts toward consensus and Best over/under like any main line);
- listed under `stale_lines` in `lines.json`, printed after the coverage table, and
  shown on the page as `stale?` plus a banner. Hover it to see the date it last matched.

It compares against the latest snapshot where DK still matched the market, not only
the one right before it. Otherwise a lagging line would flip back to `alt?` on the
next scrape, once the other books had stopped moving.

Re-evaluated 10/15 under the snapshot rule (Oct 12 data):

| Team | DK | Other books' median, Oct 5 -> Oct 12 | Result |
|---|---|---|---|
| CHA | o39.5 +100 (both dates) | 39.5 -> 37.5 (moved 2.0) | `stale?`, kept |
| BOS | o53.5 +150 (both dates) | 50.5 -> 51.5 (moved 1.0; DK already 3 off on Oct 5) | `alt?`, excluded |
| PHI | o48.5 -200 (both dates) | 50.5 -> 50.5 (no move) | `alt?`, excluded |

Keeping CHA DK puts CHA's consensus at 38.5 (four books) instead of 37.5.

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

### Daily scheduled run

A Windows Task Scheduler job, **NBA Win Totals daily update**, runs `run_update.cmd`
(which runs `python update.py`) every day at 9:00 AM while you're logged in. If the PC
was off at 9, it runs at the next chance. It runs locally on purpose: sportsbook pages
tend to block cloud IPs, so there's no GitHub Actions job.

```
powershell -File schedule_task.ps1               # (re)register, default 9:00AM
powershell -File schedule_task.ps1 -At 7:30AM    # change the time
schtasks /Run /TN "NBA Win Totals daily update"  # run it now
```

- Every run appends to `logs/update.log` (local, gitignored) and writes
  `data/run_status.json`, which the page footer shows ("Scheduled update: last run ...").
  A failed run commits and pushes only `run_status.json`, so the live footer says
  **last run FAILED** with the error and the last success time. The lines stay as they were.
- **Possibly stale book:** if a book's numbers match the latest snapshot that's 12+ hours
  old (`UNCHANGED_MIN_HOURS`) for all 30 teams, the scrape still goes through, but the page
  shows a banner saying that book's source may be serving a cached page.
- **Board comes down:** if fewer than 15 teams have a line from any book, nothing is
  overwritten. Before opening night (`SEASON_START` = 2026-10-20) that counts as a source
  failure. After opening night, the scraper marks `lines.json` with `off_board_since`
  (the header then says "final: off the board"), saves the last valid scrape as
  `data/closing_lines.json`, and exits 3. `update.py` commits and pushes that, then
  disables the scheduled task.
- Data fetches on the page add a `?t=` query string, which bypasses GitHub Pages'
  10-minute CDN cache as well as the browser's.

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
  offers can't be EV-ranked and are left out of Best under. The Best under column
  is labelled "FanDuel only for most teams" until a second source for those under
  prices is added (overrides can still add one). In the full view and
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
- **Biggest movers strip** (above the table): top 5 consensus line moves and top 5
  price moves since first tracked (Oct 5), with direction. Price moves are the change
  in implied probability for one book/side, only where that book's total hasn't moved
  (▲ pricier = that side got more expensive). Click an item to open the team.
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
- **Analysts:** tally of *explicitly stated* sides only (dataset A), one per
  analyst (their latest pick for that team), e.g. `Over 3-1`. Sorts by net lean
  (overs minus unders). Details and source links are in the drawer.
- **Expert W:** average of published win numbers / predicted records (dataset B),
  one per expert (their latest), with the source count: `52.3 (4)`. The drawer
  lists every source with date and link.
- **Rec:** expert average minus the consensus line. `Over +1.8` / `Under -2.1` when
  the gap is at least `REC_THRESHOLD` (1.5) wins; `No lean` below that; `Thin` when
  fewer than `REC_MIN_SOURCES` (3) independent experts have a number (the gap is
  still shown). Both constants sit at the top of the script in `index.html`. Sorts
  by the gap. This is a comparison to published opinions, not a model.
- **Proj:** projected wins / difference vs consensus (`52.1 / +2.6`). Full view and drawer.
- **Pyth W / Luck:** 2025-26 Pythagorean wins (from point differential) and
  Luck = actual wins minus Pyth W. Positive luck means a team won more than its
  margin suggests. Both sortable.
- **Hold:** per book per team, implied over + implied under minus 100%, only where
  both prices exist (today that's FanDuel). Shown in the full view (each book's
  header also shows its average hold) and in the drawer.
- **Sum check (header):** the sum of the 30 consensus lines vs the 1230 wins that
  exist. Above 1230 means the market implies more wins than exist, which favors
  unders collectively; below favors overs.
- **Notes:** free text per team, typed in the drawer and autosaved to this browser
  (`nbawt-notes`). A ✎ shows in the row when a note exists (hover to read it).
  The Note column sorts teams with notes first.
- **Export / Import:** Export downloads one JSON file with your picks, notes and
  parlay slips. Import on another device replaces that browser's picks, notes and
  slips after a confirmation that shows the counts. No backend.

## Parlay builder

Open **Parlay slips** (a drawer on desktop, a bottom sheet on mobile).

- **Slips:** multiple named slips, each with a **book selector** and an optional
  stake. Parlays are placed at one book, so every leg uses that book's current line
  and price. A leg the book has no line or price for is flagged, and the combined
  numbers show `-` until you switch book or remove it.
- **Adding legs:** from My Picks (checkboxes in the panel), or from any team's drawer
  (`+ Over` / `+ Under`, added to the selected slip; a slip is created if none
  exists). The same team can't be in one slip twice.
- **Per leg:** team, side, line, price, market probability (the existing model at
  that book's line), an optional **my probability %** override (saved with the
  slip), and leg EV.
- **Summary:** combined American and decimal odds, payout per $100 (and on your
  stake), implied probability (1 / decimal), model probability (product of legs,
  using your % where entered), and EV %. Negative-EV legs get a warning. The UI
  notes that the product **assumes independence**. Pushes on whole-number lines
  count as losses.
- **Correlation flags (per pair of legs):**
  - same division, both overs or both unders: slightly *negatively* correlated
    (4 head-to-head games, each a win for one and a loss for the other);
  - same division, over one and under the rival: *positively* correlated, the same
    thesis twice; some books restrict it;
  - same conference (different division): a lighter flag.
- **Exposure** (straight picks + all slips): overs vs unders, counts by conference
  and division, total stake, and teams that appear in more than one slip.
- Slips are stored in this browser (`nbawt-slips`) and travel with Export / Import.

## Expert best bets (below the table)

- **Per-expert cards** for the people listed in `data/best_bets.json` (starting set:
  Simmons, Lowe, Windhorst, Shams). A card only shows picks with a `best_bet` label
  in `analyst_picks.json`, meaning the person explicitly called it a best bet,
  favorite, lock or top pick, or put it in a ranked list. Ranked picks keep their
  stated order (`#1`, `#2`...). Labeled but unranked picks show as `unranked`.
  Conviction is never inferred from tone.
- Each pick shows team, side, the line they took, today's consensus and whether it
  **moved with or against** them (over: a higher line is against; under: a lower one
  is), plus today's best available price for that side (same Market EV pick as the
  table), the source (title, date, link, and timestamp for audio/video; YouTube links
  jump to it), and buttons for **+ My Picks** (tags that best line) or **+ slip**.
- No qualifying picks shows "No published win total best bets found" with the
  `checked_on` date from `best_bets.json`. It is never filled in.
- **Track-record badge** (e.g. `2025-26: 7-4 on stated picks (n=11, small sample)`)
  appears only when `data/track_records.json` has graded picks for that person. Under
  20 graded picks is labelled a small sample.
- **Consensus best bets:** the same team + side labeled a best bet by 2+ independent
  approved analysts (anyone in `analyst_sources.json`, not just the cards), ranked by
  how many. **Conflicts:** teams with best bets on both sides.

## Track records (`scraper/grade_picks.py`)

```
python scraper/fetch_final_records.py   # 2024-25 + 2025-26 final W-L from Basketball-Reference -> data/final_records.json
python scraper/grade_picks.py           # grade data/track_record_picks.json -> data/track_records.json
```

`track_record_picks.json` holds past-season picks collected from public archives:
person, season, team, side, line, `line_disclosed`, date, source. The grader refuses
picks dated after opening night (2024-10-22 / 2025-10-21; same-day pieces count, since games tip in the evening), duplicates, and a
line the person didn't state unless `line_source` says where it came from. Picks with
no line are counted as ungraded, never guessed. A whole-number line that lands exactly
is a push. Each season reports W-L-P, win rate and lines disclosed, and gets flagged
as a small sample under 20 graded picks.

Candidates for new analysts are researched and graded the same way, but **they're not
added to `analyst_sources.json` (or the page) until approved**.

## Analyst picks and projections (`scraper/analyst_scraper.py`)

Separate from the lines scraper; re-run as new episodes come out (most annual
win-total episodes drop mid-to-late October).

| File | What |
|---|---|
| `data/analyst_sources.json` | approved analysts, approved sources (URL, title, date, kind), show pages to watch |
| `data/analyst_picks.json` | **A.** explicitly stated sides only: analyst, team, side, line, source_url, title, date, timestamp, summary, basis (`stated`) |
| `data/expert_wins.json` | **B.** stated win numbers / predicted records: expert, team, wins, losses (records only), kind (`record` / `projected_wins`), source_url, title, date, timestamp, note |
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
python scraper/analyst_scraper.py validate        # also prints the coverage report
python scraper/analyst_scraper.py coverage        # teams with 0 / 1 / 2 / 3+ independent sources, per dataset
python scraper/analyst_scraper.py projections     # ESPN BPI -> data/projections.json
```

The input file looks like `{"picks": [...], "expert_wins": [...], "review": [...]}`.
A predicted record goes in `expert_wins`. Never turn it into a side in `picks`; the
page compares the expert average to the line instead. Rules enforced by `merge`:

- analyst must be approved and the source URL listed in `analyst_sources.json`;
- team is canonical, side is `over`/`under`, line is null or 10-70 in half-wins;
- video sources need a timestamp; summary is your own words, max 200 chars;
- `basis` must be `stated` (derived sides aren't allowed in dataset A);
- optional `best_bet`: `{"label": "best bet|favorite|lock|top pick|ranked", "rank": 1|null,
  "list_name": "...", "evidence": "how they labeled it, own words"}`. `ranked` needs a
  rank. Re-merging a pick that's already stored with a new `best_bet` adds the label;
  a different label from the stored one stops the merge;
- expert_wins: `record` needs integer wins + losses = 82; `projected_wins` has
  `losses: null`; same source/approval/date/timestamp rules as picks;
- duplicates (same person + team + source URL) are skipped, so re-runs are safe;
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
