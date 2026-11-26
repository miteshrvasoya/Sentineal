"""Refresh data/nse_equities.csv from the NSE's published equity list (needs internet access to nseindia.com)."""
import csv
import io
import sys
from pathlib import Path

import httpx

URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
OUT = Path(__file__).resolve().parents[2] / "data" / "nse_equities.csv"


def main() -> int:
    r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    rows = {}
    for x in csv.DictReader(io.StringIO(r.text)):
        x = {k.strip(): (v or "").strip() for k, v in x.items()}
        sym = x.get("SYMBOL", "").upper()
        if sym and x.get("NAME OF COMPANY") and all(c.isalnum() or c in "&-_" for c in sym):
            rows[sym] = (sym, x["NAME OF COMPANY"], x.get("ISIN NUMBER", ""))
    if len(rows) < 1500:
        print(f"Only {len(rows)} rows: refusing to overwrite {OUT}")
        return 1
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "isin"])
        w.writerows(sorted(rows.values()))
    print(f"Wrote {len(rows)} companies to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
