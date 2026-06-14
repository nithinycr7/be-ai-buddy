"""
Token + cost accounting for a single SILF story generation.

A story now triggers several LLM calls (story text, 2 scene panels, 1 animation,
the verifier judge, and sometimes a full regeneration). Each call records a
usage entry; `summarize()` rolls them into total tokens and an estimated cost.

NOTE: prices are ESTIMATES (USD per 1M tokens) — update `_PRICES` with the live
provider rates. Token counts are exact; the dollar figure is an approximation.
"""
from __future__ import annotations

# (input $/1M, output $/1M) — rough estimates, edit to match your billing.
_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.00),
    "gemini-3.0-pro":   (2.00, 12.00),
    "gpt-4o-mini":      (0.15, 0.60),
    "claude-sonnet-4-6": (3.00, 15.00),
}
_DEFAULT_PRICE = (1.00, 5.00)
_USD_TO_INR = 83.0


def usage_entry(label: str, model: str | None, in_tokens: int = 0, out_tokens: int = 0) -> dict:
    """One LLM call's usage record."""
    return {
        "label": label,
        "model": model or "unknown",
        "in_tokens": int(in_tokens or 0),
        "out_tokens": int(out_tokens or 0),
    }


def _cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = _PRICES.get(model, _DEFAULT_PRICE)
    return in_tok / 1_000_000 * pin + out_tok / 1_000_000 * pout


def summarize(calls: list[dict]) -> dict:
    """Aggregate usage entries into a cost report for one story."""
    calls = [c for c in calls if c]
    by_call = []
    total_in = total_out = 0
    total_usd = 0.0
    for c in calls:
        usd = round(_cost_usd(c["model"], c["in_tokens"], c["out_tokens"]), 6)
        total_in += c["in_tokens"]
        total_out += c["out_tokens"]
        total_usd += usd
        by_call.append({**c, "tokens": c["in_tokens"] + c["out_tokens"], "est_usd": round(usd, 6)})
    return {
        "calls": len(by_call),
        "total_tokens": total_in + total_out,
        "total_in_tokens": total_in,
        "total_out_tokens": total_out,
        "est_usd": round(total_usd, 5),
        "est_inr": round(total_usd * _USD_TO_INR, 3),
        "by_call": by_call,
        "note": "prices are estimates — update app/services/llm_cost.py with live rates",
    }
