"""
run_tests.py

Self-healing test runner.

Reads test cases from a JSON file, runs each step through SelfHealer,
logs per-step outcomes to logs/results.json, then prints a summary with
success rate and average repair time.

Usage
-----
    python run_tests.py                              # default: data/test_cases.json
    python run_tests.py --cases my_cases.json
    python run_tests.py --headless false --browser firefox
    python run_tests.py --clear-log                  # wipe previous results first

Test-case JSON format (array of objects)
-----------------------------------------
    [
      {
        "name": "Login flow",
        "url":  "https://example.com",
        "steps": [
          { "action": "expect_visible", "selector": "h1",            "description": "Heading" },
          { "action": "fill",           "selector": "#email",         "description": "Email",  "value": "user@test.com" },
          { "action": "click",          "selector": "#submit-button", "description": "Submit" }
        ]
      }
    ]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from playwright.async_api import async_playwright

import config
from engine.self_healer import HealingResult, SelfHealer
from llm.llm_client import LLMClient
from logger.results_logger import ResultsLogger, TestRecord


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

async def run_cases(
    cases: list[dict],
    *,
    headless: bool,
    browser_name: str,
    results_logger: ResultsLogger,
) -> list[dict]:
    """
    Execute every step in every test case.

    Returns a flat list of step-level summary dicts used for the final report.
    Side-effect: appends a TestRecord to *results_logger* for each step.
    """
    summaries: list[dict] = []

    async with async_playwright() as pw:
        launcher = getattr(pw, browser_name)
        browser = await launcher.launch(headless=headless, slow_mo=config.SLOW_MO)
        context = await browser.new_context()
        llm = LLMClient()

        for case_idx, case in enumerate(cases):
            case_name: str = case.get("name", f"case_{case_idx}")
            url: str = case.get("url", "")
            steps: list[dict] = case.get("steps", [])

            print(f"\n[{case_idx + 1}/{len(cases)}] {case_name}")
            print(f"  URL: {url}")

            page = await context.new_page()

            # ---- navigation ------------------------------------------------
            try:
                await page.goto(url, timeout=config.DEFAULT_TIMEOUT * 3)
            except Exception as exc:
                msg = f"  Navigation failed: {exc}"
                print(msg)
                record = TestRecord(
                    test_id=case_name,
                    original_failed=True,
                    healed=False,
                    repair_time=0.0,
                    locator_before=url,
                    locator_after=None,
                )
                results_logger.log(record)
                summaries.append(_nav_failure_summary(case_name, url, str(exc)))
                await page.close()
                continue

            # ---- steps -----------------------------------------------------
            healer = SelfHealer(page, llm)
            case_passed = True

            for step_idx, step in enumerate(steps):
                action: str = step.get("action", "")
                selector: str = step.get("selector", "")
                value: str = step.get("value", "")
                description: str = step.get("description", selector)
                test_id = f"{case_name}::{step_idx}::{description}"

                print(f"  step {step_idx}: [{action}] {description!r}  ({selector})", end="  ", flush=True)

                t0 = time.perf_counter()

                try:
                    hr = await _run_step(healer, action, selector, value, description)
                except Exception as exc:
                    elapsed = time.perf_counter() - t0
                    print(f"ERROR ({exc})")
                    record = TestRecord(
                        test_id=test_id,
                        original_failed=True,
                        healed=False,
                        repair_time=round(elapsed, 4),
                        locator_before=selector,
                        locator_after=None,
                    )
                    results_logger.log(record)
                    summaries.append({
                        "test_id": test_id,
                        "case": case_name,
                        "success": False,
                        "original_failed": True,
                        "healed": False,
                        "repair_time": round(elapsed, 4),
                        "locator_before": selector,
                        "locator_after": None,
                        "error": str(exc),
                    })
                    case_passed = False
                    break

                elapsed = time.perf_counter() - t0

                if action not in ("click", "fill", "expect_visible"):
                    print(f"SKIP (unknown action)")
                    continue

                # Determine whether original locator worked or healing was needed.
                # SelfHealer sets source="" on first-try success, and
                # "heuristic"/"llm"/"failed" otherwise.
                original_failed: bool = hr.source != ""
                healed: bool = hr.success and hr.source in ("heuristic", "llm")
                repair_time: float = round(elapsed, 4) if original_failed else 0.0
                locator_after: str | None = (
                    hr.healed_selector if healed
                    else (selector if hr.success else None)
                )

                status_tag = (
                    "PASS"         if hr.success and not original_failed else
                    "HEALED"       if healed else
                    "FAIL"
                )
                heal_info = f" → {hr.healed_selector}" if healed else ""
                print(f"{status_tag}{heal_info}  ({repair_time:.3f}s)")

                record = TestRecord(
                    test_id=test_id,
                    original_failed=original_failed,
                    healed=healed,
                    repair_time=repair_time,
                    locator_before=selector,
                    locator_after=locator_after,
                )
                results_logger.log(record)

                summaries.append({
                    "test_id": test_id,
                    "case": case_name,
                    "success": hr.success,
                    "original_failed": original_failed,
                    "healed": healed,
                    "repair_time": repair_time,
                    "locator_before": selector,
                    "locator_after": locator_after,
                })

                if not hr.success:
                    case_passed = False
                    break  # stop remaining steps on first failure

            outcome = "PASSED" if case_passed else "FAILED"
            print(f"  → Case {outcome}")
            await page.close()

        await browser.close()

    return summaries


async def _run_step(
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
    # Return a dummy failed result for unknown actions.
    return HealingResult(original_selector=selector, source="failed", success=False)


def _nav_failure_summary(case_name: str, url: str, error: str) -> dict:
    return {
        "test_id": case_name,
        "case": case_name,
        "success": False,
        "original_failed": True,
        "healed": False,
        "repair_time": 0.0,
        "locator_before": url,
        "locator_after": None,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(summaries: list[dict], results_path: str, elapsed_total: float) -> None:
    total = len(summaries)
    passed = sum(1 for s in summaries if s.get("success", False))
    failed = total - passed
    healed = sum(1 for s in summaries if s.get("healed", False))

    repair_times = [
        s["repair_time"]
        for s in summaries
        if s.get("original_failed") and s["repair_time"] > 0
    ]
    avg_repair = round(sum(repair_times) / len(repair_times), 4) if repair_times else 0.0
    success_rate = round(passed / total * 100, 1) if total else 0.0

    # Unique case count
    cases = list(dict.fromkeys(s["case"] for s in summaries))
    cases_passed = sum(
        1 for c in cases
        if all(s.get("success", False) for s in summaries if s["case"] == c)
    )

    sep = "=" * 66
    print(f"\n{sep}")
    print("  SELF-HEALING TEST SUITE — RESULTS")
    print(sep)
    print(f"  Test cases     : {len(cases)}  ({cases_passed} passed, {len(cases) - cases_passed} failed)")
    print(f"  Steps total    : {total}")
    print(f"  Steps passed   : {passed}")
    print(f"  Steps failed   : {failed}")
    print(f"  Steps healed   : {healed}")
    print(f"  Success rate   : {success_rate}%  (step-level)")
    print(f"  Avg repair time: {avg_repair}s")
    print(f"  Total wall time: {elapsed_total:.2f}s")
    print(f"  Log saved to   : {results_path}")
    print(sep)

    if not summaries:
        return

    id_col = min(max(len(s["test_id"]) for s in summaries), 52)
    header = f"  {'TEST ID':<{id_col}}  {'RESULT':>6}  {'HEALED':>6}  {'REPAIR(s)':>9}"
    print(header)
    print("  " + "-" * (id_col + 27))

    for s in summaries:
        tid = s["test_id"]
        if len(tid) > id_col:
            tid = tid[: id_col - 1] + "…"
        result_tag = "PASS" if s.get("success") else "FAIL"
        heal_tag   = "YES" if s.get("healed") else "-"
        rt = f"{s['repair_time']:.4f}" if s.get("original_failed") and s["repair_time"] > 0 else "     -"
        print(f"  {tid:<{id_col}}  {result_tag:>6}  {heal_tag:>6}  {rt:>9}")

    print(sep + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run self-healing UI tests and log results to logs/results.json"
    )
    p.add_argument(
        "--cases",
        default=os.path.join(config.DATA_DIR, "test_cases.json"),
        metavar="PATH",
        help="JSON file with test cases (default: data/test_cases.json)",
    )
    p.add_argument(
        "--headless",
        default=str(config.HEADLESS),
        metavar="BOOL",
        help="Run browser headlessly: true|false  (default: %(default)s)",
    )
    p.add_argument(
        "--browser",
        default=config.BROWSER,
        choices=["chromium", "firefox", "webkit"],
        help="Browser engine (default: %(default)s)",
    )
    p.add_argument(
        "--clear-log",
        action="store_true",
        help="Wipe logs/results.json before this run",
    )
    return p.parse_args()


def load_cases(path: str) -> list[dict]:
    if not os.path.exists(path):
        print(f"[ERROR] Test cases file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print("[ERROR] Test cases file must contain a JSON array at the top level.", file=sys.stderr)
        sys.exit(1)
    return data


async def main() -> None:
    args = parse_args()
    headless = args.headless.lower() not in ("false", "0", "no")

    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} test case(s) from: {args.cases}")

    results_logger = ResultsLogger()

    if args.clear_log:
        results_logger.clear()
        print(f"Cleared previous results log: {results_logger.path}")

    print(f"Browser: {args.browser}  |  Headless: {headless}\n")

    t_start = time.perf_counter()
    summaries = await run_cases(
        cases,
        headless=headless,
        browser_name=args.browser,
        results_logger=results_logger,
    )
    elapsed = time.perf_counter() - t_start

    print_summary(summaries, results_logger.path, elapsed)


if __name__ == "__main__":
    asyncio.run(main())
