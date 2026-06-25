"""
P0-B regression tests — invalid/missing Anthropic credentials must surface, never
silently downgrade users into fallback mode.

Covers: valid, invalid (revoked), empty/missing, malformed, rate-limited, and
timeout/unreachable. The network probe is injected so these run fully offline.
"""
from __future__ import annotations

from src.content.ai_status import (
    PROBE_INVALID,
    PROBE_RATE_LIMITED,
    PROBE_UNREACHABLE,
    PROBE_VALID,
    check_api_key,
)


def test_valid_key_reports_ok():
    s = check_api_key("sk-ant-realkey123", probe=lambda k: PROBE_VALID)
    assert s.ok is True
    assert s.fallback_active is False
    assert s.state == "valid"


def test_invalid_or_revoked_key():
    s = check_api_key("sk-ant-revoked", probe=lambda k: PROBE_INVALID)
    assert s.ok is False
    assert s.fallback_active is True
    assert s.state == "invalid"
    assert "FALLBACK" in s.message.upper()


def test_empty_key_is_missing_without_probing():
    called = {"n": 0}

    def probe(_k):  # must never be called for an empty key
        called["n"] += 1
        return PROBE_VALID

    s = check_api_key("", probe=probe)
    assert s.state == "missing"
    assert s.ok is False
    assert s.fallback_active is True
    assert called["n"] == 0


def test_none_key_falls_back_to_settings(monkeypatch):
    # When api_key is None we read settings; force it empty → missing.
    import src.content.ai_status as mod

    class FakeSettings:
        ANTHROPIC_API_KEY = ""

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())
    s = check_api_key(None, probe=lambda k: PROBE_VALID)
    assert s.state == "missing"


def test_malformed_key_is_caught_before_probe():
    called = {"n": 0}

    def probe(_k):
        called["n"] += 1
        return PROBE_VALID

    s = check_api_key("not-a-real-key", probe=probe)
    assert s.state == "malformed"
    assert s.ok is False
    assert called["n"] == 0  # never wasted a network call on an obviously bad key


def test_rate_limited_key():
    s = check_api_key("sk-ant-ok", probe=lambda k: PROBE_RATE_LIMITED)
    assert s.state == "rate_limited"
    assert s.ok is False
    assert s.fallback_active is True


def test_timeout_is_unreachable_not_invalid():
    # A network timeout must NOT be reported as an invalid key (don't scare the
    # user into regenerating a key that's actually fine).
    s = check_api_key("sk-ant-ok", probe=lambda k: PROBE_UNREACHABLE)
    assert s.state == "unreachable"
    assert s.ok is False


def test_status_dict_shape():
    s = check_api_key("sk-ant-ok", probe=lambda k: PROBE_VALID)
    d = s.as_dict()
    for key in ("state", "ok", "fallback_active", "title", "message", "checked_at"):
        assert key in d


def test_default_probe_classifies_real_sdk_exceptions(monkeypatch):
    """The default probe maps anthropic SDK exceptions to the right state."""
    import anthropic

    import src.content.ai_status as mod

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class models:  # noqa: N801
            @staticmethod
            def list(*a, **k):
                raise anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)

    # Construct a minimal client whose models.list raises AuthenticationError.
    class C:
        def __init__(self, *a, **k):
            self.models = self

        def list(self, *a, **k):
            raise anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)

    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: C())
    assert mod._default_probe("sk-ant-x") == PROBE_INVALID
