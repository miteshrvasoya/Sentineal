"""Indian equity transaction costs (delivery segment) as an editable model.

RATES CHANGE. The defaults below are approximate figures for NSE cash-market delivery trades as commonly published by
Indian brokers; check your broker's current rate card and the exchange/SEBI/government circulars, then edit them.
The point of the model is to make the order of magnitude visible: costs are a fixed drag on every round trip.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CostModel:
    brokerage_pct: float = 0.0          # fraction of trade value (discount brokers charge 0 on delivery)
    brokerage_flat: float = 0.0         # rupees per order
    brokerage_cap: float = 0.0          # rupees per order cap (0 = none)
    stt_buy: float = 0.001              # securities transaction tax, delivery: 0.1% on buy and on sell
    stt_sell: float = 0.001
    exchange_txn: float = 0.0000297     # NSE transaction charge ~0.00297% of value
    sebi: float = 0.000001              # Rs 10 per crore
    stamp_buy: float = 0.00015          # stamp duty, buy side only, delivery 0.015%
    gst: float = 0.18                   # on brokerage + exchange charge + SEBI fee
    dp_per_sell: float = 15.34          # depository charge per scrip on a sell day (incl. GST), Rs
    slippage_bps: float = 5.0           # assumed adverse price move per fill, basis points

    def brokerage(self, value: float) -> float:
        b = self.brokerage_flat + self.brokerage_pct * value
        return min(b, self.brokerage_cap) if self.brokerage_cap else b

    def charges(self, side: str, value: float) -> dict[str, float]:
        """Itemised charges in rupees for one fill of `value` rupees (slippage is applied to the price, not here)."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        brok = self.brokerage(value)
        txn = self.exchange_txn * value
        sebi = self.sebi * value
        c = {"brokerage": brok, "stt": (self.stt_buy if side == "buy" else self.stt_sell) * value, "exchange": txn, "sebi": sebi,
             "stamp": self.stamp_buy * value if side == "buy" else 0.0, "gst": self.gst * (brok + txn + sebi),
             "dp": self.dp_per_sell if side == "sell" else 0.0}
        c["total"] = sum(c.values())
        return c

    def describe(self) -> dict:
        return asdict(self)


INDIA_DELIVERY = CostModel()
NO_COSTS = CostModel(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
PRESETS = {"india_delivery": INDIA_DELIVERY, "none": NO_COSTS}
COST_KEYS = ("brokerage", "stt", "exchange", "sebi", "stamp", "gst", "dp")


def from_overrides(preset: str, overrides: dict[str, float] | None) -> CostModel:
    if preset not in PRESETS:
        raise ValueError(f"unknown cost preset {preset!r}; choose from {list(PRESETS)}")
    base = asdict(PRESETS[preset])
    for k, v in (overrides or {}).items():
        if k not in base:
            raise ValueError(f"unknown cost field {k!r}")
        if v < 0:
            raise ValueError(f"{k} cannot be negative")
        base[k] = float(v)
    return CostModel(**base)
