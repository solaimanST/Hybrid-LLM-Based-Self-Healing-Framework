import pytest_asyncio
from playwright.async_api import Browser, Page, Playwright, async_playwright

from engine.self_healer import SelfHealer


@pytest_asyncio.fixture(scope="session")
async def playwright_instance() -> Playwright:
    async with async_playwright() as p:
        yield p


@pytest_asyncio.fixture(scope="session")
async def browser(playwright_instance: Playwright) -> Browser:
    browser = await playwright_instance.chromium.launch(
        headless=True
    )
    yield browser
    await browser.close()


@pytest_asyncio.fixture
async def page(browser: Browser) -> Page:
    page = await browser.new_page()
    yield page
    await page.close()


@pytest_asyncio.fixture
async def healer(page: Page) -> SelfHealer:
    return SelfHealer(page)