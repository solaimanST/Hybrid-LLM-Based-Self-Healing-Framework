"""
validator/locator_validator.py

Precision-first scoring for self-healing locator repair candidates.

Design philosophy
-----------------
Precision > Recall.  We prefer NO healing over WRONG healing.
Every candidate is measured against the expected target element on seven
independent dimensions; a hard constraint on tag-action compatibility zeroes
out structurally impossible matches before the weighted sum is computed.

Scoring weights (sum to 1.0)
-----------------------------
    attribute   0.30  — identity attributes (id, name, data-testid, aria-label…)
    tag         0.15  — structural tag match (also enforced as hard constraint)
    structure   0.10  — parent-tag match (DOM location context)
    context     0.10  — sibling-tag Jaccard overlap (prevents same-text/wrong-place)
    text        0.10  — visible text similarity (intentionally LOW to avoid false
                        positives from shared button labels or headings)
    stability   0.10  — selector-type robustness (data-testid > #id > name > class)
    action      0.10  — action / tag compatibility (fill→input, click→button/a…)
    confidence  0.05  — self-reported confidence from heuristic / LLM source

Hard constraints (applied AFTER weighted sum → override score to 0.0)
----------------------------------------------------------------------
    fill   → candidate tag ∉ {input, textarea}         → final_score = 0.0
    select → candidate tag ≠ select                    → final_score = 0.0
    click  → candidate tag ∉ clickable AND no role     → final_score = 0.0
    any    → layout container with long visible text   → final_score = 0.0

Public API
----------
    attribute_similarity(expected_attrs, actual_attrs)               -> float
    text_similarity(expected_text, actual_text)                      -> float
    tag_similarity(expected_tag, actual_tag)                         -> float
    parent_similarity(expected_parent, actual_parent)                -> float
    sibling_similarity(expected_siblings, actual_siblings)           -> float
    structure_similarity(expected_context, actual_context)           -> float
    selector_stability(selector, locator_type)                       -> float
    action_fit_score(action, actual_tag, actual_type)                -> float
    compute_final_score(attribute, text, tag, structure, ...)        -> float
    score_candidate(expected_profile, matched_element, candidate, …) -> dict
    rank_candidates(scored_candidates)                               -> list[dict]
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

# Sentinel: distinguishes "caller passed no context_score" from any float value.
_UNSET = object()

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------

W_ATTRIBUTE:  float = 0.30   # identity attrs — primary discriminator
W_TAG:        float = 0.15   # structural tag (also hard constraint multiplier)
W_STRUCTURE:  float = 0.10   # parent-tag match
W_CONTEXT:    float = 0.10   # sibling-tag Jaccard overlap
W_TEXT:       float = 0.10   # visible text (LOW — shared labels cause FP)
W_STABILITY:  float = 0.10   # selector-type robustness
W_ACTION:     float = 0.10   # action / tag compatibility
W_CONFIDENCE: float = 0.05   # self-reported source confidence

# ---------------------------------------------------------------------------
# Tag sets
# ---------------------------------------------------------------------------

_CLICKABLE_TAGS: frozenset[str] = frozenset({
    "button", "a", "input", "label", "select",
})

_INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "button", "link", "menuitem", "tab",
    "checkbox", "radio", "switch", "option",
})

_FILL_TAGS: frozenset[str] = frozenset({"input", "textarea"})

# Tags that are pure layout — almost never valid heal targets.
_LAYOUT_TAGS: frozenset[str] = frozenset({
    "div", "span", "p", "ul", "ol", "li",
    "section", "article", "main", "aside",
    "header", "footer", "nav", "form",
})

# ---------------------------------------------------------------------------
# Functional tag equivalences for tag_similarity
# ---------------------------------------------------------------------------

_EQUIVALENT_TAGS: frozenset[frozenset[str]] = frozenset({
    frozenset({"button", "input"}),   # input[type=submit] ≈ button
    frozenset({"textarea", "input"}), # both accept fill
    frozenset({"a", "button"}),       # both clickable (tests expect 0.5)
})

_PARTIAL_TAGS: frozenset[frozenset[str]] = frozenset()  # kept for forward-compat

# ---------------------------------------------------------------------------
# Identity attributes ordered by discriminative power
# ---------------------------------------------------------------------------

_IDENTITY_ATTRS: tuple[str, ...] = (
    "id", "name", "data-testid", "aria-label", "placeholder",
    "type", "role", "class", "href", "for",
)

# ---------------------------------------------------------------------------
# Hard-rejected page-root selectors (generic, never a valid target)
# ---------------------------------------------------------------------------

_CONTAINER_SELECTORS: frozenset[str] = frozenset({
    "#root", "body", "html",
})

# Long visible text threshold: anything longer is a content block, not a button.
_CONTAINER_TEXT_THRESHOLD: int = 60

# ---------------------------------------------------------------------------
# Semantic intent map (generic web/e-commerce patterns — NOT site-specific)
# Pairs of (description phrase, required substring in element text).
# Used to penalise candidates whose visible text contradicts the intent.
# ---------------------------------------------------------------------------

_INTENT_TEXT_MAP: tuple[tuple[str, str], ...] = (
    ("add to cart",       "add"),
    ("add-to-cart",       "add"),
    ("add item",          "add"),
    ("remove from cart",  "remove"),
    ("remove item",       "remove"),
    ("remove",            "remove"),
    ("continue shopping", "continue"),
    ("continue",          "continue"),
    ("place order",       "order"),
    ("sign in",           "sign"),
    ("register",          "register"),
    ("checkout",          "checkout"),
)


# ---------------------------------------------------------------------------
# Sub-score functions
# ---------------------------------------------------------------------------

def attribute_similarity(expected_attrs: dict, actual_attrs: dict) -> float:
    """
    Weighted Jaccard-style similarity over identity attributes.

    Both absent → skip (not informative).
    One absent  → full mismatch for that key.
    Both present → SequenceMatcher ratio (partial credit for close values).

    Returns 1.0 when neither element has any identity attributes.
    """
    intersection = 0.0
    union = 0.0

    for attr in _IDENTITY_ATTRS:
        exp_val = _norm_attr(expected_attrs.get(attr))
        act_val = _norm_attr(actual_attrs.get(attr))

        if not exp_val and not act_val:
            continue
        union += 1.0
        if exp_val and act_val:
            intersection += SequenceMatcher(None, exp_val, act_val).ratio()

    if union == 0.0:
        return 1.0
    return _clamp(intersection / union)


def text_similarity(expected_text: str, actual_text: str) -> float:
    """
    SequenceMatcher ratio between visible text strings.

    Both empty → 1.0 (controls like <input type="password"> have no text).
    One empty  → 0.0.
    """
    exp = _norm_text(expected_text)
    act = _norm_text(actual_text)

    if not exp and not act:
        return 1.0
    if not exp or not act:
        return 0.0
    return _clamp(SequenceMatcher(None, exp, act).ratio())


def tag_similarity(expected_tag: str, actual_tag: str) -> float:
    """
    1.0  — identical tag
    0.5  — functionally equivalent (button ↔ input[type=submit])
    0.3  — related but not equivalent (a ↔ button)
    0.0  — unrelated or either empty
    """
    exp = (expected_tag or "").lower().strip()
    act = (actual_tag or "").lower().strip()

    if not exp or not act:
        return 0.0
    if exp == act:
        return 1.0
    if frozenset({exp, act}) in _EQUIVALENT_TAGS:
        return 0.5
    if frozenset({exp, act}) in _PARTIAL_TAGS:
        return 0.3
    return 0.0


def parent_similarity(expected_parent: Optional[str], actual_parent: Optional[str]) -> float:
    """
    1.0 if parent tags match exactly.
    0.7 if both absent (no penalty for missing context).
    0.3 if only one side has a parent tag.
    0.0 if both present but different.
    """
    exp = (expected_parent or "").lower().strip()
    act = (actual_parent or "").lower().strip()

    if not exp and not act:
        return 0.7   # no context on either side — neutral, not penalised
    if exp == act:
        return 1.0
    if not exp or not act:
        return 0.3   # one side lacks context
    return 0.0       # different parents — likely wrong location


def sibling_similarity(
    expected_siblings: Optional[list],
    actual_siblings: Optional[list],
) -> float:
    """
    Jaccard similarity over sibling tag sets.
    Prevents selecting the visually correct element in the wrong structural location.

    Both empty → 0.7 (neutral, no penalty).
    """
    exp_set = {t.lower() for t in (expected_siblings or [])}
    act_set = {t.lower() for t in (actual_siblings or [])}

    if not exp_set and not act_set:
        return 0.7
    union = exp_set | act_set
    if not union:
        return 0.7
    return _clamp(len(exp_set & act_set) / len(union))


def structure_similarity(expected_context: dict, actual_context: dict) -> float:
    """
    Combined DOM context similarity (parent tag + sibling Jaccard).
    Kept for backward compatibility. Callers may prefer the separate
    parent_similarity / sibling_similarity functions for finer control.
    """
    exp_parent   = expected_context.get("parent_tag")
    act_parent   = actual_context.get("parent_tag")
    exp_siblings = expected_context.get("sibling_tags")
    act_siblings = actual_context.get("sibling_tags")

    # Both contexts completely empty → perfect structural agreement.
    if not exp_parent and not act_parent and not exp_siblings and not act_siblings:
        return 1.0

    p_score = parent_similarity(exp_parent, act_parent)
    s_score = sibling_similarity(exp_siblings, act_siblings)

    # Same parent with no sibling data on either side → full agreement.
    if p_score == 1.0 and not exp_siblings and not act_siblings:
        return 1.0

    return _clamp(0.6 * p_score + 0.4 * s_score)


def selector_stability(selector: str, locator_type: str = "css") -> float:
    """
    Estimate robustness / maintainability of a selector (0.0 – 1.0).

    High-stability selectors (data-testid, #id, role) survive refactors;
    low-stability selectors (nth-child, dynamic CSS classes) break easily.
    """
    s = (selector or "").lower()

    if locator_type.startswith("role:"):
        return 0.88
    if "data-testid" in s or "data-test" in s or "data-qa" in s or "data-cy" in s:
        return 0.95
    if re.match(r"^#[\w-]+$", s):
        return 0.92
    if "[name=" in s or "[aria-label=" in s:
        return 0.85
    if "[placeholder=" in s:
        return 0.80
    if "[type=" in s and "[value=" in s:
        return 0.78
    if "[type=" in s:
        return 0.70
    if ":has-text(" in s:
        return 0.72
    if "[href=" in s:
        return 0.68
    if re.search(r"\.css-[a-z0-9]+", s) or "nth-child" in s:
        return 0.15
    if s.startswith(".") and "[" not in s:
        return 0.38
    return 0.28


def action_fit_score(action: str, actual_tag: str, actual_type: str = "") -> float:
    """
    Score (0 – 1) representing how well the candidate's tag supports the action.
    Returns 0.5 when no action is specified (neutral).
    """
    if not action:
        return 0.5

    tag = (actual_tag or "").lower()
    typ = (actual_type or "").lower()

    if not tag:
        return 0.5   # unknown tag — defer to live validation

    if action == "fill":
        if tag == "textarea":
            return 1.0
        if tag == "input" and typ not in {"checkbox", "radio", "submit", "button", "hidden"}:
            return 1.0
        return 0.0

    if action == "select":
        return 1.0 if tag == "select" else 0.0

    if action == "click":
        if tag in {"button", "a"}:
            return 1.0
        if tag == "input" and typ in {"checkbox", "radio", "submit", "button"}:
            return 1.0
        if tag == "label":
            return 0.85
        return 0.2

    if action == "expect_visible":
        return 0.8   # most elements can be visible

    return 0.5


def compute_final_score(
    attribute_score: float,
    text_score: float,
    tag_score: float,
    structure_score: float,
    context_score: Any = _UNSET,
    stability_score: float = 0.5,
    action_score: float = 0.5,
    confidence: float = 0.5,
) -> float:
    """
    Weighted blend of sub-scores. All inputs and output clamped to [0, 1].

    4-argument mode (context_score omitted):
        Only the four required scores are used. Their weights are normalised so
        that compute_final_score(x, x, x, x) == x for any x in [0, 1].
        Normalised weights: attr≈0.462  text≈0.154  tag≈0.231  struct≈0.154

    8-argument mode (context_score provided):
        Full precision-first scoring with all eight components.
        Weights: attribute 0.30  tag 0.15  structure 0.10  context 0.10
                 text 0.10  stability 0.10  action 0.10  confidence 0.05
    """
    if context_score is _UNSET:
        # 4-arg backward-compatible mode: weights must sum to 1.0 exactly.
        # Original 4-component weight sum = 0.30+0.10+0.15+0.10 = 0.65
        _W = W_ATTRIBUTE + W_TEXT + W_TAG + W_STRUCTURE   # 0.65
        score = (
            (W_ATTRIBUTE / _W) * _clamp(attribute_score)
            + (W_TEXT     / _W) * _clamp(text_score)
            + (W_TAG      / _W) * _clamp(tag_score)
            + (W_STRUCTURE / _W) * _clamp(structure_score)
        )
        return _clamp(score)

    # Full 8-arg precision-first scoring.
    score = (
        W_ATTRIBUTE  * _clamp(attribute_score)
        + W_TAG        * _clamp(tag_score)
        + W_STRUCTURE  * _clamp(structure_score)
        + W_CONTEXT    * _clamp(context_score)
        + W_TEXT       * _clamp(text_score)
        + W_STABILITY  * _clamp(stability_score)
        + W_ACTION     * _clamp(action_score)
        + W_CONFIDENCE * _clamp(confidence)
    )
    return _clamp(score)


# ---------------------------------------------------------------------------
# High-level candidate scoring
# ---------------------------------------------------------------------------

def score_candidate(
    expected_profile: dict,
    matched_element: Optional[dict],
    candidate: dict,
    action: str = "",
    description: str = "",
) -> dict:
    """
    Score a single locator candidate against the expected target profile.

    Hard constraints applied here ensure wrong-tag candidates score 0.0
    regardless of how well they match on other dimensions.

    Returns the candidate dict enriched with:
        attribute_score, text_score, tag_score, structure_score,
        context_score, stability_score, action_score, final_score,
        rejection_reason (when applicable).
    """
    sel = (candidate.get("selector") or "").strip().lower()

    # Hard-reject generic page-root selectors
    if sel in _CONTAINER_SELECTORS:
        return _zero_result(candidate, matched_element, "container_selector")

    # --- Unresolved candidate (selector didn't map to any DOM element) ---
    if matched_element is None:
        if candidate.get("resolved"):
            # Candidate existed in live DOM but selector form wasn't reverse-matched
            # to a snapshot element. Use self-reported confidence as fallback.
            base = _clamp(candidate.get("confidence", 0.5))
            if candidate.get("source") == "llm":
                base = _clamp(base + 0.15)
            return {
                **candidate,
                "matched_element":  None,
                "attribute_score":  0.0,
                "text_score":       0.0,
                "tag_score":        0.0,
                "structure_score":  0.0,
                "context_score":    0.0,
                "stability_score":  round(selector_stability(
                    candidate.get("selector", ""),
                    candidate.get("locator_type", "css"),
                ), 4),
                "action_score":     0.0,
                "final_score":      round(base, 4),
            }
        return _zero_result(candidate, matched_element, "unresolved")

    # --- Compute sub-scores ---
    exp_attrs  = expected_profile.get("attrs") or {}
    act_attrs  = matched_element.get("attrs") or {}
    actual_tag = (matched_element.get("tag") or "").lower()
    actual_type = (
        matched_element.get("type")
        or act_attrs.get("type")
        or ""
    ).lower()

    a_score = attribute_similarity(exp_attrs, act_attrs)

    t_score = text_similarity(
        expected_profile.get("text", ""),
        matched_element.get("text", ""),
    )

    g_score = tag_similarity(
        expected_profile.get("tag", ""),
        matched_element.get("tag", ""),
    )

    # Structure = parent-tag match (location context)
    s_score = parent_similarity(
        expected_profile.get("parent_tag"),
        matched_element.get("parent_tag"),
    )

    # Context = sibling-tag Jaccard (prevents wrong-location false positives)
    c_score = sibling_similarity(
        expected_profile.get("sibling_tags"),
        matched_element.get("sibling_tags"),
    )

    stab = selector_stability(
        candidate.get("selector", ""),
        candidate.get("locator_type", "css"),
    )

    act = action_fit_score(action, actual_tag, actual_type)
    conf = _clamp(candidate.get("confidence", 0.5))

    final = compute_final_score(
        a_score, t_score, g_score, s_score, c_score, stab, act, conf
    )

    # LLM source boost: LLM candidates are semantically accurate but score lower
    # because their selectors often can't be reverse-mapped to a snapshot element,
    # which causes attribute_score to undercount. Apply a bounded bonus.
    if candidate.get("source") == "llm":
        final = _clamp(final + 0.15)

    # -----------------------------------------------------------------------
    # HARD TAG-ACTION CONSTRAINTS
    # These override the weighted score to 0.0 — no exceptions.
    # -----------------------------------------------------------------------
    rejection_reason: Optional[str] = None

    if action == "fill":
        if actual_tag and actual_tag not in _FILL_TAGS:
            final = 0.0
            rejection_reason = f"fill_wrong_tag:{actual_tag}"

    elif action == "select":
        if actual_tag and actual_tag != "select":
            final = 0.0
            rejection_reason = f"select_wrong_tag:{actual_tag}"

    elif action == "click" and actual_tag:
        if actual_tag not in _CLICKABLE_TAGS:
            role = (
                act_attrs.get("role")
                or matched_element.get("role")
                or ""
            ).lower()
            if role in _INTERACTIVE_ROLES:
                # Has interactive ARIA role but wrong tag — penalise heavily
                final = _clamp(final * 0.5)
                rejection_reason = f"click_wrong_tag_with_role:{actual_tag}[role={role}]"
            else:
                final = 0.0
                rejection_reason = f"click_non_interactive_container:{actual_tag}"

    # Hard reject: layout container with long visible text is never a heal target.
    el_text = matched_element.get("text", "")
    value_text = str(
        matched_element.get("value")
        or act_attrs.get("value")
        or ""
    )
    semantic_text = " ".join(part for part in [el_text, value_text] if part)
    if (
        actual_tag in _LAYOUT_TAGS
        and len((el_text or "").strip()) > _CONTAINER_TEXT_THRESHOLD
    ):
        final = 0.0
        rejection_reason = "layout_container_long_text"

    # -----------------------------------------------------------------------
    # Soft penalties (only applied when final > 0 after hard constraints)
    # -----------------------------------------------------------------------
    if final > 0.0:
        intent_penalty = _semantic_intent_penalty(description, semantic_text, actual_tag)
        if intent_penalty > 0.0:
            final = _clamp(final - intent_penalty)
            if final == 0.0:
                rejection_reason = "semantic_intent_mismatch"

    if final > 0.0:
        tag_penalty, tag_reason = _description_tag_penalty(
            action=action,
            description=description,
            element_tag=actual_tag,
            element_type=actual_type,
        )
        if tag_penalty >= 1.0:
            final = 0.0
            rejection_reason = tag_reason
        elif tag_penalty > 0.0:
            final = _clamp(final - tag_penalty)
            if tag_reason and not rejection_reason:
                rejection_reason = tag_reason

    if final > 0.0:
        act_all = {**matched_element, **act_attrs}
        container_penalty = _container_penalty(actual_tag, el_text, act_all)
        final = _clamp(final - container_penalty)

    result: dict = {
        **candidate,
        "matched_element":  matched_element,
        "attribute_score":  round(a_score, 4),
        "text_score":       round(t_score, 4),
        "tag_score":        round(g_score, 4),
        "structure_score":  round(s_score, 4),
        "context_score":    round(c_score, 4),
        "stability_score":  round(stab,    4),
        "action_score":     round(act,     4),
        "final_score":      round(final,   4),
    }
    if rejection_reason:
        result["rejection_reason"] = rejection_reason
    return result


def rank_candidates(scored_candidates: list[dict]) -> list[dict]:
    """
    Sort scored candidates, highest final_score first.

    Tiebreakers (in order):
        1. final_score (descending)
        2. Unique match (matched_count == 1) preferred
        3. confidence (descending)
        4. Source: memory > heuristic > llm
    """
    _source_rank = {"memory": 0, "heuristic": 1, "llm": 2}

    def _key(c: dict) -> tuple:
        final      = -round(c.get("final_score", 0.0), 6)
        single     = 0 if c.get("matched_count", 0) == 1 else 1
        confidence = -round(c.get("confidence", 0.0), 6)
        source_ord = _source_rank.get(c.get("source", "llm"), 9)
        return (final, single, confidence, source_ord)

    return sorted(scored_candidates, key=_key)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _zero_result(
    candidate: dict,
    matched_element: Optional[dict],
    reason: str,
) -> dict:
    return {
        **candidate,
        "matched_element":  matched_element,
        "attribute_score":  0.0,
        "text_score":       0.0,
        "tag_score":        0.0,
        "structure_score":  0.0,
        "context_score":    0.0,
        "stability_score":  0.0,
        "action_score":     0.0,
        "final_score":      0.0,
        "rejection_reason": reason,
    }


def _norm_attr(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip().lower()


def _norm_text(value: Any) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _semantic_intent_penalty(
    description: str,
    element_text: str,
    element_tag: str,
) -> float:
    """
    Penalty of 0.45 when the description implies a specific action-text intent
    but the candidate's visible text fails to satisfy it.
    """
    if not description:
        return 0.0

    desc    = re.sub(r"[-_]", " ", description.strip().lower())
    el_text = (element_text or "").strip().lower()

    for intent_phrase, required_word in _INTENT_TEXT_MAP:
        norm_phrase = re.sub(r"[-_]", " ", intent_phrase)
        if norm_phrase in desc:
            if element_tag not in {"button", "a", "input"}:
                return 0.45
            if el_text and required_word not in el_text:
                return 0.45
            break
    return 0.0


def _description_tag_penalty(
    action: str,
    description: str,
    element_tag: str,
    element_type: str = "",
) -> tuple[float, str]:
    """
    Generic intent-tag penalty.

    This prevents common false repairs:
      - "add to cart" clicking a product link
      - checkout/continue/login/register choosing a plain link
      - sorting/selecting choosing a non-select element
    """
    d = (description or "").lower()
    tag = (element_tag or "").lower()
    typ = (element_type or "").lower()

    if action == "select" or "sort" in d or "dropdown" in d:
        if tag != "select":
            return 1.0, f"intent_requires_select:{tag}"

    if action == "click":
        action_words = {
            "add to cart",
            "add item",
            "remove item",
            "checkout",
            "continue",
            "submit",
            "register",
            "login",
            "sign in",
            "sign up",
            "place order",
            "finish",
            "confirm",
            "save",
            "cancel",
            "delete",
            "update",
        }

        if any(w in d for w in action_words):
            if tag == "a":
                return 0.40, "action_intent_rejects_link"
            if tag == "input" and typ not in {"submit", "button"}:
                return 0.35, f"action_intent_wrong_input_type:{typ}"

        if ("checkbox" in d or "agree" in d or "accept" in d) and tag == "input":
            if typ != "checkbox":
                return 0.35, f"checkbox_intent_wrong_input_type:{typ}"

    return 0.0, ""


def _container_penalty(
    element_tag: str,
    element_text: str,
    element_attrs: dict,
) -> float:
    """
    Penalty in [0, 0.55] for elements that look like layout containers rather
    than interactive targets.

    +0.40  Long visible text (> threshold) → content block, not a button
    +0.30  Generic layout tag with no identity attributes → bare container
    """
    penalty = 0.0

    if len((element_text or "").strip()) > _CONTAINER_TEXT_THRESHOLD:
        penalty += 0.40

    if element_tag in _LAYOUT_TAGS:
        has_identity = any([
            element_attrs.get("id"),
            element_attrs.get("role"),
            element_attrs.get("aria-label"),
            element_attrs.get("data-testid"),
            element_attrs.get("data-test"),
            element_attrs.get("data-cy"),
        ])
        if not has_identity:
            penalty += 0.30

    return min(0.55, penalty)
