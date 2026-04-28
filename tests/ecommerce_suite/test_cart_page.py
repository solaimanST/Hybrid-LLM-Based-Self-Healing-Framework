"""
tests/ecommerce_suite/test_cart_page.py

Cart page navigation and content verification tests.
Tests T_EC07–T_EC10 (4 normal / 4 broken pairs).

Covers: nearby_sibling_added, class_changed, nested_structure_changed, dom_position_changed.
Break targets: .shopping_cart_link, .inventory_item_name in cart, .cart_quantity,
               [data-test='checkout'] button.

Target site: https://www.saucedemo.com (inventory + cart pages)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"


# ---------------------------------------------------------------------------
# T_EC07 — Cart link navigates to /cart.html: nearby_sibling_added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC07_cart_link_navigates_normal(page_at_inventory: Page) -> None:
    """Normal: add item, .shopping_cart_link click → URL becomes /cart.html."""
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    cart = page_at_inventory.locator(".shopping_cart_link")
    await expect(cart).to_be_visible()
    await cart.click()
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/cart.html")
    await expect(page_at_inventory.locator(".cart_item")).to_have_count(1)


@pytest.mark.asyncio
async def test_T_EC07_cart_link_navigates_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nearby_sibling_added
    Original      : .shopping_cart_link  (in .shopping_cart_container)
    Broken        : .shopping_cart_container-SIBLING .shopping_cart_link_NEW
    Expected heal : .shopping_cart_link  or  a[href='/cart.html']
    Research note : A new sibling div inserted adjacent to the cart container
                    in the header makes the compound selector resolve to a
                    non-existent element. Tests href-attribute ('/cart.html')
                    and class-name fragment heuristics as stable fallbacks.
    """
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")

    result = await healer_hybrid.click(
        ".shopping_cart_container-SIBLING .shopping_cart_link_NEW",
        description="Shopping cart icon link in the page header",
    )
    assert result.success, (
        f"Cart link nearby-sibling healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/cart.html")


# ---------------------------------------------------------------------------
# T_EC08 — Cart item name visible and non-empty: class_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC08_cart_item_name_normal(page_at_cart: Page) -> None:
    """Normal: .inventory_item_name in cart is visible; text contains backpack name."""
    name = page_at_cart.locator(".inventory_item_name").first
    await expect(name).to_be_visible()
    text = await name.inner_text()
    assert len(text.strip()) > 0
    assert "Sauce Labs Backpack" in text


@pytest.mark.asyncio
async def test_T_EC08_cart_item_name_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (.inventory_item_name → .cart-item-title-RENAMED)
    Original      : .inventory_item_name
    Broken        : .cart-item-title-RENAMED
    Expected heal : .inventory_item_name  or  .cart_item a[data-test*='item-name']
    Research note : A design-system migration renames shared inventory classes
                    to cart-specific names. The item name link still lives inside
                    .cart_item but its class changed. Tests parent-container
                    context and anchor-element heuristics for text-bearing nodes.
    """
    result = await healer_hybrid.expect_visible(
        ".cart-item-title-RENAMED",
        description="Product name label inside cart item row",
    )
    assert result.success, (
        f"Cart item name class-changed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    name_el = page_at_cart.locator(result.healed_selector).first
    text = await name_el.inner_text()
    assert len(text.strip()) > 0, "Healed cart item name element returned empty text"


# ---------------------------------------------------------------------------
# T_EC09 — Cart quantity shows correct count: nested_structure_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC09_cart_quantity_normal(page_at_cart: Page) -> None:
    """Normal: .cart_quantity text is '1' for a single item in cart."""
    qty = page_at_cart.locator(".cart_quantity").first
    await expect(qty).to_be_visible()
    assert (await qty.inner_text()).strip() == "1"


@pytest.mark.asyncio
async def test_T_EC09_cart_quantity_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nested_structure_changed
    Original      : .cart_quantity  (direct child of .cart_item)
    Broken        : .cart_item > .cart-quantity-wrapper > .qty-label-NESTED
    Expected heal : .cart_quantity  or  div[class*='cart_quantity']
    Research note : Refactoring wraps the quantity display in a new
                    .cart-quantity-wrapper element, breaking direct-child
                    selectors. Tests class-name fragment matching that locates
                    the quantity div regardless of nesting depth.
    """
    result = await healer_hybrid.expect_visible(
        ".cart_item > .cart-quantity-wrapper > .qty-label-NESTED",
        description="Quantity label showing item count in cart row",
    )
    assert result.success, (
        f"Cart quantity nested-structure healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    qty_el = page_at_cart.locator(result.healed_selector).first
    assert (await qty_el.inner_text()).strip() == "1", (
        f"Expected quantity '1' after healing, got {await qty_el.inner_text()!r}"
    )


# ---------------------------------------------------------------------------
# T_EC10 — Checkout button navigates to step one: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC10_checkout_button_normal(page_at_cart: Page) -> None:
    """Normal: [data-test='checkout'] click navigates to /checkout-step-one.html."""
    btn = page_at_cart.locator("[data-test='checkout']")
    await expect(btn).to_be_visible()
    await btn.click()
    await expect(page_at_cart).to_have_url(f"{BASE_URL}/checkout-step-one.html")
    await expect(page_at_cart.locator("#first-name")).to_be_visible()


@pytest.mark.asyncio
async def test_T_EC10_checkout_button_broken(
    page_at_cart: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : [data-test='checkout']  (button in .cart_footer)
    Broken        : .cart-footer > .action-group > .checkout-btn-MOVED
    Expected heal : [data-test='checkout']  or  button[class*='checkout_button']
    Research note : Footer refactoring groups action buttons inside a new
                    .action-group div, invalidating direct-child selectors.
                    Tests data-test attribute and button text ('Checkout')
                    heuristics for primary call-to-action buttons in footers.
    """
    result = await healer_hybrid.click(
        ".cart-footer > .action-group > .checkout-btn-MOVED",
        description="Checkout button in the cart page footer",
    )
    assert result.success, (
        f"Checkout button dom-position healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_cart).to_have_url(f"{BASE_URL}/checkout-step-one.html")
