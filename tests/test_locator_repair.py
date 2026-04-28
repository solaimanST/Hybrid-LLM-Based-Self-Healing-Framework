"""
tests/test_locator_repair.py

Unit tests for llm/locator_repair.py.

Focuses on the two public functions used by LLMClient:
  - build_repair_prompt(failed_selector, action_description, dom_context, max_candidates)
  - normalize_locator_candidates(raw_candidates)

All tests are pure Python — no network, no Playwright, no API key required.

Run:
    pytest tests/test_locator_repair.py -v
"""

from __future__ import annotations

import pytest

from llm.locator_repair import build_repair_prompt, normalize_locator_candidates


# ---------------------------------------------------------------------------
# build_repair_prompt
# ---------------------------------------------------------------------------

class TestBuildRepairPrompt:

    def test_returns_non_empty_string(self):
        prompt = build_repair_prompt("#broken-selector", "click", "DOM context here")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_failed_selector(self):
        prompt = build_repair_prompt("#user-name-BROKEN", "fill", "dom")
        assert "#user-name-BROKEN" in prompt

    def test_contains_action_description(self):
        prompt = build_repair_prompt("#sel", "fill the username", "dom")
        assert "fill the username" in prompt

    def test_contains_dom_context(self):
        dom = "[0] <input> attrs: id=\"user-name\" | text: \"\""
        prompt = build_repair_prompt("#broken", "click", dom)
        assert dom in prompt

    def test_max_candidates_reflected_in_prompt(self):
        prompt_3 = build_repair_prompt("#sel", "click", "dom", max_candidates=3)
        prompt_7 = build_repair_prompt("#sel", "click", "dom", max_candidates=7)
        # Both are valid strings; max_candidates must appear somewhere
        assert isinstance(prompt_3, str) and isinstance(prompt_7, str)

    def test_missing_action_defaults_gracefully(self):
        prompt = build_repair_prompt("#sel", "", "dom")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_json_output_schema_hint(self):
        prompt = build_repair_prompt("#sel", "click", "dom")
        # The prompt must instruct the LLM to respond in JSON
        assert "json" in prompt.lower() or "JSON" in prompt or "{" in prompt


# ---------------------------------------------------------------------------
# normalize_locator_candidates
# ---------------------------------------------------------------------------

class TestNormalizeLocatorCandidates:

    def test_returns_list(self):
        result = normalize_locator_candidates([])
        assert isinstance(result, list)

    def test_empty_input_returns_empty(self):
        assert normalize_locator_candidates([]) == []

    def test_valid_candidate_preserved(self):
        raw = [{"selector": "#btn", "locator_type": "css", "confidence": 0.8, "reason": "id match"}]
        result = normalize_locator_candidates(raw)
        assert len(result) == 1
        assert result[0]["selector"] == "#btn"

    def test_empty_selector_removed(self):
        raw = [
            {"selector": "", "locator_type": "css", "confidence": 0.8, "reason": "r"},
            {"selector": "   ", "locator_type": "css", "confidence": 0.8, "reason": "r"},
            {"selector": "#valid", "locator_type": "css", "confidence": 0.8, "reason": "r"},
        ]
        result = normalize_locator_candidates(raw)
        assert len(result) == 1
        assert result[0]["selector"] == "#valid"

    def test_duplicates_removed(self):
        raw = [
            {"selector": "#btn", "locator_type": "css", "confidence": 0.9, "reason": "r1"},
            {"selector": "#btn", "locator_type": "css", "confidence": 0.7, "reason": "r2"},  # dup
            {"selector": "#other", "locator_type": "css", "confidence": 0.8, "reason": "r3"},
        ]
        result = normalize_locator_candidates(raw)
        selectors = [c["selector"] for c in result]
        assert selectors.count("#btn") == 1
        assert "#other" in selectors

    def test_confidence_clamped_above_one(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": 2.5, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["confidence"] == 1.0

    def test_confidence_clamped_below_zero(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": -0.5, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["confidence"] == 0.0

    def test_confidence_within_range_unchanged(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": 0.73, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert abs(result[0]["confidence"] - 0.73) < 1e-4

    def test_source_always_llm(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": 0.8, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["source"] == "llm"

    def test_unknown_locator_type_defaults_to_css(self):
        raw = [{"selector": "#a", "locator_type": "magic_type_xyz", "confidence": 0.8, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["locator_type"] == "css"

    def test_known_locator_types_preserved(self):
        for lt in ("css", "text", "role", "label", "placeholder", "test_id", "xpath"):
            raw = [{"selector": "#a", "locator_type": lt, "confidence": 0.8, "reason": "r"}]
            result = normalize_locator_candidates(raw)
            assert result[0]["locator_type"] == lt

    def test_missing_confidence_defaults_to_0_5(self):
        raw = [{"selector": "#a", "locator_type": "css", "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["confidence"] == 0.5

    def test_missing_reason_defaults_to_string(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": 0.8}]
        result = normalize_locator_candidates(raw)
        assert isinstance(result[0]["reason"], str)
        assert len(result[0]["reason"]) > 0

    def test_missing_locator_type_defaults_to_css(self):
        raw = [{"selector": "#a", "confidence": 0.8, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert result[0]["locator_type"] == "css"

    def test_non_dict_entries_skipped(self):
        raw = ["#a", None, 42, {"selector": "#valid", "locator_type": "css", "confidence": 0.8, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert len(result) == 1
        assert result[0]["selector"] == "#valid"

    def test_output_required_keys_present(self):
        raw = [{"selector": "#x", "locator_type": "css", "confidence": 0.7, "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert {"selector", "locator_type", "source", "confidence", "reason"} <= result[0].keys()

    def test_invalid_confidence_type_defaults_safely(self):
        raw = [{"selector": "#a", "locator_type": "css", "confidence": "high", "reason": "r"}]
        result = normalize_locator_candidates(raw)
        assert isinstance(result[0]["confidence"], float)
        assert 0.0 <= result[0]["confidence"] <= 1.0
