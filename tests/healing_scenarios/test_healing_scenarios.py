"""
tests/healing_scenarios/test_healing_scenarios.py

Research-grade parametrized unit tests for the healing pipeline.
These tests run WITHOUT a browser — they feed synthetic DOM snapshots
directly into the heuristic engine and validator to verify scoring
precision and correct rejection behavior.

Test categories:
  A. ID mutation          — id suffix changed (#user-name → #user-name-BROKEN)
  B. Class rename         — class name changed (.btn-login → .btn-login-v2)
  C. Text change          — visible text changed ("Log In" → "Sign In")
  D. DOM structural shift — element moved to different parent
  E. Sibling noise        — new sibling elements added around the target
  F. Tag preservation     — correct tag must be selected, not a same-text div
  G. Action constraint    — fill must reject non-input, select must reject non-select
  H. Wrong-target guard   — similar-text wrong element must score below correct one
  I. Ambiguity detection  — low-margin cases must be flagged
  J. Container rejection  — layout containers must score 0
"""

from __future__ import annotations

import pytest

from engine.heuristic_generator import generate
from validator import locator_validator as lv

# ---------------------------------------------------------------------------
# Shared DOM fixtures
# ---------------------------------------------------------------------------

_LOGIN_DOM = [
    {
        "tag": "input", "id": "user-name", "name": "user-name",
        "type": "text", "placeholder": "Username",
        "aria-label": "Username", "text": "", "is_interactive": True,
        "parent_tag": "form", "sibling_tags": ["input", "button"],
        "attrs": {"id": "user-name", "name": "user-name", "type": "text",
                  "placeholder": "Username", "aria-label": "Username"},
    },
    {
        "tag": "input", "id": "password", "name": "password",
        "type": "password", "placeholder": "Password",
        "aria-label": "Password", "text": "", "is_interactive": True,
        "parent_tag": "form", "sibling_tags": ["input", "button"],
        "attrs": {"id": "password", "name": "password", "type": "password",
                  "placeholder": "Password"},
    },
    {
        "tag": "input", "id": "login-button", "name": "login-button",
        "type": "submit", "value": "Login", "text": "", "is_interactive": True,
        "parent_tag": "form", "sibling_tags": ["input"],
        "attrs": {"id": "login-button", "type": "submit", "value": "Login"},
    },
    {
        "tag": "div", "id": "login_wrapper", "text": "Username Password Login",
        "is_interactive": False, "parent_tag": "main",
        "attrs": {"id": "login_wrapper"},
    },
]

_CART_DOM = [
    {
        "tag": "button", "class": "btn_primary btn_inventory", "text": "Add to cart",
        "data-test": "add-to-cart-sauce-labs-backpack",
        "is_interactive": True, "parent_tag": "div",
        "attrs": {"class": "btn_primary btn_inventory",
                  "data-test": "add-to-cart-sauce-labs-backpack"},
    },
    {
        "tag": "button", "class": "btn_secondary btn_inventory", "text": "Remove",
        "data-test": "remove-sauce-labs-backpack",
        "is_interactive": True, "parent_tag": "div",
        "attrs": {"class": "btn_secondary btn_inventory",
                  "data-test": "remove-sauce-labs-backpack"},
    },
    {
        "tag": "select", "id": "react-select-2-input", "class": "product_sort_container",
        "text": "", "is_interactive": True, "parent_tag": "div",
        "attrs": {"id": "react-select-2-input", "class": "product_sort_container"},
    },
    {
        "tag": "div", "class": "inventory_item_description",
        "text": "Sauce Labs Backpack. Carry all the things with the sleek, streamlined Sly Pack.",
        "is_interactive": False, "parent_tag": "div",
        "attrs": {"class": "inventory_item_description"},
    },
]


# ---------------------------------------------------------------------------
# Category A: ID mutation
# ---------------------------------------------------------------------------

