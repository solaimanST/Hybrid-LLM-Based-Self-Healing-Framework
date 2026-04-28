"""
tests/ecommerce_suite/test_checkout_form.py

Checkout step-one form fill tests — first name, last name, postal code, continue.
Tests T_EC11–T_EC14 (4 normal / 4 broken pairs).

Covers: id_changed, attribute_removed, nearby_sibling_added, dom_position_changed.
Break targets: #first-name, input[data-test='lastName'], #postal-code,
               input[data-test='continue'].

Target site: https://www.saucedemo.com (/checkout-step-one.html)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
FIRST_NAME = "John"
LAST_NAME = "Doe"
POSTAL_CODE = "90210"


# ---------------------------------------------------------------------------
# T_EC11 — First name fill: id_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC11_fill_first_name_normal(page_at_checkout_form: Page) -> None:
    """Normal: fill #first-name with 'John', verify input value equals FIRST_NAME."""
    field = page_at_checkout_form.locator("#first-name")
    await expect(field).to_be_visible()
    await field.fill(FIRST_NAME)
    assert await field.input_value() == FIRST_NAME


@pytest.mark.asyncio
async def test_T_EC11_fill_first_name_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : id_changed  (#first-name → #firstName-RENAMED)
    Original      : #first-name
    Broken        : #firstName-RENAMED
    Expected heal : #first-name  or  input[data-test='firstName']
    Research note : camelCase/kebab-case id renames are common when backend
                    form frameworks change naming conventions. The field retains
                    data-test='firstName' as a stable secondary identifier.
                    Tests data-test and placeholder ('First Name') fallbacks.
    """
    result = await healer_hybrid.fill(
        "#firstName-RENAMED",
        FIRST_NAME,
        description="First name input on checkout step-one form",
    )
    assert result.success, (
        f"First name id-changed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    field = page_at_checkout_form.locator(result.healed_selector).first
    assert await field.input_value() == FIRST_NAME


# ---------------------------------------------------------------------------
# T_EC12 — Last name fill: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC12_fill_last_name_normal(page_at_checkout_form: Page) -> None:
    """Normal: fill input[data-test='lastName'], verify value equals LAST_NAME."""
    field = page_at_checkout_form.locator("input[data-test='lastName']")
    await expect(field).to_be_visible()
    await field.fill(LAST_NAME)
    assert await field.input_value() == LAST_NAME


@pytest.mark.asyncio
async def test_T_EC12_fill_last_name_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test attr stripped from last name input)
    Original      : input[data-test='lastName']
    Broken        : input[data-test='lastName-REMOVED']
    Expected heal : #last-name  or  input[placeholder='Last Name']
    Research note : data-test attributes on form fields are stripped by CSS
                    minifiers that treat them as decorative. Tests id and
                    placeholder heuristics for identifying the correct field
                    among multiple text inputs on the same checkout form.
    """
    result = await healer_hybrid.fill(
        "input[data-test='lastName-REMOVED']",
        LAST_NAME,
        description="Last name input on checkout step-one form",
    )
    assert result.success, (
        f"Last name attribute-removed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    field = page_at_checkout_form.locator(result.healed_selector).first
    assert await field.input_value() == LAST_NAME


# ---------------------------------------------------------------------------
# T_EC13 — Postal code fill: nearby_sibling_added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC13_fill_postal_code_normal(page_at_checkout_form: Page) -> None:
    """Normal: fill #postal-code with '90210', verify value equals POSTAL_CODE."""
    field = page_at_checkout_form.locator("#postal-code")
    await expect(field).to_be_visible()
    await field.fill(POSTAL_CODE)
    assert await field.input_value() == POSTAL_CODE


@pytest.mark.asyncio
async def test_T_EC13_fill_postal_code_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nearby_sibling_added
    Original      : #postal-code
    Broken        : #postal-code-SIBLING-ADDED
    Expected heal : #postal-code  or  input[data-test='postalCode']
    Research note : A new promo-code input field inserted before the postal
                    code field shifts nth-child based selectors and confuses
                    id-fragment matching when ids look similar. Tests
                    data-test='postalCode' and placeholder ('Zip/Postal Code')
                    as stable fallbacks when the exact id no longer resolves.
    """
    result = await healer_hybrid.fill(
        "#postal-code-SIBLING-ADDED",
        POSTAL_CODE,
        description="Postal code / zip input on checkout step-one form",
    )
    assert result.success, (
        f"Postal code nearby-sibling healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    field = page_at_checkout_form.locator(result.healed_selector).first
    assert await field.input_value() == POSTAL_CODE


# ---------------------------------------------------------------------------
# T_EC14 — Continue button after form fill: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC14_continue_checkout_normal(page_at_checkout_form: Page) -> None:
    """Normal: fill all fields, click input[data-test='continue'] → step two URL."""
    await page_at_checkout_form.fill("#first-name", FIRST_NAME)
    await page_at_checkout_form.fill("#last-name", LAST_NAME)
    await page_at_checkout_form.fill("#postal-code", POSTAL_CODE)
    btn = page_at_checkout_form.locator("input[data-test='continue']")
    await expect(btn).to_be_visible()
    await btn.click()
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/checkout-step-two.html")


@pytest.mark.asyncio
async def test_T_EC14_continue_checkout_broken(
    page_at_checkout_form: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : input[data-test='continue']  (child of .checkout_buttons)
    Broken        : .checkout-buttons > .continue-group > #continue-MOVED
    Expected heal : input[data-test='continue']  or  #continue  or  input[type='submit']
    Research note : A form layout refactor groups buttons inside a new
                    .continue-group div, and uses hyphenated class names
                    instead of underscored. Direct-child selectors break because
                    .checkout-buttons (hyphen) ≠ .checkout_buttons (underscore).
                    Tests data-test, id, and type='submit' heuristics for
                    the primary CTA in multi-step checkout flows.
    """
    await page_at_checkout_form.fill("#first-name", FIRST_NAME)
    await page_at_checkout_form.fill("#last-name", LAST_NAME)
    await page_at_checkout_form.fill("#postal-code", POSTAL_CODE)

    result = await healer_hybrid.click(
        ".checkout-buttons > .continue-group > #continue-MOVED",
        description="Continue button on checkout step-one form to proceed to step two",
    )
    assert result.success, (
        f"Continue button dom-position healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}
    await expect(page_at_checkout_form).to_have_url(f"{BASE_URL}/checkout-step-two.html")
