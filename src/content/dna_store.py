"""
Content DNA store — the reusable pattern-model corpus.

Every extracted ContentDNAProfile is persisted here as JSON (alongside the
uploaded screenshots), and the store can consolidate all of them into a single
high-confidence DNA blueprint via `merge_profiles`. That consolidated profile
is the one future generation reads from.

JSON files (not a DB table) are deliberate: the DNA corpus is a small, append-
only, human-inspectable knowledge base that lives next to the screenshots it
was derived from, and it avoids a schema migration on the live SQLite DB.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from src.config import get_settings
from src.content.content_dna import (
    ContentDNAProfile,
    merge_profiles,
    seed_prior_profile,
)

log = structlog.get_logger(__name__)

_CONSOLIDATED_NAME = "_consolidated.json"


class DNAStore:
    """File-backed store of extracted DNA profiles + a consolidated view."""

    def __init__(self, root: Optional[Path] = None):
        settings = get_settings()
        self.root = root or Path(settings.OUTPUT_DIR, "content_dna")
        self.profiles_dir = self.root / "profiles"
        self.screenshots_dir = self.root / "screenshots"

    def _ensure_dirs(self) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    # ── Screenshots ──────────────────────────────────────────────────────

    def save_screenshots(self, files: list[tuple[str, bytes]]) -> list[Path]:
        """Persist uploaded (filename, bytes) screenshots into a fresh upload
        folder. Returns the saved paths in order."""
        self._ensure_dirs()
        batch = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        dest = self.screenshots_dir / batch
        dest.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for i, (filename, data) in enumerate(files):
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or f"slide_{i}.png")
            if not Path(safe).suffix:
                safe += ".png"
            path = dest / f"{i:02d}_{safe}"
            path.write_bytes(data)
            saved.append(path)
        log.info("dna_store.screenshots_saved", count=len(saved), batch=batch)
        return saved

    # ── Profiles ─────────────────────────────────────────────────────────

    def save_profile(self, profile: ContentDNAProfile) -> str:
        """Persist a single extracted profile. Returns its id (filename stem).

        Refuses to persist a PRIOR profile: a prior is a generic baseline, not
        extracted signal, so saving it would silently pollute the consolidated
        blueprint and make a failed extraction look successful (audit H2).
        Returns "" without saving in that case.
        """
        if getattr(profile, "is_prior", False):
            log.warning("dna_store.refused_prior_profile", label=profile.label)
            return ""
        self._ensure_dirs()
        pid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        path = self.profiles_dir / f"{pid}.json"
        path.write_text(json.dumps(profile.as_dict(), indent=2))
        # Refresh the consolidated blueprint so generation reads the latest.
        self.rebuild_consolidated()
        log.info("dna_store.profile_saved", id=pid,
                 overall=profile.overall_confidence)
        return pid

    def list_profiles(self) -> list[ContentDNAProfile]:
        """All saved per-upload profiles, newest first. Excludes consolidated."""
        if not self.profiles_dir.exists():
            return []
        out: list[ContentDNAProfile] = []
        for path in sorted(self.profiles_dir.glob("*.json"), reverse=True):
            if path.name == _CONSOLIDATED_NAME:
                continue
            try:
                out.append(ContentDNAProfile.from_dict(json.loads(path.read_text())))
            except Exception as exc:
                log.warning("dna_store.profile_load_failed", path=str(path), error=str(exc))
        return out

    def rebuild_consolidated(self) -> ContentDNAProfile:
        """Merge every saved profile into one blueprint and persist it."""
        self._ensure_dirs()
        # Exclude any prior profiles defensively (e.g. saved by an older build
        # before H2): a prior is a baseline, never real evidence, and must not
        # contribute to the merged blueprint.
        profiles = [p for p in self.list_profiles() if not getattr(p, "is_prior", False)]
        consolidated = merge_profiles(profiles) if profiles else seed_prior_profile()
        (self.root / _CONSOLIDATED_NAME).write_text(
            json.dumps(consolidated.as_dict(), indent=2)
        )
        return consolidated

    def get_consolidated(self) -> ContentDNAProfile:
        """The active DNA blueprint generation should read from. Falls back to
        the seeded prior when no real profile has been extracted yet."""
        path = self.root / _CONSOLIDATED_NAME
        if path.exists():
            try:
                return ContentDNAProfile.from_dict(json.loads(path.read_text()))
            except Exception as exc:
                log.warning("dna_store.consolidated_load_failed", error=str(exc))
        return self.rebuild_consolidated()


__all__ = ["DNAStore"]
