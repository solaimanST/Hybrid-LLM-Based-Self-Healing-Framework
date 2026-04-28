"""
dom/dom_analyzer.py

Async wrapper around dom_extractor that operates on a live Playwright Page.

Provides a clean interface for the healing pipeline to fetch HTML, extract
structured elements, and build LLM prompt context — all from a live page —
without exposing the details of BeautifulSoup or HTML parsing to callers.
"""

from __future__ import annotations

from playwright.async_api import Page

from dom.dom_extractor import (
    build_dom_prompt_context,
    extract_dom,
)


class DOMAnalyzer:
    """
    Captures and analyses the live DOM from a Playwright page.

    Parameters
    ----------
    page
        A live ``playwright.async_api.Page`` instance.
    """

    def __init__(self, page: Page) -> None:
        self.page = page

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_html(self) -> str:
        """Return the full outer HTML of the current page."""
        return await self.page.content()

    async def get_title(self) -> str:
        """Return the current page title (empty string if unavailable)."""
        try:
            return await self.page.title()
        except Exception:
            return ""

    async def extract_elements(self, max_elements: int = 200) -> list[dict]:
        """
        Fetch the page HTML and return normalized structured DOM elements.

        Returns the original element dict plus flattened top-level keys used by
        the healing engine, such as:
            - id
            - name
            - href
            - type
            - placeholder
            - role
            - aria_label
            - data_testid
            - classes

        Parameters
        ----------
        max_elements
            Hard cap on the number of elements returned.
        """
        html = await self.get_html()
        raw_elements = extract_dom(html, max_elements=max_elements)

        normalized: list[dict] = []
        for el in raw_elements:
            attrs = el.get("attrs") or {}

            normalized.append({
                **el,
                # Flatten key identity attributes to top-level for uniform access.
                # Always use the hyphenated form ("aria-label", "data-testid") so
                # consumers can use a single key without snake/hyphen dual lookup.
                "id":          attrs.get("id"),
                "name":        attrs.get("name"),
                "href":        attrs.get("href"),
                "type":        attrs.get("type"),
                "placeholder": attrs.get("placeholder"),
                "role":        attrs.get("role"),
                "aria-label":  attrs.get("aria-label"),
                "data-testid": attrs.get("data-testid"),
                "data-test":   attrs.get("data-test"),
                "data-cy":     attrs.get("data-cy"),
                "classes":     _normalize_classes(attrs.get("class")),
            })

        return normalized

    async def build_prompt_context(self, max_elements: int = 200) -> str:
        """
        Return a compact, line-per-element string suitable for an LLM prompt.

        Fetches and parses the live page if called standalone.
        """
        elements = await self.extract_elements(max_elements=max_elements)
        return build_dom_prompt_context(elements)

    @staticmethod
    def elements_to_prompt_context(elements: list[dict]) -> str:
        """
        Build the LLM prompt string from an already-fetched elements list.

        Use this when the DOM has already been extracted to avoid a second
        round-trip to the page.
        """
        return build_dom_prompt_context(elements)


def _normalize_classes(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split() if part.strip()]
    return []