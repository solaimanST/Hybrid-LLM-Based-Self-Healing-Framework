"""
tests/login_suite_converted/test_login_inputs.py

Inspired by:
  CraigBall26/playwright-login-suite — positive/test_valid_login.py
  CraigBall26/playwright-login-suite — negative/test_known_user_empty_password.py

Login field fill tests — username and password inputs.
Tests T_L01–T_L02 (2 normal / 2 broken pairs).

Covers: id_changed (underscore variant), placeholder_changed.
Break targets: username input (#user-name), password input (#password).

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
# T_L01 — Username fill: id_changed (kebab → snake_case variant)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L01_fill_username_normal(page_at_login: Page) -> None:
    """Normal: fill #user-name, verify input value equals USERNAME."""
    field = page_at_login.locator("#user-name")
    await expect(field).to_be_visible()
    await field.fill(USERNAME)
    assert await field.input_value() == USERNAME


@pytest.mark.asyncio
async def test_T_L01_fill_username_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed  (kebab-case → snake_case renaming)
    Original      : #user-name
    Broken        : input#user_name_field
    Expected heal : #user-name  or  input[name='user-name']
    Research note : Devs switching from kebab-case to snake_case IDs during
                    a UI refactor is a top-5 real-world selector break.
                    Tests name-attribute and placeholder fallback heuristics.
    """
    result = await healer_hybrid.fill(
        "input#user_name_field",
        USERNAME,
        description="Username text input on SauceDemo login form",
    )
    assert result.success, (
        f"Username id healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    # Verify the fill actually landed: the healed field must hold the value
    assert await page_at_login.locator(result.healed_selector).input_value() == USERNAME


# ---------------------------------------------------------------------------
# T_L02 — Password fill: placeholder_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L02_fill_password_normal(page_at_login: Page) -> None:
    """Normal: fill input[placeholder='Password'], verify value."""
    field = page_at_login.locator("input[placeholder='Password']")
    await expect(field).to_be_visible()
    await field.fill(PASSWORD)
    assert await field.input_value() == PASSWORD


@pytest.mark.asyncio
async def test_T_L02_fill_password_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : placeholder_changed  (placeholder copy reworded)
    Original      : input[placeholder='Password']
    Broken        : input[placeholder='Enter your password']
    Expected heal : #password  or  input[type='password']
    Research note : UX rewrites and i18n changes frequently alter placeholder
                    text. Tests whether type-attribute and id heuristics
                    remain stable when placeholder no longer matches.
    """
    result = await healer_hybrid.fill(
        "input[placeholder='Enter your password']",
        PASSWORD,
        description="Password input field on SauceDemo login page",
    )
    assert result.success, (
        f"Password placeholder healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    assert await page_at_login.locator(result.healed_selector).input_value() == PASSWORD
