"""
Tests for the Content DNA Extraction System.

The system must: extract per-dimension patterns with confidence + evidence,
cap single-source confidence, synthesise the five reusable formulas, raise
confidence as patterns recur across carousels (the learning step), survive a
failed / absent vision call via a clearly-labelled prior, persist + consolidate
profiles, and translate a profile into generation directives that actually
steer cover selection.
"""
from __future__ import annotations

import json

from src.content.content_dna import (
    DIMENSIONS,
    FORMULA_COMPOSITION,
    SINGLE_SOURCE_CAP,
    ContentDNAExtractor,
    ContentDNAProfile,
    Pattern,
    merge_profiles,
    seed_prior_profile,
    synthesize_profile,
)


# ── A canned vision response (one per dimension) ──────────────────────────

def _full_patterns_json(confidence: float = 0.8) -> str:
    patterns = {
        dim: {
            "observation": f"mechanism for {dim} that drives performance",
            "confidence": confidence,
            "evidence": f"visible in {dim}",
        }
        for dim in DIMENSIONS
    }
    return json.dumps({"patterns": patterns})


def _fake_vision(response: str):
    def _fn(prompt, images):
        return response
    return _fn


def _make_image(tmp_path, name="slide.png"):
    # A tiny valid-ish PNG payload (header is enough for _load_images which only
    # reads bytes; the fake vision_fn ignores content).
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return p


# ── Extraction ────────────────────────────────────────────────────────────

def test_extract_returns_all_dimensions(tmp_path):
    img = _make_image(tmp_path)
    ext = ContentDNAExtractor(vision_fn=_fake_vision(_full_patterns_json(0.8)))
    profile = ext.extract([img], label="test")
    assert not profile.is_prior
    for dim in DIMENSIONS:
        assert dim in profile.patterns
        assert profile.patterns[dim].observation


def test_single_source_confidence_is_capped(tmp_path):
    img = _make_image(tmp_path)
    # Vision claims 0.95 everywhere; a single carousel can never exceed the cap.
    ext = ContentDNAExtractor(vision_fn=_fake_vision(_full_patterns_json(0.95)))
    profile = ext.extract([img])
    for p in profile.patterns.values():
        assert p.confidence <= SINGLE_SOURCE_CAP + 1e-9


def test_extract_synthesizes_five_formulas(tmp_path):
    img = _make_image(tmp_path)
    ext = ContentDNAExtractor(vision_fn=_fake_vision(_full_patterns_json(0.6)))
    profile = ext.extract([img])
    assert profile.hook_formula.name == "Hook Formula"
    assert profile.slide_formula.name == "Slide Formula"
    assert profile.retention_formula.name == "Retention Formula"
    assert profile.cta_formula.name == "CTA Formula"
    assert profile.visual_formula.name == "Visual Formula"
    # Every formula's drivers come only from its composition dimensions.
    for key, comp in FORMULA_COMPOSITION.items():
        f = profile.formulas[key]
        for d in f.drivers:
            assert d.dimension in comp


def test_no_images_returns_prior():
    ext = ContentDNAExtractor(vision_fn=_fake_vision(_full_patterns_json()))
    profile = ext.extract([])  # nothing to look at
    assert profile.is_prior


def test_failed_vision_returns_prior(tmp_path):
    img = _make_image(tmp_path)

    def _boom(prompt, images):
        raise RuntimeError("api down")

    profile = ContentDNAExtractor(vision_fn=_boom).extract([img])
    assert profile.is_prior
    assert any("failed" in n.lower() for n in profile.notes)


def test_malformed_json_returns_prior(tmp_path):
    img = _make_image(tmp_path)
    profile = ContentDNAExtractor(vision_fn=_fake_vision("not json at all")).extract([img])
    assert profile.is_prior


def test_partial_patterns_only_keep_observed(tmp_path):
    img = _make_image(tmp_path)
    partial = json.dumps({"patterns": {
        "hook_structure": {"observation": "strong qualifier hook", "confidence": 0.6, "evidence": "x"},
        "cta_patterns": {"observation": "", "confidence": 0.9},  # empty obs dropped
    }})
    profile = ContentDNAExtractor(vision_fn=_fake_vision(partial)).extract([img])
    assert "hook_structure" in profile.patterns
    assert "cta_patterns" not in profile.patterns  # empty observation excluded


# ── Synthesis confidence ──────────────────────────────────────────────────

def test_formula_confidence_softened_by_missing_drivers():
    # Hook formula needs 3 dims; give it only 1 → confidence below the raw mean.
    patterns = {
        "hook_structure": Pattern("hook_structure", "obs", 0.8),
    }
    profile = synthesize_profile(patterns)
    assert 0 < profile.hook_formula.confidence < 0.8


# ── Learning (merge) ──────────────────────────────────────────────────────

def _profile_with(conf: float) -> ContentDNAProfile:
    patterns = {
        dim: Pattern(dim, f"obs {dim}", conf, evidence="e", sample_count=1)
        for dim in DIMENSIONS
    }
    return synthesize_profile(patterns, source_count=1)


def test_merge_raises_confidence_with_corroboration():
    single = _profile_with(0.6)
    single_conf = single.patterns["hook_structure"].confidence

    merged = merge_profiles([_profile_with(0.6), _profile_with(0.6), _profile_with(0.6)])
    merged_conf = merged.patterns["hook_structure"].confidence

    # Three carousels agreeing should beat one (and exceed the single-source cap).
    assert merged_conf > single_conf
    assert merged_conf > SINGLE_SOURCE_CAP
    assert merged.patterns["hook_structure"].sample_count == 3


def test_merge_single_profile_respects_cap():
    merged = merge_profiles([_profile_with(0.9)])
    assert merged.patterns["hook_structure"].confidence <= SINGLE_SOURCE_CAP + 1e-9


def test_merge_keeps_most_confident_observation():
    p_low = synthesize_profile({"hook_structure": Pattern("hook_structure", "weak obs", 0.3)})
    p_high = synthesize_profile({"hook_structure": Pattern("hook_structure", "strong obs", 0.6)})
    merged = merge_profiles([p_low, p_high])
    assert merged.patterns["hook_structure"].observation == "strong obs"


def test_merge_ignores_prior_when_real_exists():
    prior = seed_prior_profile()
    real = _profile_with(0.6)
    merged = merge_profiles([prior, real])
    assert not merged.is_prior


# ── Serialisation round-trip ──────────────────────────────────────────────

def test_profile_roundtrip():
    profile = _profile_with(0.55)
    d = profile.as_dict()
    back = ContentDNAProfile.from_dict(d)
    assert back.source_count == profile.source_count
    assert set(back.patterns) == set(profile.patterns)
    assert back.hook_formula.name == profile.hook_formula.name
    assert abs(back.overall_confidence - profile.overall_confidence) < 1e-6


def test_as_dict_has_formulas_and_patterns():
    d = _profile_with(0.5).as_dict()
    assert set(d["formulas"]) == set(FORMULA_COMPOSITION)
    assert set(d["patterns"]) == set(DIMENSIONS)


# ── Prior ─────────────────────────────────────────────────────────────────

def test_prior_is_labelled_and_subcap():
    prior = seed_prior_profile()
    assert prior.is_prior
    assert prior.source_count == 0
    for p in prior.patterns.values():
        assert p.confidence <= SINGLE_SOURCE_CAP + 1e-9
    assert prior.overall_confidence > 0  # still a usable baseline
