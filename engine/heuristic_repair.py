"""
engine/heuristic_repair.py

Stage 1 of the healing pipeline: DOM-aware heuristic locator candidate
generation.  No LLM is involved — all candidates are derived from the
live DOM snapshot and the broken locator string alone.

Public API
----------
    generate_heuristic_candidates(
        failed_selector, dom_elements, action="", max_candidates=5
    ) -> list[dict]

Candidate format
----------------
    {
        "selector":     str,            # CSS selector to try
        "locator_type": str,            # css | text | role | placeholder | label
        "source":       "heuristic",
        "confidence":   float,          # 0.0 – 1.0
        "reason":       str,            # one-line explanation
    }
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Suffixes that indicate a deliberately mutated/broken locator
_SUFFIX_RE = re.compile(
    r"[-_](BROKEN|OLD|NEW|V\d+|BACKUP|TEST|COPY|TMP|TEMP)$",
    flags=re.IGNORECASE,
)

#: Attributes to probe in priority order (attr_key, locator_type, base_confidence)
_ATTR_PRIORITY: tuple[tuple[str, str, float], ...] = (
    ("data-testid", "css",         0.92),
    ("id",          "css",         0.88),
    ("name",        "css",         0.80),
    ("aria-label",  "css",         0.75),
    ("placeholder", "placeholder", 0.72),
)

#: action → tag types that are likely targets (None means any interactive element)
_ACTION_TAGS: dict[str, frozenset[str]] = {
    "fill":          frozenset({"input", "textarea"}),
    "click":         frozenset({"button", "a", "input", "select"}),
    "select_option": frozenset({"select"}),
    "check":         frozenset({"input"}),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_heuristic_candidates(
    failed_selector: str,
    dom_elements: list[dict],
    action: str = "",
    max_candidates: int = 5,
) -> list[dict]:
    """
    Generate heuristic repair candidates for *failed_selector*.

    All candidates are produced from the supplied *dom_elements* snapshot
    (or, when the snapshot is empty, from the selector string alone).
    Results are deduplicated and ranked by confidence descending.

    Parameters
    ----------
    failed_selector
        The Playwright selector / locator string that failed.
    dom_elements
        Live DOM snapshot from ``dom_extractor.extract_dom()``.
    action
        The Playwright action that failed (e.g. ``"click"``, ``"fill"``).
        Used to filter candidates to the most relevant element types.
    max_candidates
        Maximum number of candidates to return.

    Returns
    -------
    List of candidate dicts, sorted by ``confidence`` descending.
    """
    seen: set[str] = set()
    candidates: list[dict] = []

    def add(c: dict) -> None:
        sel = c["selector"].strip()
        if sel and sel not in seen:
            seen.add(sel)
            candidates.append({**c, "selector": sel})

    # Filter DOM to elements relevant to the action
    relevant = _filter_by_action(dom_elements, action)

    # Strategy 1: match DOM elements by identity attributes
    for el in relevant:
        for c in _candidates_from_element(el, failed_selector):
            add(c)

    # Strategy 2: derive candidates from the broken selector string alone
    for c in _candidates_from_selector_string(failed_selector):
        add(c)

    # Strategy 3: visible text match from DOM
    for el in relevant:
        c = _candidate_from_text(el, failed_selector)
        if c:
            add(c)

    # Sort by confidence descending, cap
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[:max_candidates]


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _candidates_from_element(el: dict, failed_selector: str) -> list[dict]:
    """
    Emit CSS candidates for a DOM element, ranked by attribute quality.

    Confidence is boosted slightly when the attribute value overlaps with
    tokens in the broken selector.
    """
    result: list[dict] = []
    attrs: dict = el.get("attrs", {})
    overlap_tokens = _selector_tokens(failed_selector)

    for attr_key, locator_type, base_conf in _ATTR_PRIORITY:
        value = attrs.get(attr_key)
        if not value:
            continue

        selector = _css_for_attr(attr_key, value, el.get("tag", ""))
        if not selector:
            continue

        # Boost confidence when the value overlaps with the broken selector
        boost = 0.05 if any(t in value.lower() for t in overlap_tokens) else 0.0
        confidence = min(1.0, base_conf + boost)

        result.append({
            "selector":     selector,
            "locator_type": locator_type,
            "source":       "heuristic",
            "confidence":   round(confidence, 4),
            "reason":       f"DOM element matched by {attr_key}={value!r}.",
        })

    return result


def _candidates_from_selector_string(broken: str) -> list[dict]:
    """
    Derive candidates by mutating the broken selector string.

    Works even when no DOM snapshot is available.
    """
    result: list[dict] = []

    # Strip mutation suffix (e.g. -BROKEN, -OLD)
    cleaned = _SUFFIX_RE.sub("", broken)
    if cleaned and cleaned != broken:
        result.append({
            "selector":     cleaned,
            "locator_type": "css",
            "source":       "heuristic",
            "confidence":   0.75,
            "reason":       f"Removed mutation suffix from {broken!r}.",
        })

    # Extract bare id/name token and probe common attribute forms
    bare = _extract_bare_token(broken)
    if bare and len(bare) >= 2:
        probes: list[tuple[str, str, float, str]] = [
            (f"#{bare}",                    "css",         0.70, f"#id probe for token {bare!r}."),
            (f"[name='{bare}']",            "css",         0.65, f"[name] probe for token {bare!r}."),
            (f"[data-testid='{bare}']",     "css",         0.65, f"[data-testid] probe for {bare!r}."),
            (f"[aria-label='{bare}']",      "css",         0.60, f"[aria-label] probe for {bare!r}."),
            (f"[placeholder='{bare}']",     "placeholder", 0.60, f"[placeholder] probe for {bare!r}."),
        ]
        for sel, ltype, conf, reason in probes:
            result.append({
                "selector":     sel,
                "locator_type": ltype,
                "source":       "heuristic",
                "confidence":   conf,
                "reason":       reason,
            })

    return result


def _candidate_from_text(el: dict, failed_selector: str) -> Optional[dict]:
    """
    Emit a ``text=`` candidate when the element's visible text overlaps
    with tokens in the broken selector.
    """
    text = (el.get("text") or "").strip()
    if not text or len(text) > 60:   # skip long/empty text
        return None

    overlap_tokens = _selector_tokens(failed_selector)
    text_lower = text.lower()
    if not any(t in text_lower for t in overlap_tokens):
        return None

    return {
        "selector":     f"text={text}",
        "locator_type": "text",
        "source":       "heuristic",
        "confidence":   0.55,
        "reason":       f"Element visible text {text!r} overlaps with broken selector tokens.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _css_for_attr(attr_key: str, value: str, tag: str) -> str:
    """Build a CSS selector string for a given attribute key and value."""
    if attr_key == "id":
        return f"#{_css_escape(value)}"
    if attr_key == "data-testid":
        return f'[data-testid="{value}"]'
    if attr_key == "name":
        tag_prefix = tag if tag else "input"
        return f'{tag_prefix}[name="{value}"]'
    if attr_key == "aria-label":
        return f'[aria-label="{value}"]'
    if attr_key == "placeholder":
        return f'[placeholder="{value}"]'
    return ""


def _filter_by_action(elements: list[dict], action: str) -> list[dict]:
    """Return elements whose tag is relevant to the given action."""
    allowed = _ACTION_TAGS.get(action.lower()) if action else None
    if allowed is None:
        return [el for el in elements if el.get("is_interactive")]
    return [el for el in elements if el.get("tag") in allowed]


def _selector_tokens(selector: str) -> set[str]:
    """Extract meaningful lowercase tokens from a selector string."""
    return {t for t in re.split(r"[-_\s#.\[\]='\"/]", selector.lower()) if len(t) >= 2}


def _extract_bare_token(selector: str) -> str:
    """
    Extract the core identity token from a selector string.
    E.g. '#user-name-BROKEN' → 'user-name'.
    """
    bare = (
        selector
        .lstrip("#.[")
        .replace("]", "")
        .split("=")[-1]
        .strip("'\"")
        .strip()
    )
    return _SUFFIX_RE.sub("", bare)


_CSS_ESCAPE_RE = re.compile(r"([^\w-])", re.ASCII)


def _css_escape(value: str) -> str:
    """Escape non-word characters for use in a CSS id selector."""
    return _CSS_ESCAPE_RE.sub(r"\\\1", value)
