"""
engine/heuristic_generator.py

DOM-aware heuristic locator candidate generation (Stage 1 of the healing pipeline).

Five complementary strategies:

  1. Suffix strip       — remove common test-mutation suffixes, probe attribute
                          forms (#id, [name=], [data-testid=], …)
  2. DOM probing        — extract identity tokens from the broken locator, scan
                          the live DOM snapshot for elements whose attributes match.
                          Elements incompatible with the requested action are skipped.
  3. Partial class      — extract sub-tokens from class selectors in the broken
                          locator and find DOM elements whose class list contains
                          those tokens as substrings.  Action-filtered for
                          fill/select actions.
  4. Text search        — extract keywords from the locator and description, find
                          elements whose innerText / aria-label / placeholder contains
                          them.  Restricted to interactive tags only — div/span/h*
                          are EXCLUDED to prevent layout-container false positives.
  5. Fuzzy token scan   — score every DOM element by multi-attribute token overlap;
                          skips elements whose tag is incompatible with the action.

Action-aware filtering
----------------------
When ``action`` is supplied each strategy restricts its output to tags that
can legally accept that action:

    fill   → only {input, textarea}
    select → only {select}
    click  → only {button, a, input, label, select}
             (elements with an explicit role= attribute are still allowed)
    other  → no restriction (let live validation decide)

Filtering happens at the GENERATOR level so the validation and scoring layers
see fewer, higher-quality candidates — reducing noise and inference cost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class HeuristicCandidate:
    """A single heuristic locator candidate with audit metadata."""

    locator: str
    locator_type: str   # e.g. "css", "role:button"
    confidence: float   # 0.0 – 1.0
    strategy: str       # which rule produced this candidate
    reasoning: str      # one-line human-readable explanation


# ---------------------------------------------------------------------------
# Action-to-tag maps
# ---------------------------------------------------------------------------

_FILL_TAGS:   frozenset[str] = frozenset({"input", "textarea"})
_SELECT_TAGS: frozenset[str] = frozenset({"select"})
_CLICK_TAGS:  frozenset[str] = frozenset({"button", "a", "input", "label", "select"})

# Tags allowed in text-search strategy (interactive only — NO div/span/h*)
_TEXT_SEARCH_TAGS: frozenset[str] = frozenset({"a", "button", "label", "input", "select"})


def _is_tag_compatible(tag: str, action: str) -> bool:
    """
    Return True when a DOM element's tag can legally receive ``action``.
    Unknown tag or unknown action → True (deferred to live validation).
    """
    if not tag or not action:
        return True
    if action == "fill":
        return tag in _FILL_TAGS
    if action == "select":
        return tag in _SELECT_TAGS
    if action == "click":
        return tag in _CLICK_TAGS
    return True


def _el_has_interactive_role(el: dict[str, Any]) -> bool:
    """Return True when the element declares an interactive ARIA role."""
    attrs = el.get("attrs") or {}
    role = (el.get("role") or attrs.get("role") or "").lower()
    return role in {
        "button", "link", "menuitem", "tab",
        "checkbox", "radio", "switch", "option",
    }


# ---------------------------------------------------------------------------
# Suffix patterns for deliberate test mutations
# ---------------------------------------------------------------------------

_SUFFIX_RE = re.compile(
    r"[-_](BROKEN|OLD|NEW|V\d+|BACKUP|TEST|COPY|TMP|TEMP|REMOVED|MOVED|EXTRA|SIBLING|NESTED)$",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _normalize_space(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _css_val_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _all_classes_from_el(el: dict[str, Any]) -> list[str]:
    raw = el.get("class") or (el.get("attrs") or {}).get("class") or ""
    if isinstance(raw, list):
        return [c for c in raw if c]
    return raw.split()


def _extract_class_tokens(selector: str) -> list[str]:
    """
    Extract meaningful sub-tokens from class-name parts of a CSS selector.

    Examples:
        '.product-card-BROKEN'   → ['product', 'card']
        '.btn_inventory_BROKEN'  → ['btn', 'inventory']
    """
    class_parts = re.findall(r"\.([a-zA-Z][a-zA-Z0-9_-]*)", selector)
    tokens: list[str] = []
    for part in class_parts:
        cleaned = _SUFFIX_RE.sub("", part).lower()
        sub = re.split(r"[-_]", cleaned)
        tokens.extend(t for t in sub if len(t) >= 3)
    return list(dict.fromkeys(tokens))


def _extract_keywords(text: str) -> set[str]:
    """
    Extract meaningful lowercase words from any text (selector string or
    natural-language description).  Short tokens and pure numbers are dropped.
    """
    if not text:
        return set()
    cleaned = re.sub(r'[#.\[\]=\'"()>~+,*|^$@!/\\]', " ", text)
    tokens = re.split(r"[-_\s]+", cleaned.lower())
    return {t for t in tokens if len(t) >= 4 and not t.isdigit()}


def _token_overlap_score(el: dict[str, Any], tokens: set[str]) -> float:
    """Fraction of tokens found in any identity attribute of the element."""
    if not tokens:
        return 0.0
    attrs = el.get("attrs") or {}
    parts = [
        el.get("id") or "",
        el.get("name") or attrs.get("name") or "",
        el.get("text") or "",
        el.get("placeholder") or attrs.get("placeholder") or "",
        el.get("aria-label") or attrs.get("aria-label") or "",
        el.get("data-testid") or attrs.get("data-testid") or "",
        el.get("data-cy") or "",
        el.get("data-test") or "",
        " ".join(_all_classes_from_el(el)),
    ]
    searchable = " ".join(filter(None, parts)).lower()
    if not searchable:
        return 0.0
    matched = sum(1 for t in tokens if t in searchable)
    return matched / len(tokens)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(
    broken_locator: str,
    dom_elements: list[dict[str, Any]],
    description: str = "",
    action: str = "",
) -> list[HeuristicCandidate]:
    """
    Generate heuristic repair candidates for *broken_locator*.

    Parameters
    ----------
    broken_locator
        The Playwright selector string that failed.
    dom_elements
        Live DOM snapshot from the DOMAnalyzer.
    description
        Natural-language description of the target element.
    action
        The healing action ('click', 'fill', 'select', …).
        When supplied, candidates incompatible with the action are excluded
        at generation time, reducing noise for the validation layer.

    Returns
    -------
    Deduplicated list of ``HeuristicCandidate`` objects sorted by decreasing
    confidence.
    """
    seen: set[str] = set()
    results: list[HeuristicCandidate] = []

    def add(c: HeuristicCandidate) -> None:
        if c.locator and c.locator not in seen:
            seen.add(c.locator)
            results.append(c)

    for c in _suffix_strip_candidates(broken_locator):
        add(c)

    for c in _dom_probing_candidates(broken_locator, dom_elements, action):
        add(c)

    for c in _partial_class_candidates(broken_locator, dom_elements, action):
        add(c)

    for c in _text_search_candidates(broken_locator, dom_elements, description, action):
        add(c)

    for c in _fuzzy_token_candidates(broken_locator, dom_elements, description, action):
        add(c)

    results.sort(key=lambda c: c.confidence, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Strategy 1: Suffix strip (string-based, no DOM required)
# ---------------------------------------------------------------------------

def _suffix_strip_candidates(broken: str) -> list[HeuristicCandidate]:
    """
    Remove known mutation suffixes and probe common attribute forms.
    String-only — works even when no DOM snapshot is available.
    """
    candidates: list[HeuristicCandidate] = []

    cleaned = _SUFFIX_RE.sub("", broken)
    if cleaned != broken:
        candidates.append(HeuristicCandidate(
            locator=cleaned,
            locator_type="css",
            confidence=0.85,
            strategy="suffix_strip",
            reasoning=f"Removed mutation suffix from {broken!r}.",
        ))

    bare = (
        broken
        .lstrip("#.[")
        .replace("]", "")
        .split("=")[-1]
        .strip("'\"")
        .strip()
    )
    bare = _SUFFIX_RE.sub("", bare)

    if bare and bare != broken and len(bare) >= 3:
        for locator, ltype, conf, strategy in [
            (f"#{bare}",                "css", 0.80, "bare_id"),
            (f"[name='{bare}']",        "css", 0.70, "bare_name"),
            (f"[data-testid='{bare}']", "css", 0.70, "bare_data_testid"),
            (f"[data-test='{bare}']",   "css", 0.70, "bare_data_test"),
            (f"[data-cy='{bare}']",     "css", 0.68, "bare_data_cy"),
            (f"[aria-label='{bare}']",  "css", 0.60, "bare_aria_label"),
            (f"[placeholder='{bare}']", "css", 0.60, "bare_placeholder"),
        ]:
            candidates.append(HeuristicCandidate(
                locator=locator,
                locator_type=ltype,
                confidence=conf,
                strategy=strategy,
                reasoning=f"Attribute probe with bare token {bare!r}.",
            ))

    return candidates


# ---------------------------------------------------------------------------
# Strategy 2: DOM probing — identity-token matching against live snapshot
# ---------------------------------------------------------------------------

def _dom_probing_candidates(
    broken: str,
    dom_elements: list[dict[str, Any]],
    action: str = "",
) -> list[HeuristicCandidate]:
    """
    Extract identity tokens from *broken*, scan the DOM for exact matches,
    and emit multiple CSS locator forms for each matched element.

    Elements whose tag is incompatible with *action* are skipped unless they
    carry an interactive ARIA role (which overrides the structural constraint
    for click).
    """
    if not dom_elements:
        return []

    candidates: list[HeuristicCandidate] = []

    probes: list[tuple[str, str, float]] = [
        (_extract_id_token(broken),                  "id",          0.90),
        (_extract_attr_token(broken, "name"),         "name",        0.85),
        (_extract_attr_token(broken, "data-testid"),  "data-testid", 0.85),
        (_extract_attr_token(broken, "data-test"),    "data-test",   0.85),
        (_extract_attr_token(broken, "data-cy"),      "data-cy",     0.84),
        (_extract_attr_token(broken, "placeholder"),  "placeholder", 0.80),
        (_extract_attr_token(broken, "role"),         "role",        0.76),
    ]

    for raw_token, attr_key, base_conf in probes:
        if not raw_token:
            continue
        clean_token = _SUFFIX_RE.sub("", raw_token)
        if not clean_token:
            continue

        el = _find_by_attr(dom_elements, attr_key, clean_token)
        if el is None:
            continue

        el_tag = (el.get("tag") or "").lower()
        # Skip elements incompatible with the action unless they have an
        # interactive role (e.g. div[role="button"] is valid for click).
        if action and not _is_tag_compatible(el_tag, action):
            if action == "click" and _el_has_interactive_role(el):
                pass  # allow — has interactive role
            else:
                continue

        for c in _locators_for_element(el, attr_key, clean_token, base_conf):
            candidates.append(c)

    return candidates


def _locators_for_element(
    el: dict[str, Any],
    matched_attr: str,
    matched_value: str,
    base_conf: float,
) -> list[HeuristicCandidate]:
    """
    Emit all useful CSS locator forms for a DOM element matched by
    ``matched_attr`` = ``matched_value``.
    """
    result: list[HeuristicCandidate] = []
    reason_prefix = f"DOM match by {matched_attr}={matched_value!r}"
    attrs = el.get("attrs") or {}

    el_id       = str(el.get("id")          or "").strip()
    el_name     = str(el.get("name")        or attrs.get("name") or "").strip()
    el_testid   = str(el.get("data-testid") or attrs.get("data-testid") or "").strip()
    el_datatest = str(el.get("data-test")   or "").strip()
    el_datacy   = str(el.get("data-cy")     or "").strip()
    el_ph       = str(el.get("placeholder") or attrs.get("placeholder") or "").strip()
    el_aria     = str(el.get("aria-label")  or attrs.get("aria-label") or "").strip()
    el_href     = str(el.get("href")        or attrs.get("href") or "").strip()
    el_role     = str(el.get("role")        or attrs.get("role") or "").strip()
    el_tag      = str(el.get("tag")         or "input").strip()

    specs: list[tuple[str, str, float, str]] = []

    if el_id:
        specs.append((
            f"#{_css_val_escape(el_id)}", "css", base_conf,
            f"{reason_prefix}; using #id.",
        ))
    if el_testid:
        specs.append((
            f'[data-testid="{el_testid}"]', "css", base_conf - 0.02,
            f"{reason_prefix}; using data-testid.",
        ))
    if el_datatest:
        specs.append((
            f'[data-test="{el_datatest}"]', "css", base_conf - 0.02,
            f"{reason_prefix}; using data-test.",
        ))
    if el_datacy:
        specs.append((
            f'[data-cy="{el_datacy}"]', "css", base_conf - 0.02,
            f"{reason_prefix}; using data-cy.",
        ))
    if el_name:
        specs.append((
            f'{el_tag}[name="{_css_val_escape(el_name)}"]', "css", base_conf - 0.05,
            f"{reason_prefix}; using [name].",
        ))
    if el_ph:
        specs.append((
            f'[placeholder="{_css_val_escape(el_ph)}"]', "css", base_conf - 0.05,
            f"{reason_prefix}; using [placeholder].",
        ))
    if el_aria:
        specs.append((
            f'[aria-label="{_css_val_escape(el_aria)}"]', "css", base_conf - 0.08,
            f"{reason_prefix}; using [aria-label].",
        ))
    if el_href and el_tag == "a":
        specs.append((
            f'a[href="{_css_val_escape(el_href)}"]', "css", base_conf - 0.04,
            f"{reason_prefix}; using href.",
        ))
    if el_role and el_tag:
        specs.append((
            f'{el_tag}[role="{_css_val_escape(el_role)}"]', "css", base_conf - 0.06,
            f"{reason_prefix}; using tag+role.",
        ))

    for locator, ltype, conf, reasoning in specs:
        result.append(HeuristicCandidate(
            locator=locator,
            locator_type=ltype,
            confidence=conf,
            strategy=f"dom_{matched_attr}",
            reasoning=reasoning,
        ))

    return result


# ---------------------------------------------------------------------------
# Strategy 3: Partial class matching
# ---------------------------------------------------------------------------

def _partial_class_candidates(
    broken: str,
    dom_elements: list[dict[str, Any]],
    action: str = "",
) -> list[HeuristicCandidate]:
    """
    Extract class-name sub-tokens from the broken selector, find DOM elements
    whose class list contains those tokens as substrings.

    For fill/select actions, elements whose tag cannot accept the action are
    skipped.  For click, all elements in _CLICK_TAGS are accepted.
    """
    tokens = _extract_class_tokens(broken)
    if not tokens:
        return []

    candidates: list[HeuristicCandidate] = []

    for el in dom_elements:
        el_tag = (el.get("tag") or "").strip().lower()

        # Strict tag filtering for fill and select
        if action in {"fill", "select"} and el_tag:
            if not _is_tag_compatible(el_tag, action):
                continue

        el_classes = _all_classes_from_el(el)
        if not el_classes:
            continue

        el_class_str = " ".join(el_classes).lower()
        matched_tokens = [t for t in tokens if t in el_class_str]
        if not matched_tokens:
            continue

        coverage  = len(set(matched_tokens)) / len(tokens)
        base_conf = 0.56 + 0.15 * coverage

        for token in dict.fromkeys(matched_tokens):
            esc = _css_val_escape(token)
            candidates.append(HeuristicCandidate(
                locator=f'[class*="{esc}"]',
                locator_type="css",
                confidence=base_conf - 0.08,
                strategy="partial_class_contain",
                reasoning=f"Class substring: token={token!r} found in element classes.",
            ))
            if el_tag:
                candidates.append(HeuristicCandidate(
                    locator=f'{el_tag}[class*="{esc}"]',
                    locator_type="css",
                    confidence=base_conf - 0.04,
                    strategy="partial_class_tag",
                    reasoning=f"{el_tag}[class*='{token}']: tag + class substring.",
                ))

        for cls in el_classes[:2]:
            if any(t in cls.lower() for t in matched_tokens):
                loc = f".{cls}" if not el_tag else f"{el_tag}.{cls}"
                candidates.append(HeuristicCandidate(
                    locator=loc,
                    locator_type="css",
                    confidence=base_conf + 0.02,
                    strategy="partial_class_stable",
                    reasoning=f"Stable class .{cls} matched tokens {matched_tokens!r}.",
                ))

    return candidates


# ---------------------------------------------------------------------------
# Strategy 4: Text-based element search (interactive tags ONLY)
# ---------------------------------------------------------------------------

def _text_search_candidates(
    broken: str,
    dom_elements: list[dict[str, Any]],
    description: str = "",
    action: str = "",
) -> list[HeuristicCandidate]:
    """
    Find DOM elements whose innerText, aria-label, or placeholder contains
    keywords extracted from the broken selector or description.

    IMPORTANT: tag-qualified :has-text() candidates are restricted to
    _TEXT_SEARCH_TAGS (interactive elements only).  div, span, h1-h3, and
    other layout tags are NEVER emitted to prevent layout-container false
    positives — these are the most common source of wrong-location healing.
    """
    keywords = _extract_keywords(broken) | _extract_keywords(description)
    if not keywords:
        return []

    candidates: list[HeuristicCandidate] = []

    for el in dom_elements:
        el_tag = (el.get("tag") or "").strip().lower()

        # Skip elements incompatible with the action (fill/select strict)
        if action in {"fill", "select"} and el_tag:
            if not _is_tag_compatible(el_tag, action):
                continue

        text = _normalize_space(el.get("text") or "")
        aria = el.get("aria-label") or (el.get("attrs") or {}).get("aria-label") or ""
        ph   = el.get("placeholder") or (el.get("attrs") or {}).get("placeholder") or ""

        searchable = f"{text} {aria} {ph}".strip().lower()
        if not searchable:
            continue

        hits = [kw for kw in keywords if kw in searchable]
        if not hits:
            continue

        coverage  = len(hits) / len(keywords)
        base_conf = 0.50 + 0.18 * coverage

        # Generic :has-text() (no tag prefix — broader match)
        if text and len(text) <= 80:
            candidates.append(HeuristicCandidate(
                locator=f':has-text("{_css_val_escape(text)}")',
                locator_type="css",
                confidence=base_conf,
                strategy="text_search",
                reasoning=f"innerText contains keyword(s) {hits!r}.",
            ))
            # Tag-qualified form: ONLY for interactive tags (no div/span/h*)
            if el_tag in _TEXT_SEARCH_TAGS:
                candidates.append(HeuristicCandidate(
                    locator=f'{el_tag}:has-text("{_css_val_escape(text)}")',
                    locator_type="css",
                    confidence=base_conf + 0.04,
                    strategy="text_search_tag",
                    reasoning=f"{el_tag}:has-text matched keyword(s) {hits!r}.",
                ))

        if aria:
            candidates.append(HeuristicCandidate(
                locator=f'[aria-label="{_css_val_escape(aria[:100])}"]',
                locator_type="css",
                confidence=base_conf + 0.06,
                strategy="aria_text_search",
                reasoning=f"aria-label contains keyword(s) {hits!r}.",
            ))

        if ph and el_tag in {"input", "textarea"}:
            candidates.append(HeuristicCandidate(
                locator=f'{el_tag}[placeholder="{_css_val_escape(ph[:100])}"]',
                locator_type="css",
                confidence=base_conf + 0.05,
                strategy="placeholder_text_search",
                reasoning=f"placeholder contains keyword(s) {hits!r}.",
            ))

    return candidates


# ---------------------------------------------------------------------------
# Strategy 5: Fuzzy DOM-wide token scan (last resort)
# ---------------------------------------------------------------------------

def _fuzzy_token_candidates(
    broken: str,
    dom_elements: list[dict[str, Any]],
    description: str = "",
    action: str = "",
) -> list[HeuristicCandidate]:
    """
    Tokenize the broken selector and description, score every DOM element by
    multi-attribute token overlap, emit the best locator for each top-scoring
    element.

    Elements whose tag is incompatible with the action are skipped.  For click,
    elements with an interactive role are still considered even if their tag is
    not in _CLICK_TAGS.
    """
    tokens = _extract_keywords(broken) | _extract_keywords(description)
    if not tokens:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for el in dom_elements:
        el_tag = (el.get("tag") or "").strip().lower()

        # Action-based tag filtering
        if action and el_tag:
            if not _is_tag_compatible(el_tag, action):
                if action == "click" and _el_has_interactive_role(el):
                    pass  # allow — has interactive role
                else:
                    continue

        s = _token_overlap_score(el, tokens)
        if s > 0.0:
            scored.append((s, el))

    scored.sort(key=lambda x: x[0], reverse=True)

    candidates: list[HeuristicCandidate] = []
    seen_ids: set[str] = set()

    for score, el in scored[:8]:
        conf  = min(0.80, 0.40 + score * 0.40)
        el_tag = (el.get("tag") or "").strip().lower()
        attrs = el.get("attrs") or {}

        el_id     = el.get("id") or ""
        el_testid = el.get("data-testid") or attrs.get("data-testid") or ""
        el_datacy = el.get("data-cy") or ""
        el_name   = el.get("name") or attrs.get("name") or ""
        el_ph     = el.get("placeholder") or attrs.get("placeholder") or ""
        el_aria   = el.get("aria-label") or attrs.get("aria-label") or ""
        el_href   = el.get("href") or attrs.get("href") or ""

        if el_id and el_id not in seen_ids:
            seen_ids.add(el_id)
            candidates.append(HeuristicCandidate(
                locator=f"#{_css_val_escape(el_id)}",
                locator_type="css",
                confidence=conf,
                strategy="fuzzy_id",
                reasoning=f"Fuzzy token match (score={score:.2f}): #{el_id}.",
            ))
        elif el_testid:
            candidates.append(HeuristicCandidate(
                locator=f'[data-testid="{el_testid}"]',
                locator_type="css",
                confidence=conf,
                strategy="fuzzy_testid",
                reasoning=f"Fuzzy token match (score={score:.2f}): data-testid.",
            ))
        elif el_datacy:
            candidates.append(HeuristicCandidate(
                locator=f'[data-cy="{el_datacy}"]',
                locator_type="css",
                confidence=conf,
                strategy="fuzzy_datacy",
                reasoning=f"Fuzzy token match (score={score:.2f}): data-cy.",
            ))
        elif el_name and el_tag:
            candidates.append(HeuristicCandidate(
                locator=f'{el_tag}[name="{_css_val_escape(el_name)}"]',
                locator_type="css",
                confidence=conf - 0.05,
                strategy="fuzzy_name",
                reasoning=f"Fuzzy token match (score={score:.2f}): [name].",
            ))
        elif el_ph and el_tag in {"input", "textarea"}:
            candidates.append(HeuristicCandidate(
                locator=f'{el_tag}[placeholder="{_css_val_escape(el_ph)}"]',
                locator_type="css",
                confidence=conf - 0.05,
                strategy="fuzzy_placeholder",
                reasoning=f"Fuzzy token match (score={score:.2f}): placeholder.",
            ))
        elif el_aria:
            candidates.append(HeuristicCandidate(
                locator=f'[aria-label="{_css_val_escape(el_aria)}"]',
                locator_type="css",
                confidence=conf - 0.05,
                strategy="fuzzy_aria",
                reasoning=f"Fuzzy token match (score={score:.2f}): aria-label.",
            ))
        elif el_href and el_tag == "a":
            candidates.append(HeuristicCandidate(
                locator=f'a[href="{_css_val_escape(el_href)}"]',
                locator_type="css",
                confidence=conf - 0.08,
                strategy="fuzzy_href",
                reasoning=f"Fuzzy token match (score={score:.2f}): href.",
            ))

    return candidates


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _extract_id_token(locator: str) -> str:
    m = re.search(r"#([\w-]+)", locator)
    return m.group(1) if m else ""


def _extract_attr_token(locator: str, attr: str) -> str:
    m = re.search(rf"{re.escape(attr)}=['\"]([^'\"]+)['\"]", locator)
    return m.group(1) if m else ""


def _find_by_attr(
    dom_elements: list[dict[str, Any]],
    attr_key: str,
    value: str,
) -> dict[str, Any] | None:
    target = value.lower()
    for el in dom_elements:
        raw = el.get(attr_key) or (el.get("attrs") or {}).get(attr_key) or ""
        if str(raw).strip().lower() == target:
            return el
    return None
