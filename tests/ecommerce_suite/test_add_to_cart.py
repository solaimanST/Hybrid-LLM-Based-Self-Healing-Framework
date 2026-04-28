"""
tests/ecommerce_suite/test_add_to_cart.py

Add-to-cart flow tests — button targeting and cart badge verification.
Tests T_EC01–T_EC03 (3 normal / 3 broken pairs).

Covers: nested_structure_changed, attribute_removed, dom_position_changed.
Break targets: .btn_inventory add-to-cart button, .shopping_cart_badge.

Target site: https://www.saucedemo.com (inventory page, requires login)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"


# ---------------------------------------------------------------------------
# T_EC01 — Add first item by .btn_inventory class: nested_structure_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC01_add_to_cart_by_class_normal(page_at_inventory: Page) -> None:
    """Normal: click first .btn_inventory, cart badge increments to 1."""
    btn = page_at_inventory.locator(".btn_inventory").first
    await expect(btn).to_be_visible()
    await btn.click()
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")


@pytest.mark.asyncio
async def test_T_EC01_add_to_cart_by_class_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nested_structure_changed
    Original      : .btn_inventory  (button inside .pricebar)
    Broken        : .inventory_item > .item-button-container > .add-to-cart-btn-NESTED
    Expected heal : button[data-test='add-to-cart-sauce-labs-backpack']
    Research note : A layout refactor wraps the add-to-cart button in a new
                    .item-button-container div, invalidating any path-dependent
                    selector. Tests text-content ('Add to cart') and tag/class
                    heuristics that are path-agnostic.
    """
    result = await healer_hybrid.click(
        ".inventory_item > .item-button-container > .add-to-cart-btn-NESTED",
        description="Add to cart button inside product inventory card",
    )
    assert result.success, (
        f"Add-to-cart nested-structure healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")
    await expect(
        page_at_inventory.locator("[data-test='remove-sauce-labs-backpack']")
    ).to_be_visible()


# ---------------------------------------------------------------------------
# T_EC02 — Add backpack by data-test attribute: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC02_add_to_cart_by_data_test_normal(page_at_inventory: Page) -> None:
    """Normal: add backpack via [data-test='add-to-cart-sauce-labs-backpack'], badge shows 1."""
    btn = page_at_inventory.locator("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(btn).to_be_visible()
    await btn.click()
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")
    remove_btn = page_at_inventory.locator("[data-test='remove-sauce-labs-backpack']")
    await expect(remove_btn).to_be_visible()


@pytest.mark.asyncio
async def test_T_EC02_add_to_cart_by_data_test_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test attr stripped from button)
    Original      : [data-test='add-to-cart-sauce-labs-backpack']
    Broken        : [data-test='add-to-cart-ATTRIBUTE-REMOVED']
    Expected heal : button[data-test='add-to-cart-sauce-labs-backpack'] or button.btn_primary.btn_inventory
    Research note : data-test attributes are stripped from production builds by
                    some CI pipelines that bundle separately from the test env.
                    Tests recovery via button text ('Add to cart'), class heuristics,
                    and tag-type fallbacks when data-test is the only identifier.
    """
    result = await healer_hybrid.click(
        "[data-test='add-to-cart-ATTRIBUTE-REMOVED']",
        description="Add to cart button for Sauce Labs Backpack on inventory page",
    )
    assert result.success, (
        f"Add-to-cart attribute-removed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")
    await expect(
        page_at_inventory.locator("[data-test='remove-sauce-labs-backpack']")
    ).to_be_visible()


# ---------------------------------------------------------------------------
# T_EC03 — Cart badge count after multiple adds: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC03_cart_badge_multi_add_normal(page_at_inventory: Page) -> None:
    """Normal: add 2 items, .shopping_cart_badge shows '2' with matching inner text."""
    btns = page_at_inventory.locator(".btn_inventory")
    await btns.nth(0).click()
    await btns.nth(1).click()
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("2")
    assert (await badge.inner_text()).strip() == "2"


@pytest.mark.asyncio
async def test_T_EC03_cart_badge_multi_add_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : .shopping_cart_badge  (span inside .shopping_cart_link)
    Broken        : .top-bar > .cart-container > .badge-MOVED
    Expected heal : .shopping_cart_badge  or  a[href='/cart.html'] span
    Research note : Header restructuring places the badge span inside a new
                    .cart-container wrapper, breaking direct-child path selectors.
                    Tests href-based ancestor recovery and class-name heuristics
                    for a count-bearing inline element inside the cart link.
    """
    await page_at_inventory.locator(".btn_inventory").nth(0).click()
    await page_at_inventory.locator(".btn_inventory").nth(1).click()

    result = await healer_hybrid.expect_visible(
        ".top-bar > .cart-container > .badge-MOVED",
        description="Cart badge showing item count in the page header",
    )
    assert result.success, (
        f"Cart badge dom-position healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    badge = page_at_inventory.locator(result.healed_selector).first
    assert (await badge.inner_text()).strip() == "2", (
        f"Expected badge count '2' after healing, got {await badge.inner_text()!r}"
    )
