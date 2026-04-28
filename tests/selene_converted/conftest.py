"""
tests/selene_converted/conftest.py

Shared fixtures for the selene-converted healing dataset.
Inherits session-scoped `browser` from tests/conftest.py.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import Page

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
USERNAME = "standard_user"
PASSWORD = "secret_sauce"


@pytest_asyncio.fixture
async def page_at_login(page: Page) -> Page:
    await page.goto(BASE_URL, timeout=30_000)
    yield page


@pytest_asyncio.fixture
async def page_at_inventory(page: Page) -> Page:
    await page.goto(BASE_URL, timeout=30_000)
    await page.fill("#user-name", USERNAME)
    await page.fill("#password", PASSWORD)
    await page.click("#login-button")
    await page.wait_for_url("**/inventory.html", timeout=15_000)
    yield page


@pytest.fixture
def healer_hybrid(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="hybrid")


@pytest.fixture
def healer_heuristic(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="heuristic")


@pytest.fixture
def healer_none(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="none")
