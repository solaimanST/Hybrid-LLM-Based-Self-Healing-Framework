"""
Tests for dom/dom_extractor.py

Covers extract_dom() (pure HTML string) and extract_dom_from_page()
(live Playwright page). Also verifies the element cap and selector
generation logic.

Run:
    pytest tests/test_dom_extractor.py -v -s
"""

import json
import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from dom.dom_extractor import extract_dom, extract_dom_from_page, INTERACTIVE_TAGS

# ---------------------------------------------------------------------------
# Static HTML fixtures
# ---------------------------------------------------------------------------

SIMPLE_HTML = """
<html><body>
  <form>
    <input id="email" name="email" type="email" placeholder="Email address" required>
    <input id="pass"  name="password" type="password" placeholder="Password">
    <select id="role" name="role" aria-label="User role">
      <option value="admin">Admin</option>
    </select>
    <textarea id="bio" name="bio" placeholder="Tell us about yourself"></textarea>
    <button type="submit" data-testid="submit-btn">Sign in</button>
    <a href="/forgot" aria-label="Forgot password">Forgot password?</a>
  </form>
</body></html>
"""

HIDDEN_HTML = """
<html><body>
  <input id="visible-input" name="q" type="text" placeholder="Search">
  <input id="hidden-style"  name="h" type="text" style="display:none">
  <button style="visibility:hidden">Invisible</button>
  <script>var x = 1;</script>
  <button id="real-btn">Click me</button>
</body></html>
"""

LARGE_HTML_BUTTON_COUNT = 250


def make_large_html(n: int) -> str:
    buttons = "\n".join(f'<button id="btn-{i}">Button {i}</button>' for i in range(n))
    return f"<html><body>{buttons}</body></html>"


# ---------------------------------------------------------------------------
# extract_dom() — static HTML
# ---------------------------------------------------------------------------

class TestExtractDom:

    def test_returns_list_of_dicts(self):
        result = extract_dom(SIMPLE_HTML)
        assert isinstance(result, list)
        assert all(isinstance(el, dict) for el in result)

    def test_only_interactive_tags_included(self):
        result = extract_dom(SIMPLE_HTML)
        tags_found = {el["tag"] for el in result}
        assert tags_found <= INTERACTIVE_TAGS

    def test_correct_element_count(self):
        result = extract_dom(SIMPLE_HTML)
        # 6 interactive elements in SIMPLE_HTML
        assert len(result) == 6

    def test_required_keys_present(self):
        required = {
            "index", "tag", "id", "class", "name", "type", "role",
            "aria-label", "placeholder", "value", "href",
            "disabled", "required", "checked", "readonly",
            "text", "css_selector",
        }
        result = extract_dom(SIMPLE_HTML)
        for el in result:
            assert required <= el.keys(), f"Missing keys in {el}"

    def test_index_is_sequential(self):
        result = extract_dom(SIMPLE_HTML)
        assert [el["index"] for el in result] == list(range(len(result)))

    def test_attribute_values_extracted_correctly(self):
        result = extract_dom(SIMPLE_HTML)
        email_input = next(el for el in result if el["id"] == "email")

        assert email_input["tag"] == "input"
        assert email_input["name"] == "email"
        assert email_input["type"] == "email"
        assert email_input["placeholder"] == "Email address"
        assert email_input["required"] is True
        assert email_input["disabled"] is False

    def test_boolean_attrs_false_when_absent(self):
        result = extract_dom(SIMPLE_HTML)
        btn = next(el for el in result if el["tag"] == "button")
        assert btn["disabled"] is False
        assert btn["checked"] is False
        assert btn["readonly"] is False

    def test_text_extracted(self):
        result = extract_dom(SIMPLE_HTML)
        btn = next(el for el in result if el["tag"] == "button")
        assert "Sign in" in btn["text"]

    def test_href_on_anchor(self):
        result = extract_dom(SIMPLE_HTML)
        link = next(el for el in result if el["tag"] == "a")
        assert link["href"] == "/forgot"
        assert link["aria-label"] == "Forgot password"

    def test_data_testid_captured(self):
        result = extract_dom(SIMPLE_HTML)
        btn = next(el for el in result if el.get("data-testid") == "submit-btn")
        assert btn is not None

    def test_none_for_missing_optional_attrs(self):
        result = extract_dom(SIMPLE_HTML)
        email_input = next(el for el in result if el["id"] == "email")
        assert email_input["role"] is None
        assert email_input["href"] is None

    def test_cap_at_max_elements(self):
        html = make_large_html(LARGE_HTML_BUTTON_COUNT)
        result = extract_dom(html, max_elements=200)
        assert len(result) == 200

    def test_custom_max_elements(self):
        html = make_large_html(50)
        result = extract_dom(html, max_elements=10)
        assert len(result) == 10

    def test_hidden_elements_excluded(self):
        result = extract_dom(HIDDEN_HTML)
        ids = [el["id"] for el in result if el.get("id")]
        assert "hidden-style" not in ids
        # display:none button also excluded
        texts = [el["text"] for el in result]
        assert not any("Invisible" in t for t in texts)

    def test_visible_elements_kept(self):
        result = extract_dom(HIDDEN_HTML)
        ids = [el["id"] for el in result if el.get("id")]
        assert "visible-input" in ids
        assert "real-btn" in ids

    def test_result_is_json_serialisable(self):
        result = extract_dom(SIMPLE_HTML)
        dumped = json.dumps(result)
        reloaded = json.loads(dumped)
        assert len(reloaded) == len(result)

    def test_include_tags_filter(self):
        result = extract_dom(SIMPLE_HTML, include_tags=frozenset({"button"}))
        assert all(el["tag"] == "button" for el in result)
        assert len(result) == 1

    def test_extra_attrs_captured(self):
        html = '<html><body><button data-track="cta-click">Buy</button></body></html>'
        result = extract_dom(html, extra_attrs=["data-track"])
        assert result[0]["data-track"] == "cta-click"

    def test_empty_html_returns_empty_list(self):
        assert extract_dom("<html><body></body></html>") == []

    def test_text_truncated_at_200_chars(self):
        long_text = "x" * 300
        html = f"<html><body><button>{long_text}</button></body></html>"
        result = extract_dom(html)
        assert len(result[0]["text"]) <= 201   # 200 + "…"
        assert result[0]["text"].endswith("…")


