"""
Tests for the one-action carousel workflow (Pipeline.run_create_carousel).

The orchestrator is the single primary CTA: it must build immediately when
games are ready, retry once when the review panel rejects a draft, and warm up
the prerequisite chain in the background when there aren't enough rated games —
so the user never has to orchestrate discovery → rating → generation by hand.
"""
from __future__ import annotations

import asyncio

from src.scheduler.pipeline import Pipeline


def _run(coro):
    """Drive a coroutine on a dedicated loop, then drain any background tasks it
    spawned (e.g. the warm-up) so nothing leaks across tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(coro)
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _pipeline_with(factory_results):
    """A Pipeline whose run_carousel_factory yields the given results in order,
    and whose warm-up is stubbed so no real crawling/AI happens."""
    p = Pipeline.__new__(Pipeline)        # skip heavy __init__
    p._warming = False
    results = list(factory_results)
    calls = {"factory": 0, "warmup": 0}

    async def fake_factory():
        calls["factory"] += 1
        return results[min(calls["factory"] - 1, len(results) - 1)]

    async def fake_warmup():
        calls["warmup"] += 1
        p._warming = False

    p.run_carousel_factory = fake_factory
    p._warmup_for_carousel = fake_warmup
    return p, calls


def test_create_builds_immediately_when_ready():
    p, calls = _pipeline_with([{"carousels": 1, "part": 4, "final_score": 86.0}])
    out = _run(p.run_create_carousel())
    assert out["status"] == "created"
    assert out["part"] == 4
    assert calls["factory"] == 1
    assert calls["warmup"] == 0


def test_create_retries_once_on_panel_rejection():
    # First attempt rejected by the panel, second clears it.
    p, calls = _pipeline_with([
        {"carousels": 0, "rejected": True, "final_score": 74.0},
        {"carousels": 1, "part": 5},
    ])
    out = _run(p.run_create_carousel())
    assert out["status"] == "created"
    assert calls["factory"] == 2


def test_create_reports_retry_when_both_drafts_rejected():
    p, calls = _pipeline_with([
        {"carousels": 0, "rejected": True},
        {"carousels": 0, "rejected": True},
    ])
    out = _run(p.run_create_carousel())
    assert out["status"] == "retry"
    assert "message" in out
    assert calls["factory"] == 2


def test_create_warms_up_when_not_enough_games():
    p, calls = _pipeline_with([{"carousels": 0}])   # not enough candidates
    out = _run(p.run_create_carousel())   # _run drains the spawned warm-up task
    assert out["status"] == "warming_up"
    assert "message" in out
    assert calls["warmup"] == 1


def test_create_does_not_double_warm():
    p, calls = _pipeline_with([{"carousels": 0}])
    p._warming = True                      # a warm-up is already in flight
    out = _run(p.run_create_carousel())
    assert out["status"] == "warming_up"
    assert calls["warmup"] == 0            # didn't start a second one
