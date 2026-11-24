"""Consensus panel: every model's vote side by side, how much they disagree, and which have a demonstrated edge.

Disagreement is shown as LOW CONVICTION, never hidden. Baselines are listed separately and do not vote.
"""
from __future__ import annotations

import numpy as np


def build(views: dict[str, dict], metrics: dict[str, dict], baselines: set[str]) -> dict:
    rows, base_rows, ens_row = [], [], None
    for name, v in views.items():
        m = metrics.get(name) or {}
        d = m.get("directional") or {}
        row = {"name": name, "kind": v.get("kind"), "vote": v["vote"], "p_up": v["p_up"], "p_flat": v["p_flat"], "p_down": v["p_down"],
               "conviction": v["conviction"], "net": v["p_up"] - v["p_down"], "verdict": m.get("verdict"), "verdict_reason": m.get("verdict_reason"),
               "hit_rate": d.get("hit_rate"), "naive_rate": d.get("naive_rate"), "brier_skill": m.get("brier_skill"),
               "n_effective": m.get("n_effective"), "edge": m.get("verdict") == "demonstrated edge", "median_return": v["quantiles"].get("50")}
        if name == "ensemble":
            ens_row = row
        else:
            (base_rows if name in baselines else rows).append(row)
    votes = {k: sum(1 for r in rows if r["vote"] == k) for k in ("up", "flat", "down")}
    n = len(rows)
    out: dict = {"models": rows, "baselines": base_rows, "ensemble": ens_row, "votes": votes, "n_models": n,
                 "n_edge": sum(1 for r in rows if r["edge"])}
    if n == 0:
        out.update(majority=None, majority_share=None, spread=None, disagreement=None, conviction=None, headline="No models have been run yet.")
        return out
    major = max(votes, key=votes.get)           # type: ignore[arg-type]
    share = votes[major] / n
    spread = float(np.std([r["net"] for r in rows])) if n > 1 else 0.0
    dis = "high" if (spread >= 0.2 or share < 0.5) else "medium" if (spread >= 0.08 or share < 0.75) else "low"
    conv = "low" if dis == "high" or out["n_edge"] == 0 else "moderate"
    if n == 1:
        headline = "Only one model has been run, so there is nothing to compare."
    elif dis == "high":
        headline = "The models disagree. Treat this as low conviction."
    elif out["n_edge"] == 0:
        headline = f"Most models lean {major}, but none has a demonstrated edge over the baseline, so this is weak evidence."
    else:
        headline = f"{votes[major]} of {n} models lean {major}; {out['n_edge']} have a demonstrated edge. Evidence is modest, not a guarantee."
    out.update(majority=major, majority_share=share, spread=spread, disagreement=dis, conviction=conv, headline=headline,
               how_to_read="Votes come from the most probable of up / flat / down. 'Edge' means the model beat the naive baseline out of sample "
                           "with statistical significance after correcting for the number of models tried. Disagreement between models is "
                           "information: it means the data does not clearly favour one outcome.")
    return out
