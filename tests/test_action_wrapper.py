"""
tests/test_action_wrapper.py

Unit and integration tests for engine/action_wrapper.py.

Verifies:
  - ActionResult shape
  - page_title is captured
  - html is captured on failure only
  - screenshot_path is a string in the result
  - JSON serialisability of results
  - supported actions succeed and fail gracefully

Run:
    pytest -q tests/test_action_wrapper.py
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from engine.action_wrapper import ActionWrapper

BASE_URL = "https://www.saucedemo.com"


@pytest_asyncio.fixture
async def browser_ctx():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            channel="chrome",   # 🔥 THIS IS THE FIX
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
    try:
        yield pg
    finally:
        await pg.close()


@pytest.fixture
def wrapper(page):
    return ActionWrapper(page, timeout=8_000, capture_html=True)


REQUIRED_KEYS = {
    "success",
    "action",
    "selector",
    "value",
    "url",
    "page_title",
    "html",
    "dom_excerpt",
    "error",
    "error_type",
    "traceback",
    "timestamp",
    "duration_ms",
    "screenshot_path",
    "step_name",
}


def assert_result_shape(result: dict) -> None:
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"ActionResult missing keys: {missing}"
    assert isinstance(result["success"], bool)
    assert isinstance(result["duration_ms"], float)
    assert result["duration_ms"] >= 0
    assert isinstance(result["page_title"], str)
    assert isinstance(result["screenshot_path"], str)


@pytest.mark.asyncio
async def test_navigate_success(page, wrapper):
    result = await wrapper.navigate(BASE_URL)

    assert_result_shape(result)
    assert result["success"] is True
    assert result["action"] == "navigate"
    assert "saucedemo.com" in result["url"]
    assert result["error"] == ""
    assert result["html"] == ""
    assert result["page_title"] != ""


@pytest.mark.asyncio
async def test_navigate_failure(wrapper):
    result = await wrapper.navigate("https://255.255.255.255", timeout=3_000)

    assert_result_shape(result)
    assert result["success"] is False
    assert result["action"] == "navigate"
    assert result["error"] != ""
    assert result["error_type"] != ""
    assert result["traceback"] != ""


@pytest.mark.asyncio
async def test_fill_success(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.fill(
        "#user-name",
        "standard_user",
        step_name="Username field",
    )

    assert_result_shape(result)
    assert result["success"] is True
    assert result["value"] == "standard_user"
    assert result["selector"] == "Username field"
    assert result["html"] == ""


@pytest.mark.asyncio
async def test_fill_failure_bad_selector(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.fill(
        "#does-not-exist-BROKEN",
        "anything",
        step_name="Broken input",
        timeout=2_000,
    )

    assert_result_shape(result)
    assert result["success"] is False
    assert result["action"] == "fill"
    assert result["value"] == "anything"
    assert result["error"] != ""
    assert result["error_type"] in ("TimeoutError", "Error")
    assert "<html" in result["html"].lower()
    assert "saucedemo.com" in result["url"]


@pytest.mark.asyncio
async def test_click_success(page, wrapper):
    await wrapper.navigate(BASE_URL)
    await wrapper.fill("#user-name", "standard_user")
    await wrapper.fill("#password", "secret_sauce")
    result = await wrapper.click("#login-button", step_name="Login button")

    assert_result_shape(result)
    assert result["success"] is True
    assert result["action"] == "click"


@pytest.mark.asyncio
async def test_click_failure_bad_selector(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.click("#ghost-button-BROKEN", timeout=2_000)

    assert_result_shape(result)
    assert result["success"] is False
    assert result["html"] != ""
    assert result["traceback"] != ""


@pytest.mark.asyncio
async def test_wait_for_visible_success(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.wait_for_visible(
        "#login-button",
        step_name="Login button visible",
    )

    assert_result_shape(result)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_wait_for_visible_failure(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.wait_for_visible("#phantom-BROKEN", timeout=2_000)

    assert_result_shape(result)
    assert result["success"] is False
    assert "<html" in result["html"].lower()


@pytest.mark.asyncio
async def test_hover_success(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.hover("#login-button")

    assert_result_shape(result)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_press_tab(page, wrapper):
    await wrapper.navigate(BASE_URL)
    await page.focus("#user-name")
    result = await wrapper.press(
        "#user-name",
        "Tab",
        step_name="Tab from username",
    )

    assert_result_shape(result)
    assert result["success"] is True
    assert result["value"] == "Tab"


@pytest.mark.asyncio
async def test_click_locator(page, wrapper):
    await wrapper.navigate(BASE_URL)
    await wrapper.fill("#user-name", "standard_user")
    await wrapper.fill("#password", "secret_sauce")
    locator = page.locator("#login-button")
    result = await wrapper.click_locator(locator, step_name="Login via locator obj")

    assert_result_shape(result)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_fill_locator(page, wrapper):
    await wrapper.navigate(BASE_URL)
    locator = page.get_by_placeholder("Username")
    result = await wrapper.fill_locator(
        locator,
        "standard_user",
        step_name="Username via locator obj",
    )

    assert_result_shape(result)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_success_result_is_json_serialisable(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.wait_for_visible("#user-name")

    assert result["success"] is True
    dumped = json.dumps(result)
    reloaded = json.loads(dumped)
    assert reloaded["success"] is True
    assert "page_title" in reloaded


@pytest.mark.asyncio
async def test_failure_result_is_json_serialisable(page, wrapper):
    await wrapper.navigate(BASE_URL)
    result = await wrapper.click("#totally-fake-BROKEN", timeout=1_500)

    assert result["success"] is False
    dumped = json.dumps(result)
    reloaded = json.loads(dumped)
    assert reloaded["success"] is False
    assert reloaded["html"] != ""
    assert "screenshot_path" in reloaded