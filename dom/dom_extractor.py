"""
dom/dom_extractor.py

Extracts a structured, JSON-serialisable list of interactive DOM elements
from raw HTML using BeautifulSoup.

Public API
----------
    extract_dom(html, max_elements=200, include_tags=None, extra_attrs=None) -> list[dict]
    extract_dom_from_page(page, ...)                                           -> list[dict]   (async)
    build_dom_prompt_context(elements)                                         -> str
    filter_candidate_elements(elements, action=None)                           -> list[dict]
"""

from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Tags considered interactive / meaningful for UI testing (backward-compat)
INTERACTIVE_TAGS: frozenset[str] = frozenset(
    {"button", "input", "a", "select", "textarea"}
)

#: Extended tag set used as the default extraction target.
#: INTERACTIVE_TAGS is preserved unchanged for backward-compat; callers that
#: relied on include_tags=None now get richer coverage via EXTRACTED_TAGS.
EXTRACTED_TAGS: frozenset[str] = INTERACTIVE_TAGS | frozenset(
    {"div", "span", "p", "h1", "h2", "h3", "h4", "label", "li"}
)

#: Flat attributes extracted from every element as top-level keys
EXTRACTED_ATTRS: tuple[str, ...] = (
    "id",
    "class",
    "name",
    "type",
    "role",
    "aria-label",
    "aria-describedby",
    "aria-expanded",
    "aria-hidden",
    "placeholder",
    "value",
    "href",
    "for",
    "data-testid",
    "data-test",
    "data-cy",
    "disabled",
    "required",
    "checked",
    "readonly",
    "tabindex",
)

#: Attribute keys surfaced in the nested ``attrs`` dict (for new-style callers)
_ATTRS_KEYS: tuple[str, ...] = (
    "id", "class", "name", "type", "role",
    "aria-label", "placeholder", "href", "for",
    "data-testid", "data-test", "value",
)

MAX_ELEMENTS: int   = 500
MAX_TEXT_LEN: int   = 200   # chars of visible inner text
MAX_ATTR_LEN: int   = 300   # chars per attribute value

