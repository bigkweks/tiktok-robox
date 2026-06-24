"""
Content DNA Extraction System.

The platform's real job is NOT to generate carousels — it is to understand
*why* previously successful carousels performed, encode that into reusable
pattern models, and drive every future generation from that extracted DNA
instead of a generic prompt.

When screenshots of a proven carousel are uploaded, `ContentDNAExtractor`
asks Claude (vision) to analyse them and answer "why did this work?" across
14 performance dimensions:

    hook_structure, curiosity_mechanisms, information_hierarchy,
    slide_progression, emotional_triggers, retention_loops, swipe_incentives,
    save_triggers, follow_triggers, cta_patterns, reading_pace,
    typography_patterns, visual_hierarchy, content_density

Each extracted pattern carries a **confidence score** and the evidence that
supports it — we never present a pattern as fact when it came from a single
example. The 14 dimensions are then synthesised into five reusable formulas:

    1. Hook Formula        — what makes the cover stop the scroll
    2. Slide Formula       — how each slide is built to be absorbed
    3. Retention Formula   — what carries the viewer slide → slide
    4. CTA Formula         — what converts a viewer to a save / follow
    5. Visual Formula      — the typography / hierarchy / density rules

Crucially the extractor returns a *blueprint of mechanisms*, never the literal
content — the DNA describes the underlying pattern ("conditional qualifier that
gates the in-group audience"), not a phrase to copy.

`merge_profiles` is the learning step: when the same dimension recurs across
multiple analysed carousels, its confidence rises toward certainty (a pattern
seen once is a guess; a pattern seen in five winners is a law). This turns a
pile of single observations into a high-confidence, reusable pattern model.

The module is deterministic and fully testable without network access: the
Claude vision call is injected (`vision_fn`), and when no key / call is
available a clearly-labelled low-confidence PRIOR profile (seeded from the
reverse-engineered 118.5K-view reference carousel) keeps the system working.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

import structlog

log = structlog.get_logger(__name__)


# ── The 14 extracted dimensions ───────────────────────────────────────────

DIMENSIONS: tuple[str, ...] = (
    "hook_structure",
    "curiosity_mechanisms",
    "information_hierarchy",
    "slide_progression",
    "emotional_triggers",
    "retention_loops",
    "swipe_incentives",
    "save_triggers",
    "follow_triggers",
    "cta_patterns",
    "reading_pace",
    "typography_patterns",
    "visual_hierarchy",
    "content_density",
)

# Which dimensions compose each of the five reusable formulas. A formula is a
# higher-order pattern model assembled from the lower-level dimension patterns.
FORMULA_COMPOSITION: dict[str, tuple[str, ...]] = {
    "hook_formula": ("hook_structure", "curiosity_mechanisms", "emotional_triggers"),
    "slide_formula": (
        "information_hierarchy", "slide_progression", "content_density", "reading_pace",
    ),
    "retention_formula": ("retention_loops", "swipe_incentives", "slide_progression"),
    "cta_formula": ("cta_patterns", "save_triggers", "follow_triggers"),
    "visual_formula": ("typography_patterns", "visual_hierarchy", "content_density"),
}

# A single example can never make us certain — confidence from one carousel is
# capped here. Corroboration across carousels (merge_profiles) is what lifts a
# pattern above this ceiling toward a reliable, reusable law.
SINGLE_SOURCE_CAP: float = 0.65

# A pattern below this confidence is "weak" — surfaced but never used to drive
# generation on its own.
WEAK_CONFIDENCE: float = 0.40


# ── Data models ────────────────────────────────────────────────────────────

@dataclass
class Pattern:
    """One extracted pattern for one dimension — the *mechanism*, plus how
    confident we are and what evidence supports it."""
    dimension: str
    observation: str          # WHY it works — the underlying mechanism, not the content
    confidence: float         # 0..1 — capped at SINGLE_SOURCE_CAP until corroborated
    evidence: str = ""        # what in the screenshots supports this
    sample_count: int = 1     # how many analysed carousels exhibited this pattern

    def as_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "observation": self.observation,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        return cls(
            dimension=d.get("dimension", ""),
            observation=d.get("observation", ""),
            confidence=float(d.get("confidence", 0.0)),
            evidence=d.get("evidence", ""),
            sample_count=int(d.get("sample_count", 1)),
        )


@dataclass
class Formula:
    """A reusable pattern model — a named formula assembled from the dimension
    patterns that drive it, with an aggregate confidence."""
    name: str                       # human label, e.g. "Hook Formula"
    template: str                   # the reusable structural template
    components: list[str]           # ordered building blocks of the template
    drivers: list[Pattern] = field(default_factory=list)
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "template": self.template,
            "components": self.components,
            "drivers": [p.as_dict() for p in self.drivers],
            "confidence": round(self.confidence, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Formula":
        return cls(
            name=d.get("name", ""),
            template=d.get("template", ""),
            components=list(d.get("components", [])),
            drivers=[Pattern.from_dict(p) for p in d.get("drivers", [])],
            confidence=float(d.get("confidence", 0.0)),
        )


@dataclass
class ContentDNAProfile:
    """The Content DNA Profile — the structured blueprint of *why* a carousel
    (or a corpus of carousels) works. Drives future generation."""
    source_count: int                                  # carousels analysed into this profile
    patterns: dict[str, Pattern]                       # one per dimension
    hook_formula: Formula
    slide_formula: Formula
    retention_formula: Formula
    cta_formula: Formula
    visual_formula: Formula
    overall_confidence: float = 0.0
    label: str = ""                                    # optional name for this profile
    is_prior: bool = False                             # True when seeded, not extracted
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def formulas(self) -> dict[str, Formula]:
        return {
            "hook_formula": self.hook_formula,
            "slide_formula": self.slide_formula,
            "retention_formula": self.retention_formula,
            "cta_formula": self.cta_formula,
            "visual_formula": self.visual_formula,
        }

    def confident_patterns(self, floor: float = WEAK_CONFIDENCE) -> dict[str, Pattern]:
        """Only the patterns strong enough to trust for generation."""
        return {k: p for k, p in self.patterns.items() if p.confidence >= floor}

    def as_dict(self) -> dict:
        return {
            "source_count": self.source_count,
            "label": self.label,
            "is_prior": self.is_prior,
            "overall_confidence": round(self.overall_confidence, 3),
            "created_at": self.created_at,
            "notes": self.notes,
            "patterns": {k: p.as_dict() for k, p in self.patterns.items()},
            "formulas": {k: f.as_dict() for k, f in self.formulas.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContentDNAProfile":
        patterns = {k: Pattern.from_dict(v) for k, v in d.get("patterns", {}).items()}
        fmap = d.get("formulas", {})

        def _f(key: str) -> Formula:
            return Formula.from_dict(fmap.get(key, {})) if fmap.get(key) else _empty_formula(key)

        return cls(
            source_count=int(d.get("source_count", 1)),
            label=d.get("label", ""),
            is_prior=bool(d.get("is_prior", False)),
            overall_confidence=float(d.get("overall_confidence", 0.0)),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            notes=list(d.get("notes", [])),
            patterns=patterns,
            hook_formula=_f("hook_formula"),
            slide_formula=_f("slide_formula"),
            retention_formula=_f("retention_formula"),
            cta_formula=_f("cta_formula"),
            visual_formula=_f("visual_formula"),
        )


_FORMULA_LABELS: dict[str, str] = {
    "hook_formula": "Hook Formula",
    "slide_formula": "Slide Formula",
    "retention_formula": "Retention Formula",
    "cta_formula": "CTA Formula",
    "visual_formula": "Visual Formula",
}


def _empty_formula(key: str) -> Formula:
    return Formula(name=_FORMULA_LABELS.get(key, key), template="", components=[])


# ── Synthesis: dimension patterns → five formulas ──────────────────────────

def _synthesize_formula(key: str, patterns: dict[str, Pattern]) -> Formula:
    """Assemble one reusable formula from its component dimension patterns.

    The template is the ordered chain of component dimensions (a structural
    recipe, not literal copy); confidence is the mean of the driver
    confidences, lightly penalised when a driver is missing so a half-observed
    formula never reads as fully trustworthy.
    """
    comp_dims = FORMULA_COMPOSITION[key]
    drivers = [patterns[d] for d in comp_dims if d in patterns and patterns[d].observation]
    present = len(drivers)
    expected = len(comp_dims)

    components = [d.replace("_", " ") for d in comp_dims if d in patterns and patterns[d].observation]
    template = " → ".join(components) if components else ""

    if present == 0:
        conf = 0.0
    else:
        mean = sum(p.confidence for p in drivers) / present
        coverage = present / expected
        conf = round(mean * (0.6 + 0.4 * coverage), 3)   # missing drivers soften confidence

    return Formula(
        name=_FORMULA_LABELS[key],
        template=template,
        components=components,
        drivers=drivers,
        confidence=conf,
    )


def synthesize_profile(
    patterns: dict[str, Pattern],
    *,
    source_count: int = 1,
    label: str = "",
    is_prior: bool = False,
    notes: Optional[list[str]] = None,
) -> ContentDNAProfile:
    """Build a full ContentDNAProfile from the 14 dimension patterns."""
    formulas = {k: _synthesize_formula(k, patterns) for k in FORMULA_COMPOSITION}
    formula_confs = [f.confidence for f in formulas.values() if f.confidence > 0]
    overall = round(sum(formula_confs) / len(formula_confs), 3) if formula_confs else 0.0
    return ContentDNAProfile(
        source_count=source_count,
        patterns=patterns,
        hook_formula=formulas["hook_formula"],
        slide_formula=formulas["slide_formula"],
        retention_formula=formulas["retention_formula"],
        cta_formula=formulas["cta_formula"],
        visual_formula=formulas["visual_formula"],
        overall_confidence=overall,
        label=label,
        is_prior=is_prior,
        notes=notes or [],
    )


# ── Learning: merge multiple profiles into a stronger pattern model ─────────

def _corroborate(confidences: Sequence[float], sample_count: int) -> float:
    """Confidence after `sample_count` corroborating observations.

    One observation = a guess (returns the raw confidence, capped). Each
    additional carousel that exhibits the same pattern lifts confidence toward
    certainty: merged = avg + (1 - avg) * (k-1)/k. So 2 sources roughly halve
    the remaining doubt, 3 sources take ~2/3, and so on — patterns that recur
    across many proven carousels become reliable, reusable laws.
    """
    if not confidences:
        return 0.0
    avg = sum(confidences) / len(confidences)
    if sample_count <= 1:
        return round(min(avg, SINGLE_SOURCE_CAP), 3)
    consensus = (sample_count - 1) / sample_count
    return round(min(0.98, avg + (1.0 - avg) * consensus), 3)


def merge_profiles(
    profiles: Sequence[ContentDNAProfile],
    *,
    label: str = "Consolidated DNA",
) -> ContentDNAProfile:
    """Consolidate several analysed carousels into one high-confidence pattern
    model. A dimension reported by more carousels gets higher confidence; the
    most-confident observation is kept as the canonical phrasing.

    This is the system's learning step — it is how a pile of single-carousel
    guesses becomes a trustworthy, reusable DNA blueprint.
    """
    real = [p for p in profiles if not p.is_prior] or list(profiles)
    if not real:
        return seed_prior_profile()

    merged: dict[str, Pattern] = {}
    for dim in DIMENSIONS:
        observed = [p.patterns[dim] for p in real
                    if dim in p.patterns and p.patterns[dim].observation]
        if not observed:
            continue
        # Canonical observation = the single most-confident phrasing seen.
        best = max(observed, key=lambda x: x.confidence)
        total_samples = sum(o.sample_count for o in observed)
        conf = _corroborate([o.confidence for o in observed], total_samples)
        merged[dim] = Pattern(
            dimension=dim,
            observation=best.observation,
            confidence=conf,
            evidence=best.evidence,
            sample_count=total_samples,
        )

    all_prior = all(p.is_prior for p in real)
    notes = [f"Consolidated from {len(real)} analysed carousel(s)."]
    return synthesize_profile(
        merged,
        source_count=sum(p.source_count for p in real),
        label=label,
        is_prior=all_prior,
        notes=notes,
    )


# ── The seeded PRIOR (offline / cold-start baseline) ───────────────────────

# A clearly-labelled, low-confidence baseline derived from the reverse-
# engineered 118.5K-view reference carousel documented in the project handoff.
# It keeps the system functional with zero uploads — but every pattern is
# marked is_prior with sub-cap confidence so it never masquerades as an
# extraction from the creator's own proven posts.
_PRIOR_OBSERVATIONS: dict[str, tuple[str, str, float]] = {
    "hook_structure": (
        "Cover is a white pattern-interrupt against a dark feed with one "
        "dominant keyword (ROBLOX) and a niche curiosity line — the title IS "
        "the viewer's own search query.",
        "23.9% of reference traffic came from search matching the title.",
        0.55,
    ),
    "curiosity_mechanisms": (
        "Opens an information gap by promising specific, vetted picks the "
        "viewer hasn't seen, not a generic 'amazing games' claim.",
        "Niche-specific hook framing observed on the cover.",
        0.5,
    ),
    "information_hierarchy": (
        "Each game slide leads with the strongest trust signal (real Roblox "
        "game-page layout) then score then caption — credibility before claim.",
        "Game slides mirror an authentic Roblox game page.",
        0.5,
    ),
    "slide_progression": (
        "Six slides: a title card then five game slides; best game held for "
        "the last slide so completing the carousel is rewarded.",
        "Retention-arc ordering, best-for-last.",
        0.45,
    ),
    "emotional_triggers": (
        "Trust + mild FOMO ('save before everyone finds them') rather than "
        "hype or shock.",
        "Curation-proof + part-N series framing.",
        0.4,
    ),
    "retention_loops": (
        "Score reveal + casual caption on every slide creates a repeating "
        "'what did the next one get?' micro-loop that pulls the swipe.",
        "Burned-in score on each game slide.",
        0.45,
    ),
    "swipe_incentives": (
        "Each slide withholds the next game's score, so the only way to resolve "
        "the curiosity is to swipe.",
        "Per-slide score withholding.",
        0.45,
    ),
    "save_triggers": (
        "Framed as a referenceable curated list ('save these for later'), which "
        "is the behaviour that earns saves.",
        "Save-oriented cover CTA.",
        0.45,
    ),
    "follow_triggers": (
        "'Part N' series marker plus a soft last-slide follow chip converts on "
        "the completion high, not desperately.",
        "Part-N marker + final-slide follow nudge.",
        0.45,
    ),
    "cta_patterns": (
        "CTAs are natural creator lines ('which one are you opening first?'), "
        "placed above TikTok's bottom UI overlay so they're never occluded.",
        "Upper-middle CTA placement.",
        0.4,
    ),
    "reading_pace": (
        "Captions are 3–8 words, lowercase, scannable in under two seconds so "
        "the viewer never stalls on a slide.",
        "Short casual caption voice.",
        0.5,
    ),
    "typography_patterns": (
        "One bold display face (Poppins), a single dominant wordmark, one red "
        "accent — premium and legible at thumbnail scale.",
        "Poppins + single Roblox-red accent.",
        0.5,
    ),
    "visual_hierarchy": (
        "Left-aligned, asymmetric off a red rail; the eye travels top→down "
        "through hook → keyword → value → credibility.",
        "Asymmetric red-rail cover composition.",
        0.45,
    ),
    "content_density": (
        "Low density per slide — generous whitespace, one idea per slide — so "
        "each is absorbed instantly without clutter.",
        "Minimal, one-idea-per-slide layout.",
        0.45,
    ),
}


def seed_prior_profile() -> ContentDNAProfile:
    """The cold-start baseline DNA (clearly labelled, sub-cap confidence)."""
    patterns = {
        dim: Pattern(
            dimension=dim,
            observation=obs,
            confidence=min(conf, SINGLE_SOURCE_CAP),
            evidence=evid,
            sample_count=1,
        )
        for dim, (obs, evid, conf) in _PRIOR_OBSERVATIONS.items()
    }
    return synthesize_profile(
        patterns,
        source_count=0,
        label="Reference prior (118.5K-view carousel)",
        is_prior=True,
        notes=[
            "PRIOR — seeded from the reverse-engineered reference post, NOT "
            "extracted from your uploads. Upload real winners to replace it.",
        ],
    )


# ── Extraction (Claude vision) ─────────────────────────────────────────────

_EXTRACTION_PROMPT = """You are a TikTok growth analyst who reverse-engineers WHY a \
photo carousel performed. You are looking at the slides of a carousel that \
genuinely performed well (high saves / follows / reach).

