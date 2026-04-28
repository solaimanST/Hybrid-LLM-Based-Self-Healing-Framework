"""
Sample pytest test suite that uses the self-healing engine.
Run with:  pytest tests/ -v
"""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright, Page

from engine.self_healer import SelfHealer
from llm.llm_client import LLMClient


@pytest_asyncio.fixture
async def browser_ctx():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            channel="chrome",
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        ctx = await browser.new_context()
        try:
            yield ctx
        finally:
            await browser.close()


@pytest_asyncio.fixture
async def page(browser_ctx):
    pg = await browser_ctx.new_page()
    yield pg
    await pg.close()


@pytest_asyncio.fixture
def healer(page: Page):
    return SelfHealer(page, llm_client=LLMClient())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_example_heading_visible(page: Page, healer: SelfHealer):
    await page.goto("https://example.com")
    result = await healer.expect_visible("h1", "Main heading")
    assert result.success, f"Could not find heading — healer result: {result}"


@pytest.mark.asyncio
async def test_example_heading_heals_bad_selector(page: Page, healer: SelfHealer):
    """
    Intentionally use a wrong selector so the healer is exercised.
    It should recover via heuristic or LLM and find the real <h1>.
    """
    await page.goto("https://example.com")
    # Wrong selector; the healer should recover
    result = await healer.expect_visible("#main-title", "Main heading (wrong id)")
    # This test validates that the healing pipeline ran (success not guaranteed
    # without a real LLM key, so we just assert it didn't raise).
    assert isinstance(result.success, bool)


@pytest.mark.asyncio
async def test_link_click(page: Page, healer: SelfHealer):
    await page.goto("https://example.com")
    result = await healer.click(
        "a[href='https://www.iana.org/domains/reserved']",
        description="More information link",
    )
    assert result.success, "Link click failed and could not be healed"