#: action → tags most likely to host it
_ACTION_TAG_MAP: dict[str, frozenset[str]] = {
    "click":          frozenset({"button", "a", "input", "select"}),
    "fill":           frozenset({"input", "textarea"}),
    "select_option":  frozenset({"select"}),
    "check":          frozenset({"input"}),
    "expect_visible": INTERACTIVE_TAGS,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_dom(
    html: str,
    *,
    max_elements: int = MAX_ELEMENTS,
    include_tags: Optional[frozenset[str]] = None,
    extra_attrs: Optional[list[str]] = None,
) -> list[dict]:
    """
    Parse *html* and return a list of element dicts.

    Each dict exposes:
      - Flat top-level keys for every attribute in EXTRACTED_ATTRS
        (plus any *extra_attrs*), boolean attrs, ``text``, ``css_selector``
      - ``attrs``      : nested dict of the 10 most useful identity attributes
      - ``parent_tag`` : immediate parent tag name (or None)
      - ``sibling_tags``: adjacent sibling tag names
      - ``is_interactive``: True for button/input/a/select/textarea

    Parameters
    ----------
    html
        Raw HTML string (e.g. from ``await page.content()``).
    max_elements
        Hard cap on returned elements.  Default 200.
    include_tags
        Override the set of tags to extract.
    extra_attrs
        Additional attribute names to capture as flat top-level keys.
    """
    tags_to_find = include_tags or EXTRACTED_TAGS
    attrs_to_extract = list(EXTRACTED_ATTRS) + (extra_attrs or [])

    soup = BeautifulSoup(html, "lxml")
    _strip_non_content(soup)

    results: list[dict] = []
    index = 0

    for tag in soup.find_all(list(tags_to_find)):
        if index >= max_elements:
            break
        if not isinstance(tag, Tag):
            continue
        if _is_hidden(tag):
            continue

        results.append(_build_element(tag, index, attrs_to_extract))
        index += 1

    return results


async def extract_dom_from_page(
    page,
    *,
    max_elements: int = MAX_ELEMENTS,
    include_tags: Optional[frozenset[str]] = None,
    extra_attrs: Optional[list[str]] = None,
) -> list[dict]:
    """
    Async convenience wrapper — fetches HTML from a live Playwright page
    and returns the same structured list as ``extract_dom()``.
    """
    html: str = await page.content()
    return extract_dom(
        html,
        max_elements=max_elements,
        include_tags=include_tags,
        extra_attrs=extra_attrs,
    )


def build_dom_prompt_context(elements: list[dict]) -> str:
    """
    Render *elements* as a compact, line-per-element string for LLM prompts.

    Format per line:
        [i] <tag> attrs: key="val" ... | text: "..."
    """
    lines: list[str] = []
    for el in elements:
        attrs = el.get("attrs") or {}
        attr_parts = [f'{k}="{v}"' for k, v in attrs.items() if v is not None]
        attr_str = " ".join(attr_parts) or "-"
        text = str(el.get("text") or "").strip()
        text_display = f'"{text[:80]}"' if text else '""'
        lines.append(
            f"[{el['index']}] <{el['tag']}> attrs: {attr_str} | text: {text_display}"
        )
    return "\n".join(lines)


def filter_candidate_elements(
    elements: list[dict],
    action: Optional[str] = None,
) -> list[dict]:
    """
    Return the subset of *elements* most likely to be the target of *action*.

    When *action* is None or unknown, all ``is_interactive`` elements are returned.
    """
    if not action:
        return [el for el in elements if el.get("is_interactive")]

    allowed = _ACTION_TAG_MAP.get(action.lower())
    if allowed is None:
        return [el for el in elements if el.get("is_interactive")]

    return [el for el in elements if el.get("tag") in allowed]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_non_content(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["script", "style", "noscript", "head"]):
        tag.decompose()


def _is_hidden(tag: Tag) -> bool:
    # HTML boolean `hidden` attribute
    if tag.get("hidden") is not None:
        return True
    # aria-hidden="true" — screen-reader and test-runner hidden
    if str(tag.get("aria-hidden", "")).strip().lower() == "true":
        return True
    style = tag.get("style", "")
    if isinstance(style, list):
        style = " ".join(style)
    return bool(
        re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", style, re.I)
    )


def _build_element(tag: Tag, index: int, attrs_to_extract: list[str]) -> dict:
    element: dict[str, Any] = {"index": index, "tag": tag.name}

    # Flat top-level attributes (backward-compatible schema)
    for attr in attrs_to_extract:
        raw = tag.get(attr)
        if raw is None:
            element[attr] = False if attr in ("disabled", "required", "checked", "readonly") else None
        elif attr in ("disabled", "required", "checked", "readonly"):
            element[attr] = True
        elif isinstance(raw, list):
            element[attr] = _truncate(" ".join(str(v) for v in raw), MAX_ATTR_LEN)
        else:
            element[attr] = _truncate(str(raw), MAX_ATTR_LEN)

    # Visible text
    element["text"] = _clean_text(tag.get_text(separator=" "))

    # Best-effort CSS selector
    element["css_selector"] = _build_selector(tag)

    # Nested attrs dict for new-style callers (e.g. heuristic_repair, dom_analyzer)
    element["attrs"] = {
        k: element.get(k) for k in _ATTRS_KEYS
    }

    # Structural context
    element["parent_tag"]   = _parent_tag(tag)
    element["sibling_tags"] = _sibling_tags(tag)
    element["is_interactive"] = tag.name in INTERACTIVE_TAGS

    return element


def _build_selector(tag: Tag) -> str:
    """Build the most specific unique CSS selector, in priority order."""
    el_id = tag.get("id")
    if el_id and isinstance(el_id, str) and el_id.strip():
        return f"#{_css_escape(el_id.strip())}"

    testid = tag.get("data-testid")
    if testid and isinstance(testid, str) and testid.strip():
        return f'[data-testid="{testid.strip()}"]'

    cy = tag.get("data-cy")
    if cy and isinstance(cy, str) and cy.strip():
        return f'[data-cy="{cy.strip()}"]'

    name = tag.get("name")
    if name and isinstance(name, str) and name.strip():
        return f'{tag.name}[name="{name.strip()}"]'

    parts = [tag.name]
    el_type = tag.get("type")
    if el_type:
        parts.append(f'[type="{el_type}"]')
    classes = tag.get("class")
    if classes:
        first_cls = classes[0] if isinstance(classes, list) else classes.split()[0]
        parts.append(f".{_css_escape(first_cls)}")
    return "".join(parts)


def _parent_tag(tag: Tag) -> Optional[str]:
    parent = tag.parent
    if parent and isinstance(parent, Tag) and parent.name not in ("html", "[document]"):
        return parent.name
    return None


def _sibling_tags(tag: Tag, window: int = 3) -> list[str]:
    siblings: list[str] = []
    prev = tag
    for _ in range(window):
        prev = prev.find_previous_sibling()
        if prev is None or not isinstance(prev, Tag):
            break
        siblings.insert(0, prev.name)
    nxt = tag
    for _ in range(window):
        nxt = nxt.find_next_sibling()
        if nxt is None or not isinstance(nxt, Tag):
            break
        siblings.append(nxt.name)
    return siblings


def _clean_text(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip()
    return _truncate(cleaned, MAX_TEXT_LEN)


def _truncate(value: str, limit: int) -> str:
    if len(value) > limit:
        return value[:limit].rstrip() + "…"
    return value


_CSS_ESCAPE_RE = re.compile(r"([^\w-])", re.ASCII)


def _css_escape(value: str) -> str:
    return _CSS_ESCAPE_RE.sub(r"\\\1", value)
