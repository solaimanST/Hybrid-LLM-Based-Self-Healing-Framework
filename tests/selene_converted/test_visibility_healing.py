"""
tests/selene_converted/test_visibility_healing.py

Converted from Selene: visibility, existence, and state checks.
Tests T13–T20 (4 normal / 4 broken pairs).

Covers: logo visibility, error message, cart badge, graceful failure
        under healing_mode='none', attribute_removed, text_changed.

Target site: https://www.saucedemo.com
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"
BAD_PASSWORD = "wrong_password"


# ---------------------------------------------------------------------------
# T13 — App logo visibility: id_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T13_logo_visible_normal(page_at_inventory: Page) -> None:
    """Normal: app logo is visible after login."""
    logo = page_at_inventory.locator(".app_logo")
    await expect(logo).to_be_visible()
    text = await logo.inner_text()
    assert "Swag" in text


@pytest.mark.asyncio
async def test_T13_logo_visible_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed
    Original      : .app_logo
    Broken        : .application-logo-BROKEN
    Expected heal : .app_logo or .header_label
    Research note : Logo element class renames are common after rebrand.
                    Tests whether heuristic recovers via text content 'Swag Labs'.
    """
    result = await healer_hybrid.expect_visible(
        ".application-logo-BROKEN",
        description="App logo in the top navigation header",
    )
    assert result.success, (
        f"Logo visibility healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T14 — Login error message: data-test attribute changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T14_error_message_normal(page_at_login: Page) -> None:
    """Normal: error message appears with correct data-test attribute."""
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", BAD_PASSWORD)
    await page_at_login.click("#login-button")
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    text = await error.inner_text()
    assert "Username and password do not match" in text


@pytest.mark.asyncio
async def test_T14_error_message_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test attr renamed/removed)
    Original      : [data-test='error']
    Broken        : [data-test='login-error-message-REMOVED']
    Expected heal : [data-test='error'] or .error-message-container or h3
    Research note : data-test attributes are sometimes removed in production
                    builds. Tests recovery via class, role, or text heuristics.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", BAD_PASSWORD)
    await page_at_login.click("#login-button")

    result = await healer_hybrid.expect_visible(
        "[data-test='login-error-message-REMOVED']",
        description="Login error message container after failed authentication",
    )
    assert result.success, (
        f"Error msg healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T15 — Cart badge after add: text_changed in selector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T15_cart_badge_normal(page_at_inventory: Page) -> None:
    """Normal: add item then cart badge shows '1' via .shopping_cart_badge."""
    await page_at_inventory.locator(".btn_inventory").first.click()
    badge = page_at_inventory.locator(".shopping_cart_badge")
    await expect(badge).to_be_visible()
    await expect(badge).to_have_text("1")


@pytest.mark.asyncio
async def test_T15_cart_badge_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (badge class renamed)
    Original      : .shopping_cart_badge
    Broken        : .cart-item-count-BROKEN
    Expected heal : .shopping_cart_badge or span inside .shopping_cart_link
    Research note : Badge span class changes during cart component refactors.
                    Tests parent-relative heuristics (.shopping_cart_link > span).
    """
    await page_at_inventory.locator(".btn_inventory").first.click()

    result = await healer_hybrid.expect_visible(
        ".cart-item-count-BROKEN",
        description="Cart item count badge in the navigation header",
    )
    assert result.success, (
        f"Cart badge healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None


# ---------------------------------------------------------------------------
# T16 — Sort dropdown: name_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T16_sort_dropdown_normal(page_at_inventory: Page) -> None:
    """Normal: product sort container is visible and selectable."""
    dropdown = page_at_inventory.locator(".product_sort_container")
    await expect(dropdown).to_be_visible()
    await dropdown.select_option("za")
    items = page_at_inventory.locator(".inventory_item_name")
    first_text = await items.first.inner_text()
    assert len(first_text) > 0


@pytest.mark.asyncio
async def test_T16_sort_dropdown_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (sort dropdown class renamed)
    Original      : .product_sort_container
    Broken        : .sort-select-BROKEN
    Expected heal : .product_sort_container or select[data-test='product-sort-container']
    Research note : Sort/filter control class changes break regression tests.
                    Tests select-element-specific heuristics.
    """
    result = await healer_hybrid.expect_visible(
        ".sort-select-BROKEN",
        description="Product sort dropdown on inventory page",
    )
    assert result.success, (
        f"Sort dropdown healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T17 — Graceful failure: healing_mode='none' must not attempt repair
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T17_graceful_failure_no_healing(
    page_at_login: Page, healer_none: SelfHealer
) -> None:
    """
    Break type    : id_changed  (intentionally not healed)
    Original      : #user-name
    Broken        : #username-BROKEN
    Expected heal : N/A — healing_mode='none'
    Research note : Control case for the dataset. Validates that the framework
                    correctly reports failure and does NOT silently succeed.
                    Used as baseline for comparing healing modes in the paper.
    """
    result = await healer_none.fill(
        "#username-BROKEN",
        USERNAME,
        description="Username field with healing explicitly disabled",
    )
    assert result.success is False, (
        "Expected failure when healing_mode='none'"
    )
    assert result.healed_selector is None
    assert result.source == "failed"
    assert result.original_error != ""


# ---------------------------------------------------------------------------
# T18 — Inventory title text: text_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T18_page_title_normal(page_at_inventory: Page) -> None:
    """Normal: inventory page title shows 'Products'."""
    title = page_at_inventory.locator(".title")
    await expect(title).to_be_visible()
    await expect(title).to_have_text("Products")


@pytest.mark.asyncio
async def test_T18_page_title_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed
    Original      : .title
    Broken        : .page-heading-BROKEN
    Expected heal : .title or h2[class*='title'] or span with text 'Products'
    Research note : Generic class names like .title get prefixed/namespaced
                    during component extraction. Tests text-content heuristics
                    as a robust fallback when class is non-unique.
    """
    result = await healer_hybrid.expect_visible(
        ".page-heading-BROKEN",
        description="Page title heading on inventory page showing 'Products'",
    )
    assert result.success, (
        f"Title class healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T19 — Item detail price: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T19_item_price_normal(page_at_inventory: Page) -> None:
    """Normal: price label visible with $ prefix."""
    price = page_at_inventory.locator(".inventory_item_price").first
    await expect(price).to_be_visible()
    text = await price.inner_text()
    assert text.startswith("$")


@pytest.mark.asyncio
async def test_T19_item_price_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed
    Original      : .inventory_item_price
    Broken        : .item-price-label-BROKEN
    Expected heal : .inventory_item_price or [data-test*='price'] or span with '$'
    Research note : Price display elements are frequently restyled. Tests
                    text-pattern heuristics (contains '$') as healing signal.
    """
    result = await healer_hybrid.expect_visible(
        ".item-price-label-BROKEN",
        description="Product price label inside inventory item card",
    )
    assert result.success, (
        f"Price label healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T20 — Footer copyright: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T20_footer_normal(page_at_inventory: Page) -> None:
    """Normal: footer copyright text is visible."""
    footer = page_at_inventory.locator(".footer_copy")
    await expect(footer).to_be_visible()
    text = await footer.inner_text()
    assert "© 2024" in text or "Sauce Labs" in text


@pytest.mark.asyncio
async def test_T20_footer_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : .footer_copy  (direct child of footer)
    Broken        : .footer > .footer-inner > .copyright-MOVED
    Expected heal : .footer_copy or footer p or [class*='footer']
    Research note : Footer restructuring is common in responsive redesigns.
                    Tests partial class-name matching heuristics.
    """
    result = await healer_hybrid.expect_visible(
        ".footer > .footer-inner > .copyright-MOVED",
        description="Footer copyright text at the bottom of inventory page",
    )
    assert result.success, (
        f"Footer position healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
