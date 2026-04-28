"""
tests/selene_converted/test_form_healing.py

Converted from Selene: form interaction patterns.
Tests T04–T11 (4 normal / 4 broken pairs).

Covers: name attribute, type attribute, class rename, full login flow healing.

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
# T04 — Full login flow: id_changed on username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T04_login_flow_normal(page_at_login: Page) -> None:
    """Normal: complete login flow with stable selectors."""
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)
    await page_at_login.click("#login-button")
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


@pytest.mark.asyncio
async def test_T04_login_flow_broken_username_id(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed
    Original      : #user-name
    Broken        : #login-username-BROKEN
    Expected heal : #user-name  (or placeholder/role equivalent)
    Research note : Simulates a developer renaming the input id during
                    a login page refactor. Full end-to-end healing test.
    """
    result = await healer_hybrid.fill(
        "#login-username-BROKEN",
        USERNAME,
        description="Username input on SauceDemo login form",
    )
    assert result.success, (
        f"Username healing failed — source={result.source}, "
        f"error={result.original_error}"
    )

    # Complete login using stable selectors to confirm the healed fill worked
    await page_at_login.fill("#password", PASSWORD)
    await page_at_login.click("#login-button")
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


# ---------------------------------------------------------------------------
# T05 — Password field: name attribute changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T05_password_by_name_normal(page_at_login: Page) -> None:
    """Normal: locate password by input[name='password']."""
    field = page_at_login.locator("input[name='password']")
    await expect(field).to_be_visible()
    await field.fill(PASSWORD)
    assert await field.input_value() == PASSWORD


@pytest.mark.asyncio
async def test_T05_password_by_name_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : name_changed
    Original      : input[name='password']
    Broken        : input[name='user_password_field']
    Expected heal : #password or input[type='password']
    Research note : name attribute changes are common in server-side form
                    refactors. Tests type-attribute and id heuristics.
    """
    result = await healer_hybrid.fill(
        "input[name='user_password_field']",
        PASSWORD,
        description="Password input field on login page",
    )
    assert result.success, (
        f"Password healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T06 — Login button: type attribute removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T06_button_by_type_normal(page_at_login: Page) -> None:
    """Normal: locate login button by input[type='submit']."""
    btn = page_at_login.locator("input[type='submit']")
    await expect(btn).to_be_visible()
    # Don't actually submit — just validate presence
    assert await btn.get_attribute("id") == "login-button"


@pytest.mark.asyncio
async def test_T06_button_by_type_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (type='submit' removed, became type='button')
    Original      : input[type='submit']
    Broken        : input[type='submit-action-REMOVED']
    Expected heal : #login-button or .submit-button
    Research note : Developers sometimes change submit inputs to type=button
                    when adding custom JS validation. Tests id/class recovery.
    """
    result = await healer_hybrid.click(
        "input[type='submit-action-REMOVED']",
        description="Login submit button (type attribute changed)",
    )
    assert result.success, (
        f"Button type healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T07 — Login button: button_converted (input → button element)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T07_button_converted_normal(page_at_login: Page) -> None:
    """Normal: click login button by data-test attribute."""
    # SauceDemo doesn't have data-test on the button but has id
    btn = page_at_login.locator("#login-button")
    await expect(btn).to_be_visible()
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)
    await btn.click()
    await expect(page_at_login).to_have_url(f"{BASE_URL}/inventory.html")


@pytest.mark.asyncio
async def test_T07_button_converted_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : button_converted
    Original      : #login-button  (input[type='submit'])
    Broken        : button#login-button-NEW  (hypothetical element type change)
    Expected heal : #login-button or .submit-button or input[type='submit']
    Research note : Framework migrations (React, Vue) sometimes change
                    <input type='submit'> to <button>. Tests tag-agnostic
                    heuristic recovery using id fragments and text content.
    """
    await page_at_login.fill("#user-name", USERNAME)
    await page_at_login.fill("#password", PASSWORD)

    result = await healer_hybrid.click(
        "button#login-button-NEW",
        description="Login button (element type changed from input to button)",
    )
    assert result.success, (
        f"Button-converted healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
