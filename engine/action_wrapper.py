"""
engine/action_wrapper.py

Wraps Playwright page actions with structured error capture.

Every method returns an ActionResult dict — never raises — so callers can
inspect the failure details and decide how to respond.

Supported actions
-----------------
    click, fill, select_option, check, hover, press, wait_for_visible, navigate

ActionResult keys
-----------------
    success          bool    — True when the action completed without error
    action           str     — action name
    selector         str     — raw selector / locator description
    value            Any     — value for fill/select (None for others)
    url              str     — page URL at time of call
    page_title       str     — page title at time of call
    html             str     — full page HTML (on failure only; "" on success)
    dom_excerpt      str     — first 2000 chars of HTML (on failure only)
    error            str     — human-readable error message ("" on success)
    error_type       str     — exception class name ("" on success)
    traceback        str     — full traceback ("" on success)
    timestamp        str     — ISO-8601 UTC
    duration_ms      float   — wall-clock time in milliseconds
    screenshot_path  str     — path to screenshot file ("" if not captured)
    step_name        str     — optional human label for the step
"""

from __future__ import annotations

import os
import time
import traceback as tb
from datetime import datetime, timezone
from typing import Any, Optional

from playwright.async_api import (
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PWTimeout,
)

import config

# ---------------------------------------------------------------------------
# ActionResult
# ---------------------------------------------------------------------------

ActionResult = dict  # typed alias — all values are JSON-serialisable


def _ok(
    action: str,
    selector: str,
    value: Any,
    url: str,
    title: str,
    duration_ms: float,
    step_name: str = "",
    screenshot_path: str = "",
) -> ActionResult:
    return {
        "success":         True,
        "action":          action,
        "selector":        selector,
        "value":           value,
        "url":             url,
        "page_title":      title,
        "html":            "",
        "dom_excerpt":     "",
        "error":           "",
        "error_type":      "",
        "traceback":       "",
        "timestamp":       _utc_now(),
        "duration_ms":     round(duration_ms, 2),
        "screenshot_path": screenshot_path,
        "step_name":       step_name,
    }


def _fail(
    action: str,
    selector: str,
    value: Any,
    url: str,
    title: str,
    html: str,
    exc: Exception,
    duration_ms: float,
    step_name: str = "",
    screenshot_path: str = "",
) -> ActionResult:
    return {
        "success":         False,
        "action":          action,
        "selector":        selector,
        "value":           value,
        "url":             url,
        "page_title":      title,
        "html":            html,
        "dom_excerpt":     html[:2000] if html else "",
        "error":           str(exc),
        "error_type":      type(exc).__name__,
        "traceback":       tb.format_exc(),
        "timestamp":       _utc_now(),
        "duration_ms":     round(duration_ms, 2),
        "screenshot_path": screenshot_path,
        "step_name":       step_name,
    }


# ---------------------------------------------------------------------------
# ActionWrapper
# ---------------------------------------------------------------------------

class ActionWrapper:
    """
    Wraps Playwright page actions with structured error capture.

    Parameters
    ----------
    page
        Playwright Page object.
    timeout
        Default timeout in ms for every action.
    capture_html
        When True (default), captures page.content() on failure.
    """

    def __init__(
        self,
        page: Page,
        timeout: int = config.DEFAULT_TIMEOUT,
        capture_html: bool = True,
    ) -> None:
        self.page = page
        self.timeout = timeout
        self.capture_html = capture_html

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    async def click(
        self,
        selector: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
        force: bool = False,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.click(timeout=t, force=force)
            return _ok("click", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "click")
            return _fail("click", label, None, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def fill(
        self,
        selector: str,
        value: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
        clear_first: bool = True,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            loc = self.page.locator(selector).first
            if clear_first:
                await loc.clear(timeout=t)
            await loc.fill(value, timeout=t)
            return _ok("fill", label, value, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "fill")
            return _fail("fill", label, value, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def select_option(
        self,
        selector: str,
        value: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.select_option(value, timeout=t)
            return _ok("select_option", label, value, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "select_option")
            return _fail("select_option", label, value, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def check(
        self,
        selector: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.check(timeout=t)
            return _ok("check", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "check")
            return _fail("check", label, None, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def hover(
        self,
        selector: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.hover(timeout=t)
            return _ok("hover", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "hover")
            return _fail("hover", label, None, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def press(
        self,
        selector: str,
        key: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.press(key, timeout=t)
            return _ok("press", label, key, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "press")
            return _fail("press", label, key, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def wait_for_visible(
        self,
        selector: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or selector
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.locator(selector).first.wait_for(state="visible", timeout=t)
            return _ok("wait_for_visible", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(selector, "wait_for_visible")
            return _fail("wait_for_visible", label, None, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def navigate(
        self,
        url: str,
        *,
        step_name: str = "",
        timeout: Optional[int] = None,
    ) -> ActionResult:
        label = step_name or url
        t = timeout or self.timeout
        start = _now()
        try:
            await self.page.goto(url, timeout=t)
            return _ok("navigate", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url_ctx = self.page.url
            title = await self._title()
            html = await self._html()
            shot = await self._screenshot(url, "navigate")
            return _fail("navigate", label, None, url_ctx, title, html, exc,
                         _elapsed(start), label, shot)

    # ------------------------------------------------------------------
    # Locator-based overloads
    # ------------------------------------------------------------------

    async def click_locator(
        self, locator: Locator, *, step_name: str = ""
    ) -> ActionResult:
        label = step_name or repr(locator)
        start = _now()
        try:
            await locator.click(timeout=self.timeout)
            return _ok("click", label, None, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(label, "click")
            return _fail("click", label, None, url, title, html, exc,
                         _elapsed(start), label, shot)

    async def fill_locator(
        self, locator: Locator, value: str, *, step_name: str = ""
    ) -> ActionResult:
        label = step_name or repr(locator)
        start = _now()
        try:
            await locator.clear(timeout=self.timeout)
            await locator.fill(value, timeout=self.timeout)
            return _ok("fill", label, value, self.page.url,
                       await self._title(), _elapsed(start), label)
        except (PWTimeout, PlaywrightError, Exception) as exc:
            url, title, html, shot = await self._fail_ctx(label, "fill")
            return _fail("fill", label, value, url, title, html, exc,
                         _elapsed(start), label, shot)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _title(self) -> str:
        try:
            return await self.page.title()
        except Exception:
            return ""

    async def _html(self) -> str:
        if not self.capture_html:
            return ""
        try:
            return await self.page.content()
        except Exception:
            return ""

    async def _screenshot(self, selector: str, action: str) -> str:
        if not config.CAPTURE_SCREENSHOT_ON_FAILURE:
            return ""
        try:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            safe = "".join(c if c.isalnum() else "_" for c in selector)[:40]
            path = os.path.join(config.LOG_DIR, f"fail_{action}_{safe}_{ts}.png")
            await self.page.screenshot(path=path, full_page=False)
            return path
        except Exception:
            return ""

    async def _fail_ctx(
        self, selector: str, action: str
    ) -> tuple[str, str, str, str]:
        """Return (url, title, html, screenshot_path) for a failure context."""
        url   = self.page.url
        title = await self._title()
        html  = await self._html()
        shot  = await self._screenshot(selector, action)
        return url, title, html, shot


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.perf_counter()


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