Your job is NOT to describe what you see and NOT to copy any text. Your job is \
to extract the underlying, reusable MECHANISMS — the "why this worked" — so the \
patterns can be reapplied to brand-new content.

Analyse these {n} slide image(s) and return ONLY valid JSON with this exact shape:

{{
  "patterns": {{
    "hook_structure":       {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "curiosity_mechanisms": {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "information_hierarchy": {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "slide_progression":    {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "emotional_triggers":   {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "retention_loops":      {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "swipe_incentives":     {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "save_triggers":        {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "follow_triggers":      {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "cta_patterns":         {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "reading_pace":         {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "typography_patterns":  {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "visual_hierarchy":     {{"observation": "...", "confidence": 0.0, "evidence": "..."}},
    "content_density":      {{"observation": "...", "confidence": 0.0, "evidence": "..."}}
  }}
}}

Rules:
- "observation" states the MECHANISM and WHY it drives performance, in one
  sentence. Describe the pattern, never the literal words on the slide.
- "confidence" is 0.0-1.0 — how sure you are this pattern is real and is a
  *cause* of performance, given you only have these images. Be honest; if a
  dimension isn't clearly evidenced, score it low.
- "evidence" is the specific visual detail that supports the observation.
- If a dimension genuinely can't be assessed, set observation to "" and
  confidence to 0.0.
Return ONLY the JSON object, no other text."""


@dataclass
class ContentDNAExtractor:
    """Extracts a ContentDNAProfile from uploaded carousel screenshots.

    The Claude vision call is injectable (`vision_fn`) so the extraction logic
    is fully testable offline; when no key / call is available the extractor
    returns the clearly-labelled PRIOR profile instead of failing.
    """
    vision_fn: Optional[Callable[[str, list[tuple[str, bytes]]], str]] = None
    model: Optional[str] = None

    def extract(
        self,
        image_paths: Sequence[Path | str],
        label: str = "",
    ) -> ContentDNAProfile:
        images = self._load_images(image_paths)
        if not images:
            log.warning("content_dna.no_images")
            prof = seed_prior_profile()
            prof.notes.append("No readable screenshots supplied; returned prior.")
            return prof

        prompt = _EXTRACTION_PROMPT.format(n=len(images))
        try:
            raw = (self.vision_fn or self._default_vision)(prompt, images)
            patterns = self._parse(raw)
            if not patterns:
                raise ValueError("no patterns parsed from vision response")
        except Exception as exc:
            log.error("content_dna.extract_failed", error=str(exc))
            prof = seed_prior_profile()
            prof.notes.append(f"Extraction failed ({exc}); returned prior.")
            return prof

        # Single-example extraction: every confidence is capped — one carousel
        # can corroborate a pattern but never prove it.
        for p in patterns.values():
            p.confidence = min(p.confidence, SINGLE_SOURCE_CAP)

        prof = synthesize_profile(
            patterns,
            source_count=1,
            label=label or "Extracted DNA",
            is_prior=False,
            notes=[f"Extracted from {len(images)} slide image(s)."],
        )
        log.info("content_dna.extracted", slides=len(images),
                 overall=prof.overall_confidence,
                 dims=len([p for p in patterns.values() if p.observation]))
        return prof

    # ── helpers ──

    @staticmethod
    def _load_images(image_paths: Sequence[Path | str]) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for ip in image_paths:
            path = Path(ip)
            if not path.exists() or not path.is_file():
                continue
            suffix = path.suffix.lower()
            media = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif",
            }.get(suffix, "image/png")
            try:
                out.append((media, path.read_bytes()))
            except Exception as exc:
                log.warning("content_dna.image_read_failed", path=str(path), error=str(exc))
        return out

    def _default_vision(self, prompt: str, images: list[tuple[str, bytes]]) -> str:
        """Real Claude vision call. Imported lazily so the module loads (and
        tests run) without the anthropic package / an API key present."""
        import anthropic  # noqa: PLC0415

        from src.config import get_settings  # noqa: PLC0415
        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        content: list[dict] = []
        for media_type, data in images[:10]:   # cap payload at 10 slides
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": prompt})

        resp = client.messages.create(
            model=self.model or settings.ANTHROPIC_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text.strip()

    @staticmethod
    def _parse(raw: str) -> dict[str, Pattern]:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("no JSON object in vision response")
        data = json.loads(match.group())
        raw_patterns = data.get("patterns", data)   # tolerate a bare patterns map
        patterns: dict[str, Pattern] = {}
        for dim in DIMENSIONS:
            entry = raw_patterns.get(dim)
            if not isinstance(entry, dict):
                continue
            obs = (entry.get("observation") or "").strip()
            if not obs:
                continue
            try:
                conf = float(entry.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            patterns[dim] = Pattern(
                dimension=dim,
                observation=obs,
                confidence=max(0.0, min(1.0, conf)),
                evidence=(entry.get("evidence") or "").strip(),
                sample_count=1,
            )
        return patterns


__all__ = [
    "DIMENSIONS",
    "FORMULA_COMPOSITION",
    "SINGLE_SOURCE_CAP",
    "WEAK_CONFIDENCE",
    "Pattern",
    "Formula",
    "ContentDNAProfile",
    "ContentDNAExtractor",
    "synthesize_profile",
    "merge_profiles",
    "seed_prior_profile",
]
