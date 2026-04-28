"""
engine/repair_memory.py

Persistent memory of previously successful locator repairs.

When a healing attempt succeeds, the winning selector is saved to
config.REPAIR_MEMORY_PATH.  On subsequent runs, memory candidates are
checked first (before heuristics or LLM) so known-good selectors are
tried with high confidence at zero API cost.

Public API
----------
    RepairMemory
        .load()                                  -> list[dict]
        .save(records)                           -> None
        .add_record(record)                      -> None
        .find_candidates(failed_selector, action, max_candidates) -> list[dict]

Memory record format (stored)
------------------------------
    {
        "failed_selector":  "#user-name-BROKEN",
        "healed_selector":  "#user-name",
        "locator_type":     "css",
        "action":           "fill",
        "url":              "https://example.com/login",
        "timestamp":        "2026-04-08T...",
        "hit_count":        3
    }

Candidate format (returned to the pipeline)
-------------------------------------------
    {
        "selector":     "#user-name",
        "locator_type": "css",
        "source":       "memory",
        "confidence":   0.95,
        "reason":       "previous successful repair"
    }
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)

_MEMORY_PATH: str = config.REPAIR_MEMORY_PATH
_MEMORY_CONFIDENCE: float = 0.95   # memory candidates are high-confidence


class RepairMemory:
    """
    Thread-safe persistent store for successful locator repairs.

    Parameters
    ----------
    path
        Path to the JSON file used for persistence.
        Defaults to ``config.REPAIR_MEMORY_PATH``.
    """

    _lock = threading.Lock()

    def __init__(self, path: str | None = None) -> None:
        self.path = path or _MEMORY_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def load(self) -> list[dict]:
        """Return all stored repair records (may be empty)."""
        with self._lock:
            return self._load_raw()

    def save(self, records: list[dict]) -> None:
        """Overwrite the memory file with *records*."""
        with self._lock:
            self._save_raw(records)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_record(self, record: dict) -> None:
        """
        Add or update a repair record.

        If a record with the same ``failed_selector`` already exists, its
        ``hit_count`` is incremented and the ``healed_selector`` / metadata
        is updated.  Otherwise a new entry is appended.

        Parameters
        ----------
        record
            Dict with at least ``failed_selector`` and ``healed_selector``.
        """
        failed  = str(record.get("failed_selector") or "").strip()
        healed  = str(record.get("healed_selector") or "").strip()
        if not failed or not healed:
            logger.debug("RepairMemory.add_record: skipped incomplete record")
            return

        with self._lock:
            records = self._load_raw()
            existing = next(
                (r for r in records if r.get("failed_selector") == failed), None
            )
            if existing:
                existing["healed_selector"] = healed
                existing["locator_type"]    = record.get("locator_type", existing.get("locator_type", "css"))
                existing["action"]          = record.get("action", existing.get("action", ""))
                existing["url"]             = record.get("url", existing.get("url", ""))
                existing["hit_count"]       = existing.get("hit_count", 1) + 1
                existing["timestamp"]       = _now()
            else:
                records.append({
                    "failed_selector": failed,
                    "healed_selector": healed,
                    "locator_type":    record.get("locator_type", "css"),
                    "action":          record.get("action", ""),
                    "url":             record.get("url", ""),
                    "timestamp":       _now(),
                    "hit_count":       1,
                })
            self._save_raw(records)
            logger.debug("RepairMemory: saved repair %r → %r", failed, healed)

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def find_candidates(
        self,
        failed_selector: str,
        action: str = "",
        max_candidates: int = 3,
    ) -> list[dict]:
        """
        Return memory-sourced candidates for *failed_selector*.

        Strategy (in order):
          1. Exact match on ``failed_selector`` (highest priority).
          2. Records with the same action (if *action* is provided).

        Each returned candidate has ``source="memory"`` and
        ``confidence=0.95``.

        Parameters
        ----------
        failed_selector
            The selector that just failed.
        action
            Playwright action being attempted (e.g. ``"click"``).
        max_candidates
            Maximum number of candidates to return.
        """
        records = self.load()
        if not records:
            return []

        seen: set[str] = set()
        candidates: list[dict] = []

        def _add(r: dict) -> None:
            sel = str(r.get("healed_selector") or "").strip()
            if sel and sel not in seen:
                seen.add(sel)

                hit_count = int(r.get("hit_count", 1) or 1)
                confidence = min(
                    0.98,
                    _MEMORY_CONFIDENCE + min(0.03, hit_count * 0.01),
                )

                candidates.append({
                    "selector":     sel,
                    "locator_type": r.get("locator_type", "css"),
                    "source":       "memory",
                    "confidence":   round(confidence, 4),
                    "reason":       f"previous successful repair, hit_count={hit_count}",
                })

        # 1. Exact failed_selector match
        for r in records:
            if r.get("failed_selector") == failed_selector:
                _add(r)

        # 2. Same-action matches (if action provided and not already at cap)
        if action and len(candidates) < max_candidates:
            for r in records:
                if r.get("action") == action and r.get("failed_selector") != failed_selector:
                    _add(r)
                    if len(candidates) >= max_candidates:
                        break

        return candidates[:max_candidates]

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
            logger.warning("RepairMemory: could not read %s: %s", self.path, exc)
            return []

    def _save_raw(self, records: list[dict]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
        except OSError as exc:
            logger.error("RepairMemory: could not write %s: %s", self.path, exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
