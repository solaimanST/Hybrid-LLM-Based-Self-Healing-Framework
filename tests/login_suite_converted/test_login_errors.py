"""
tests/login_suite_converted/test_login_errors.py

Inspired by:
  CraigBall26/playwright-login-suite — negative/test_login_known_user_incorrect_password.py
  CraigBall26/playwright-login-suite — negative/test_empty_email_shows_error.py
  CraigBall26/playwright-login-suite — negative/test_known_user_empty_password.py
  CraigBall26/playwright-login-suite — negative/test_login_unknown_user_incorrect_password.py

Error message visibility tests for failed and edge-case login attempts.
Tests T_L05–T_L08 (4 normal / 4 broken pairs).

Covers: class_invented, id_invented, selector_path_changed, locked_out_user.
Break targets: error message element [data-test='error'].

Target site: https://www.saucedemo.com (login page)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
LOCKED_USER = "locked_out_user"
PASSWORD = "secret_sauce"
WRONG_PASSWORD = "totally_wrong_password"


# ---------------------------------------------------------------------------
# T_L05 — Invalid credentials error: class_invented
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L05_invalid_creds_error_normal(page_at_login: Page) -> None:
    """Normal: wrong password triggers [data-test='error'] with mismatch message."""
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", WRONG_PASSWORD)
    await page_at_login.click("#login-button")
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    text = await error.inner_text()
    assert "Username and password do not match" in text


@pytest.mark.asyncio
async def test_T_L05_invalid_creds_error_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_invented  (non-existent error-specific class)
    Original      : [data-test='error']
    Broken        : .login-error-text
    Expected heal : [data-test='error']  or  .error-message-container h3
    Research note : Error element class names are invented when data-test
                    attrs are stripped from production builds. Tests DOM-context
                    recovery via parent class (.error-message-container) and tag.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", WRONG_PASSWORD)
    await page_at_login.click("#login-button")

    result = await healer_hybrid.expect_visible(
        ".login-error-text",
        description="Error message shown after invalid username/password on login page",
    )
    assert result.success, (
        f"Invalid-creds error healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T_L06 — Empty username validation: id_invented
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L06_empty_username_error_normal(page_at_login: Page) -> None:
    """Normal: submitting with empty username shows 'Username is required'."""
    await page_at_login.click("#login-button")
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    text = await error.inner_text()
    assert "Username is required" in text


@pytest.mark.asyncio
async def test_T_L06_empty_username_error_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_invented  (error element has no real id on SauceDemo)
    Original      : [data-test='error']
    Broken        : #validation-error
    Expected heal : [data-test='error']  or  h3.error-message-container__text
    Research note : Testers sometimes assume an id exists on validation elements.
                    Validates that heuristics fall back to data-test or class
                    selectors when the element never had an id attribute.
    """
    await page_at_login.click("#login-button")

    result = await healer_hybrid.expect_visible(
        "#validation-error",
        description="Validation error shown when username field is left empty",
    )
    assert result.success, (
        f"Empty-username validation healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T_L07 — Empty password validation: selector_path_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L07_empty_password_error_normal(page_at_login: Page) -> None:
    """Normal: valid username but empty password shows 'Password is required'."""
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.click("#login-button")
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    text = await error.inner_text()
    assert "Password is required" in text


@pytest.mark.asyncio
async def test_T_L07_empty_password_error_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : selector_path_changed  (ancestor path invented/wrong)
    Original      : [data-test='error']
    Broken        : form .error-banner
    Expected heal : [data-test='error']  or  .error-message-container > h3
    Research note : The error h3 lives inside .error-message-container, not
                    directly under <form>. Invented ancestor paths fail silently
                    on most CSS engines. Tests ancestor-agnostic heuristics that
                    locate the closest matching element regardless of nesting.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.click("#login-button")

    result = await healer_hybrid.expect_visible(
        "form .error-banner",
        description="Password-required error shown when password field is left empty",
    )
    assert result.success, (
        f"Empty-password path healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T_L08 — Locked-out user error: class_invented
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L08_locked_user_error_normal(page_at_login: Page) -> None:
    """Normal: locked_out_user login shows locked-out error message."""
    await page_at_login.fill("#user-name", LOCKED_USER)
    await page_at_login.fill("#password", PASSWORD)
    await page_at_login.click("#login-button")
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    text = await error.inner_text()
    assert "locked out" in text.lower()


@pytest.mark.asyncio
async def test_T_L08_locked_user_error_broken(
    page_at_login: Page, healer_heuristic: SelfHealer
) -> None:
    """
    Break type    : class_invented  (hypothetical per-error-type class)
    Original      : [data-test='error']
    Broken        : .locked-user-error
    Expected heal : [data-test='error']  or  .error-message-container h3
    Research note : Some apps conditionally add CSS classes per error type
                    (e.g., .locked-user-error, .invalid-creds-error) and later
                    remove them. Uses healer_heuristic (no LLM) to validate
                    the non-LLM recovery path for paper comparison.
    """
    await page_at_login.fill("#user-name", LOCKED_USER)
    await page_at_login.fill("#password", PASSWORD)
    await page_at_login.click("#login-button")

    result = await healer_heuristic.expect_visible(
        ".locked-user-error",
        description="Locked-out account error shown after login attempt with a suspended user",
    )
    assert result.success, (
        f"Locked-user error healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    # heuristic mode only — no llm source expected
    assert result.source in {"heuristic", "memory"}
