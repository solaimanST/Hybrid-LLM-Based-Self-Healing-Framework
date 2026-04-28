"""
tests/ecommerce_suite/test_sorting.py

Product sort dropdown tests — selecting sort options and verifying item order.
Tests T_EC17–T_EC20 (4 normal / 4 broken pairs).

Covers: class_changed, attribute_removed, nearby_sibling_added, dom_position_changed.
Break targets: select[data-test='product-sort-container'].
Sort options: 'az' (A-Z), 'za' (Z-A), 'lohi' (price low→high), 'hilo' (price high→low).

Target site: https://www.saucedemo.com (inventory page, requires login)
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from engine.self_healer import SelfHealer

BASE_URL = "https://www.saucedemo.com"
_SORT_SELECTOR = "select[data-test='product-sort-container']"


def _parse_price(text: str) -> float:
    return float(text.strip().lstrip("$"))


# ---------------------------------------------------------------------------
# T_EC17 — Sort Z-A: class_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC17_sort_za_normal(page_at_inventory: Page) -> None:
    """Normal: select 'za' on sort dropdown, first item name > last item name."""
    dropdown = page_at_inventory.locator(_SORT_SELECTOR)
    await expect(dropdown).to_be_visible()
    await dropdown.select_option("za")

    names = page_at_inventory.locator(".inventory_item_name")
    count = await names.count()
    assert count > 1
    first = (await names.nth(0).inner_text()).strip()
    last = (await names.nth(count - 1).inner_text()).strip()
    assert first > last, f"Z-A sort failed: '{first}' should be > '{last}'"


@pytest.mark.asyncio
async def test_T_EC17_sort_za_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : class_changed  (.product_sort_container → .sort-select-RENAMED)
    Original      : select[data-test='product-sort-container']
    Broken        : select.sort-select-RENAMED
    Expected heal : select[data-test='product-sort-container']  or  select.product_sort_container
    Research note : CSS class renames during utility-class migrations remove
                    the old BEM class from the select element. Tests data-test
                    attribute fallback and select-element role heuristics.
                    Sort result verified by comparing first and last product names.
    """
    result = await healer_hybrid.select_option(
        "select.sort-select-RENAMED",
        "za",
        description="Product sort order dropdown on inventory page",
    )
    assert result.success, (
        f"Sort dropdown class-changed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}

    names = page_at_inventory.locator(".inventory_item_name")
    count = await names.count()
    first = (await names.nth(0).inner_text()).strip()
    last = (await names.nth(count - 1).inner_text()).strip()
    assert first > last, f"Z-A sort (healed) failed: '{first}' should be > '{last}'"


# ---------------------------------------------------------------------------
# T_EC18 — Sort A-Z default verify: attribute_removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC18_sort_az_normal(page_at_inventory: Page) -> None:
    """Normal: select 'az', first item name alphabetically precedes last."""
    dropdown = page_at_inventory.locator(_SORT_SELECTOR)
    await dropdown.select_option("az")

    names = page_at_inventory.locator(".inventory_item_name")
    count = await names.count()
    assert count > 1
    first = (await names.nth(0).inner_text()).strip()
    last = (await names.nth(count - 1).inner_text()).strip()
    assert first < last, f"A-Z sort failed: '{first}' should be < '{last}'"


@pytest.mark.asyncio
async def test_T_EC18_sort_az_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : attribute_removed  (data-test removed from sort select)
    Original      : select[data-test='product-sort-container']
    Broken        : select[data-test='sort-ATTR-REMOVED']
    Expected heal : select.product_sort_container  or  select[class*='sort']
    Research note : data-test removal from interactive widgets is a common
                    production-build optimisation. The select element retains
                    a class-based identifier. Tests class-fragment and select-
                    tag heuristics for recovery without the data-test attribute.
                    Sort result verified by alphabetical name comparison.
    """
    result = await healer_hybrid.select_option(
        "select[data-test='sort-ATTR-REMOVED']",
        "az",
        description="Product sort dropdown — data-test attribute removed in production build",
    )
    assert result.success, (
        f"Sort dropdown attribute-removed healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}

    names = page_at_inventory.locator(".inventory_item_name")
    count = await names.count()
    first = (await names.nth(0).inner_text()).strip()
    last = (await names.nth(count - 1).inner_text()).strip()
    assert first < last, f"A-Z sort (healed) failed: '{first}' should be < '{last}'"


# ---------------------------------------------------------------------------
# T_EC19 — Sort price high-to-low: nearby_sibling_added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC19_sort_price_hilo_normal(page_at_inventory: Page) -> None:
    """Normal: sort 'hilo', first product price is >= last product price."""
    dropdown = page_at_inventory.locator(_SORT_SELECTOR)
    await dropdown.select_option("hilo")

    prices = page_at_inventory.locator(".inventory_item_price")
    count = await prices.count()
    assert count > 1
    first_price = _parse_price(await prices.nth(0).inner_text())
    last_price = _parse_price(await prices.nth(count - 1).inner_text())
    assert first_price >= last_price, (
        f"High-to-low sort failed: first=${first_price:.2f} < last=${last_price:.2f}"
    )


@pytest.mark.asyncio
async def test_T_EC19_sort_price_hilo_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : nearby_sibling_added
    Original      : select[data-test='product-sort-container']
    Broken        : .subheader-inner > .sort-wrapper-EXTRA > select.sort-dropdown-SIBLING
    Expected heal : select[data-test='product-sort-container']  or  select.product_sort_container
    Research note : A new .sort-wrapper-EXTRA container inserted adjacent to the
                    subheader title changes the ancestor path to the select element.
                    The broken selector resolves to an element that does not exist.
                    Tests class-fragment and data-test heuristics that match the
                    select regardless of changed ancestor structure.
    """
    result = await healer_hybrid.select_option(
        ".subheader-inner > .sort-wrapper-EXTRA > select.sort-dropdown-SIBLING",
        "hilo",
        description="Price sort dropdown — new sibling wrapper inserted in subheader",
    )
    assert result.success, (
        f"Sort dropdown nearby-sibling healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}

    prices = page_at_inventory.locator(".inventory_item_price")
    count = await prices.count()
    first_price = _parse_price(await prices.nth(0).inner_text())
    last_price = _parse_price(await prices.nth(count - 1).inner_text())
    assert first_price >= last_price, (
        f"High-to-low sort (healed) failed: first=${first_price:.2f} < last=${last_price:.2f}"
    )


# ---------------------------------------------------------------------------
# T_EC20 — Sort price low-to-high: dom_position_changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_EC20_sort_price_lohi_normal(page_at_inventory: Page) -> None:
    """Normal: sort 'lohi', first product price is <= last product price."""
    dropdown = page_at_inventory.locator(_SORT_SELECTOR)
    await dropdown.select_option("lohi")

    prices = page_at_inventory.locator(".inventory_item_price")
    count = await prices.count()
    assert count > 1
    first_price = _parse_price(await prices.nth(0).inner_text())
    last_price = _parse_price(await prices.nth(count - 1).inner_text())
    assert first_price <= last_price, (
        f"Low-to-high sort failed: first=${first_price:.2f} > last=${last_price:.2f}"
    )


@pytest.mark.asyncio
async def test_T_EC20_sort_price_lohi_broken(
    page_at_inventory: Page, healer_hybrid: SelfHealer
) -> None:
    """
    Break type    : dom_position_changed
    Original      : select[data-test='product-sort-container']  (child of .right_component)
    Broken        : .header-secondary-container > .sort-container-MOVED > select
    Expected heal : select[data-test='product-sort-container']  or  select.product_sort_container
    Research note : Header secondary container restructuring moves the sort select
                    into a new .sort-container-MOVED div. '.header-secondary-container'
                    (hyphen) also does not match the real '.header_secondary_container'
                    (underscore), so both the ancestor and intermediate node fail.
                    Tests data-test and tag-plus-class heuristics for a standalone
                    select element in the inventory toolbar.
    """
    result = await healer_hybrid.select_option(
        ".header-secondary-container > .sort-container-MOVED > select",
        "lohi",
        description="Product sort dropdown moved into new sort-container in header",
    )
    assert result.success, (
        f"Sort dropdown dom-position healing failed — "
        f"source={result.source}, error={result.original_error}"
    )
    assert result.healed_selector is not None
    assert result.source in {"heuristic", "llm", "memory"}

    prices = page_at_inventory.locator(".inventory_item_price")
    count = await prices.count()
    first_price = _parse_price(await prices.nth(0).inner_text())
    last_price = _parse_price(await prices.nth(count - 1).inner_text())
    assert first_price <= last_price, (
        f"Low-to-high sort (healed) failed: first=${first_price:.2f} > last=${last_price:.2f}"
    )
