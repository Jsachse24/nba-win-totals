"""Analyst win-total picks + projections. Separate from the lines scraper.

A script can fetch transcripts and articles, but it can't reliably tell
"I'm taking the over" from "I like them" without guessing. So the work is split:

  1. discover  -- list new over/under episodes on the watched show pages
                  (prints only; add the ones you want to data/analyst_sources.json)
  2. fetch     -- download each source's text into analyst_cache/ (gitignored):
                  YouTube captions + description via yt-dlp, article text via requests
  3. (Claude reads the cached text and writes a picks file -- see README)
  4. merge F   -- validate picks/review items in file F and add them to
                  data/analyst_picks.json / data/picks_review_log.json, skipping duplicates
  5. projections -- pull ESPN BPI projected wins into data/projections.json
                  (fails loudly until ESPN publishes 2026-27 numbers)

    python scraper/analyst_scraper.py discover
    python scraper/analyst_scraper.py fetch [--source ID] [--force] [--cookies-from-browser chrome]
    python scraper/analyst_scraper.py merge new_picks.json [--dry-run]
    python scraper/analyst_scraper.py validate
    python scraper/analyst_scraper.py projections [--dry-run]
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import DATA, ROOT, load_json  # noqa: E402
from teams import ABBRS  # noqa: E402

SOURCES = DATA / "analyst_sources.json"
PICKS = DATA / "analyst_picks.json"
REVIEW = DATA / "picks_review_log.json"
PROJECTIONS = DATA / "projections.json"
CACHE = ROOT / "analyst_cache"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
SIDES = ("over", "under")
BASES = ("stated", "derived_from_wl_prediction")
SUMMARY_MAX = 200  # own-words summary, not a quote
PICK_FIELDS = ("analyst", "team", "side", "line", "source_url", "title", "date", "timestamp", "summary", "basis")
REVIEW_FIELDS = ("analyst", "team", "source_url", "title", "date", "timestamp", "reason")
DISCOVER_RE = re.compile(r"over[-\s/]?unders?|win[-\s]totals?", re.I)

BPI_URL = "https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/nba/powerindex?season=2027&limit=50"
BPI_PAGE = "https://www.espn.com/nba/bpi"
BPI_SEASON = 2027  # ESPN labels 2026-27 as 2027
# ESPN abbreviations that differ from ours
ESPN_ABBR = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRK": "BKN"}


class Bad(Exception):
    pass


def save(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        raise Bad(f"HTTP {r.status_code} from {url}")
    return r


def sources_cfg():
    cfg = load_json(SOURCES)
    if cfg is None:
        sys.exit(f"missing {SOURCES}")
    return cfg


# ------------------------------------------------------------- discover

def cmd_discover(_args):
    cfg = sources_cfg()
    known = {s["url"].rstrip("/") for s in cfg["sources"]}
    for w in cfg.get("watch", []):
        try:
            soup = BeautifulSoup(get(w["url"]).text, "html.parser")
        except Exception as e:  # noqa: BLE001
            print(f"!! {w['name']}: {e}")
            continue
        found = {}
        for a in soup.find_all("a", href=True):
            href = requests.compat.urljoin(w["url"], a["href"]).split("?")[0].rstrip("/")
            if not href.startswith(w["url"].rstrip("/") + "/"):
                continue
            text = a.get_text(" ", strip=True)
            if DISCOVER_RE.search(href) or DISCOVER_RE.search(text):
                found[href] = found.get(href) or text
        new = {h: t for h, t in found.items() if h not in known}
        print(f"== {w['name']}: {len(new)} new candidate(s)")
        for h, t in sorted(new.items()):
            print(f"   {t[:90] or '(no title)'}\n   {h}")


# ---------------------------------------------------------------- fetch

def _vtt_to_text(vtt):
    """Collapse a (rolling auto-caption) VTT into '[mm:ss] text' lines, ~20s per line."""
    out, seen_tail, bucket, bucket_t = [], "", [], None
    for block in vtt.split("\n\n"):
        m = re.search(r"(\d+):(\d\d):(\d\d)\.\d+ -->", block)
        if not m:
            continue
        secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        lines = [re.sub(r"<[^>]+>", "", ln).strip() for ln in block.split("\n")[1:]]
        for ln in lines:
            if not ln or "-->" in ln or ln == seen_tail:
                continue
            seen_tail = ln
            if bucket_t is None:
                bucket_t = secs
            bucket.append(ln)
        if bucket and secs - bucket_t >= 20:
            out.append(f"[{bucket_t // 60:02d}:{bucket_t % 60:02d}] " + " ".join(bucket))
            bucket, bucket_t = [], None
    if bucket:
        out.append(f"[{bucket_t // 60:02d}:{bucket_t % 60:02d}] " + " ".join(bucket))
    return "\n".join(out)


def fetch_youtube(src, cookies_browser):
    try:
        import yt_dlp
    except ImportError:
        raise Bad("yt-dlp not installed (pip install yt-dlp)")
    tmp = CACHE / "_yt"
    tmp.mkdir(parents=True, exist_ok=True)
    opts = {
        "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-orig"], "subtitlesformat": "vtt",
        "outtmpl": str(tmp / "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True,
        "js_runtimes": {"node": {}},
    }
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(src["url"], download=True)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "not a bot" in msg:
            raise Bad("YouTube bot check -- re-run with --cookies-from-browser <chrome|edge|firefox>")
        raise Bad(msg)
    vtts = sorted(tmp.glob(f"{info['id']}*.vtt"))
    if not vtts:
        raise Bad("no English captions available for this video")
    # Prefer human captions over auto-generated ones
    vtt = next((p for p in vtts if ".en." in p.name and "orig" not in p.name), vtts[0])
    body = _vtt_to_text(vtt.read_text(encoding="utf-8"))
    head = [f"TITLE: {info.get('title')}", f"UPLOAD DATE: {info.get('upload_date')}",
            f"CHANNEL: {info.get('channel')}", f"CAPTIONS: {vtt.name}", "", "DESCRIPTION:",
            info.get("description") or "", "", "TRANSCRIPT:"]
    for p in vtts:
        p.unlink()
    return "\n".join(head) + "\n" + body


def fetch_article(src):
    soup = BeautifulSoup(get(src["url"]).text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "aside", "form"]):
        t.decompose()
    # Pages can have several <article>s (headers, related stories); use the one with the most prose.
    cands = soup.find_all(["article", "main"]) + [soup.body]
    root = max(cands, key=lambda c: sum(len(p.get_text()) for p in c.find_all("p")))
    paras = [p.get_text(" ", strip=True) for p in root.find_all(["h1", "h2", "h3", "p", "li"])]
    text = "\n".join(p for p in paras if p)
    title = soup.title.get_text(strip=True) if soup.title else ""
    warn = "\nWARNING: very little text -- probably paywalled or JS-rendered.\n" if len(text) < 1500 else ""
    return f"TITLE: {title}{warn}\n\nTEXT:\n{text}"


def cmd_fetch(args):
    cfg = sources_cfg()
    CACHE.mkdir(exist_ok=True)
    todo = [s for s in cfg["sources"] if not args.source or s["id"] == args.source]
    if args.source and not todo:
        sys.exit(f"no source with id {args.source!r}")
    failed = 0
    for s in todo:
        out = CACHE / f"{s['id']}.txt"
        if out.exists() and not args.force:
            print(f"   cached  {s['id']}")
            continue
        try:
            body = fetch_youtube(s, args.cookies_from_browser) if s["kind"] == "youtube" else fetch_article(s)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"!! FAILED {s['id']}: {e}")
            continue
        out.write_text(f"SOURCE ID: {s['id']}\nURL: {s['url']}\nFETCHED: {datetime.now().isoformat(timespec='seconds')}\n"
                       + body + "\n", encoding="utf-8")
        print(f"   fetched {s['id']} -> {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    if failed:
        sys.exit(f"\n{failed} source(s) failed.")


# ----------------------------------------------------------- validation

def _analysts(cfg):
    return {a["name"] for a in cfg["analysts"]}


def _source_by_url(cfg):
    return {s["url"]: s for s in cfg["sources"]}


def pick_key(p):
    return (p["analyst"], p["team"], p["source_url"])


def pick_id(p):
    return hashlib.sha1("|".join(pick_key(p)).encode()).hexdigest()[:12]


def _check_date(v, where, errs):
    try:
        date.fromisoformat(v)
    except (TypeError, ValueError):
        errs.append(f"{where}: date must be YYYY-MM-DD, got {v!r}")


def validate_pick(p, cfg, where):
    errs = []
    missing = [f for f in PICK_FIELDS if f not in p]
    if missing:
        return [f"{where}: missing field(s) {missing}"]
    src = _source_by_url(cfg).get(p["source_url"])
    if p["analyst"] not in _analysts(cfg):
        errs.append(f"{where}: analyst {p['analyst']!r} isn't approved in analyst_sources.json")
    if p["team"] not in ABBRS:
        errs.append(f"{where}: unknown team {p['team']!r}")
    if p["side"] not in SIDES:
        errs.append(f"{where}: side must be over/under, got {p['side']!r}")
    if p["line"] is not None and (not isinstance(p["line"], (int, float)) or isinstance(p["line"], bool)
                                  or not 10 <= p["line"] <= 70 or (p["line"] * 2) % 1):
        errs.append(f"{where}: line must be null or a number 10-70 in half-win steps, got {p['line']!r}")
    if src is None:
        errs.append(f"{where}: source_url isn't listed in analyst_sources.json")
    elif src["kind"] == "youtube" and not p["timestamp"]:
        errs.append(f"{where}: video source needs a timestamp")
    if p["timestamp"] and not re.fullmatch(r"(\d+:)?\d{1,2}:\d\d", p["timestamp"]):
        errs.append(f"{where}: timestamp must look like 12:34 or 1:02:03, got {p['timestamp']!r}")
    _check_date(p["date"], where, errs)
    if not p["summary"] or len(p["summary"]) > SUMMARY_MAX:
        errs.append(f"{where}: summary must be 1-{SUMMARY_MAX} chars (own words, no long quotes)")
    if p["basis"] not in BASES:
        errs.append(f"{where}: basis must be one of {BASES}")
    return errs


def validate_review(r, cfg, where):
    errs = []
    missing = [f for f in REVIEW_FIELDS if f not in r]
    if missing:
        return [f"{where}: missing field(s) {missing}"]
    if r["team"] is not None and r["team"] not in ABBRS:
        errs.append(f"{where}: unknown team {r['team']!r}")
    if r["source_url"] not in _source_by_url(cfg):
        errs.append(f"{where}: source_url isn't listed in analyst_sources.json")
    _check_date(r["date"], where, errs)
    if not r["reason"]:
        errs.append(f"{where}: reason is required")
    return errs


def validate_files(cfg):
    errs = []
    picks = load_json(PICKS, {"picks": []})["picks"]
    seen = {}
    for i, p in enumerate(picks):
        errs += validate_pick(p, cfg, f"analyst_picks.json #{i}")
        if all(f in p for f in ("analyst", "team", "source_url")):
            k = pick_key(p)
            if k in seen:
                errs.append(f"analyst_picks.json #{i}: duplicate of #{seen[k]} {k}")
            seen[k] = i
    for i, r in enumerate(load_json(REVIEW, {"items": []})["items"]):
        errs += validate_review(r, cfg, f"picks_review_log.json #{i}")
    errs += validate_projections(load_json(PROJECTIONS, {"projections": []}))
    return errs


def validate_projections(pj):
    errs = []
    rows = pj.get("projections", [])
    if not rows:
        return errs
    teams = [r.get("team") for r in rows]
    if sorted(teams) != sorted(ABBRS):
        errs.append(f"projections.json: need exactly the 30 canonical teams, got {len(set(teams))}")
    for r in rows:
        w = r.get("projected_wins")
        if not isinstance(w, (int, float)) or not 5 <= w <= 77:
            errs.append(f"projections.json {r.get('team')}: projected_wins {w!r} out of range")
        for f in ("system", "source", "date"):
            if not r.get(f):
                errs.append(f"projections.json {r.get('team')}: missing {f}")
    if not errs:
        s = sum(r["projected_wins"] for r in rows)
        if abs(s - 1230) > 30:
            errs.append(f"projections.json: projected wins sum to {s:g}, expected ~1230")
    return errs


def cmd_validate(_args):
    errs = validate_files(sources_cfg())
    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    if errs:
        sys.exit("\nFAIL: analyst data invalid.")
    n = len(load_json(PICKS, {"picks": []})["picks"])
    print(f"Analyst data OK ({n} picks).")


# ---------------------------------------------------------------- merge

def cmd_merge(args):
    cfg = sources_cfg()
    incoming = load_json(Path(args.file))
    if incoming is None:
        sys.exit(f"no such file {args.file}")
    picks_doc = load_json(PICKS, {"picks": []})
    review_doc = load_json(REVIEW, {"items": []})
    existing = {pick_key(p): p for p in picks_doc["picks"]}
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    errs, added, dup = [], [], 0
    for i, p in enumerate(incoming.get("picks", [])):
        e = validate_pick(p, cfg, f"incoming pick #{i}")
        if e:
            errs += e
            continue
        k = pick_key(p)
        if k in existing:
            old = existing[k]
            if old["side"] != p["side"] or old["line"] != p["line"]:
                errs.append(f"incoming pick #{i} {k}: conflicts with existing record "
                            f"({old['side']} {old['line']} vs {p['side']} {p['line']}) -- resolve by hand")
            else:
                dup += 1
            continue
        rec = {"id": pick_id(p), **{f: p[f] for f in PICK_FIELDS}, "added_at": now}
        existing[k] = rec
        added.append(rec)

    rev_keys = {(r["analyst"], r["team"], r["source_url"], r["timestamp"]) for r in review_doc["items"]}
    rev_added = []
    for i, r in enumerate(incoming.get("review", [])):
        e = validate_review(r, cfg, f"incoming review #{i}")
        if e:
            errs += e
            continue
        k = (r["analyst"], r["team"], r["source_url"], r["timestamp"])
        if k in rev_keys:
            dup += 1
            continue
        rev_keys.add(k)
        rev_added.append({**{f: r[f] for f in REVIEW_FIELDS}, "note": r.get("note", ""), "added_at": now})

    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    if errs:
        sys.exit("\nFAIL: nothing merged.")
    print(f"{len(added)} new pick(s), {len(rev_added)} new review item(s), {dup} duplicate(s) skipped.")
    for r in added:
        print(f"  + {r['analyst']:<16} {r['team']} {r['side']:<5} {r['line'] if r['line'] is not None else '-'}")
    if args.dry_run:
        print("Dry run -- nothing written.")
        return
    picks_doc["picks"] += added
    picks_doc["picks"].sort(key=lambda p: (p["team"], p["analyst"], p["date"]))
    review_doc["items"] += rev_added
    save(PICKS, picks_doc)
    save(REVIEW, review_doc)


# ---------------------------------------------------------- projections

def cmd_projections(args):
    d = get(BPI_URL).json()
    req = (d.get("requestedSeason") or {}).get("year")
    if req != BPI_SEASON:
        sys.exit(f"FAIL: ESPN BPI returned season {req} ({(d.get('requestedSeason') or {}).get('displayName')}), "
                 f"not 2026-27 -- 2026-27 projections aren't published yet. projections.json NOT written.")
    cat_names = {c["name"]: c["names"] for c in d["categories"]}
    wi = cat_names["projections"].index("projectedw")
    li = cat_names["projections"].index("projectedl")
    today = date.today().isoformat()
    rows, errs = [], []
    for t in d["teams"]:
        ab = t["team"]["abbreviation"]
        ab = ESPN_ABBR.get(ab, ab)
        proj = next(c for c in t["categories"] if c["name"] == "projections")
        w, l = proj["values"][wi], proj["values"][li]
        if w is None or l is None or abs(w + l - 82) > 0.6:
            errs.append(f"{ab}: projected {w}-{l} doesn't add to 82")
        rows.append({"team": ab, "projected_wins": w, "system": "ESPN BPI", "source": BPI_PAGE,
                     "date": (d.get("lastUpdated") or today)[:10]})
    doc = {"system": "ESPN BPI", "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "projections": sorted(rows, key=lambda r: r["team"])}
    errs += validate_projections(doc)
    for e in errs:
        print(f"ERROR: {e}", file=sys.stderr)
    if errs:
        sys.exit("FAIL: projections.json NOT written.")
    for r in doc["projections"]:
        print(f"  {r['team']:<4} {r['projected_wins']:.1f}")
    if args.dry_run:
        print("Dry run -- nothing written.")
        return
    save(PROJECTIONS, doc)
    print(f"Wrote {PROJECTIONS.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover").set_defaults(fn=cmd_discover)
    f = sub.add_parser("fetch")
    f.add_argument("--source")
    f.add_argument("--force", action="store_true", help="re-fetch even if cached")
    f.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="let yt-dlp read your YouTube cookies from this browser (gets past the bot check)")
    f.set_defaults(fn=cmd_fetch)
    m = sub.add_parser("merge")
    m.add_argument("file")
    m.add_argument("--dry-run", action="store_true")
    m.set_defaults(fn=cmd_merge)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    p = sub.add_parser("projections")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_projections)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