class TestIdMutation:
    @pytest.mark.parametrize("broken,expected_locator", [
        ("#user-name-BROKEN",  "#user-name"),
        ("#user-name-OLD",     "#user-name"),
        ("#user-name-V2",      "#user-name"),
        ("#password-REMOVED",  "#password"),
    ])
    def test_suffix_strip_finds_id(self, broken: str, expected_locator: str) -> None:
        cands = generate(broken, _LOGIN_DOM, description="Username input")
        locators = [c.locator for c in cands]
        assert expected_locator in locators, (
            f"Expected {expected_locator!r} in candidates for broken={broken!r}, got {locators}"
        )

    def test_id_candidate_has_high_confidence(self) -> None:
        cands = generate("#user-name-BROKEN", _LOGIN_DOM)
        id_cand = next((c for c in cands if c.locator == "#user-name"), None)
        assert id_cand is not None
        assert id_cand.confidence >= 0.80


# ---------------------------------------------------------------------------
# Category B: Class rename
# ---------------------------------------------------------------------------

class TestClassRename:
    def test_partial_class_match_finds_element(self) -> None:
        cands = generate(".btn_inventory_BROKEN", _CART_DOM, description="Add to cart button")
        locators = [c.locator for c in cands]
        assert any("btn" in loc or "inventory" in loc for loc in locators), (
            f"No class-based candidate found. Candidates: {locators}"
        )

    def test_partial_class_candidate_is_produced(self) -> None:
        cands = generate(".btn_primary_BROKEN", _CART_DOM)
        strategies = {c.strategy for c in cands}
        assert any("class" in s for s in strategies), (
            f"No partial class strategy found. Strategies: {strategies}"
        )


# ---------------------------------------------------------------------------
# Category C: Text change
# ---------------------------------------------------------------------------

class TestTextChange:
    def test_text_search_finds_button(self) -> None:
        cands = generate("#submit-btn-BROKEN", _CART_DOM, description="Add to cart button")
        locators = [c.locator for c in cands]
        assert any("add to cart" in loc.lower() or "add-to-cart" in loc.lower()
                   for loc in locators), (
            f"No text-based candidate for 'Add to cart'. Candidates: {locators}"
        )

    def test_long_text_element_not_selected(self) -> None:
        """Description text DOM elements should not appear as candidates."""
        cands = generate("#product-desc-BROKEN", _CART_DOM, description="Product description")
        for c in cands:
            assert "Sauce Labs Backpack. Carry" not in c.locator


# ---------------------------------------------------------------------------
# Category D: DOM structural shift
# ---------------------------------------------------------------------------

class TestDomShift:
    def test_attribute_match_survives_parent_change(self) -> None:
        dom = [
            {
                "tag": "input", "id": "user-name", "name": "user-name",
                "type": "text", "placeholder": "Username",
                "parent_tag": "section",   # changed from form
                "sibling_tags": ["label"],  # changed siblings
                "attrs": {"id": "user-name", "name": "user-name", "type": "text"},
            }
        ]
        cands = generate("#user-name-BROKEN", dom, description="Username")
        locators = [c.locator for c in cands]
        assert "#user-name" in locators


# ---------------------------------------------------------------------------
# Category E: Sibling noise
# ---------------------------------------------------------------------------

class TestSiblingNoise:
    def test_correct_element_wins_despite_noisy_siblings(self) -> None:
        dom_with_noise = _LOGIN_DOM + [
            {
                "tag": "button", "id": "noise-btn-1", "text": "Cancel",
                "is_interactive": True, "parent_tag": "form",
                "attrs": {"id": "noise-btn-1"},
            },
            {
                "tag": "button", "id": "noise-btn-2", "text": "Reset",
                "is_interactive": True, "parent_tag": "form",
                "attrs": {"id": "noise-btn-2"},
            },
        ]
        cands = generate("#login-button-BROKEN", dom_with_noise, description="Login submit button")
        top = cands[0] if cands else None
        assert top is not None
        assert "login-button" in top.locator or "login" in top.locator.lower()


# ---------------------------------------------------------------------------
# Category F: Tag preservation
# ---------------------------------------------------------------------------

