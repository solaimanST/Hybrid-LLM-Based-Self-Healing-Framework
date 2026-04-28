"""
tests/ecommerce_suite/test_continue_shopping.py

Continue Shopping button tests — return to inventory from cart.
Tests T_EC15–T_EC16 (2 normal / 2 broken pairs).

Covers: attribute_removed, nested_structure_changed.
Break targets: [data-test='continue-shopping'] in .cart_footer.

Target site: https://www.saucedemo.com (/cart.html)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"


# ---------------------------------------------------------------------------
# T_EC15 — Continue shopping button is visible: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC15_continue_shopping_visible_normal(page_at_cart: Page) -> None:
    """Normal: [data-test='continue-shopping'] is visible; text mentions 'Continue Shopping'."""
    btn = page_at_cart.locator("[data-test='continue-shopping']")
    await expect(btn).to_be_visible()
    text = await btn.inner_text()
    assert len(text.strip()) > 0
    assert "continue" in text.lower() or "shopping" in text.lower()


@pytest.mark.asyncio
async def test_T_EC15_continue_shopping_visible_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test stripped from continue button)
    Original      : [data-test='continue-shopping']
    Broken        : button[data-test='continue-shopping-REMOVED']
    Expected heal : [data-test='continue-shopping']  or  a[href='/inventory.html']
    Research note : data-test values are truncated when switching to a shorter
                    attribute naming convention in a new component library.
                    Tests href-anchor ('/inventory.html') and button-text
                    ('Continue Shopping') recovery for secondary nav buttons.
    """
    result = await healer_hybrid.expect_visible(
        "button[data-test='continue-shopping-REMOVED']",
        description="Continue Shopping button in cart page footer",
    )
    assert result.success, (
        f"Continue shopping attribute-removed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    btn = page_at_cart.locator(result.healed_selector).first
    text = await btn.inner_text()
    assert len(text.strip()) > 0, "Healed continue-shopping button has empty text"


# ---------------------------------------------------------------------------
# T_EC16 — Continue shopping navigates back to /inventory.html: nested_structure_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC16_continue_shopping_navigates_normal(page_at_cart: Page) -> None:
    """Normal: click [data-test='continue-shopping'] → /inventory.html with 6 items."""
    await page_at_cart.click("[data-test='continue-shopping']")
    await expect(page_at_cart).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_cart.locator(".inventory_item")).to_have_count(6)


@pytest.mark.asyncio
async def test_T_EC16_continue_shopping_navigates_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nested_structure_changed
    Original      : [data-test='continue-shopping']  (direct child of .cart_footer)
    Broken        : .cart-footer > .navigation-group > .continue-shopping-btn-NESTED
    Expected heal : [data-test='continue-shopping']  or  button[class*='back']
    Research note : Footer layout refactoring wraps navigation and action
                    buttons into separate .navigation-group and .action-group
                    containers. Direct-child selectors break when the new group
                    wrapper is inserted. Tests data-test and button-text
                    ('Continue Shopping') heuristics for recovery. Navigation
                    success verified by URL and inventory item count.
    """
    result = await healer_hybrid.click(
        ".cart-footer > .navigation-group > .continue-shopping-btn-NESTED",
        description="Continue Shopping button that returns user to the inventory page",
    )
    assert result.success, (
        f"Continue shopping nested-structure healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_cart).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_cart.locator(".inventory_item")).to_have_count(6)
