"""
tests/login_suite_converted/conftest.py

Fixtures for the login_suite_converted test suite.
Inherits browser/page from tests/conftest.py.

Target site: https://www.saucedemo.com
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from playwright.async_api import Page

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
STANDARD_USER = "standard_user"
LOCKED_USER = "locked_out_user"
PASSWORD = "secret_sauce"
WRONG_PASSWORD = "wrong_password_123"


@pytest_asyncio.fixture
async def page_at_login(page: Page) -> Page:
    await page.goto(BASE_URL, timeout=30_000)
    yield page


@pytest.fixture
def healer_hybrid(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="hybrid")


@pytest.fixture
def healer_heuristic(page: Page) -> SelfHealer:
    return SelfHealer(page, healing_mode="heuristic")
