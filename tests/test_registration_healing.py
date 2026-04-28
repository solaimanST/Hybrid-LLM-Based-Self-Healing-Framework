import time

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

REGISTER_URL = "https://naveenautomationlabs.com/opencart/index.php?route=account/register"


async def fill_required_registration_fields(healer: SelfHealer) -> str:
    unique_email = f"john_{int(time.time() * 1000)}@example.com"

    await healer.fill("#input-firstname", "John", "First Name")
    await healer.fill("#input-lastname", "Doe", "Last Name")
    await healer.fill("#input-email", unique_email, "Email")
    await healer.fill("#input-telephone", "01700000000", "Telephone")
    await healer.fill("#input-password", "Test12345", "Password")
    await healer.fill("#input-confirm", "Test12345", "Confirm Password")

    return unique_email


async def print_validation_messages_if_any(page: Page) -> None:
    alerts = await page.locator(".alert, .text-danger, .warning").all_inner_texts()
    if alerts:
        print("Validation messages:", alerts)


@pytest.mark.asyncio
async def test_tc1_valid_registration(page: Page, healer: SelfHealer):
    await page.goto(REGISTER_URL)

    await fill_required_registration_fields(healer)
    await healer.click("input[name='agree']", "Agree checkbox")
    await healer.click("input[value='Continue']", "Continue Button")

    await print_validation_messages_if_any(page)
    await expect(page.locator("h1")).to_have_text("Your Account Has Been Created!")


@pytest.mark.asyncio
async def test_tc2_broken_firstname_should_heal(page: Page, healer: SelfHealer):
    await page.goto(REGISTER_URL)

    result = await healer.fill("#input-firstname-BROKEN", "John", "First Name")

    assert result.success is True
    assert result.source in ["heuristic", "llm", "memory"]
    assert result.healed_selector is not None

    await expect(page.locator("#input-firstname")).to_have_value("John")


@pytest.mark.asyncio
async def test_tc3_broken_checkbox_should_heal(page: Page, healer: SelfHealer):
    await page.goto(REGISTER_URL)
    await fill_required_registration_fields(healer)

    result = await healer.click("input[name='agree-BROKEN']", "Agree checkbox")

    assert result.success is True
    assert result.healed_selector is not None
    assert await page.locator("input[name='agree']").is_checked()


@pytest.mark.asyncio
async def test_tc4_broken_submit_should_heal(page: Page, healer: SelfHealer):
    await page.goto(REGISTER_URL)
    await fill_required_registration_fields(healer)
    await healer.click("input[name='agree']", "Agree checkbox")

    result = await healer.click(".btn-primary-BROKEN", "Continue Button")

    assert result.success is True
    assert result.healed_selector is not None

    await print_validation_messages_if_any(page)
    await expect(page.locator("h1")).to_have_text("Your Account Has Been Created!")


@pytest.mark.asyncio
async def test_tc5_multiple_failures(page: Page, healer: SelfHealer):
    await page.goto(REGISTER_URL)

    r1 = await healer.fill("#input-firstname-BROKEN", "John", "First Name")
    await healer.fill("#input-lastname", "Doe", "Last Name")

    unique_email = f"john_{int(time.time() * 1000)}@example.com"
    await healer.fill("#input-email", unique_email, "Email")
    await healer.fill("#input-telephone", "01700000000", "Telephone")
    await healer.fill("#input-password", "Test12345", "Password")
    await healer.fill("#input-confirm", "Test12345", "Confirm Password")

    r2 = await healer.click("input[name='agree-BROKEN']", "Agree checkbox")
    r3 = await healer.click(".btn-primary-BROKEN", "Continue Button")

    assert r1.success is True
    assert r2.success is True
    assert r3.success is True

    await print_validation_messages_if_any(page)
    await expect(page.locator("h1")).to_have_text("Your Account Has Been Created!")