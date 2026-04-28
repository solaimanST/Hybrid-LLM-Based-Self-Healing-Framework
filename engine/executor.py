"""
engine/executor.py

Test executor — reads test cases from data/test_cases.json, runs each step
through SelfHealer, evaluates optional oracle checks, and returns structured
TestResult objects.

A step is considered a true success only when both the action succeeds AND
any oracle check passes.  A healed step that fails its oracle is counted as
a false repair.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import async_playwright

import config
from engine.self_healer import HealingResult, SelfHealer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Outcome of a single test step."""

    action: str
    selector_before: str
    selector_after: Optional[str]
    original_failed: bool
    healed: bool
    healing_source: str           # "original" | "memory" | "heuristic" | "llm" | "failed"
    repair_time_sec: float
    candidate_count: int
    winning_score: float
    passed: bool
    false_repair: bool            # healed but oracle failed
    error: str = ""
    oracle_key: str = ""
    oracle_expected: str = ""
    oracle_actual: str = ""


@dataclass
class TestResult:
    """Outcome of a single test case."""

    name: str
    app: str                      # "url" field from the test case, used as app identifier
    mode: str                     # healing mode used
    passed: bool
    healed: bool
    steps: list[StepResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class TestExecutor:
    """
    Discovers and runs all test cases from data/test_cases.json (or a
    custom path), applying the full self-healing pipeline on each step.

    Parameters
    ----------
    base_url
        Override the URL for every test case.
    overrides
        Dict of runtime overrides: browser, headless, mode.
    dataset
        Path to a JSON test-cases file.  Defaults to
        ``config.DATA_DIR/test_cases.json``.
    """

    def __init__(
        self,
        base_url: str = "",
        overrides: Optional[dict] = None,
        dataset: Optional[str] = None,
    ) -> None:
        self.base_url = base_url
        self.overrides: dict = overrides or {}
        self.dataset = dataset or os.path.join(config.DATA_DIR, "test_cases.json")
        self._setup_logging()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_all(self) -> list[TestResult]:
        cases = self._load_test_cases()
        results: list[TestResult] = []

        browser_type = self.overrides.get("browser", config.BROWSER)
        headless     = self.overrides.get("headless", config.HEADLESS)
        mode         = self.overrides.get("mode", config.HEALING_MODE)

        async with async_playwright() as pw:
            launcher = getattr(pw, browser_type)
            browser  = await launcher.launch(headless=headless, slow_mo=config.SLOW_MO)
            context  = await browser.new_context()

            for case in cases:
                page = await context.new_page()
                result = await self._run_case(page, case, mode)
                results.append(result)
                await page.close()

            await browser.close()

        return results

    # ------------------------------------------------------------------
    # Internal: case runner
    # ------------------------------------------------------------------

    async def _run_case(
        self, page: Any, case: dict, mode: str
    ) -> TestResult:
        name = case.get("name", "unnamed")
        url  = case.get("url") or self.base_url
        app  = url
        steps: list[dict] = case.get("steps", [])

        logger.info("Running test: %s", name)

        result = TestResult(name=name, app=app, mode=mode, passed=True, healed=False)

        # Navigation
        try:
            await page.goto(url, timeout=config.DEFAULT_TIMEOUT * 3)
        except Exception as exc:
            result.passed = False
            result.steps.append(StepResult(
                action="goto", selector_before=url, selector_after=None,
                original_failed=True, healed=False, healing_source="failed",
                repair_time_sec=0.0, candidate_count=0, winning_score=0.0,
                passed=False, false_repair=False, error=str(exc),
            ))
            return result

        healer = SelfHealer(page, healing_mode=mode)

        for step in steps:
            step_result = await self._run_step(healer, page, step)
            result.steps.append(step_result)

            if not step_result.passed:
                result.passed = False
                break

            if step_result.healed and not step_result.false_repair:
                result.healed = True

        return result

    # ------------------------------------------------------------------
    # Internal: step runner
    # ------------------------------------------------------------------

    async def _run_step(
        self, healer: SelfHealer, page: Any, step: dict
    ) -> StepResult:
        action      = step.get("action", "")
        selector    = step.get("selector", "")
        value       = step.get("value", "")
        description = step.get("description", selector)
        oracle      = step.get("oracle")         # optional dict

        # Execute action with healing
        try:
            hr: HealingResult = await self._dispatch(
                healer, action, selector, value, description
            )
        except Exception as exc:
            return StepResult(
                action=action, selector_before=selector, selector_after=None,
                original_failed=True, healed=False, healing_source="failed",
                repair_time_sec=0.0, candidate_count=0, winning_score=0.0,
                passed=False, false_repair=False, error=str(exc),
            )

        original_failed = hr.source != "original"
        healed          = hr.success and original_failed
        selector_after  = hr.healed_selector or (selector if hr.success else None)
        candidate_count = len(hr.candidates)

        # Oracle check
        oracle_ok, oracle_key, oracle_expected, oracle_actual = True, "", "", ""
        if hr.success and oracle:
            oracle_ok, oracle_key, oracle_expected, oracle_actual = \
                await self._check_oracle(page, oracle)

        # A healed step whose oracle fails is a false repair
        false_repair = healed and not oracle_ok

        return StepResult(
            action=action,
            selector_before=selector,
            selector_after=selector_after,
            original_failed=original_failed,
            healed=healed,
            healing_source=hr.source,
            repair_time_sec=hr.repair_time_sec,
            candidate_count=candidate_count,
            winning_score=hr.winning_score,
            passed=hr.success and oracle_ok,
            false_repair=false_repair,
            error=hr.original_error if not hr.success else (
                f"Oracle failed: {oracle_key}={oracle_actual!r} != {oracle_expected!r}"
                if not oracle_ok else ""
            ),
            oracle_key=oracle_key,
            oracle_expected=oracle_expected,
            oracle_actual=oracle_actual,
        )

    @staticmethod
    async def _dispatch(
        healer: SelfHealer,
        action: str,
        selector: str,
        value: str,
        description: str,
    ) -> HealingResult:
        if action == "click":
            return await healer.click(selector, description)
        if action == "fill":
            return await healer.fill(selector, value, description)
        if action == "expect_visible":
            return await healer.expect_visible(selector, description)
        # Unknown action — report as immediate failure
        return HealingResult(
            original_selector=selector,
            success=False,
            source="failed",
            original_error=f"Unknown action: {action!r}",
        )

    @staticmethod
    async def _check_oracle(
        page: Any, oracle: dict
    ) -> tuple[bool, str, str, str]:
        """
        Evaluate an oracle assertion.

        Supported checks:
            url_equals      — page URL must equal the value
            visible_text    — inner text of selector must contain value
            input_value     — input value must equal value

        Returns (passed, key, expected, actual).
        """
        for check_key, expected in oracle.items():
            expected_str = str(expected)
            try:
                if check_key == "url_equals":
                    actual = page.url
                    ok = actual == expected_str
                elif check_key == "url_contains":
                    actual = page.url
                    ok = expected_str in actual
                elif check_key == "visible_text":
                    # oracle value should be "selector:expected_text"
                    sel, _, text = expected_str.partition(":")
                    actual = (await page.locator(sel.strip()).first.inner_text()).strip()
                    ok = text.strip() in actual
                elif check_key == "input_value":
                    sel, _, text = expected_str.partition(":")
                    actual = await page.locator(sel.strip()).first.input_value()
                    ok = actual == text.strip()
                else:
                    logger.warning("Unknown oracle check: %r", check_key)
                    continue

                if not ok:
                    return False, check_key, expected_str, actual
            except Exception as exc:
                return False, check_key, expected_str, f"ERROR: {exc}"

        return True, "", "", ""

    # ------------------------------------------------------------------
    # Test case loading
    # ------------------------------------------------------------------

    def _load_test_cases(self) -> list[dict]:
        if not os.path.exists(self.dataset):
            logger.warning("No test cases file at %s — using built-in sample.", self.dataset)
            return self._sample_cases()
        try:
            with open(self.dataset, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                logger.error("Test cases file must be a JSON array.")
                return self._sample_cases()
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not load test cases: %s", exc)
            return self._sample_cases()

    @staticmethod
    def _sample_cases() -> list[dict]:
        return [
            {
                "name": "Example.com heading visible",
                "url":  "https://example.com",
                "steps": [
                    {
                        "action":      "expect_visible",
                        "selector":    "h1",
                        "description": "Main page heading",
                    }
                ],
            }
        ]

    @staticmethod
    def _setup_logging() -> None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        log_file = os.path.join(config.LOG_DIR, "run.log")
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(log_file, encoding="utf-8"),
            ],
        )
