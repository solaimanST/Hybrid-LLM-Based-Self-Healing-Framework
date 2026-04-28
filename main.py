"""
main.py

Entry point for the Hybrid LLM-Based Self-Healing UI Testing Framework.

Usage:
    python main.py
    python main.py --url https://www.saucedemo.com
    python main.py --mode heuristic --headless
    python main.py --browser firefox --no-headless
    python main.py --dataset data/my_cases.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console

import config
from engine.executor import TestExecutor
from validator.result_validator import ResultValidator

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hybrid LLM-Based Self-Healing UI Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="",
        help="Override target URL for all test cases",
    )
    parser.add_argument(
        "--browser",
        default=None,
        choices=["chromium", "firefox", "webkit"],
        help=f"Browser engine (default from config: {config.BROWSER})",
    )
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=None,
        help="Run browser in headless mode",
    )
    headless_group.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run browser with visible UI",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=["none", "heuristic", "llm_only", "hybrid"],
        help=f"Healing mode override (default from config: {config.HEALING_MODE})",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to JSON test cases file (default: data/test_cases.json)",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    overrides: dict = {}
    if args.browser:
        overrides["browser"] = args.browser
    if args.headless is not None:
        overrides["headless"] = args.headless
    if args.mode:
        overrides["mode"] = args.mode

    executor = TestExecutor(
        base_url=args.url,
        overrides=overrides,
        dataset=args.dataset,
    )

    console.rule("[bold cyan]Self-Healing Framework — Test Run")
    results = await executor.run_all()

    validator = ResultValidator()
    metrics = validator.summarize(results)

    return 0 if metrics["failed_tests"] == 0 else 1


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(run(args)))
