"""Publish-target adapter.

Recoil is framework-agnostic: the default target is Recoil's own version store
(`recoil publish` flips is_published after a PASS gate). A Guild.ai target is
interface-ready behind the same contract; it is intentionally not wired to an
unverified SDK/CLI — selecting it without configuration produces a clear error
instead of a hardcoded guess.
"""

from __future__ import annotations

import os
import sqlite3
from abc import ABC, abstractmethod

from .. import db


class PublishTarget(ABC):
    name: str = "target"

    @abstractmethod
    def publish(self, conn: sqlite3.Connection, version_id: str) -> str:
        """Mark the version live. Returns a human-readable confirmation."""


class LocalPublishTarget(PublishTarget):
    name = "local"

    def publish(self, conn: sqlite3.Connection, version_id: str) -> str:
        db.set_published(conn, version_id, True)
        version = db.get_version(conn, version_id)
        label = version["label"] if version else version_id
        return f"version {label} is now published in Recoil's version store"


class GuildPublishTarget(PublishTarget):
    name = "guild"

    def publish(self, conn: sqlite3.Connection, version_id: str) -> str:
        raise RuntimeError(
            "Guild.ai publish target selected but not configured. Verify the current "
            "Guild SDK/CLI and implement the publish call here, or use "
            "RECOIL_PUBLISH_TARGET=local (default)."
        )


def get_publish_target() -> PublishTarget:
    name = os.environ.get("RECOIL_PUBLISH_TARGET", "local").strip().lower()
    if name == "guild":
        return GuildPublishTarget()
    return LocalPublishTarget()
