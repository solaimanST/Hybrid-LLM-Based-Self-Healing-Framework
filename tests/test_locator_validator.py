"""
tests/test_locator_validator.py

Unit tests for validator/locator_validator.py.

Tests the simple scoring and ranking API:
  - attribute_similarity
  - text_similarity
  - tag_similarity
  - structure_similarity
  - compute_final_score
  - score_candidate
  - rank_candidates

No Playwright, no network, no API key required.

Run:
    pytest tests/test_locator_validator.py -v
"""

from __future__ import annotations

import json

import pytest

from validator.locator_validator import (
    attribute_similarity,
    compute_final_score,
    rank_candidates,
    score_candidate,
    structure_similarity,
    tag_similarity,
    text_similarity,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _candidate(
    selector: str = "#btn",
    source: str = "heuristic",
    locator_type: str = "css",
    confidence: float = 0.8,
    reason: str = "test candidate",
) -> dict:
    return {
        "selector": selector,
        "source": source,
        "locator_type": locator_type,
        "confidence": confidence,
        "reason": reason,
    }


def _scored_candidate(
    selector: str = "#btn",
    final_score: float = 0.5,
    source: str = "heuristic",
    confidence: float = 0.8,
    matched_count: int = 1,
) -> dict:
    """Pre-built scored candidate for rank_candidates tests."""
    return {
        "selector": selector,
        "source": source,
        "locator_type": "css",
        "confidence": confidence,
        "reason": "r",
        "final_score": final_score,
        "matched_count": matched_count,
    }


# ---------------------------------------------------------------------------
# attribute_similarity
# ---------------------------------------------------------------------------

class TestAttributeSimilarity:

    def test_identical_attrs_return_1(self):
        attrs = {"id": "btn-login", "name": "login", "type": "submit"}
        assert attribute_similarity(attrs, attrs) == 1.0

    def test_empty_attrs_both_return_1(self):
        assert attribute_similarity({}, {}) == 1.0

    def test_completely_different_attrs_return_low(self):
        a = {"id": "username-field", "name": "username", "type": "text"}
        b = {"id": "submit-button", "name": "submit", "type": "submit"}
        score = attribute_similarity(a, b)
        assert 0.0 <= score < 1.0

    def test_partial_match_between_0_and_1(self):
        a = {"id": "user-name", "name": "user-name", "type": "text"}
        b = {"id": "user-name", "name": "user-name", "type": "password"}
        score = attribute_similarity(a, b)
        assert 0.0 < score < 1.0

    def test_one_side_missing_attr_penalised(self):
        a = {"id": "user-name"}
        b = {"id": None}
        score = attribute_similarity(a, b)
        assert score < 1.0

    def test_similar_id_gets_partial_credit(self):
        a = {"id": "user-name"}
        b = {"id": "user-email"}
        score = attribute_similarity(a, b)
        assert 0.0 < score < 1.0

    def test_result_clamped_to_0_1(self):
        attrs = {"id": "x"}
        score = attribute_similarity(attrs, attrs)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# text_similarity
# ---------------------------------------------------------------------------

class TestTextSimilarity:

    def test_both_empty_returns_1(self):
        assert text_similarity("", "") == 1.0

    def test_identical_text_returns_1(self):
        assert text_similarity("Login", "Login") == 1.0

    def test_one_empty_returns_0(self):
        assert text_similarity("Login", "") == 0.0
        assert text_similarity("", "Login") == 0.0

    def test_similar_text_between_0_and_1(self):
        score = text_similarity("Sign in", "Sign up")
        assert 0.0 < score < 1.0

    def test_completely_different_text_low_score(self):
        score = text_similarity("Submit", "Cancel")
        assert score < 0.9

    def test_case_insensitive(self):
        assert text_similarity("LOGIN", "login") == 1.0

    def test_result_clamped_to_0_1(self):
        score = text_similarity("hello", "world")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# tag_similarity
# ---------------------------------------------------------------------------

class TestTagSimilarity:

    def test_identical_tag_returns_1(self):
        assert tag_similarity("input", "input") == 1.0
        assert tag_similarity("button", "button") == 1.0

    def test_equivalent_tags_return_half(self):
        assert tag_similarity("button", "input") == 0.5
        assert tag_similarity("input", "button") == 0.5
        assert tag_similarity("textarea", "input") == 0.5
        assert tag_similarity("a", "button") == 0.5

    def test_unrelated_tags_return_0(self):
        assert tag_similarity("input", "a") == 0.0
        assert tag_similarity("select", "a") == 0.0

    def test_empty_tag_returns_0(self):
        assert tag_similarity("", "input") == 0.0
        assert tag_similarity("input", "") == 0.0

    def test_result_clamped_to_0_1(self):
        score = tag_similarity("input", "button")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# structure_similarity
# ---------------------------------------------------------------------------

class TestStructureSimilarity:

    def test_identical_context_returns_1(self):
        ctx = {"parent_tag": "form", "sibling_tags": ["input", "label"]}
        assert structure_similarity(ctx, ctx) == 1.0

    def test_empty_contexts_return_1(self):
        assert structure_similarity({}, {}) == 1.0

    def test_different_parent_lowers_score(self):
        a = {"parent_tag": "form", "sibling_tags": []}
        b = {"parent_tag": "div", "sibling_tags": []}
        score = structure_similarity(a, b)
        assert score < 1.0

    def test_same_parent_scores_high(self):
        a = {"parent_tag": "form", "sibling_tags": []}
        b = {"parent_tag": "form", "sibling_tags": []}
        score = structure_similarity(a, b)
        assert score == 1.0

    def test_result_clamped_to_0_1(self):
        a = {"parent_tag": "form", "sibling_tags": ["a", "b"]}
        b = {"parent_tag": "div", "sibling_tags": ["c", "d"]}
        score = structure_similarity(a, b)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# compute_final_score
# ---------------------------------------------------------------------------

class TestComputeFinalScore:

    def test_all_perfect_returns_1(self):
        assert compute_final_score(1.0, 1.0, 1.0, 1.0) == 1.0

    def test_all_zero_returns_0(self):
        assert compute_final_score(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_wrong_tag_lowers_score(self):
        score_good_tag  = compute_final_score(1.0, 1.0, 1.0, 1.0)
        score_wrong_tag = compute_final_score(1.0, 1.0, 0.0, 1.0)
        assert score_wrong_tag < score_good_tag

    def test_wrong_text_lowers_score(self):
        score_good_text  = compute_final_score(1.0, 1.0, 1.0, 1.0)
        score_wrong_text = compute_final_score(1.0, 0.0, 1.0, 1.0)
        assert score_wrong_text < score_good_text

    def test_result_clamped_to_0_1(self):
        score = compute_final_score(0.5, 0.5, 0.5, 0.5)
        assert 0.0 <= score <= 1.0

    def test_weights_sum_to_1(self):
        # If all inputs are 0.5, result should be 0.5
        assert abs(compute_final_score(0.5, 0.5, 0.5, 0.5) - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------

class TestScoreCandidate:

    def _profile(self, attrs=None, text="", tag="input", parent_tag=None, sibling_tags=None):
        return {
            "attrs": attrs or {},
            "text": text,
            "tag": tag,
            "parent_tag": parent_tag,
            "sibling_tags": sibling_tags or [],
        }

    def test_no_matched_element_scores_zero(self):
        cand = _candidate()
        result = score_candidate({}, None, cand)

        assert result["final_score"] == 0.0
        assert result["attribute_score"] == 0.0
        assert result["text_score"] == 0.0
        assert result["tag_score"] == 0.0
        assert result["structure_score"] == 0.0
        assert result["matched_element"] is None

    def test_exact_match_scores_high(self):
        profile = self._profile(
            attrs={"id": "login-btn", "name": "login"},
            text="Login",
            tag="input",
        )
        matched = self._profile(
            attrs={"id": "login-btn", "name": "login"},
            text="Login",
            tag="input",
        )
        cand = _candidate("#login-btn")
        result = score_candidate(profile, matched, cand)

        assert result["final_score"] > 0.8

    def test_wrong_tag_lowers_final_score(self):
        profile = self._profile(tag="input")
        matched_correct = self._profile(tag="input")
        matched_wrong   = self._profile(tag="a")

        cand = _candidate()
        score_correct = score_candidate(profile, matched_correct, cand)["final_score"]
        score_wrong   = score_candidate(profile, matched_wrong,   cand)["final_score"]

        assert score_correct > score_wrong

    def test_wrong_text_lowers_final_score(self):
        profile = self._profile(text="Login", tag="button")
        matched_correct = self._profile(text="Login",  tag="button")
        matched_wrong   = self._profile(text="Cancel", tag="button")

        cand = _candidate()
        score_correct = score_candidate(profile, matched_correct, cand)["final_score"]
        score_wrong   = score_candidate(profile, matched_wrong,   cand)["final_score"]

        assert score_correct > score_wrong

    def test_output_contains_all_required_keys(self):
        cand = _candidate()
        result = score_candidate({}, None, cand)

        required = {
            "selector", "source", "locator_type", "confidence", "reason",
            "matched_element", "attribute_score", "text_score",
            "tag_score", "structure_score", "final_score",
        }
        assert required <= result.keys()

    def test_original_candidate_fields_preserved(self):
        cand = _candidate(selector="#my-btn", source="memory", confidence=0.95)
        result = score_candidate({}, None, cand)

        assert result["selector"] == "#my-btn"
        assert result["source"] == "memory"
        assert result["confidence"] == 0.95

    def test_result_is_json_serialisable(self):
        cand = _candidate()
        result = score_candidate({}, None, cand)
        dumped = json.dumps(result)
        reloaded = json.loads(dumped)
        assert reloaded["final_score"] == 0.0


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

class TestRankCandidates:

    def test_sorted_by_final_score_descending(self):
        candidates = [
            _scored_candidate("#a", final_score=0.3),
            _scored_candidate("#b", final_score=0.9),
            _scored_candidate("#c", final_score=0.6),
        ]
        ranked = rank_candidates(candidates)
        scores = [c["final_score"] for c in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_highest_score_is_first(self):
        candidates = [
            _scored_candidate("#low",  final_score=0.2),
            _scored_candidate("#high", final_score=0.8),
            _scored_candidate("#mid",  final_score=0.5),
        ]
        ranked = rank_candidates(candidates)
        assert ranked[0]["selector"] == "#high"

    def test_prefers_single_match_when_scores_equal(self):
        c_single = _scored_candidate("#a", final_score=0.7, matched_count=1)
        c_multi  = _scored_candidate("#b", final_score=0.7, matched_count=5)

        ranked = rank_candidates([c_multi, c_single])
        assert ranked[0]["selector"] == "#a"

    def test_source_priority_when_all_tied(self):
        # All equal final_score, single match, equal confidence
        c_llm      = _scored_candidate("#llm",      final_score=0.5, source="llm",      confidence=0.8)
        c_heuristic= _scored_candidate("#heuristic",final_score=0.5, source="heuristic",confidence=0.8)
        c_memory   = _scored_candidate("#memory",   final_score=0.5, source="memory",   confidence=0.8)

        ranked = rank_candidates([c_llm, c_heuristic, c_memory])
        assert ranked[0]["selector"] == "#memory"
        assert ranked[1]["selector"] == "#heuristic"
        assert ranked[2]["selector"] == "#llm"

    def test_confidence_tiebreaker_after_score(self):
        c_low_conf  = _scored_candidate("#a", final_score=0.0, confidence=0.5)
        c_high_conf = _scored_candidate("#b", final_score=0.0, confidence=0.9)

        ranked = rank_candidates([c_low_conf, c_high_conf])
        assert ranked[0]["selector"] == "#b"

    def test_empty_list_returns_empty(self):
        assert rank_candidates([]) == []

    def test_single_candidate_returned_as_is(self):
        cands = [_scored_candidate("#only", final_score=0.7)]
        ranked = rank_candidates(cands)
        assert len(ranked) == 1
        assert ranked[0]["selector"] == "#only"

    def test_missing_fields_handled_gracefully(self):
        # Candidates without final_score/matched_count should not raise
        cands = [{"selector": "#x", "source": "llm"}]
        ranked = rank_candidates(cands)
        assert len(ranked) == 1
