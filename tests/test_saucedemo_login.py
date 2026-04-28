"""
tests/test_saucedemo_login.py

SauceDemo login integration tests for the self-healing framework.

Tests:
  1. Normal successful login using correct Playwright locators.
  2. Strict self-healing: intentionally broken selector must be healed
     without any manual fallback.
  3. Graceful failure: healing_mode="none" must fail cleanly and log
     the error correctly.

Credentials (publicly documented):
    username : standard_user
    password : secret_sauce
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright, Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def browser_ctx():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            channel="chrome",
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        try:
            yield ctx
        finally:
            await browser.close()


@pytest_asyncio.fixture
async def page(browser_ctx):
    pg = await browser_ctx.new_page()
    await pg.goto(BASE_URL, timeout=30_000)
    try:
        yield pg
    finally:
        await pg.close()


@pytest.fixture
def healer(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="hybrid")


# ---------------------------------------------------------------------------
# Test 1: Normal successful login (no healing involved)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(page: Page) -> None:
    """Happy-path login using stable semantic Playwright locators."""
    await page.get_by_placeholder("Username").fill(USERNAME)
    await page.get_by_placeholder("Password").fill(PASSWORD)
    await page.get_by_role("button", name="Login").click()

    await expect(page).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page.locator(".title")).to_have_text("Products")


# ---------------------------------------------------------------------------
# Test 2: Strict self-healing test — broken selector must be healed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healing_succeeds_with_broken_selector(
    page: Page, healer: SelfHealer
) -> None:
    """
    The broken selector '#user-name-BROKEN' must be healed by the engine.
    No manual fallback is allowed inside this test.
    """
    result = await healer.fill(
        "#user-name-BROKEN",
        USERNAME,
        description="Username input field",
    )

    assert result.success is True, (
        f"Self-healing FAILED for '#user-name-BROKEN'.\n"
        f"  source         : {result.source}\n"
        f"  attempts       : {result.attempts}\n"
        f"  original_error : {result.original_error}"
    )
    assert result.healed_selector is not None, (
        "Healed selector must not be None on success"
    )
    assert result.source in {"heuristic", "llm", "memory"}, (
        f"Unexpected source: {result.source!r}"
    )

    # Complete login to confirm healed fill really worked
    await page.fill("#password", PASSWORD)
    await page.click("#login-button")
    await expect(page).to_have_url(f"{BASE_URL}/inventory.html")
    await expect(page.locator(".title")).to_have_text("Products")


# ---------------------------------------------------------------------------
# Test 3: Graceful failure when healing is disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graceful_failure_with_healing_disabled(page: Page) -> None:
    """
    When healing_mode='none', the healer must not attempt repair.
    The result must report failure cleanly with a non-empty error message
    and no healed_selector.
    """
    healer_no_heal = SelfHealer(page, healing_mode="none")

    result = await healer_no_heal.fill(
        "#user-name-BROKEN",
        USERNAME,
        description="Broken selector with healing disabled",
    )

    assert result.success is False, (
        "Expected healing to fail when healing_mode='none'"
    )
    assert result.healed_selector is None, (
        "No healed_selector should be set when healing fails"
    )
    assert result.source == "failed", (
        f"Expected source='failed', got {result.source!r}"
    )
    assert result.original_error != "", (
        "original_error must be populated on failure"
    )