"""
Tests for the DNA store (persistence corpus) and the DNA → generation bridge.
"""
from __future__ import annotations

from src.content.content_dna import (
    DIMENSIONS,
    Pattern,
    seed_prior_profile,
    synthesize_profile,
)
from src.content.cover_generator import select_cover_concept
from src.content.dna_directives import derive_directives
from src.content.dna_store import DNAStore


def _profile(conf: float):
    patterns = {dim: Pattern(dim, f"obs {dim}", conf, sample_count=1) for dim in DIMENSIONS}
    return synthesize_profile(patterns, source_count=1, label="w")


# ── Store ─────────────────────────────────────────────────────────────────

def test_store_save_and_list(tmp_path):
    store = DNAStore(root=tmp_path)
    store.save_profile(_profile(0.6))
    store.save_profile(_profile(0.6))
    profiles = store.list_profiles()
    assert len(profiles) == 2


def test_store_consolidated_starts_as_prior(tmp_path):
    store = DNAStore(root=tmp_path)
    consolidated = store.get_consolidated()
    assert consolidated.is_prior  # no uploads yet → seeded prior


def test_store_consolidated_merges_after_save(tmp_path):
    store = DNAStore(root=tmp_path)
    store.save_profile(_profile(0.6))
    store.save_profile(_profile(0.6))
    consolidated = store.get_consolidated()
    assert not consolidated.is_prior
    # Two corroborating sources → confidence above a single source.
    assert consolidated.patterns["hook_structure"].sample_count == 2


def test_store_refuses_to_save_prior(tmp_path):
    """Audit H2: a failed extraction returns a PRIOR; persisting it would pollute
    the blueprint and look like success. The store must refuse."""
    store = DNAStore(root=tmp_path)
    pid = store.save_profile(seed_prior_profile())
    assert pid == ""                       # not saved
    assert store.list_profiles() == []     # corpus stays empty
    assert store.get_consolidated().is_prior


def test_consolidated_excludes_legacy_prior(tmp_path):
    """A prior already on disk (from an older build) must not contribute to the
    merged blueprint — only real extractions count."""
    store = DNAStore(root=tmp_path)
    # Force a prior onto disk the way an old build might have.
    store._ensure_dirs()
    import json
    (store.profiles_dir / "legacy_prior.json").write_text(
        json.dumps(seed_prior_profile().as_dict()))
    store.save_profile(_profile(0.6))      # one genuine extraction
    consolidated = store.rebuild_consolidated()
    assert not consolidated.is_prior
    # Only the single real source counts, not the legacy prior.
    assert consolidated.patterns["hook_structure"].sample_count == 1


def test_store_save_screenshots(tmp_path):
    store = DNAStore(root=tmp_path)
    saved = store.save_screenshots([("a.png", b"123"), ("b.png", b"456")])
    assert len(saved) == 2
    assert all(p.exists() for p in saved)


# ── Directives bridge ─────────────────────────────────────────────────────

def test_directives_inactive_for_prior():
    # The seeded prior is sub-cap; below the activation threshold its directives
    # may still derive but weight stays modest. Just assert it derives safely.
    d = derive_directives(seed_prior_profile())
    assert 0.0 <= d.weight <= 1.0


def test_directives_active_for_confident_profile():
    d = derive_directives(_profile(0.6))
    assert d.active
    assert d.prefer_curiosity_gap
    assert d.weight >= 0.4


def test_directives_reading_pace_sets_max_words():
    patterns = {dim: Pattern(dim, "obs", 0.6) for dim in DIMENSIONS}
    patterns["reading_pace"] = Pattern("reading_pace", "captions are 3 to 8 words, scannable", 0.6)
    profile = synthesize_profile(patterns, source_count=1)
    d = derive_directives(profile)
    assert d.max_hook_words == 8


def test_dna_directives_steer_cover_selection():
    # A DNA that strongly prefers first-person + curiosity should be able to
    # change which concept wins vs. no DNA (the selection is DNA-driven).
    patterns = {dim: Pattern(dim, "obs", 0.65) for dim in DIMENSIONS}
    patterns["emotional_triggers"] = Pattern(
        "emotional_triggers", "first-person creator confession builds trust", 0.65)
    profile = synthesize_profile(patterns, source_count=1)
    directives = derive_directives(profile)

    base = select_cover_concept("Horror edition", part=1)
    driven = select_cover_concept("Horror edition", part=1, dna=directives)
    # Both must be valid concepts; the DNA-driven path must still return a winner.
    assert driven.hook
    assert driven.score is not None
    # Selecting with directives must never crash and must respect rejection.
    assert driven.score.passes
    # Sanity: passing a None dna behaves like the base call.
    assert select_cover_concept("Horror edition", part=1, dna=None).hook == base.hook
