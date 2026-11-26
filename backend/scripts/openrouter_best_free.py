"""Rank the free OpenRouter models available RIGHT NOW and test the best few with real calls.

    make openrouter-check            (needs OPENROUTER_API_KEY in .env and internet access)

Uses about 2 requests per tested model. The free tier allows roughly 20 requests/minute and 50/day, so the default
tests 4 models (8 requests). Prints the winner and the line to put in .env.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.llm import openrouter as orr  # noqa: E402
from app.llm.providers.openai_compat import OpenAICompatProvider  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=4, help="how many top-ranked models to test live")
    ap.add_argument("--runs", type=int, default=2, help="calls per model")
    a = ap.parse_args()
    key = get_settings().openrouter_api_key
    if not key:
        print("Set OPENROUTER_API_KEY in .env first (free key from openrouter.ai/keys).")
        return 1
    print("Fetching the model catalogue...")
    ranked = orr.rank_free_models(await orr.fetch_models(key), 12)
    if not ranked:
        print("No free models matched.")
        return 1
    print(f"\nTop free models by declared capabilities ({len(ranked)} shown):")
    for i, r in enumerate(ranked, 1):
        print(f"{i:2d}. {r['id']:55s} score {r['score']:5.1f}  {'; '.join(r['reasons'][:3])}")
    prov = OpenAICompatProvider("openrouter", key, "https://openrouter.ai/api/v1", True, headers={"X-Title": "QuantLens"})
    print(f"\nLive test of the top {a.top} ({a.runs} calls each)...")
    results = []
    for r in ranked[:a.top]:
        t = await orr.live_test(prov, r["id"], a.runs)
        results.append(t)
        print(f"  {t['model']:55s} valid {t['valid_rate']:.0%}  avg {t['avg_seconds']}s  {t['errors'][:1] if t['errors'] else ''}")
        await asyncio.sleep(3.5)                                    # stay under the per-minute limit
    working = [t for t in results if t["valid_rate"] > 0]
    if not working:
        print("\nNone of the tested models answered correctly. Check your key, that free-model use is enabled in OpenRouter privacy settings, or try again later (daily limit?).")
        return 2
    best = sorted(working, key=lambda t: (-t["valid_rate"], t["avg_seconds"] or 99))[0]
    print(f"\nBest right now: {best['model']}\nAdd this to .env:\n  OPENROUTER_MODEL={best['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