class TestTagPreservation:
    def test_button_ranks_above_div_after_validator_scoring(self) -> None:
        """
        After validator scoring (which applies tag-action multiplier), the button
        must outscore the div for a click action, even when the div has a matching id.

        NOTE: The generator itself sorts by confidence (no tag multiplier) — this
        test verifies the FULL pipeline via locator_validator.score_candidate, which
        is what HeuristicEngine uses after candidate generation.
        """
        div_el = {"tag": "div", "id": "login-btn", "text": "Login",
                  "attrs": {"id": "login-btn"}}
        button_el = {"tag": "button", "id": "login-button", "text": "Login",
                     "attrs": {"id": "login-button"}}
        expected = {"tag": "button", "text": "Login", "attrs": {"id": "login-button"}}

        def _score(el, sel):
            return lv.score_candidate(
                expected_profile=expected,
                matched_element=el,
                candidate={"selector": sel, "source": "heuristic", "confidence": 0.9,
                            "resolved": True},
                action="click",
                description="Login button",
            )["final_score"]

        button_score = _score(button_el, "#login-button")
        div_score    = _score(div_el, "#login-btn")
        assert button_score > div_score, (
            f"After validator scoring, div ({div_score:.3f}) should not beat "
            f"button ({button_score:.3f}) for a click action."
        )


# ---------------------------------------------------------------------------
# Category G: Action-tag constraint (validator)
# ---------------------------------------------------------------------------

class TestActionTagConstraint:
    def _score(self, candidate: dict, expected: dict, action: str) -> dict:
        return lv.score_candidate(
            expected_profile=expected,
            matched_element=candidate,
            candidate={"selector": "#x", "source": "heuristic", "confidence": 0.9, "resolved": True},
            action=action,
        )

    def test_fill_on_div_scores_zero(self) -> None:
        div_el = {"tag": "div", "text": "Username", "id": "user-name", "attrs": {"id": "user-name"}}
        expected = {"tag": "input", "attrs": {"id": "user-name"}}
        result = self._score(div_el, expected, action="fill")
        assert result["final_score"] == 0.0, (
            f"fill on div should score 0, got {result['final_score']}"
        )

    def test_fill_on_input_scores_positive(self) -> None:
        input_el = {"tag": "input", "type": "text", "id": "user-name", "attrs": {"id": "user-name"}}
        expected = {"tag": "input", "attrs": {"id": "user-name"}}
        result = self._score(input_el, expected, action="fill")
        assert result["final_score"] > 0.0

    def test_select_on_input_scores_zero(self) -> None:
        input_el = {"tag": "input", "type": "text", "id": "sort", "attrs": {"id": "sort"}}
        expected = {"tag": "select", "attrs": {"id": "sort"}}
        result = self._score(input_el, expected, action="select")
        assert result["final_score"] == 0.0

    def test_select_on_select_scores_positive(self) -> None:
        select_el = {"tag": "select", "id": "sort", "attrs": {"id": "sort"}}
        expected = {"tag": "select", "attrs": {"id": "sort"}}
        result = self._score(select_el, expected, action="select")
        assert result["final_score"] > 0.0

    def test_click_on_bare_div_scores_zero(self) -> None:
        div_el = {"tag": "div", "text": "Click me", "id": "btn", "attrs": {"id": "btn"}}
        expected = {"tag": "button", "attrs": {"id": "btn"}}
        result = self._score(div_el, expected, action="click")
        assert result["final_score"] == 0.0

    def test_click_on_div_with_button_role_scores_positive(self) -> None:
        div_el = {
            "tag": "div", "text": "Click me", "id": "btn",
            "role": "button",
            "attrs": {"id": "btn", "role": "button"},
        }
        expected = {"tag": "div", "attrs": {"id": "btn", "role": "button"}}
        result = self._score(div_el, expected, action="click")
        assert result["final_score"] > 0.0


# ---------------------------------------------------------------------------
# Category H: Wrong-target guard
# ---------------------------------------------------------------------------

