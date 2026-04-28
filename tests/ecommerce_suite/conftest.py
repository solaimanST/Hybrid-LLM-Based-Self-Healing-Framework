"""
tests/ecommerce_suite/conftest.py

Fixtures for the ecommerce_suite test suite.

Target site: https://www.saucedemo.com
Covers: inventory page, cart page, checkout step-one.

Each fixture resets SauceDemo browser state before login so tests do not leak
cart/session state into each other.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import Page

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"
BACKPACK_DATA_TEST = "add-to-cart-sauce-labs-backpack"


async def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    """Navigate with bounded retries for transient external-site timeouts."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                try:
                    await page.context.clear_cookies()
                    await page.evaluate("window.localStorage.clear()")
                    await page.evaluate("window.sessionStorage.clear()")
                except Exception:
                    pass
    if last_error is not None:
        raise last_error


async def _reset_app_state(page: Page) -> None:
    """Reset cookies, storage, and return to a clean SauceDemo login page."""
    await page.context.clear_cookies()
    await page.context.clear_permissions()

    await _goto_with_retry(page, BASE_URL)
    await page.evaluate("window.localStorage.clear()")
    await page.evaluate("window.sessionStorage.clear()")

    await _goto_with_retry(page, BASE_URL)


async def _login(page: Page) -> None:
    """Login as standard SauceDemo user and wait for inventory page."""
    await _reset_app_state(page)

    await page.fill("#user-name", USERNAME)
    await page.fill("#password", PASSWORD)
    await page.click("#login-button")
    await page.wait_for_url("**/inventory.html", timeout=15_000)


async def _cleanup_app_state(page: Page) -> None:
    """Best-effort cleanup so one test's cart/session cannot affect the next."""
    try:
        await page.evaluate("window.localStorage.clear()")
        await page.evaluate("window.sessionStorage.clear()")
        await page.context.clear_cookies()
        await page.context.clear_permissions()
    except Exception:
        pass


@pytest_asyncio.fixture
async def page_at_inventory(page: Page) -> Page:
    """Logged in on inventory page with an empty cart."""
    await _login(page)
    try:
        yield page
    finally:
        await _cleanup_app_state(page)


@pytest_asyncio.fixture
async def page_at_cart(page: Page) -> Page:
    """Logged in, backpack in cart, on cart page."""
    await _login(page)
    await page.click(f"[data-test='{BACKPACK_DATA_TEST}']")
    await page.click(".shopping_cart_link")
    await page.wait_for_url("**/cart.html", timeout=10_000)
    try:
        yield page
    finally:
        await _cleanup_app_state(page)


@pytest_asyncio.fixture
async def page_at_checkout_form(page: Page) -> Page:
    """Logged in, backpack in cart, on checkout step-one page."""
    await _login(page)
    await page.click(f"[data-test='{BACKPACK_DATA_TEST}']")
    await page.click(".shopping_cart_link")
    await page.wait_for_url("**/cart.html", timeout=10_000)
    await page.click("[data-test='checkout']")
    await page.wait_for_url("**/checkout-step-one.html", timeout=10_000)
    try:
        yield page
    finally:
        await _cleanup_app_state(page)


@pytest.fixture
def healer_hybrid(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="hybrid")


@pytest.fixture
def healer_heuristic(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="heuristic")
