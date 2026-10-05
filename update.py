"""Scrape -> validate -> commit -> push (GitHub Pages redeploys on push).

    python update.py                 # full run
    python update.py --skip-scrape   # just validate overrides + publish (e.g. scraper broken)
    python update.py --partial       # publish even if one source failed
    python update.py --no-push       # commit locally only
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--partial", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    step = [sys.executable, "scraper/validate.py"] if args.skip_scrape else [sys.executable, "scraper/scrape.py"]
    if args.partial and not args.skip_scrape:
        step.append("--partial")
    if run(step, check=False).returncode != 0:
        sys.exit("\nStopped: scrape/validation failed. Nothing committed.")

    run(["git", "add", "data", "index.html"])
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("\nNo data changes to commit.")
        return
    msg = f"Update lines {datetime.now():%Y-%m-%d %H:%M}" + (" (overrides only)" if args.skip_scrape else "")
    run(["git", "commit", "-m", msg])
    if args.no_push:
        print("\nCommitted locally (--no-push).")
        return
    if run(["git", "push"], check=False).returncode != 0:
        sys.exit("\nCommit made but push failed -- check the remote, then `git push`.")
    print("\nPushed. GitHub Pages usually updates within a minute or two.")


if __name__ == "__main__":
    main()
