"""
tests/selene_converted/test_collections_healing.py

Converted from Selene: collection / multi-element patterns.
Tests T08–T13 (3 normal / 3 broken pairs).
This is an extended dataset, separate from the official controlled baseline.

Covers: item count, list class rename, nested structure change,
        sibling insertion, add-to-cart button, product name text.

Target site: https://www.saucedemo.com (inventory page, requires login)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"


# ---------------------------------------------------------------------------
# T08 — Inventory item count: class_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T08_inventory_count_normal(page_at_inventory: Page) -> None:
    """Normal: 6 product cards present on inventory page."""
    items = page_at_inventory.locator(".inventory_item")
    await expect(items).to_have_count(6)


@pytest.mark.asyncio
async def test_T08_inventory_count_broken(
    page_at_inventory: Page, healer_heuristic: SelfHealer
) -> None:
    """
    Break type    : class_changed
    Original      : .inventory_item
    Broken        : .inventory_item-BROKEN
    Expected heal : .inventory_item or div[data-test*='inventory']
    Research note : CSS class renames during design-system migrations.
                    Heuristic-only mode tested here (no LLM cost).
                    Validates that heuristics recover collection selectors.
    """
    result = await healer_heuristic.expect_visible(
        ".inventory_item-BROKEN",
        description=(
            "Inventory item product card collection; exactly six repeated "
            "product cards on the inventory page"
        ),
    )
    assert result.success, (
        f"Collection class healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "memory"}
    await expect(page_at_inventory.locator(result.healed_selector).first).to_be_visible()
    await expect(page_at_inventory.locator(result.healed_selector)).to_have_count(6)
    first_card = page_at_inventory.locator(result.healed_selector).first
    await expect(first_card.locator(".inventory_item_price")).to_be_visible()
    await expect(first_card.locator("button").first).to_contain_text("Add to cart")


# ---------------------------------------------------------------------------
# T09 — Product name text match: text_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T09_product_name_normal(page_at_inventory: Page) -> None:
    """Normal: first product name text is present and visible."""
    name = page_at_inventory.locator(".inventory_item_name").first
    await expect(name).to_be_visible()
    text = await name.inner_text()
    assert len(text) > 0


@pytest.mark.asyncio
async def test_T09_product_name_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (item name class renamed)
    Original      : .inventory_item_name
    Broken        : .inventory_item_name-BROKEN
    Expected heal : .inventory_item_name or a[data-test*='item-name']
    Research note : Name/title class changes are frequent in UI redesigns.
                    Tests recovery of text-content elements using parent
                    container context heuristics.
    """
    result = await healer_hybrid.expect_visible(
        ".inventory_item_name-BROKEN",
        description=(
            "Product name link label inside an inventory item product card"
        ),
    )
    assert result.success, (
        f"Product name healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    healed = page_at_inventory.locator(result.healed_selector).first
    await expect(healed).to_be_visible()
    text = (await healed.inner_text()).strip()
    assert text
    assert text != "Products"
    assert not text.startswith("$")
    assert await healed.evaluate("el => !!el.closest('.inventory_item')")


# ---------------------------------------------------------------------------
# T10 — Add-to-cart button: nested_structure_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T10_add_to_cart_normal(page_at_inventory: Page) -> None:
    """Normal: click 'Add to cart' on first product, cart badge shows 1."""
    btn = page_at_inventory.locator(".btn_inventory").first
    await expect(btn).to_be_visible()
    await btn.click()
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")


@pytest.mark.asyncio
async def test_T10_add_to_cart_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nested_structure_changed
    Original      : .btn_inventory  (button directly inside .inventory_item)
    Broken        : .inventory_item > .item-actions > .add-cart-btn-BROKEN
    Expected heal : .btn_inventory or button[data-test*='add-to-cart']
    Research note : Layout restructuring wraps buttons in new container divs.
                    Tests whether heuristics recover via text content
                    ('Add to cart') and button role despite path change.
    """
    result = await healer_hybrid.click(
        ".inventory_item > .item-actions > .add-cart-btn-BROKEN",
        description="Add to cart button inside product card",
    )
    assert result.success, (
        f"Nested structure healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory.html")
    assert result.source in {"heuristic", "llm", "memory"}

    # Confirm cart badge incremented to prove the click actually landed
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_have_text("1")


# ---------------------------------------------------------------------------
# T11 — Nav menu burger: nearby_sibling_added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T11_nav_menu_normal(page_at_inventory: Page) -> None:
    """Normal: open hamburger menu via the accessible menu button."""
    burger = page_at_inventory.locator("#react-burger-menu-btn")
    await expect(burger).to_be_visible()
    await burger.click()
    menu = page_at_inventory.locator(".bm-menu")
    await expect(menu).to_be_visible()
    await expect(page_at_inventory.locator(".bm-menu-wrap")).to_have_attribute(
        "aria-hidden", "false"
    )


@pytest.mark.asyncio
async def test_T11_nav_menu_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nearby_sibling_added
    Original      : #react-burger-menu-btn
    Broken        : #react-burger-menu-btn-EXTRA  (sibling element inserted before it)
    Expected heal : .bm-burger-button or button[aria-label*='menu']
    Research note : New toolbar buttons inserted as siblings shift positional
                    selectors. Tests nth-child / aria-label heuristics.
    """
    result = await healer_hybrid.click(
        "#react-burger-menu-btn-EXTRA",
        description=(
            "Hamburger menu button that opens the navigation menu"
        ),
    )
    assert result.success, (
        f"Sibling-added healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None

    menu = page_at_inventory.locator(".bm-menu")
    await expect(menu).to_be_visible()
    await expect(page_at_inventory.locator(".bm-menu-wrap")).to_have_attribute(
        "aria-hidden", "false"
    )


# ---------------------------------------------------------------------------
# T12 — Cart link: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T12_cart_link_normal(page_at_inventory: Page) -> None:
    """Normal: shopping cart icon link exists in header."""
    cart = page_at_inventory.locator(".shopping_cart_link")
    await expect(cart).to_be_visible()


@pytest.mark.asyncio
async def test_T12_cart_link_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : .shopping_cart_link  (direct child of header)
    Broken        : .header-actions > .cart-wrapper > .shopping_cart_link_MOVED
    Expected heal : .shopping_cart_link or a[href='/cart.html']
    Research note : Header restructuring moves cart into a wrapper div.
                    Tests href-attribute and class heuristic fallbacks.
    """
    result = await healer_hybrid.click(
        ".header-actions > .cart-wrapper > .shopping_cart_link_MOVED",
        description=(
            "Shopping cart anchor link in the page header that navigates to "
            "the cart page"
        ),
    )
    assert result.success, (
        f"DOM position healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/cart.html")
