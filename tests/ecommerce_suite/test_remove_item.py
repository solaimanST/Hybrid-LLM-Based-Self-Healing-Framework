"""
tests/ecommerce_suite/test_remove_item.py

Remove-item flow tests — remove buttons on inventory and cart pages.
Tests T_EC04–T_EC06 (3 normal / 3 broken pairs).

Covers: class_changed, attribute_removed, nearby_sibling_added.
Break targets: .btn_secondary remove button on inventory page;
               [data-test='remove-*'] on inventory and cart pages.

Target site: https://www.saucedemo.com (inventory + cart pages)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"


# ---------------------------------------------------------------------------
# T_EC04 — Remove button on inventory page: class_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC04_remove_from_inventory_normal(page_at_inventory: Page) -> None:
    """Normal: add backpack → .btn_secondary Remove visible → click → badge gone."""
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")

    remove = page_at_inventory.locator(".btn_secondary.btn_inventory").first
    await expect(remove).to_be_visible()
    await remove.click()
    await expect(badge).to_have_count(0)
    add_btn = page_at_inventory.locator("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(add_btn).to_be_visible()


@pytest.mark.asyncio
async def test_T_EC04_remove_from_inventory_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (.btn_secondary → .btn-remove-RENAMED)
    Original      : .btn_secondary.btn_inventory
    Broken        : .btn-remove-RENAMED
    Expected heal : button[data-test='remove-sauce-labs-backpack'] or button.btn_secondary.btn_inventory
    Research note : Design system upgrades rename secondary button classes.
                    'btn_secondary' becoming 'btn-remove' is a BEM-to-utility
                    refactor. Tests data-test wildcard ('remove') and button
                    text ('Remove') heuristics as stable fallbacks when the
                    class name is the only anchor in the broken selector.
    """
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")

    result = await healer_hybrid.click(
        ".btn-remove-RENAMED",
        description="Remove button on inventory page after item was added to cart",
    )
    assert result.success, (
        f"Remove class-changed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(badge).to_have_count(0)


# ---------------------------------------------------------------------------
# T_EC05 — Remove specific product by data-test on inventory: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC05_remove_by_data_test_normal(page_at_inventory: Page) -> None:
    """Normal: add backpack, [data-test='remove-sauce-labs-backpack'] removes it, badge gone."""
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_text("1")

    await page_at_inventory.click("[data-test='remove-sauce-labs-backpack']")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_count(0)
    add_btn = page_at_inventory.locator("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(add_btn).to_be_visible()


@pytest.mark.asyncio
async def test_T_EC05_remove_by_data_test_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test stripped from remove button)
    Original      : [data-test='remove-sauce-labs-backpack']
    Broken        : button[data-test='remove-ATTR-REMOVED']
    Expected heal : button[data-test='remove-sauce-labs-backpack'] or button.btn_secondary.btn_inventory
    Research note : CI build tools can strip data-test attributes before
                    deployment, leaving only the class and text content as
                    anchors. Tests class-based and button-text ('Remove')
                    heuristics for identifying the correct remove button among
                    multiple add/remove buttons visible on the same page.
    """
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_text("1")

    result = await healer_hybrid.click(
        "button[data-test='remove-ATTR-REMOVED']",
        description="Remove Sauce Labs Backpack button on inventory page",
    )
    assert result.success, (
        f"Remove attribute-removed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_count(0)


# ---------------------------------------------------------------------------
# T_EC06 — Remove from cart page: nearby_sibling_added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC06_remove_from_cart_normal(page_at_cart: Page) -> None:
    """Normal: on cart page, [data-test='remove-sauce-labs-backpack'] removes the item."""
    items = page_at_cart.locator(".cart_item")
    await expect(items).to_have_count(1)

    await page_at_cart.click("[data-test='remove-sauce-labs-backpack']")
    await expect(items).to_have_count(0)
    await expect(page_at_cart.locator(".shopping_cart_badge")).to_have_count(0)


@pytest.mark.asyncio
async def test_T_EC06_remove_from_cart_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nearby_sibling_added
    Original      : [data-test='remove-sauce-labs-backpack']
    Broken        : .cart_item_label > .item-actions-SIBLING > .remove-btn-EXTRA
    Expected heal : [data-test='remove-sauce-labs-backpack'] or button.btn_secondary.cart_button
    Research note : A new .item-actions-SIBLING wrapper div inserted next to
                    .cart_item_label makes the compound selector point at a
                    non-existent intermediate node. Tests data-test wildcard
                    ('remove') and button text ('Remove') heuristics for
                    recovering the correct sibling button within the cart row.
    """
    items = page_at_cart.locator(".cart_item")
    await expect(items).to_have_count(1)

    result = await healer_hybrid.click(
        ".cart_item_label > .item-actions-SIBLING > .remove-btn-EXTRA",
        description="Remove button inside cart item row on the cart page",
    )
    assert result.success, (
        f"Cart remove nearby-sibling healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(items).to_have_count(0)
