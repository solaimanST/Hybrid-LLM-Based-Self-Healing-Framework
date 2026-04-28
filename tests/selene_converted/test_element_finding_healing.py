"""
tests/selene_converted/test_element_finding_healing.py

Converted from Selene: element finding patterns.
Each "broken" test simulates a real-world DOM change and evaluates
whether the self-healing engine can recover without manual fallbacks.
This is an extended dataset, separate from the official controlled baseline.

Tests T01–T06 (3 normal / 3 broken pairs).

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
# T01 — Find by CSS ID
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T01_find_by_id_normal(page_at_login: Page) -> None:
    """Normal: locate username input by stable #user-name id."""
    field = page_at_login.locator("#user-name")
    await expect(field).to_be_visible()
    await field.fill(USERNAME)
    assert await field.input_value() == USERNAME


@pytest.mark.asyncio
async def test_T01_find_by_id_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #user-name
    Broken        : #username-field-BROKEN
    Expected heal : #user-name  (or semantic equivalent)
    Research note : Most common real-world break; tests ID-fallback via
                    placeholder / role heuristics.
    """
    result = await healer_hybrid.fill(
        "#username-field-BROKEN",
        USERNAME,
        description="Username input field on login page",
    )
    assert result.success, (
        f"Healing failed — source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    assert await page_at_login.locator("#user-name").input_value() == USERNAME


# ---------------------------------------------------------------------------
# T02 — Find by placeholder attribute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T02_find_by_placeholder_normal(page_at_login: Page) -> None:
    """Normal: locate username by [placeholder='Username']."""
    field = page_at_login.locator("[placeholder='Username']")
    await expect(field).to_be_visible()
    await field.fill(USERNAME)
    assert await field.input_value() == USERNAME


@pytest.mark.asyncio
async def test_T02_find_by_placeholder_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : placeholder_changed
    Original      : [placeholder='Username']
    Broken        : [placeholder='Enter your username here']
    Expected heal : #user-name or [placeholder='Username']
    Research note : Placeholder text is changed during i18n/rebrand.
                    Tests whether heuristics recover via id or role.
    """
    result = await healer_hybrid.fill(
        "[placeholder='Enter your username here']",
        USERNAME,
        description="Username input identified by placeholder text",
    )
    assert result.success, (
        f"Healing failed — source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    assert await page_at_login.locator("#user-name").input_value() == USERNAME


# ---------------------------------------------------------------------------
# T03 — Find by CSS class on button
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T03_find_by_class_normal(page_at_login: Page) -> None:
    """Normal: locate login button by .submit-button class."""
    btn = page_at_login.locator(".submit-button")
    await expect(btn).to_be_visible()
    await btn.click()
    # With empty creds → stays on login page with error
    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()


@pytest.mark.asyncio
async def test_T03_find_by_class_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed
    Original      : .submit-button
    Broken        : .login-submit-btn-BROKEN
    Expected heal : #login-button or input[type='submit']
    Research note : Class renames during CSS refactors are extremely common.
                    Tests id + type attribute heuristic fallbacks.
    """
    result = await healer_hybrid.click(
        ".login-submit-btn-BROKEN",
        description="Login submit button",
    )
    assert result.success, (
        f"Healing failed — source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}

    error = page_at_login.locator("[data-test='error']")
    await expect(error).to_be_visible()
    await expect(error).to_contain_text("Username is required")
