"""
Performance store — the genome corpus.

Every generated carousel's `CarouselGenome` is persisted here as JSON. Like the
DNA corpus, a flat JSON file (not a DB table) is deliberate: the learning corpus
is append-mostly, human-inspectable, lives next to the rest of `output/`, and
needs no SQLite migration. Outcomes can be patched in place by id once the
analytics loop attaches realised saves/follows.

The store is also the single convenience surface the rest of the app calls:
`component_bias(category)` for the generator and `insights()` for the dashboard,
both computed from the corpus on demand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog

from src.config import get_settings
from src.learning.genome import CarouselGenome

log = structlog.get_logger(__name__)

_CORPUS_NAME = "genomes.json"


class PerformanceStore:
    def __init__(self, root: Optional[Path] = None):
        settings = get_settings()
        self.root = Path(root) if root else Path(settings.OUTPUT_DIR, "performance")
        self.path = self.root / _CORPUS_NAME

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────

    def list_dicts(self) -> list[dict]:
        """Every stored genome as a raw dict (newest first), tolerant of a
        missing or corrupt corpus."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except Exception as exc:
            log.warning("performance_store.load_failed", error=str(exc))
            return []
        if not isinstance(data, list):
            return []
        return sorted(data, key=lambda g: g.get("created_at", ""), reverse=True)

    def list_genomes(self) -> list[CarouselGenome]:
        return [CarouselGenome.from_dict(d) for d in self.list_dicts()]

    def count(self) -> int:
        return len(self.list_dicts())

    # ── Write ─────────────────────────────────────────────────────────────

    def record(self, genome: CarouselGenome) -> str:
        """Append a genome to the corpus. Returns its id."""
        self._ensure()
        data = self.list_dicts()
        data.append(genome.as_dict())
        self.path.write_text(json.dumps(data, indent=2))
        log.info("performance_store.recorded", id=genome.id, part=genome.part,
                 approved=genome.approved, final_score=genome.final_score)
        return genome.id

    def update_outcome(self, genome_id: str, outcome: dict) -> bool:
        """Patch a genome's realised outcomes in place (the analytics-loop hook).

        `outcome` should carry a `performance_index` in [0,1] plus `samples`;
        once set, `ranking.effectiveness` lets measured performance dominate the
        proxy. Returns True if a matching genome was found.
        """
        data = self.list_dicts()
        hit = False
        for d in data:
            if d.get("id") == genome_id:
                d["outcomes"] = outcome
                hit = True
                break
        if hit:
            self._ensure()
            self.path.write_text(json.dumps(data, indent=2))
            log.info("performance_store.outcome_updated", id=genome_id)
        return hit

    # ── Learning surfaces ────────────────────────────────────────────────

    def component_bias(self, category: str) -> dict[str, float]:
        """The generation nudge map for a category (empty at cold start)."""
        from src.learning.ranking import component_bias
        return component_bias(self.list_dicts(), category)

    def insights(self) -> dict:
        """The full Performance Insights dashboard payload."""
        from src.learning.insights import build_insights
        return build_insights(self.list_dicts())


__all__ = ["PerformanceStore"]
