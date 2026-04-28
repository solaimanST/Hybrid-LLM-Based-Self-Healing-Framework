"""
tests/ecommerce_suite/test_extended_ecommerce_flows.py

Extended SauceDemo ecommerce flow tests.

These tests expand the ecommerce dataset with end-to-end interactions that
exercise product details, navigation menu behavior, checkout overview, order
completion, and checkout cancellation.  Broken-selector cases use the generic
SelfHealer pipeline and always verify a real UI effect after healing.
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
FIRST_NAME = "Ada"
LAST_NAME = "Lovelace"
POSTAL_CODE = "12345"


async def _open_product_detail(page: Page) -> None:
    await page.click("#item_4_title_link")
    await page.wait_for_url("**/inventory-item.html?id=4", timeout=10_000)


async def _open_menu(page: Page) -> None:
    await page.click("#react-burger-menu-btn")
    await expect(page.locator(".bm-menu-wrap")).to_have_attribute("aria-hidden", "false")


async def _fill_checkout_form(page: Page) -> None:
    await page.fill("#first-name", FIRST_NAME)
    await page.fill("#last-name", LAST_NAME)
    await page.fill("#postal-code", POSTAL_CODE)


async def _go_to_checkout_overview(page: Page) -> None:
    await _fill_checkout_form(page)
    await page.click("#continue")
    await page.wait_for_url("**/checkout-step-two.html", timeout=10_000)


# ---------------------------------------------------------------------------
# T_EXT01 — Product detail navigation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT01_product_detail_normal(page_at_inventory: Page) -> None:
    """Normal: product name link opens the backpack product detail page."""
    await _open_product_detail(page_at_inventory)
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory-item.html?id=4")
    await expect(page_at_inventory.locator(".inventory_details_name")).to_contain_text(
        "Sauce Labs Backpack"
    )


@pytest.mark.asyncio
async def test_T_EXT01_product_detail_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #item_4_title_link
    Broken        : #item_4_title_link-BROKEN
    Expected heal : #item_4_title_link or a[data-test='item-4-title-link']
    """
    result = await healer_hybrid.click(
        "#item_4_title_link-BROKEN",
        description="Product name link that opens the Sauce Labs Backpack detail page",
    )
    assert result.success, f"Product detail healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory-item.html?id=4")
    await expect(page_at_inventory.locator(".inventory_details_name")).to_contain_text(
        "Sauce Labs Backpack"
    )


# ---------------------------------------------------------------------------
# T_EXT02 — Back to products from detail page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT02_back_to_products_normal(page_at_inventory: Page) -> None:
    """Normal: Back to products returns from product detail to inventory."""
    await _open_product_detail(page_at_inventory)
    await page_at_inventory.click("#back-to-products")
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_inventory.locator(".inventory_item")).to_have_count(6)


@pytest.mark.asyncio
async def test_T_EXT02_back_to_products_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #back-to-products
    Broken        : #back-to-products-BROKEN
    Expected heal : #back-to-products or button[data-test='back-to-products']
    """
    await _open_product_detail(page_at_inventory)
    result = await healer_hybrid.click(
        "#back-to-products-BROKEN",
        description="Back to products button returning from product detail to inventory",
    )
    assert result.success, f"Back-to-products healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_inventory.locator(".inventory_item")).to_have_count(6)


# ---------------------------------------------------------------------------
# T_EXT03 — Burger menu open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT03_burger_menu_open_normal(page_at_inventory: Page) -> None:
    """Normal: hamburger button opens the side navigation menu."""
    await _open_menu(page_at_inventory)
    await expect(page_at_inventory.locator("#logout_sidebar_link")).to_be_visible()


@pytest.mark.asyncio
async def test_T_EXT03_burger_menu_open_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #react-burger-menu-btn
    Broken        : #react-burger-menu-btn-EXTRA
    Expected heal : #react-burger-menu-btn or button text 'Open Menu'
    """
    result = await healer_hybrid.click(
        "#react-burger-menu-btn-EXTRA",
        description="Hamburger menu button that opens the side navigation menu",
    )
    assert result.success, f"Burger-menu healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory.locator(".bm-menu-wrap")).to_have_attribute(
        "aria-hidden", "false"
    )
    await expect(page_at_inventory.locator("#logout_sidebar_link")).to_be_visible()


# ---------------------------------------------------------------------------
# T_EXT04 — Close menu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT04_close_menu_normal(page_at_inventory: Page) -> None:
    """Normal: close button hides the side navigation menu."""
    await _open_menu(page_at_inventory)
    await page_at_inventory.click("#react-burger-cross-btn")
    await expect(page_at_inventory.locator(".bm-menu-wrap")).to_have_attribute(
        "aria-hidden", "true"
    )


@pytest.mark.asyncio
async def test_T_EXT04_close_menu_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #react-burger-cross-btn
    Broken        : #react-burger-cross-btn-BROKEN
    Expected heal : #react-burger-cross-btn or close-menu button
    """
    await _open_menu(page_at_inventory)
    result = await healer_hybrid.click(
        "#react-burger-cross-btn-BROKEN",
        description="Close menu button that hides the side navigation menu",
    )
    assert result.success, f"Close-menu healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory.locator(".bm-menu-wrap")).to_have_attribute(
        "aria-hidden", "true"
    )


# ---------------------------------------------------------------------------
# T_EXT05 — Logout through menu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT05_logout_normal(page_at_inventory: Page) -> None:
    """Normal: logout menu item returns to the login page."""
    await _open_menu(page_at_inventory)
    await page_at_inventory.click("#logout_sidebar_link")
    await expect(page_at_inventory.locator("#user-name")).to_be_visible()
    await expect(page_at_inventory).to_have_url(BASE_URL + "/")


@pytest.mark.asyncio
async def test_T_EXT05_logout_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #logout_sidebar_link
    Broken        : #logout_sidebar_link-BROKEN
    Expected heal : #logout_sidebar_link
    """
    await _open_menu(page_at_inventory)
    result = await healer_hybrid.click(
        "#logout_sidebar_link-BROKEN",
        description="Logout link in the side navigation menu returning to login page",
    )
    assert result.success, f"Logout healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory.locator("#user-name")).to_be_visible()
    await expect(page_at_inventory).to_have_url(BASE_URL + "/")


