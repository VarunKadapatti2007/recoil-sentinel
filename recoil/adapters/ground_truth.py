"""ground-truth provider adapter.

default is a local json store ("what the human operator actually did") used to
ground the judge. there's an interface-ready airbyte version that would pull
resolutions from a ticketing system, but it's not wired to an unverified api on
purpose — it raises a clear error pointing operators at the local store until a
connector is set up. swap providers via RECOIL_GROUND_TRUTH_PROVIDER.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from .. import config


class GroundTruthProvider(ABC):
    name: str = "ground_truth"

    @abstractmethod
    def lookup(self, ref: str) -> Optional[dict[str, Any]]:
        """resolve a ground_truth_ref to a context snapshot, or none."""


class LocalJSONGroundTruth(GroundTruthProvider):
    """reads data/frozen_evals/ground_truth.json — keyed by ref."""

    name = "local"

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (config.FROZEN_EVALS_DIR / "ground_truth.json")

    def lookup(self, ref: str) -> Optional[dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            store = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return store.get(ref)

    def write_store(self, store: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")


class AirbyteGroundTruth(GroundTruthProvider):
    """interface-ready airbyte connector path. not load-bearing: only kicks in
    when explicitly selected and configured; otherwise it tells the operator what to do."""

    name = "airbyte"

    def lookup(self, ref: str) -> Optional[dict[str, Any]]:
        raise RuntimeError(
            "Airbyte ground-truth connector selected but not configured. "
            "Set up a connector sync into data/frozen_evals/ground_truth.json and use "
            "RECOIL_GROUND_TRUTH_PROVIDER=local, or implement the connector pull here."
        )


def get_ground_truth_provider() -> GroundTruthProvider:
    name = os.environ.get("RECOIL_GROUND_TRUTH_PROVIDER", "local").strip().lower()
    if name == "airbyte":
        return AirbyteGroundTruth()
    return LocalJSONGroundTruth()
