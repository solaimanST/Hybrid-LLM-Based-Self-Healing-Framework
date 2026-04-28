"""
tests/login_suite_converted/test_login_button.py

Inspired by:
  CraigBall26/playwright-login-suite — positive/test_valid_login.py

Login button click tests — button targeting and full login flow.
Tests T_L03–T_L04 (2 normal / 2 broken pairs).

Covers: class_changed (class rename), attribute_value_changed (button label text).
Break targets: login submit button (#login-button / input[type='submit']).

Target site: https://www.saucedemo.com (login page)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"


# ---------------------------------------------------------------------------
# T_L03 — Login button click: class_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L03_click_login_button_normal(page_at_login: Page) -> None:
    """Normal: fill credentials and click #login-button; expect inventory URL."""
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)
    await page_at_login.click("#login-button")
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


@pytest.mark.asyncio
async def test_T_L03_click_login_button_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (submit-button → btn-submit rename)
    Original      : #login-button  /  .submit-button
    Broken        : input.btn-submit
    Expected heal : #login-button  or  input[type='submit']
    Research note : Design-system migrations frequently rename button classes.
                    '.submit-button' becoming '.btn-submit' is a BEM-to-utility
                    refactor pattern. Tests id heuristic as a stable fallback
                    when CSS class is the only anchor in the broken selector.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)

    result = await healer_hybrid.click(
        "input.btn-submit",
        description="Login submit button on SauceDemo login form",
    )
    assert result.success, (
        f"Button class healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    # Verify the click triggered real navigation — not just a healed locator match
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


# ---------------------------------------------------------------------------
# T_L04 — Full login flow: attribute_value_changed (button label text)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L04_full_login_flow_normal(page_at_login: Page) -> None:
    """Normal: full login via input[type='submit'] with value='Login'."""
    btn = page_at_login.locator("input[type='submit']")
    await expect(btn).to_be_visible()
    assert await btn.get_attribute("value") == "Login"
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)
    await btn.click()
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


@pytest.mark.asyncio
async def test_T_L04_full_login_flow_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_value_changed  (button label 'Login' → 'Sign In')
    Original      : input[value='Login']
    Broken        : input[value='Sign In']
    Expected heal : #login-button  or  input[type='submit']
    Research note : Button label copy changes (i18n, UX rewrites) break
                    value-anchored selectors. Tests fallback to type+id
                    heuristics when the value attribute text no longer matches.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)

    result = await healer_hybrid.click(
        "input[value='Sign In']",
        description="Login submit button — label changed from 'Login' to 'Sign In'",
    )
    assert result.success, (
        f"Button value healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")
