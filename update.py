"""Scrape -> validate -> commit -> push (GitHub Pages redeploys on push).

    python update.py                 # full run
    python update.py --skip-scrape   # just validate overrides + publish (e.g. scraper broken)
    python update.py --partial       # publish even if one source failed
    python update.py --no-push       # commit locally only

Every run appends to logs/update.log (local only) and writes data/run_status.json,
which the page footer shows. A failed run still commits and pushes run_status.json,
so the live page says the last run failed instead of silently going stale.

When the scraper reports the board is down (scraper/scrape.py exits 3 after opening
night), this commits lines.json (marked off_board_since) + data/closing_lines.json
and disables the scheduled task.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "logs" / "update.log"
STATUS = ROOT / "data" / "run_status.json"
TASK_NAME = "NBA Win Totals daily update"  # created by schedule_task.ps1
OFF_BOARD_EXIT = 3  # scraper/scrape.py


def log(msg):
    print(msg)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S%z} {msg}\n")


def run(cmd, check=True):
    log(f"$ {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    print(out, end="")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(out)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {p.returncode}")
    return p


def last_line(p):
    lines = [l for l in ((p.stderr or "") + (p.stdout or "")).splitlines() if l.strip()]
    return lines[-1].strip() if lines else f"exit {p.returncode}"


def write_status(ok, state, message):
    prev = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    status = {"last_run": now, "ok": ok, "state": state, "message": message[:300],
              "last_success": now if ok else prev.get("last_success")}
    STATUS.write_text(json.dumps(status, indent=1) + "\n", encoding="utf-8")


def publish(paths, msg, push):
    run(["git", "add", *paths])
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        log("No changes to commit.")
        return
    run(["git", "commit", "-m", msg])
    if push:
        run(["git", "push"])
        log("Pushed. GitHub Pages usually updates within a minute or two.")
    else:
        log("Committed locally (--no-push).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()
    stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
    log(f"=== update.py {' '.join(sys.argv[1:])}")

    step = [sys.executable, "scraper/validate.py"] if args.skip_scrape else [sys.executable, "scraper/scrape.py"]
    if args.partial and not args.skip_scrape:
        step.append("--partial")
    p = run(step, check=False)

    try:
        if p.returncode == OFF_BOARD_EXIT:
            write_status(True, "off_board", "Win totals are off the board. Kept the last valid lines and saved closing_lines.json.")
            publish(["data"], f"Win totals off the board {stamp}: save closing lines", not args.no_push)
            r = subprocess.run(["schtasks", "/Change", "/TN", TASK_NAME, "/DISABLE"], capture_output=True, text=True)
            log("Scheduled task disabled." if r.returncode == 0 else f"Couldn't disable the scheduled task: {r.stderr.strip()}")
            return
        if p.returncode != 0:
            msg = last_line(p)
            write_status(False, "failed", msg)
            log(f"FAILED: {msg}")
            # Only the status file, so the page footer shows the failure
            publish([str(STATUS.relative_to(ROOT))], f"Update failed {stamp}", not args.no_push)
            sys.exit(1)
        write_status(True, "ok", "Overrides validated" if args.skip_scrape else "Scraped and validated")
        msg = f"Update lines {stamp}" + (" (overrides only)" if args.skip_scrape else "")
        publish(["data", "index.html"], msg, not args.no_push)
    except RuntimeError as e:
        log(f"FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
