"""live, keyless ground-truth sources for the sentinel agent.

response shapes checked against the live apis at build time (2026-06-12):
- coingecko /simple/price -> {coin: {usd, usd_market_cap, usd_24h_change}}
- defillama /protocols    -> [{name, slug, tvl, change_1d, change_7d, category, url, chain}]
- defillama /v2/chains    -> [{name, tvl}]

every metric keeps its own source url and fetch time — those become the
citations in cited.md and the ground truth the verifier/judge grades against.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import config

log = logging.getLogger("recoil.sentinel")

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,ethereum,solana&vs_currencies=usd"
    "&include_24hr_change=true&include_market_cap=true"
)
LLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
LLAMA_CHAINS_URL = "https://api.llama.fi/v2/chains"

# defillama's tvl leaderboard is mostly exchange custody; we want real defi only.
_EXCLUDED_CATEGORIES = {"CEX", "Chain", "Bridge", "RWA"}


class SourceError(Exception):
    pass


def _get_json(client: httpx.Client, url: str) -> Any:
    last_exc: Exception | None = None
    for attempt in range(config.EXTERNAL_RETRIES + 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt < config.EXTERNAL_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"failed to fetch {url}: {last_exc}") from last_exc


def fetch_snapshot(*, top_n_protocols: int = 8, top_n_chains: int = 6) -> dict[str, Any]:
    """grab a live market snapshot. returns:
    {fetched_at, metrics: {key: {label, value, unit, source, source_url, extra}}}
    raises SourceError if nothing is reachable — the agent shouldn't run blind.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    metrics: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    with httpx.Client(
        timeout=config.EXTERNAL_TIMEOUT_S,
        headers={"User-Agent": "recoil-sentinel/0.1"},
        follow_redirects=True,
    ) as client:
        try:
            prices = _get_json(client, COINGECKO_URL)
            for coin, data in prices.items():
                metrics[f"price:{coin}"] = {
                    "label": f"{coin.capitalize()} price (USD)",
                    "value": float(data["usd"]),
                    "unit": "usd",
                    "source": "CoinGecko",
                    "source_url": COINGECKO_URL,
                    "extra": {
                        "market_cap_usd": data.get("usd_market_cap"),
                        "change_24h_pct": data.get("usd_24h_change"),
                    },
                }
                if data.get("usd_24h_change") is not None:
                    metrics[f"change24h:{coin}"] = {
                        "label": f"{coin.capitalize()} 24h change (%)",
                        "value": round(float(data["usd_24h_change"]), 4),
                        "unit": "pct",
                        "source": "CoinGecko",
                        "source_url": COINGECKO_URL,
                        "extra": {},
                    }
        except SourceError as exc:
            errors.append(str(exc))

        try:
            protocols = _get_json(client, LLAMA_PROTOCOLS_URL)
            defi = [
                p
                for p in protocols
                if p.get("tvl") and p.get("category") not in _EXCLUDED_CATEGORIES
            ]
            defi.sort(key=lambda p: p["tvl"], reverse=True)
            for p in defi[:top_n_protocols]:
                slug = p.get("slug") or p["name"].lower().replace(" ", "-")
                metrics[f"tvl:protocol:{slug}"] = {
                    "label": f"{p['name']} TVL (USD)",
                    "value": round(float(p["tvl"]), 2),
                    "unit": "usd",
                    "source": "DefiLlama",
                    "source_url": f"https://defillama.com/protocol/{slug}",
                    "extra": {
                        "category": p.get("category"),
                        "chain": p.get("chain"),
                        "change_1d_pct": p.get("change_1d"),
                        "change_7d_pct": p.get("change_7d"),
                    },
                }
        except SourceError as exc:
            errors.append(str(exc))

        try:
            chains = _get_json(client, LLAMA_CHAINS_URL)
            chains = [c for c in chains if c.get("tvl")]
            chains.sort(key=lambda c: c["tvl"], reverse=True)
            for c in chains[:top_n_chains]:
                key = c["name"].lower().replace(" ", "-")
                metrics[f"tvl:chain:{key}"] = {
                    "label": f"{c['name']} chain TVL (USD)",
                    "value": round(float(c["tvl"]), 2),
                    "unit": "usd",
                    "source": "DefiLlama",
                    "source_url": f"https://defillama.com/chain/{c['name']}",
                    "extra": {},
                }
        except SourceError as exc:
            errors.append(str(exc))

    if not metrics:
        raise SourceError("all ground-truth sources unreachable: " + " | ".join(errors))
    if errors:
        log.warning("partial snapshot (%d metrics): %s", len(metrics), errors)

    return {"fetched_at": fetched_at, "metrics": metrics, "source_errors": errors}