# ---------------------------------------------------------------------------
# CSS selector generation
# ---------------------------------------------------------------------------

class TestCssSelector:

    def test_id_selector_preferred(self):
        result = extract_dom(SIMPLE_HTML)
        email = next(el for el in result if el["id"] == "email")
        assert email["css_selector"] == "#email"

    def test_data_testid_selector(self):
        html = '<html><body><button data-testid="my-btn">Go</button></body></html>'
        result = extract_dom(html)
        assert result[0]["css_selector"] == '[data-testid="my-btn"]'

    def test_name_selector_fallback(self):
        html = '<html><body><input name="query" type="text"></body></html>'
        result = extract_dom(html)
        assert result[0]["css_selector"] == 'input[name="query"]'

    def test_tag_type_class_fallback(self):
        html = '<html><body><button type="submit" class="btn primary">OK</button></body></html>'
        result = extract_dom(html)
        assert "button" in result[0]["css_selector"]


# ---------------------------------------------------------------------------
# extract_dom_from_page() — live Playwright
# ---------------------------------------------------------------------------

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


@pytest.mark.asyncio
async def test_extract_dom_from_page_saucedemo(page):
    await page.goto("https://www.saucedemo.com")
    result = await extract_dom_from_page(page)

    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(el, dict) for el in result)

    # Saucedemo login form has username input, password input, login button
    ids = [el.get("id") for el in result]
    assert "user-name" in ids
    assert "password" in ids
    assert "login-button" in ids

    print(f"\n[saucedemo] extracted {len(result)} elements")
    for el in result:
        print(
            f"  [{el['index']:02d}] <{el['tag']}> "
            f"id={el['id']!r:20} "
            f"name={el['name']!r:20} "
            f"css={el['css_selector']!r:30} "
            f"text={el['text'][:40]!r}"
        )


@pytest.mark.asyncio
async def test_extract_dom_from_page_max_elements(page):
    await page.goto("https://www.saucedemo.com")
    result = await extract_dom_from_page(page, max_elements=2)
    assert len(result) <= 2


@pytest.mark.asyncio
async def test_extract_dom_result_json_serialisable(page):
    await page.goto("https://www.saucedemo.com")
    result = await extract_dom_from_page(page)
    dumped = json.dumps(result)          # must not raise
    assert len(json.loads(dumped)) == len(result)
