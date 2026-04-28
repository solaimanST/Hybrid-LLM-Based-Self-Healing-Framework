"""
tests/test_healing_engine.py

Unit tests for engine/self_healer.py (SelfHealer).

All tests are pure Python — no network, no Playwright, no API key required.
The DOM analyzer, heuristic generator, LLM client, and repair memory are
all mocked at the method or module level.

Verifies:
  - Original selector success returns without healing
  - healing_mode="none" fails cleanly after one attempt
  - Hybrid mode collects candidates from memory, heuristic, and LLM
  - Ranking selects the best candidate (source priority tiebreaker)
  - Failed candidates are skipped; the next is tried in order
  - Repair memory is persisted on successful healing

Run:
    pytest tests/test_healing_engine.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.self_healer import SelfHealer, HealingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(url: str = "https://example.com") -> MagicMock:
    page = MagicMock()
    page.url = url
    return page


def _cand(
    selector: str,
    source: str = "heuristic",
    confidence: float = 0.8,
) -> dict:
    """Build a minimal resolved candidate dict.

    ``final_score`` is pre-set to ``confidence`` so that tests which patch
    ``_score_candidates`` as an identity function see a positive score and
    the heal loop doesn't skip the candidate via ``if score <= 0: continue``.
    """
    return {
        "selector": selector,
        "source": source,
        "locator_type": "css",
        "confidence": confidence,
        "reason": "unit-test candidate",
        "resolved": True,
        "matched_count": 1,
        "matched_element": None,
        "final_score": confidence,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def page():
    return _make_page()


@pytest.fixture
def memory():
    m = MagicMock()
    m.find_candidates.return_value = []
    m.add_record = MagicMock()
    return m


@pytest.fixture
def llm_client():
    client = MagicMock()
    client.suggest_selectors = AsyncMock(return_value=[])
    return client


@pytest.fixture
def healer(page, memory, llm_client):
    return SelfHealer(
        page=page,
        llm_client=llm_client,
        memory=memory,
        healing_mode="hybrid",
    )


# ---------------------------------------------------------------------------
# Test: original selector succeeds — no healing attempted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_original_selector_success(healer, llm_client):
    """When the original selector works, return immediately with source='original'."""
    with patch.object(healer, "_try_action", new=AsyncMock(return_value=(True, ""))):
        result = await healer.fill("#user-name", "standard_user")

    assert isinstance(result, HealingResult)
    assert result.success is True
    assert result.source == "original"
    assert result.healed_selector is None
    assert result.attempts == 1
    llm_client.suggest_selectors.assert_not_called()


# ---------------------------------------------------------------------------
# Test: healing_mode="none" — fail immediately, no repair attempted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healing_mode_none_fails_cleanly(page, memory, llm_client):
    """healing_mode='none' must report failure without attempting any repair."""
    healer = SelfHealer(
        page=page,
        llm_client=llm_client,
        memory=memory,
        healing_mode="none",
    )
    with patch.object(healer, "_try_action", new=AsyncMock(return_value=(False, "timeout error"))):
        result = await healer.fill("#user-name-BROKEN", "value")

    assert result.success is False
    assert result.source == "failed"
    assert result.healed_selector is None
    assert result.original_error == "timeout error"
    assert result.attempts == 1
    llm_client.suggest_selectors.assert_not_called()
    memory.find_candidates.assert_not_called()


# ---------------------------------------------------------------------------
# Test: hybrid mode collects candidates from memory, heuristic, and LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_mode_merges_all_sources(healer, memory, llm_client):
    """
    In hybrid mode, candidates from memory, heuristic, and LLM must all be
    collected and present in the final result.candidates list.
    """
    mem_cand = _cand("#mem-selector",       source="memory",    confidence=0.9)
    h_cand   = _cand("#heuristic-selector", source="heuristic", confidence=0.8)
    llm_cand = _cand("#llm-selector",       source="llm",       confidence=0.7)

    memory.find_candidates.return_value = [mem_cand]
    llm_client.suggest_selectors.return_value = [llm_cand]

    # Original fails; first ranked candidate (memory) succeeds.
    try_side = AsyncMock(side_effect=[(False, "original error"), (True, "")])

    with (
        patch.object(healer, "_try_action", new=try_side),
        patch.object(healer, "_extract_dom", new=AsyncMock(return_value=[])),
        patch.object(healer._dom, "build_prompt_context", new=AsyncMock(return_value="")),
        patch.object(healer, "_resolve_candidates", new=AsyncMock(
            return_value=[mem_cand, h_cand, llm_cand]
        )),
        patch.object(healer, "_score_candidates", side_effect=lambda *a, **kw: a[0]),
        patch(
            "engine.self_healer.generate_heuristic_candidates",
            return_value=[h_cand],
        ),
    ):
        result = await healer.fill("#broken-selector", "value", description="test field")

    assert result.success is True
    sources = {c.get("source") for c in result.candidates}
    assert "memory"    in sources
    assert "heuristic" in sources
    assert "llm"       in sources


# ---------------------------------------------------------------------------
# Test: best-ranked candidate chosen by source priority tiebreaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_best_ranked_candidate_chosen(healer, memory, llm_client):
    """
    When all candidates have final_score=0.0 (matched_element=None) and equal
    confidence, rank_candidates must prefer memory > heuristic > llm.
    The memory candidate's selector must become healed_selector.
    """
    mem_cand = _cand("#mem-selector",       source="memory",    confidence=0.8)
    h_cand   = _cand("#heuristic-selector", source="heuristic", confidence=0.8)
    llm_cand = _cand("#llm-selector",       source="llm",       confidence=0.8)

    memory.find_candidates.return_value = [mem_cand]
    llm_client.suggest_selectors.return_value = [llm_cand]

    def _try(action, selector, fill_value, **kwargs):
        # Original fails; every healed candidate succeeds immediately.
        return (False, "timeout") if selector == "#broken-selector" else (True, "")

    with (
        patch.object(healer, "_try_action", new=AsyncMock(side_effect=_try)),
        patch.object(healer, "_extract_dom", new=AsyncMock(return_value=[])),
        patch.object(healer._dom, "build_prompt_context", new=AsyncMock(return_value="")),
        # Return candidates in deliberately wrong order — ranking must correct it.
        patch.object(healer, "_resolve_candidates", new=AsyncMock(
            return_value=[llm_cand, h_cand, mem_cand]
        )),
        patch.object(healer, "_score_candidates", side_effect=lambda *a, **kw: a[0]),
        patch(
            "engine.self_healer.generate_heuristic_candidates",
            return_value=[h_cand],
        ),
    ):
        result = await healer.fill("#broken-selector", "value")

    assert result.success is True
    assert result.healed_selector == "#mem-selector"
    assert result.source == "memory"


# ---------------------------------------------------------------------------
# Test: failed candidates are skipped; next candidate is tried in order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_candidates_skipped(healer, memory, llm_client):
    """
    If the top-ranked candidate fails, the engine must continue to the next.
    attempts must count the original + each candidate tried.
    """
    cand1 = _cand("#cand1", source="heuristic", confidence=0.9)
    cand2 = _cand("#cand2", source="heuristic", confidence=0.7)

    memory.find_candidates.return_value = []
    llm_client.suggest_selectors.return_value = []

    def _try(action, selector, fill_value, **kwargs):
        # Original and cand1 fail; cand2 succeeds.
        return (False, "not found") if selector in ("#broken", "#cand1") else (True, "")

    with (
        patch.object(healer, "_try_action", new=AsyncMock(side_effect=_try)),
        patch.object(healer, "_extract_dom", new=AsyncMock(return_value=[])),
        patch.object(healer._dom, "build_prompt_context", new=AsyncMock(return_value="")),
        # cand1 has higher confidence → ranked first; cand2 ranked second.
        patch.object(healer, "_resolve_candidates", new=AsyncMock(
            return_value=[cand1, cand2]
        )),
        patch.object(healer, "_score_candidates", side_effect=lambda *a, **kw: a[0]),
        patch(
            "engine.self_healer.generate_heuristic_candidates",
            return_value=[cand1, cand2],
        ),
    ):
        result = await healer.fill("#broken", "value")

    assert result.success is True
    assert result.healed_selector == "#cand2"
    assert result.attempts == 3   # original + cand1 + cand2


# ---------------------------------------------------------------------------
# Test: repair memory persisted on successful healing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repair_memory_saved_on_success(healer, memory, llm_client):
    """
    When a candidate succeeds, memory.add_record must be called exactly once
    with the correct failed_selector and healed_selector fields.
    """
    h_cand = _cand("#healed-selector", source="heuristic", confidence=0.8)

    memory.find_candidates.return_value = []
    llm_client.suggest_selectors.return_value = []

    def _try(action, selector, fill_value, **kwargs):
        return (False, "err") if selector == "#failed-sel" else (True, "")

    with (
        patch.object(healer, "_try_action", new=AsyncMock(side_effect=_try)),
        patch.object(healer, "_extract_dom", new=AsyncMock(return_value=[])),
        patch.object(healer._dom, "build_prompt_context", new=AsyncMock(return_value="")),
        patch.object(healer, "_resolve_candidates", new=AsyncMock(return_value=[h_cand])),
        patch.object(healer, "_score_candidates", side_effect=lambda *a, **kw: a[0]),
        patch(
            "engine.self_healer.generate_heuristic_candidates",
            return_value=[h_cand],
        ),
    ):
        result = await healer.fill("#failed-sel", "value")

    assert result.success is True
    assert result.healed_selector == "#healed-selector"

    memory.add_record.assert_called_once()
    record = memory.add_record.call_args[0][0]
    assert record["failed_selector"] == "#failed-sel"
    assert record["healed_selector"] == "#healed-selector"
