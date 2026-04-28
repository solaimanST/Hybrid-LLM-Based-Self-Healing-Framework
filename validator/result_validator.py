"""
validator/result_validator.py

Summarises test results across all modes and test cases, writes detailed
JSON reports, and prints a readable console table via rich.

Distinguishes between:
  - genuinely successful repairs (healed + oracle passed)
  - false repairs (healed but oracle failed)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.table import Table

import config

if TYPE_CHECKING:
    from engine.executor import StepResult, TestResult

logger = logging.getLogger(__name__)
console = Console()


class ResultValidator:
    """
    Aggregates TestResult objects, computes summary metrics, and writes reports.
    """

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def summarize(self, results: list[TestResult]) -> dict:
        """
        Compute metrics, print console table, write JSON reports.

        Returns the metrics dict for programmatic use.
        """
        metrics = self._compute_metrics(results)
        self._print_table(results, metrics)
        self._write_reports(results, metrics)
        return metrics

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_metrics(results: list[TestResult]) -> dict:
        total_tests       = len(results)
        passed_tests      = sum(1 for r in results if r.passed)
        failed_tests      = total_tests - passed_tests

        all_steps: list[StepResult] = [s for r in results for s in r.steps]
        total_steps       = len(all_steps)
        failed_steps      = sum(1 for s in all_steps if not s.passed)
        healed_steps      = sum(1 for s in all_steps if s.healed)
        true_healed       = sum(1 for s in all_steps if s.healed and not s.false_repair)
        false_repairs     = sum(1 for s in all_steps if s.false_repair)

        # Healing success rate = truly healed / all steps that originally failed
        originally_failed = sum(1 for s in all_steps if s.original_failed)
        healing_rate      = round(true_healed / originally_failed, 4) if originally_failed else 0.0
        false_repair_rate = round(false_repairs / healed_steps, 4) if healed_steps else 0.0

        repair_times = [s.repair_time_sec for s in all_steps if s.original_failed and s.repair_time_sec > 0]
        avg_repair_time = round(sum(repair_times) / len(repair_times), 4) if repair_times else 0.0

        cand_counts = [s.candidate_count for s in all_steps if s.original_failed]
        avg_candidates = round(sum(cand_counts) / len(cand_counts), 2) if cand_counts else 0.0

        return {
            "total_tests":       total_tests,
            "passed_tests":      passed_tests,
            "failed_tests":      failed_tests,
            "total_steps":       total_steps,
            "failed_steps":      failed_steps,
            "originally_failed": originally_failed,
            "healed_steps":      healed_steps,
            "true_healed":       true_healed,
            "false_repairs":     false_repairs,
            "healing_rate":      healing_rate,
            "false_repair_rate": false_repair_rate,
            "avg_repair_time_s": avg_repair_time,
            "avg_candidates":    avg_candidates,
        }

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    @staticmethod
    def _print_table(results: list[TestResult], metrics: dict) -> None:
        table = Table(
            title="Self-Healing Test Results",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold cyan",
        )
        table.add_column("Test",    style="bold", no_wrap=True)
        table.add_column("Mode",    justify="center", style="dim")
        table.add_column("Status",  justify="center")
        table.add_column("Healed",  justify="center")
        table.add_column("Steps",   justify="right")
        table.add_column("False R", justify="center")

        for r in results:
            status    = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
            healed    = "[yellow]YES[/yellow]" if r.healed else "no"
            false_r   = sum(1 for s in r.steps if s.false_repair)
            fr_str    = f"[red]{false_r}[/red]" if false_r else "-"
            table.add_row(r.name, r.mode, status, healed, str(len(r.steps)), fr_str)

        console.print(table)

        m = metrics
        console.print(
            f"\n  Tests   : [green]{m['passed_tests']}[/green] passed / "
            f"[red]{m['failed_tests']}[/red] failed / {m['total_tests']} total"
        )
        console.print(
            f"  Steps   : {m['total_steps']} total, "
            f"{m['originally_failed']} originally failed, "
            f"[yellow]{m['true_healed']}[/yellow] truly healed"
        )
        console.print(f"  Healing rate      : {m['healing_rate']:.1%}")
        console.print(f"  False repair rate : {m['false_repair_rate']:.1%}")
        console.print(f"  Avg repair time   : {m['avg_repair_time_s']:.3f}s")
        console.print(f"  Avg candidates    : {m['avg_candidates']:.1f}\n")

    # ------------------------------------------------------------------
    # Report writing
    # ------------------------------------------------------------------

    def _write_reports(self, results: list[TestResult], metrics: dict) -> None:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        payload = self._build_payload(results, metrics)

        # Overwrite canonical results path
        try:
            with open(config.RESULTS_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            logger.info("Results written to %s", config.RESULTS_PATH)
        except OSError as exc:
            logger.error("Could not write results: %s", exc)

        # Timestamped snapshot
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap_path = os.path.join(config.LOG_DIR, f"report_{ts}.json")
        try:
            with open(snap_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            logger.info("Snapshot written to %s", snap_path)
        except OSError as exc:
            logger.error("Could not write snapshot: %s", exc)

    @staticmethod
    def _build_payload(results: list[TestResult], metrics: dict) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": metrics,
            "tests": [
                {
                    "name":   r.name,
                    "app":    r.app,
                    "mode":   r.mode,
                    "passed": r.passed,
                    "healed": r.healed,
                    "steps": [
                        {
                            "action":          s.action,
                            "selector_before": s.selector_before,
                            "selector_after":  s.selector_after,
                            "original_failed": s.original_failed,
                            "healed":          s.healed,
                            "false_repair":    s.false_repair,
                            "healing_source":  s.healing_source,
                            "repair_time_sec": s.repair_time_sec,
                            "candidate_count": s.candidate_count,
                            "winning_score":   s.winning_score,
                            "passed":          s.passed,
                            "error":           s.error,
                        }
                        for s in r.steps
                    ],
                }
                for r in results
            ],
        }
