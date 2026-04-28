"""
logger/results_logger.py

Append-only JSON logger for self-healing test results.

Stores per-test and per-step records to config.LOG_DIR, buffered in memory
and flushed together for efficiency.

Public API
----------
    ResultsLogger
        .log_test_result(result: dict)  -> None
        .log_step_result(step: dict)    -> None
        .flush()                        -> None
        .load_all()                     -> list[dict]
        .clear()                        -> None
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)

_LOG_PATH: str = os.path.join(config.LOG_DIR, "session.json")


class ResultsLogger:
    """
    Thread-safe, buffered logger that persists step and test records to
    ``logs/session.json``.

    Records are held in memory until ``flush()`` is called (or the object
    is used as a context manager).  Calling ``log_test_result`` /
    ``log_step_result`` adds to the in-memory buffer; ``flush()`` writes
    everything to disk atomically.

    Parameters
    ----------
    path
        Path to the JSON log file.  Defaults to ``logs/session.json``.
    """

    _lock = threading.Lock()

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or _LOG_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._buffer: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_test_result(self, result: dict) -> None:
        """
        Buffer a test-level result record.

        Expected keys (all optional — will be set to safe defaults if missing):
            test_id, app, mode, passed, healed, step_count, timestamp
        """
        record = {
            "record_type":  "test",
            "test_id":      str(result.get("name") or result.get("test_id") or ""),
            "app":          str(result.get("app") or ""),
            "mode":         str(result.get("mode") or ""),
            "passed":       bool(result.get("passed", False)),
            "healed":       bool(result.get("healed", False)),
            "step_count":   int(result.get("step_count") or len(result.get("steps", []))),
            "timestamp":    _now(),
        }
        with self._lock:
            self._buffer.append(record)

    def log_step_result(self, step: dict) -> None:
        """
        Buffer a step-level result record.

        Expected keys (all optional):
            test_id, app, mode, action, original_locator, healed_locator,
            source, repair_time_sec, candidates, chosen_candidate,
            final_success, false_repair
        """
        record = {
            "record_type":       "step",
            "test_id":           str(step.get("test_id") or ""),
            "app":               str(step.get("app") or ""),
            "mode":              str(step.get("mode") or ""),
            "action":            str(step.get("action") or ""),
            "original_locator":  str(step.get("original_locator") or step.get("selector_before") or ""),
            "healed_locator":    step.get("healed_locator") or step.get("selector_after"),
            "source":            str(step.get("source") or step.get("healing_source") or ""),
            "repair_time_sec":   float(step.get("repair_time_sec") or 0.0),
            "candidates":        step.get("candidates") or [],
            "chosen_candidate":  step.get("chosen_candidate") or step.get("healed_locator"),
            "final_success":     bool(step.get("final_success") if "final_success" in step else step.get("passed", False)),
            "false_repair":      bool(step.get("false_repair", False)),
            "timestamp":         _now(),
        }
        with self._lock:
            self._buffer.append(record)

    def flush(self) -> None:
        """Write all buffered records to disk and clear the buffer."""
        with self._lock:
            if not self._buffer:
                return
            existing = self._load_raw()
            existing.extend(self._buffer)
            self._save_raw(existing)
            flushed = len(self._buffer)
            self._buffer.clear()
        logger.debug("ResultsLogger: flushed %d record(s) to %s", flushed, self.path)

    def load_all(self) -> list[dict]:
        """Return all persisted records (does not include unflushed buffer)."""
        with self._lock:
            return self._load_raw()

    def clear(self) -> None:
        """Delete all persisted records and clear the buffer."""
        with self._lock:
            self._buffer.clear()
            self._save_raw([])

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "ResultsLogger":
        return self

    def __exit__(self, *_: object) -> None:
        self.flush()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_raw(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ResultsLogger: could not read %s: %s", self.path, exc)
            return []

    def _save_raw(self, records: list[dict]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
        except OSError as exc:
            logger.error("ResultsLogger: could not write %s: %s", self.path, exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
