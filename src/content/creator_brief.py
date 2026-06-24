"""
Creator brief + slide-purpose planner.

The quality engine answers "is this post good enough to ship?". This module
answers the question that comes *before* generation: "who am I making this for,
and what is each slide actually doing for them?".

A real creator doesn't fill five slides. They make five decisions. Before a
carousel is built we infer the audience for the edition (who's scrolling, why
they'd care, what they already know, what they believe, what would surprise
them, what makes them save, what makes them follow), then assign every slide an
explicit *purpose* drawn from a fixed vocabulary. A slide whose content serves
no purpose — an empty, generic, or AI-tell caption that builds no credibility
and triggers nothing — is flagged so the regeneration loop replaces it instead
of shipping dead weight.

Deterministic and heuristic (no API calls): the briefs are authored per niche,
the purpose assignment is structural, and "does this slide serve its purpose?"
reuses the same signal primitives as the quality reviewer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.content.caption_utils import has_ai_tell, is_generic, normalize_caption

# ── Purpose vocabulary ─────────────────────────────────────────────────────
# Every slide must do exactly one primary job for the viewer. These are the only
# jobs that exist; a slide that does none of them does not belong in the post.
PURPOSES: tuple[str, ...] = (
    "stop_scrolling",
    "create_curiosity",
    "build_credibility",
    "deliver_value",
    "challenge_assumptions",
    "reveal_information",
    "trigger_saving",
    "trigger_sharing",
    "trigger_following",
)


# ── Audience brief (the "who am I talking to" inference) ───────────────────

@dataclass(frozen=True)
class AudienceBrief:
    """The inferred audience for one edition — the seven questions answered."""
    edition: str
    who: str            # who is scrolling
    why_care: str       # why they would care
    knows: str          # what they already know (the obvious games)
    believes: str       # the assumption worth challenging
    surprise: str       # what would genuinely surprise them
    save_trigger: str   # what makes this worth saving
    follow_trigger: str  # what makes them follow for more

    def as_dict(self) -> dict:
        return {
            "edition": self.edition, "who": self.who, "why_care": self.why_care,
            "knows": self.knows, "believes": self.believes, "surprise": self.surprise,
            "save_trigger": self.save_trigger, "follow_trigger": self.follow_trigger,
        }


# Per-edition briefs. Each is a real audience model, not a label — the language
# is specific to the niche because that specificity is what separates a creator
# who knows their viewer from a model filling a template.
EDITION_BRIEFS: dict[str, AudienceBrief] = {
    "Friends edition": AudienceBrief(
        edition="Friends edition",
        who="someone in a group chat who's the one that picks the game",
        why_care="they've played Brookhaven and Murder Mystery to death with friends",
        knows="the big 5 everyone defaults to on a Friday night",
        believes="all the good co-op games are already famous",
        surprise="there's a whole tier of group games their squad has never opened",
        save_trigger="a ready-made list to send the chat next time nobody can decide",
        follow_trigger="they never run out of something new to play together",
    ),
    "Hidden Gems": AudienceBrief(
        edition="Hidden Gems",
        who="a player tired of the same front-page games the algorithm keeps pushing",
        why_care="they want to be the one who finds it before it blows up",
        knows="whatever's trending on the Roblox home page this week",
        believes="if a game were good it would already be popular",
        surprise="genuinely polished games sitting at a few thousand visits",
        save_trigger="a curated find-list they can mine when they're bored",
        follow_trigger="someone is doing the digging so they don't have to",
    ),
    "Horror edition": AudienceBrief(
        edition="Horror edition",
        who="a horror fan who's already beaten Doors, Mimic and the obvious ones",
        why_care="they want a game that can actually scare them again",
        knows="Doors, The Mimic, Apeirophobia — the front-page horror canon",
        believes="they've already played everything genuinely scary on Roblox",
        surprise="under-the-radar horror that lands a real scare the big ones don't",
        save_trigger="a queue of scares for the next late-night solo session",
        follow_trigger="a steady supply of horror they haven't been spoiled on",
    ),
    "Solo edition": AudienceBrief(
        edition="Solo edition",
        who="a player who mostly plays alone and is sick of being told to find friends",
        why_care="they want something absorbing that doesn't need a squad",
        knows="the multiplayer games everyone assumes you play with others",
        believes="Roblox is only fun with friends",
        surprise="single-player Roblox experiences with real depth exist",
        save_trigger="a solo backlog for when they just want to zone out alone",
        follow_trigger="someone curates for the solo player specifically",
    ),
    "Anime edition": AudienceBrief(
        edition="Anime edition",
        who="an anime fan grinding the big anime games and hitting a wall",
        why_care="they want abilities and combat that actually feel good, not reskins",
        knows="Blox Fruits, Anime Adventures and the usual grind games",
        believes="every anime game is a copy of the same three",
        surprise="anime games with combat or progression the big ones don't have",
        save_trigger="a list of fresh grinds for when the current one gets stale",
        follow_trigger="they get put onto anime games before the hype wave",
    ),
    "PvP edition": AudienceBrief(
        edition="PvP edition",
        who="a competitive player who wants a real skill ceiling, not luck",
        why_care="they want lobbies where mechanics decide the win, not stats",
        knows="the popular PvP games that have turned into stat-checks",
        believes="all the skill-based PvP scenes are dead or sweaty in a bad way",
        surprise="under-the-radar PvP where movement and aim still matter",
        save_trigger="a shortlist of skill games to climb when they're tilted off the main one",
        follow_trigger="they keep getting pointed to scenes worth grinding",
    ),
    "Underrated edition": AudienceBrief(
        edition="Underrated edition",
        who="a player who takes pride in playing what nobody else has found",
        why_care="being early to a good game is the whole flex",
        knows="whatever's already viral — which is exactly what they're avoiding",
        believes="popularity equals quality, and they resent it",
        surprise="games that are objectively good and somehow still invisible",
        save_trigger="a stash of finds to drop on friends before they're cool",
        follow_trigger="a reliable source of 'before it blew up' games",
    ),
    "Brainrot edition": AudienceBrief(
        edition="Brainrot edition",
        who="someone who wants to turn their brain off and laugh",
        why_care="they want unserious chaos, not a 60-hour grind",
        knows="the obvious meme games their whole feed already plays",
        believes="the funny games are all played out by now",
        surprise="absurd games their feed hasn't shoved at them yet",
        save_trigger="a pile of chaos to pull from when they're bored in class",
        follow_trigger="a steady drip of dumb-fun games to send friends",
    ),
}

# Fallback for any edition without an authored brief — generic but still a real
# audience model, never empty.
_DEFAULT_BRIEF = AudienceBrief(
    edition="default",
    who="a Roblox player scrolling for something new to play",
    why_care="they've burned through the front-page games and want more",
    knows="whatever's currently trending",
    believes="the good stuff is already popular",
    surprise="there are better games one search away",
    save_trigger="a list worth coming back to",
    follow_trigger="they never run out of games to try",
)


def brief_for(edition: Optional[str]) -> AudienceBrief:
    """The inferred audience for an edition (never None)."""
    return EDITION_BRIEFS.get(edition or "", _DEFAULT_BRIEF)


# ── Slide plan (every slide a decision, not a fill) ────────────────────────

@dataclass
class PlannedSlide:
    index: int
    role: str               # "cover" | "game" | "closer"
    purpose: str            # primary job (one of PURPOSES)
    secondary: tuple[str, ...]  # additional jobs this slide also does
    serves_purpose: bool    # does the actual content deliver the job?
    note: str = ""


@dataclass
class CarouselPlan:
    brief: AudienceBrief
    slides: list[PlannedSlide] = field(default_factory=list)

    @property
    def purposeful(self) -> bool:
        """True only if every slide delivers on the job it was assigned."""
        return bool(self.slides) and all(s.serves_purpose for s in self.slides)

    @property
    def dead_slides(self) -> list[int]:
        """Indices of slides that serve no purpose (regenerate, don't ship)."""
        return [s.index for s in self.slides if not s.serves_purpose]

    def as_dict(self) -> dict:
        return {
            "brief": self.brief.edition,
            "purposeful": self.purposeful,
            "dead_slides": self.dead_slides,
            "slides": [
                {"index": s.index, "role": s.role, "purpose": s.purpose,
                 "secondary": list(s.secondary), "serves": s.serves_purpose,
                 "note": s.note}
                for s in self.slides
            ],
        }


def _cover_serves(hook: str) -> tuple[bool, str]:
    """A cover earns its place if it stops the scroll AND opens a curiosity gap
    — i.e. it isn't empty, generic, or an AI tell."""
    h = (hook or "").strip()
    if not h:
        return False, "empty cover hook — nothing to stop the scroll"
    if has_ai_tell(h):
        return False, "cover reads AI-generated — breaks trust instantly"
    if is_generic(h):
        return False, "cover is generic filler — no curiosity gap"
    return True, ""


def _game_serves(caption: str, blurb: str) -> tuple[bool, str]:
    """A game slide earns its place if it delivers concrete value: a real,
    specific caption that builds credibility or reveals something. An empty,
    generic, or AI caption delivers nothing and is dead weight."""
    c = (caption or "").strip()
    if not c:
        return False, "empty caption — slide delivers no value"
    if has_ai_tell(c):
        return False, "caption reads AI-generated — kills credibility"
    if is_generic(c):
        return False, "caption is generic ('fun game') — reveals nothing specific"
    return True, ""


def plan_carousel(
    edition: str,
    cover_hook: str,
    captions: Sequence[str],
    blurbs: Sequence[str],
    cta: str,
) -> CarouselPlan:
    """
    Turn an assembled carousel into an explicit plan: the inferred audience plus
    a purpose for every slide and a verdict on whether each slide delivers it.

    Slide topology mirrors the renderer:
      - slide 0  : the cover  → stop scrolling + create curiosity
      - slides 1.. : one per game → build credibility / deliver value / reveal,
                     with the standout middle slide tasked to challenge the
                     'if it were good it'd be popular' assumption, and the final
                     game slide additionally carrying the follow + save trigger
                     (it's where the CTA chip and the payoff game live).
    """
    brief = brief_for(edition)
    caps = [c for c in captions]
    n = len(caps)
    slides: list[PlannedSlide] = []

    ok, note = _cover_serves(cover_hook)
    slides.append(PlannedSlide(
        index=0, role="cover", purpose="stop_scrolling",
        secondary=("create_curiosity",), serves_purpose=ok, note=note,
    ))

    for i, cap in enumerate(caps):
        last = i == n - 1
        # Rotate the per-slide job so the post reads as a built argument, not a
        # flat list: open on credibility, reveal through the middle, and let the
        # standout slide challenge the viewer's "good = popular" assumption.
        if i == 0:
            purpose = "build_credibility"
        elif i == n - 2 and n >= 3:
            purpose = "challenge_assumptions"
        else:
            purpose = "reveal_information"

        secondary: tuple[str, ...] = ("deliver_value",)
        role = "game"
        if last:
            # The last slide is the payoff: it's where saving and following are
            # actually triggered (best game + CTA chip live here).
            secondary = ("deliver_value", "trigger_saving", "trigger_following")
            role = "closer"

        blurb = blurbs[i] if i < len(blurbs) else ""
        ok, note = _game_serves(cap, blurb)
        slides.append(PlannedSlide(
            index=i + 1, role=role, purpose=purpose,
            secondary=secondary, serves_purpose=ok, note=note,
        ))

    return CarouselPlan(brief=brief, slides=slides)


__all__ = [
    "PURPOSES", "AudienceBrief", "EDITION_BRIEFS", "brief_for",
    "PlannedSlide", "CarouselPlan", "plan_carousel",
]