# ---------------------------------------------------------------------------
# T_EXT06 — Reset app state through menu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT06_reset_app_state_normal(page_at_inventory: Page) -> None:
    """Normal: reset app state clears cart badge and restores add button."""
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_text("1")
    await _open_menu(page_at_inventory)
    await page_at_inventory.click("#reset_sidebar_link")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_count(0)
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory.html")


@pytest.mark.asyncio
async def test_T_EXT06_reset_app_state_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #reset_sidebar_link
    Broken        : #reset_sidebar_link-BROKEN
    Expected heal : #reset_sidebar_link
    """
    await page_at_inventory.click("[data-test='add-to-cart-sauce-labs-backpack']")
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_text("1")
    await _open_menu(page_at_inventory)
    result = await healer_hybrid.click(
        "#reset_sidebar_link-BROKEN",
        description="Reset app state link in side navigation menu clearing the cart",
    )
    assert result.success, f"Reset-app-state healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_inventory.locator(".shopping_cart_badge")).to_have_count(0)
    await expect(page_at_inventory).to_have_url(f"{BASE_URL}/inventory.html")


# ---------------------------------------------------------------------------
# T_EXT07 — Checkout overview
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT07_checkout_overview_normal(page_at_checkout_form: Page) -> None:
    """Normal: continue from checkout form reaches checkout overview."""
    await _go_to_checkout_overview(page_at_checkout_form)
    await expect(page_at_checkout_form.locator(".summary_info")).to_be_visible()
    await expect(page_at_checkout_form.locator(".cart_item")).to_have_count(1)


@pytest.mark.asyncio
async def test_T_EXT07_checkout_overview_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #continue
    Broken        : #continue-MOVED
    Expected heal : #continue or input[data-test='continue']
    """
    await _fill_checkout_form(page_at_checkout_form)
    result = await healer_hybrid.click(
        "#continue-MOVED",
        description="Continue button on checkout step-one form to show checkout overview",
    )
    assert result.success, f"Checkout-overview healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/checkout-step-two.html")
    await expect(page_at_checkout_form.locator(".summary_info")).to_be_visible()


# ---------------------------------------------------------------------------
# T_EXT08 — Finish checkout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT08_finish_checkout_normal(page_at_checkout_form: Page) -> None:
    """Normal: finish button completes checkout."""
    await _go_to_checkout_overview(page_at_checkout_form)
    await page_at_checkout_form.click("#finish")
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/checkout-complete.html")
    await expect(page_at_checkout_form.locator(".complete-header")).to_have_text(
        "Thank you for your order!"
    )


@pytest.mark.asyncio
async def test_T_EXT08_finish_checkout_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #finish
    Broken        : #finish-BROKEN
    Expected heal : #finish or button[data-test='finish']
    """
    await _go_to_checkout_overview(page_at_checkout_form)
    result = await healer_hybrid.click(
        "#finish-BROKEN",
        description="Finish button on checkout overview completing the order",
    )
    assert result.success, f"Finish-checkout healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/checkout-complete.html")
    await expect(page_at_checkout_form.locator(".complete-header")).to_have_text(
        "Thank you for your order!"
    )


# ---------------------------------------------------------------------------
# T_EXT09 — Back home after completed checkout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT09_back_home_normal(page_at_checkout_form: Page) -> None:
    """Normal: Back Home returns from checkout complete to inventory."""
    await _go_to_checkout_overview(page_at_checkout_form)
    await page_at_checkout_form.click("#finish")
    await page_at_checkout_form.click("#back-to-products")
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_checkout_form.locator(".inventory_item")).to_have_count(6)


@pytest.mark.asyncio
async def test_T_EXT09_back_home_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #back-to-products
    Broken        : #back-to-products-BROKEN
    Expected heal : #back-to-products
    """
    await _go_to_checkout_overview(page_at_checkout_form)
    await page_at_checkout_form.click("#finish")
    result = await healer_hybrid.click(
        "#back-to-products-BROKEN",
        description="Back Home button returning from checkout complete to inventory",
    )
    assert result.success, f"Back-home healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page_at_checkout_form.locator(".inventory_item")).to_have_count(6)


# ---------------------------------------------------------------------------
# T_EXT10 — Cancel checkout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EXT10_cancel_checkout_normal(page_at_checkout_form: Page) -> None:
    """Normal: cancel button leaves checkout form and returns to cart."""
    await page_at_checkout_form.click("#cancel")
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/cart.html")
    await expect(page_at_checkout_form.locator(".cart_item")).to_have_count(1)


@pytest.mark.asyncio
async def test_T_EXT10_cancel_checkout_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #cancel
    Broken        : #cancel-BROKEN
    Expected heal : #cancel or button[data-test='cancel']
    """
    result = await healer_hybrid.click(
        "#cancel-BROKEN",
        description="Cancel button on checkout step-one returning to cart page",
    )
    assert result.success, f"Cancel-checkout healing failed: {result.original_error}"
    assert result.healed_selector is not None
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/cart.html")
    await expect(page_at_checkout_form.locator(".cart_item")).to_have_count(1)
