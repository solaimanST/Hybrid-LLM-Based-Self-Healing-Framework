"""
tests/login_suite_converted/test_login_ui.py

Inspired by:
  CraigBall26/playwright-login-suite — positive/test_valid_login.py
  (branding / layout visibility inferred from the suite's page-object structure)

Login page UI structure tests — logo and container visibility.
Tests T_L09–T_L10 (2 normal / 2 broken pairs).

Covers: class_changed (invented brand name), class_separator_changed (underscore → hyphen).
Break targets: .login_logo, .login_container.

Target site: https://www.saucedemo.com (login page)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer


# ---------------------------------------------------------------------------
# T_L09 — Login logo visibility: class_changed (invented brand-name class)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L09_logo_visibility_normal(page_at_login: Page) -> None:
    """Normal: .login_logo is visible and contains 'Swag Labs'."""
    logo = page_at_login.locator(".login_logo")
    await expect(logo).to_be_visible()
    text = await logo.inner_text()
    assert "Swag Labs" in text


@pytest.mark.asyncio
async def test_T_L09_logo_visibility_broken(
    page_at_login: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (invented brand-specific class name)
    Original      : .login_logo
    Broken        : .swag-labs-logo
    Expected heal : .login_logo  or  div[class*='logo']
    Research note : Branding element class renames are common after rebrands
                    or white-labelling. Tests partial class-fragment matching
                    heuristics ('logo' substring) as a robust fallback when
                    the full class name has changed.
    """
    result = await healer_hybrid.expect_visible(
        ".swag-labs-logo",
        description="Swag Labs branding logo displayed on the login page header",
    )
    assert result.success, (
        f"Logo class healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}


# ---------------------------------------------------------------------------
# T_L10 — Login container: class_separator_changed (underscore → hyphen)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_L10_login_container_normal(page_at_login: Page) -> None:
    """Normal: .login_container wraps the entire login UI and is visible."""
    container = page_at_login.locator(".login_container")
    await expect(container).to_be_visible()


@pytest.mark.asyncio
async def test_T_L10_login_container_broken(
    page_at_login: Page, healer_heuristic: SelfHealer
) -> None:
    """
    Break type    : class_separator_changed  (underscore → hyphen)
    Original      : .login_container
    Broken        : .login-container
    Expected heal : .login_container  or  .login-box
    Research note : BEM and utility-CSS migrations systematically convert
                    underscore classes to hyphens — one of the highest-frequency
                    real-world selector breaks. Tests partial-class-name matching
                    on 'login' + 'container' fragments without LLM involvement.
    """
    result = await healer_heuristic.expect_visible(
        ".login-container",
        description="Main container wrapping all login form elements on SauceDemo",
    )
    assert result.success, (
        f"Container separator healing failed — source={result.source}, "
        f"error={result.original_error}"
    )
    assert result.healed_selector is not None
    # heuristic-only — validates non-LLM path for this common break type
    assert result.source in {"heuristic", "memory"}
