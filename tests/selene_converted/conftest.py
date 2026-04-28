"""
tests/selene_converted/conftest.py

Shared fixtures for the selene-converted healing dataset.
Inherits session-scoped `browser` from tests/conftest.py.

This suite is an extended real-world converted dataset for scalability and
generalization checks. The controlled evaluation baseline remains
tests/test_registration_healing.py plus tests/ecommerce_suite.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import Page

from engine.repair_memory import RepairMemory
from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"


async def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    """Navigate with bounded retries for transient external-site timeouts."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            await page.wait_for_selector("#user-name", timeout=15_000)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                try:
                    await page.context.clear_cookies()
                    await page.context.clear_permissions()
                    await page.evaluate("window.localStorage.clear()")
                    await page.evaluate("window.sessionStorage.clear()")
                except Exception:
                    pass
    if last_error is not None:
        raise last_error


async def _reset_app_state(page: Page) -> None:
    """Reset browser/app state before each converted-dataset test."""
    await page.context.clear_cookies()
    await page.context.clear_permissions()

    await _goto_with_retry(page, BASE_URL)
    await page.evaluate("window.localStorage.clear()")
    await page.evaluate("window.sessionStorage.clear()")

    await _goto_with_retry(page, BASE_URL)


async def _login(page: Page) -> None:
    """Login as the standard external test user from a clean login page."""
    await _reset_app_state(page)
    await page.fill("#user-name", USERNAME)
    await page.fill("#password", PASSWORD)
    await page.click("#login-button")
    await page.wait_for_url("**/inventory.html", timeout=15_000)


async def _cleanup_app_state(page: Page) -> None:
    """Best-effort cleanup only; avoid teardown navigation that can stall."""
    try:
        await page.evaluate("window.localStorage.clear()")
        await page.evaluate("window.sessionStorage.clear()")
        await page.context.clear_cookies()
        await page.context.clear_permissions()
    except Exception:
        pass


@pytest_asyncio.fixture
async def page_at_login(page: Page) -> Page:
    await _reset_app_state(page)
    try:
        yield page
    finally:
        await _cleanup_app_state(page)


@pytest_asyncio.fixture
async def page_at_inventory(page: Page) -> Page:
    await _login(page)
    try:
        yield page
    finally:
        await _cleanup_app_state(page)


@pytest.fixture
def healer_hybrid(page: Page, tmp_path) -> SelfHealer:
    return SelfHealer(
        page,
        memory=RepairMemory(path=str(tmp_path / "repair_memory.json")),
        healing_mode="hybrid",
    )


@pytest.fixture
def healer_heuristic(page: Page, tmp_path) -> SelfHealer:
    return SelfHealer(
        page,
        memory=RepairMemory(path=str(tmp_path / "repair_memory.json")),
        healing_mode="heuristic",
    )


@pytest.fixture
def healer_none(page: Page, tmp_path) -> SelfHealer:
    return SelfHealer(
        page,
        memory=RepairMemory(path=str(tmp_path / "repair_memory.json")),
        healing_mode="none",
    )
