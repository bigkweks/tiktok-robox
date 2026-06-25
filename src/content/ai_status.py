"""
AI credential status — make silent fallback impossible.

The rating engine degrades gracefully to a rule-based fallback when the Anthropic
API call fails (rating_engine.py). That graceful degradation is GOOD for
robustness but DANGEROUS for trust: a user with a missing / invalid / expired key
gets a product that *looks* like it is working while silently producing
non-AI output. They blame "weak AI" when the real problem is configuration.

This module makes the credential state explicit and checkable from three places:
  - startup (dashboard.startup)
  - the dashboard at any time (GET /api/ai-status)
  - onboarding (scripts/check_api_key.py, called by quickstart.sh)

It distinguishes the states a user actually needs to tell apart — missing,
malformed, invalid/revoked, rate-limited, unreachable (network/timeout) — and
provides a single ``ok`` flag plus a human message. When ``ok`` is False the
system is in FALLBACK MODE and the UI must say so.

The network probe is isolated in ``_default_probe`` and fully injectable, so the
classification logic is testable offline with no real API calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import structlog

from src.config import get_settings

log = structlog.get_logger(__name__)


# Probe result vocabulary (what _default_probe returns). Kept as plain strings so
# tests can inject a probe without constructing real SDK exceptions.
PROBE_VALID = "valid"
PROBE_INVALID = "invalid"            # 401 — wrong / revoked / expired key
PROBE_RATE_LIMITED = "rate_limited"  # 429
PROBE_UNREACHABLE = "unreachable"    # network / timeout — can't tell if key is good
PROBE_ERROR = "error"                # anything else


@dataclass
class AIStatus:
    """The resolved AI credential state surfaced to the user."""
    state: str          # "valid" | "missing" | "malformed" | "invalid" | "rate_limited" | "unreachable" | "error"
    ok: bool            # True only when AI generation is genuinely available
    fallback_active: bool   # True whenever output would be rule-based, not AI
    title: str          # short banner headline
    message: str        # full human explanation + what to do
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "ok": self.ok,
            "fallback_active": self.fallback_active,
            "title": self.title,
            "message": self.message,
            "checked_at": self.checked_at,
        }


# Static (no-network) states ------------------------------------------------

def _missing() -> AIStatus:
    return AIStatus(
        state="missing", ok=False, fallback_active=True,
        title="No Anthropic API key — running in FALLBACK mode",
        message=(
            "No ANTHROPIC_API_KEY is configured, so ratings and captions are "
            "rule-based, NOT AI-generated. Add your key to the .env file "
            "(it starts with 'sk-ant-') and restart to enable real AI."
        ),
    )


def _malformed() -> AIStatus:
    return AIStatus(
        state="malformed", ok=False, fallback_active=True,
        title="Anthropic API key looks malformed — FALLBACK mode",
        message=(
            "The ANTHROPIC_API_KEY does not look like a real Anthropic key "
            "(it should start with 'sk-ant-'). Output is running in rule-based "
            "fallback mode until a valid key is set."
        ),
    )


_PROBE_STATUS: dict[str, AIStatus] = {}


def _status_for_probe(state: str) -> AIStatus:
    if state == PROBE_VALID:
        return AIStatus(
            state="valid", ok=True, fallback_active=False,
            title="Anthropic AI connected",
            message="Your Anthropic API key is valid. Ratings and captions are AI-generated.",
        )
    if state == PROBE_INVALID:
        return AIStatus(
            state="invalid", ok=False, fallback_active=True,
            title="Anthropic rejected your API key — FALLBACK mode",
            message=(
                "Anthropic rejected this API key (it is invalid, expired, or "
                "revoked). Ratings and captions are rule-based fallback, NOT AI. "
                "Generate a fresh key at console.anthropic.com, update .env, and "
                "restart."
            ),
        )
    if state == PROBE_RATE_LIMITED:
        return AIStatus(
            state="rate_limited", ok=False, fallback_active=True,
            title="Anthropic is rate-limiting — temporary FALLBACK mode",
            message=(
                "Anthropic is currently rate-limiting requests for this key, so "
                "new content may use rule-based fallback until it clears. Your key "
                "is valid — wait a few minutes or check your plan's limits."
            ),
        )
    if state == PROBE_UNREACHABLE:
        return AIStatus(
            state="unreachable", ok=False, fallback_active=True,
            title="Can't reach Anthropic (network/timeout) — FALLBACK mode",
            message=(
                "Could not reach the Anthropic API (network error or timeout). "
                "Your key may be fine, but until the connection works, content "
                "falls back to rule-based output. Check your internet connection."
            ),
        )
    return AIStatus(
        state="error", ok=False, fallback_active=True,
        title="Anthropic check failed — FALLBACK mode",
        message=(
            "An unexpected error occurred while checking the Anthropic API. "
            "Content may use rule-based fallback. See the logs for details."
        ),
    )


def _default_probe(key: str) -> str:
    """Make one cheap authenticated call to classify the key. Network + SDK
    exceptions are translated to the PROBE_* vocabulary here, so callers (and
    tests) never need to construct real SDK exceptions."""
    import anthropic  # noqa: PLC0415
    try:
        client = anthropic.Anthropic(api_key=key, timeout=10.0, max_retries=0)
        # models.list is an authenticated, token-free call — it proves the key
        # works without spending generation tokens.
        client.models.list(limit=1)
        return PROBE_VALID
    except anthropic.AuthenticationError:
        return PROBE_INVALID
    except anthropic.PermissionDeniedError:
        return PROBE_INVALID
    except anthropic.RateLimitError:
        return PROBE_RATE_LIMITED
    except (anthropic.APITimeoutError, anthropic.APIConnectionError):
        return PROBE_UNREACHABLE
    except anthropic.APIStatusError as exc:
        code = getattr(exc, "status_code", None)
        if code in (401, 403):
            return PROBE_INVALID
        if code == 429:
            return PROBE_RATE_LIMITED
        return PROBE_ERROR
    except Exception:  # noqa: BLE001 — any other failure is a non-valid state
        return PROBE_ERROR


def check_api_key(
    api_key: Optional[str] = None,
    *,
    probe: Optional[Callable[[str], str]] = None,
) -> AIStatus:
    """
    Resolve the current AI credential state.

    `api_key` defaults to the configured ANTHROPIC_API_KEY. `probe` is injectable
    for testing — it takes the key and returns one of the PROBE_* strings.
    """
    key = api_key if api_key is not None else get_settings().ANTHROPIC_API_KEY
    key = (key or "").strip()

    if not key:
        status = _missing()
    elif not key.startswith("sk-ant-"):
        status = _malformed()
    else:
        probe = probe or _default_probe
        state = probe(key)
        status = _status_for_probe(state)

    if status.ok:
        log.info("ai_status.checked", state=status.state)
    else:
        # Loud by design — a degraded AI state must never pass silently.
        log.error("ai_status.fallback_active", state=status.state,
                  title=status.title)
    return status


__all__ = ["AIStatus", "check_api_key", "PROBE_VALID", "PROBE_INVALID",
           "PROBE_RATE_LIMITED", "PROBE_UNREACHABLE", "PROBE_ERROR"]
