"""on-chain ground truth — wallet & transaction integrity checks.

same engine as the market sentinel (generate -> verify -> gate -> freeze), just
with the ground-truth source swapped to the blockchain itself over keyless
json-rpc. the agent makes structured claims about a wallet's on-chain state and
every number gets checked against the chain before we publish or act. a
hallucinated balance, wrong amount, or fake transaction gets blocked — in crypto
a wrong number is irreversible lost money.

checked against live base sepolia rpc at build time (2026-06-12).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .. import config

log = logging.getLogger("recoil.sentinel")

RPC_URLS = {
    "base-sepolia": "https://sepolia.base.org",
    "base": "https://mainnet.base.org",
}
# canonical usdc contracts (the token x402 settles in)
USDC_CONTRACTS = {
    "base-sepolia": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
}
EXPLORERS = {
    "base-sepolia": "https://sepolia.basescan.org",
    "base": "https://basescan.org",
}
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"


class ChainError(Exception):
    pass


def _rpc(client: httpx.Client, url: str, method: str, params: list[Any]) -> Any:
    resp = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ChainError(f"{method} failed: {data['error']}")
    return data["result"]


def fetch_wallet_snapshot(
    address: Optional[str] = None, network: Optional[str] = None
) -> dict[str, Any]:
    """grab a wallet's live on-chain state. returns the standard snapshot shape
    so it flows through the existing generate/verify/gate engine as-is:
    {fetched_at, metrics, source_errors, subject}. raises ChainError on failure —
    the agent should never reason about a wallet it couldn't actually read."""
    address = (address or config.X402_WALLET_ADDRESS or "").strip()
    network = (network or config.X402_NETWORK or "base-sepolia").strip()
    if not address:
        raise ChainError("no wallet address (set X402_WALLET_ADDRESS or pass --address)")
    url = RPC_URLS.get(network)
    if not url:
        raise ChainError(f"unsupported network {network!r} (use base-sepolia or base)")
    explorer = EXPLORERS.get(network, "")
    fetched_at = datetime.now(timezone.utc).isoformat()

    with httpx.Client(
        timeout=config.EXTERNAL_TIMEOUT_S, headers={"User-Agent": "recoil-sentinel/0.1"}
    ) as client:
        chain_id = int(_rpc(client, url, "eth_chainId", []), 16)
        bal_wei = int(_rpc(client, url, "eth_getBalance", [address, "latest"]), 16)
        nonce = int(_rpc(client, url, "eth_getTransactionCount", [address, "latest"]), 16)
        usdc_contract = USDC_CONTRACTS.get(network)
        usdc_raw = 0
        if usdc_contract:
            call_data = ERC20_BALANCE_OF_SELECTOR + address.lower().replace("0x", "").rjust(64, "0")
            usdc_raw = int(
                _rpc(client, url, "eth_call", [{"to": usdc_contract, "data": call_data}, "latest"]),
                16,
            )

    addr_url = f"{explorer}/address/{address}" if explorer else url
    metrics = {
        "wallet:eth_balance": {
            "label": f"ETH balance of {address}",
            "value": round(bal_wei / 1e18, 9),
            "unit": "eth",
            "source": f"{network} RPC (eth_getBalance)",
            "source_url": addr_url,
            "extra": {"wei": bal_wei},
        },
        "wallet:tx_count": {
            "label": f"On-chain transaction count (nonce) of {address}",
            "value": nonce,
            "unit": "count",
            "source": f"{network} RPC (eth_getTransactionCount)",
            "source_url": addr_url,
            "extra": {},
        },
        "wallet:usdc_balance": {
            "label": f"USDC balance of {address}",
            "value": round(usdc_raw / 1e6, 6),
            "unit": "usdc",
            "source": f"{network} RPC (ERC-20 balanceOf)",
            "source_url": addr_url,
            "extra": {"raw": usdc_raw, "contract": usdc_contract},
        },
        "wallet:chain_id": {
            "label": "Chain ID",
            "value": chain_id,
            "unit": "id",
            "source": f"{network} RPC (eth_chainId)",
            "source_url": url,
            "extra": {"network": network},
        },
    }
    return {
        "fetched_at": fetched_at,
        "metrics": metrics,
        "source_errors": [],
        "subject": {"address": address, "network": network, "explorer": addr_url, "chain_id": chain_id},
    }


def fetch_transaction_snapshot(tx_hash: str, network: Optional[str] = None) -> dict[str, Any]:
    """grab one transaction's on-chain facts to verify integrity — sender,
    recipient, and value as recorded on-chain. raises ChainError if the tx
    doesn't exist (a made-up tx hash is itself a caught failure)."""
    network = (network or config.X402_NETWORK or "base-sepolia").strip()
    url = RPC_URLS.get(network)
    if not url:
        raise ChainError(f"unsupported network {network!r}")
    explorer = EXPLORERS.get(network, "")
    fetched_at = datetime.now(timezone.utc).isoformat()
    with httpx.Client(timeout=config.EXTERNAL_TIMEOUT_S) as client:
        tx = _rpc(client, url, "eth_getTransactionByHash", [tx_hash])
        if tx is None:
            raise ChainError(f"transaction {tx_hash} does not exist on {network}")
        value_wei = int(tx["value"], 16)
    tx_url = f"{explorer}/tx/{tx_hash}" if explorer else url
    metrics = {
        "tx:value_eth": {
            "label": f"Value of tx {tx_hash[:12]}…",
            "value": round(value_wei / 1e18, 9),
            "unit": "eth",
            "source": f"{network} RPC (eth_getTransactionByHash)",
            "source_url": tx_url,
            "extra": {"from": tx["from"], "to": tx["to"], "wei": value_wei},
        }
    }
    return {
        "fetched_at": fetched_at,
        "metrics": metrics,
        "source_errors": [],
        "subject": {"tx_hash": tx_hash, "network": network, "explorer": tx_url, "from": tx["from"], "to": tx["to"]},
    }
