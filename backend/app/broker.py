"""Angel One holdings sync. READ-ONLY: the app only ever reads your holdings; there is no order, trade or fund-transfer code anywhere.

The snapshot is stored in `broker_holdings`, replaced on each sync. `app.portfolio` merges it with the transactions you entered yourself.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import BrokerHolding
from app.providers.base import ProviderError

SOURCE = "angelone"
SETUP_STEPS = [
    "Create a free SmartAPI app at smartapi.angelone.in (log in with your Angel One account) and copy its API key.",
    "In the Angel One app, enable TOTP and copy the TOTP secret text shown beside the QR code (the long code, not the 6 digits).",
    "Put ANGEL_API_KEY, ANGEL_CLIENT_CODE (your login ID), ANGEL_PIN and ANGEL_TOTP_SECRET in the .env file and restart the backend.",
    "Come back here and press Sync my holdings. The app only reads your holdings and prices; it can never place orders.",
]
HINTS = {"AG8001": "Angel One rejected the API key (invalid token). Check ANGEL_API_KEY.", "AB1010": "Angel One rejected the login. Check client code, PIN and TOTP secret.",
         "AB1050": "Angel One says the TOTP is wrong. Check ANGEL_TOTP_SECRET and that your computer's clock is accurate."}


def missing_fields(creds: dict[str, str]) -> list[str]:
    names = {"api_key": "ANGEL_API_KEY", "client": "ANGEL_CLIENT_CODE", "pin": "ANGEL_PIN", "totp": "ANGEL_TOTP_SECRET"}
    return [names[k] for k, v in creds.items() if not v]


def status(db: Session, angel) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    rows = list(db.scalars(select(BrokerHolding).where(BrokerHolding.source == SOURCE)))
    return {"configured": angel.is_configured(), "missing": missing_fields(angel.creds), "steps": SETUP_STEPS, "holdings": len(rows),
            "last_sync": max((r.synced_at for r in rows), default=None), "read_only": True}


def friendly(e: Exception) -> str:
    msg = str(e)
    for code, hint in HINTS.items():
        if code in msg:
            return f"{hint} (Angel One said: {msg[:120]})"
    return msg[:300]


def store(db: Session, holdings: list[dict]) -> dict[str, Any]:
    """Replace the stored snapshot and report what changed since the last sync."""
    now = int(time.time())
    old = {r.symbol: r for r in db.scalars(select(BrokerHolding).where(BrokerHolding.source == SOURCE))}
    new = {h["symbol"]: h for h in holdings}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(s for s in set(new) & set(old) if abs(new[s]["qty"] - old[s].qty) > 1e-9 or abs(new[s]["avg_price"] - old[s].avg_price) > 1e-6)
    for r in old.values():
        db.delete(r)
    db.flush()
    for h in holdings:
        db.add(BrokerHolding(source=SOURCE, symbol=h["symbol"], exchange=h["exchange"], isin=h["isin"], qty=h["qty"], avg_price=h["avg_price"], ltp=h["ltp"], synced_at=now))
    db.commit()
    return {"count": len(holdings), "added": added, "removed": removed, "changed": changed, "synced_at": now}


async def sync(db: Session, angel) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    if not angel.is_configured():
        return {"ok": False, "configured": False, "missing": missing_fields(angel.creds), "steps": SETUP_STEPS,
                "message": "Angel One is not connected yet. Add your SmartAPI details to .env (steps below)."}
    try:
        holdings = await angel.fetch_holdings()
    except ProviderError as e:
        return {"ok": False, "configured": True, "message": friendly(e)}
    return {"ok": True, "configured": True, **store(db, holdings)}
