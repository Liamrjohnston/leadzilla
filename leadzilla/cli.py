"""leadzilla — find and qualify business leads, judged by Jev.

  leadzilla run --niche "real estate brokerages" --place "Vancouver, BC" \
      --offer "AI marketing automation for brokerages" --target 50 --out leads.csv
  leadzilla export --niche ... --place ... --offer ... --out leads.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .jev import Jev
from . import export as E
from .pipeline import Run
from .store import Store

def export(store: Store, cid: int, path: str, fmt: str | None = None) -> int:
    return E.write(store.leads(cid), path, E.guess_format(path, fmt))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="leadzilla", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "export"):
        p = sub.add_parser(name)
        p.add_argument("--niche", required=True)
        p.add_argument("--place", required=True)
        p.add_argument("--offer", required=True, help="what you sell; leads are scored against it")
        p.add_argument("--db", default="~/.leadzilla/leadzilla.db")
        p.add_argument("--out", default="leads.csv", help="file to write; .xlsx gives a formatted spreadsheet")
        p.add_argument("--format", default=None, choices=["csv", "xlsx", "instantly", "smartlead", "lemlist", "linkedin"],
                       help="file layout (default from the --out extension)")
        if name == "run":
            p.add_argument("--target", type=int, default=50, help="new leads to find this run")
            p.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one site")
            p.add_argument("--browser", action="store_true", help="retry JavaScript-only pages in a browser")
            p.add_argument("--backend", choices=["http", "composio"], default=None)
            p.add_argument("--stats", default=None, help="write run stats JSON here")
            p.add_argument("--no-search", action="store_true", help="OpenStreetMap only, skip web search")
            p.add_argument("--radius-km", type=float, default=15.0, help="widen the place's map bounds by this much")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        s = Store(a.db)
        n = export(s, s.campaign(a.niche, a.place, a.offer), a.out, a.format)
        print(f"{n} leads -> {a.out}")
        return 0
    jev = Jev(backend=a.backend)
    logging.getLogger("scrapling").setLevel(logging.ERROR)
    run = Run(a.niche, a.place, a.offer, a.target, a.db, jev, delay=a.delay, browser=a.browser,
              use_search=not a.no_search, radius_km=a.radius_km)
    stats = run.go()
    n = export(run.store, run.cid, a.out, a.format)
    j, c = stats["jev"], stats["claude_estimate"]
    print(f"\nLEADZILLA: {stats['kept']} new leads ({n} in this campaign) -> {a.out}")
    print(f"  sites checked {stats['sites_checked']}, pages read {stats['pages_fetched']}, "
          f"{stats['seconds']}s")
    print(f"  Jev: {j['calls']} calls, {j['input_tokens']:,} tokens, ${j['cost_usd']:.4f}")
    print(f"  Same pages read by Claude (estimate): Haiku ${c['haiku']:.2f}, Sonnet ${c['sonnet']:.2f}, "
          f"Opus ${c['opus']:.2f}")
    if a.stats:
        with open(a.stats, "w") as f:
            json.dump(stats, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