class TestWrongTargetGuard:
    def test_correct_element_outscores_wrong_element(self) -> None:
        correct = {"tag": "input", "id": "user-name", "placeholder": "Username",
                   "type": "text", "text": "",
                   "attrs": {"id": "user-name", "placeholder": "Username", "type": "text"}}
        wrong   = {"tag": "input", "id": "password", "placeholder": "Password",
                   "type": "password", "text": "",
                   "attrs": {"id": "password", "placeholder": "Password", "type": "password"}}
        expected = {"tag": "input", "id": "user-name",
                    "attrs": {"id": "user-name", "placeholder": "Username"}}

        def _score(el):
            return lv.score_candidate(
                expected_profile=expected,
                matched_element=el,
                candidate={"selector": "#x", "source": "heuristic", "confidence": 0.9,
                            "resolved": True},
                action="fill",
            )["final_score"]

        assert _score(correct) > _score(wrong), (
            "Wrong element (password field) scored >= correct element (username field)"
        )

    def test_container_with_matching_text_loses_to_button(self) -> None:
        container = {
            "tag": "div", "id": "cart-section", "text": "Add to cart items",
            "attrs": {"id": "cart-section"},
        }
        button = {
            "tag": "button", "id": "add-to-cart-btn", "text": "Add to cart",
            "attrs": {"id": "add-to-cart-btn"},
        }
        expected = {"tag": "button", "text": "Add to cart",
                    "attrs": {"id": "add-to-cart-btn"}}

        def _score(el):
            return lv.score_candidate(
                expected_profile=expected,
                matched_element=el,
                candidate={"selector": "#x", "source": "heuristic", "confidence": 0.7,
                            "resolved": True},
                action="click",
                description="add to cart button",
            )["final_score"]

        assert _score(button) > _score(container), (
            f"Container scored {_score(container):.3f} >= button {_score(button):.3f}"
        )


# ---------------------------------------------------------------------------
# Category I: Ambiguity detection (low margin)
# ---------------------------------------------------------------------------

class TestAmbiguityDetection:
    def test_identical_elements_produce_low_margin(self) -> None:
        """
        When two buttons have the same text and the broken selector is class-based,
        the margin between top and second candidate should be low (< 0.15),
        which will trigger a LOW_MARGIN risk flag in the pipeline.
        """
        dom = [
            {"tag": "button", "text": "Submit", "class": "btn-primary",
             "attrs": {"class": "btn-primary"}},
            {"tag": "button", "text": "Submit", "class": "btn-secondary",
             "attrs": {"class": "btn-secondary"}},
        ]
        cands = generate(".btn-primary-BROKEN", dom, description="Submit button")
        if len(cands) >= 2:
            margin = cands[0].confidence - cands[1].confidence
            # Low margin indicates ambiguity — both elements are plausible
            assert margin < 0.15, (
                f"Expected low margin for ambiguous case but got {margin:.3f}. "
                "This means one candidate is strongly preferred, which is acceptable."
            )


# ---------------------------------------------------------------------------
# Category J: Container rejection
# ---------------------------------------------------------------------------

class TestContainerRejection:
    def test_layout_div_with_long_text_scores_zero(self) -> None:
        container = {
            "tag": "div",
            "text": "This is a product description with a lot of text. It goes on and on.",
            "attrs": {},
        }
        expected = {"tag": "button", "attrs": {}}
        result = lv.score_candidate(
            expected_profile=expected,
            matched_element=container,
            candidate={"selector": "div", "source": "heuristic", "confidence": 0.5,
                        "resolved": True},
            action="click",
        )
        assert result["final_score"] == 0.0

    def test_known_container_selector_scores_zero(self) -> None:
        for bad_sel in ["#page_wrapper", "#header_container", "#contents_wrapper"]:
            result = lv.score_candidate(
                expected_profile={"tag": "button", "attrs": {}},
                matched_element={"tag": "div", "text": "header", "attrs": {}},
                candidate={"selector": bad_sel, "source": "heuristic", "confidence": 0.9,
                            "resolved": True},
                action="click",
            )
            assert result["final_score"] == 0.0, (
                f"Container selector {bad_sel!r} should score 0, got {result['final_score']}"
            )
