"""
engine/healing_engine.py

Legacy self-healing pipeline (Stage 0 → Stage 1 → Stage 2).

This module is retained for backward compatibility.  New code should use
engine.self_healer.SelfHealer which integrates repair memory, heuristic
repair, and the validator via a cleaner interface.

Pipeline per failed action:
  Stage 0 — try original locator
  Stage 1 — heuristic repair (DOM-aware structural probing)
  Stage 2 — LLM repair + DOM-similarity validation

Supported actions: click, fill, expect_visible
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import Page, TimeoutError as PWTimeout, Error as PWError

import config
from dom.dom_extractor import extract_dom_from_page
from engine import heuristic_generator
from engine.action_wrapper import ActionWrapper
from llm.locator_repair import LocatorRepairer, RepairCandidate, RepairResult
from validator import locator_validator as lv

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: int      = getattr(config, "DEFAULT_TIMEOUT", 10_000)
MAX_HEAL_ATTEMPTS: int    = getattr(config, "MAX_HEAL_ATTEMPTS", 3)
MIN_LLM_CONFIDENCE: float = 0.5
MIN_COMBINED_SCORE: float = 0.35


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class HealingAttempt:
    """Record of a single locator tried during healing."""
    locator:        str
    stage:          str
    action:         str
    success:        bool
    error:          str   = ""
    strategy:       str   = ""
    llm_confidence: float = 0.0
    dom_score:      float = 0.0
    combined_score: float = 0.0


@dataclass
class HealingResult:
    """
    Complete audit trail for one healing session.

    Attributes
    ----------
    success          : True if any stage produced a working locator.
    stage            : "original" | "heuristic" | "llm" | "failed"
    original_locator : The selector that initially failed.
    repaired_locator : The locator that eventually worked (None on failure).
    action           : "click", "fill", or "expect_visible".
    fill_value       : Value used for fill actions.
    description      : Human-readable label.
    attempts         : All locators tried, in order.
    dom_element      : Best-matched DOM element dict from the extractor.
    llm_result       : Raw RepairResult from the LLM.
    validation       : Scored/ranked candidates (list of dicts).
    total_ms         : Wall-clock duration in ms.
    page_url         : URL when healing started.
    """
    success:           bool
    stage:             str
    original_locator:  str
    repaired_locator:  Optional[str]
    action:            str
    fill_value:        str
    description:       str
    attempts:          list[HealingAttempt] = field(default_factory=list)
    dom_element:       Optional[dict[str, Any]] = None
    llm_result:        Optional[RepairResult] = None
    validation:        Optional[list[dict]] = None
    total_ms:          float = 0.0
    page_url:          str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success":           self.success,
            "stage":             self.stage,
            "original_locator":  self.original_locator,
            "repaired_locator":  self.repaired_locator,
            "action":            self.action,
            "fill_value":        self.fill_value,
            "description":       self.description,
            "total_ms":          round(self.total_ms, 2),
            "page_url":          self.page_url,
            "attempts": [
                {
                    "locator":        a.locator,
                    "stage":          a.stage,
                    "strategy":       a.strategy,
                    "success":        a.success,
                    "error":          a.error,
                    "llm_confidence": round(a.llm_confidence, 4),
                    "dom_score":      round(a.dom_score, 4),
                    "combined_score": round(a.combined_score, 4),
                }
                for a in self.attempts
            ],
            "dom_element": self.dom_element,
            "llm_candidates": (
                [c.model_dump() for c in self.llm_result.candidates]
                if self.llm_result and self.llm_result.success
                else []
            ),
        }


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------

def _heuristic_candidates(broken: str) -> list[str]:
    """Return heuristic candidate locator strings (no metadata)."""
    return [c.locator for c in heuristic_generator.generate(broken, [])]


# ---------------------------------------------------------------------------
# Playwright execution
# ---------------------------------------------------------------------------

async def _execute(
    page: Page,
    locator_str: str,
    action: str,
    fill_value: str,
    timeout: int,
) -> tuple[bool, str]:
    try:
        loc = _resolve_locator(page, locator_str)
        if action == "click":
            await loc.first.click(timeout=timeout)
        elif action == "fill":
            await loc.first.clear(timeout=timeout)
            await loc.first.fill(fill_value, timeout=timeout)
        elif action == "expect_visible":
            await loc.first.wait_for(state="visible", timeout=timeout)
        else:
            raise ValueError(f"Unsupported action: {action!r}")
        return True, ""
    except (PWTimeout, PWError, ValueError, Exception) as exc:
        return False, str(exc)


def _resolve_locator(page: Page, locator_str: str):
    """Resolve a locator expression string to a Playwright Locator."""
    s = locator_str.strip()

    m = re.search(r"get_by_placeholder\(['\"]([^'\"]+)['\"]\)", s)
    if m:
        return page.get_by_placeholder(m.group(1))

    m = re.search(r"get_by_label\(['\"]([^'\"]+)['\"]\)", s)
    if m:
        return page.get_by_label(m.group(1))

    m = re.search(r"get_by_text\(['\"]([^'\"]+)['\"]\)", s)
    if m:
        return page.get_by_text(m.group(1))

    m = re.search(r"get_by_title\(['\"]([^'\"]+)['\"]\)", s)
    if m:
        return page.get_by_title(m.group(1))

    m = re.search(r"get_by_alt_text\(['\"]([^'\"]+)['\"]\)", s)
    if m:
        return page.get_by_alt_text(m.group(1))

    m_role = re.search(r"get_by_role\(['\"](\w+)['\"](.*)\)", s)
    if m_role:
        role = m_role.group(1)
        rest = m_role.group(2)
        m_name = re.search(r"name=['\"]([^'\"]+)['\"]", rest)
        if m_name:
            return page.get_by_role(role, name=m_name.group(1))  # type: ignore[arg-type]
        return page.get_by_role(role)  # type: ignore[arg-type]

    m = re.search(r'page\.locator\(["\']([^"\']+)["\']\)', s)
    if m:
        return page.locator(m.group(1))

    return page.locator(s)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class HealingEngine:
    """
    Legacy self-healing Playwright action engine.

    Parameters
    ----------
    page
        Live Playwright Page object.
    repairer
        LocatorRepairer instance.  Created automatically if omitted.
    timeout
        Per-action timeout in ms.
    min_llm_confidence
        Discard LLM candidates below this confidence.
    min_combined_score
        Discard validated candidates below this combined score.
    max_llm_candidates
        Cap on validated candidates to try.
    """

    def __init__(
        self,
        page: Page,
        *,
        repairer: Optional[LocatorRepairer] = None,
        timeout: int = DEFAULT_TIMEOUT,
        min_llm_confidence: float = MIN_LLM_CONFIDENCE,
        min_combined_score: float = MIN_COMBINED_SCORE,
        max_llm_candidates: int = MAX_HEAL_ATTEMPTS,
    ) -> None:
        self.page = page
        self._wrapper = ActionWrapper(page, timeout=timeout, capture_html=True)
        self._repairer = repairer or LocatorRepairer()
        self._timeout = timeout
        self._min_llm_conf = min_llm_confidence
        self._min_combined = min_combined_score
        self._max_candidates = max_llm_candidates
        self._history: list[HealingResult] = []

    async def click(self, locator: str, *, description: str = "") -> HealingResult:
        return await self._heal("click", locator, "", description)

    async def fill(self, locator: str, value: str, *, description: str = "") -> HealingResult:
        return await self._heal("fill", locator, value, description)

    async def expect_visible(self, locator: str, *, description: str = "") -> HealingResult:
        return await self._heal("expect_visible", locator, "", description)

    @property
    def history(self) -> list[HealingResult]:
        return list(self._history)

    @property
    def healed_count(self) -> int:
        return sum(1 for r in self._history if r.stage not in ("original", "failed"))

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self._history if r.stage == "failed")

    async def _heal(
        self,
        action: str,
        locator: str,
        fill_value: str,
        description: str,
    ) -> HealingResult:
        t0 = time.perf_counter()
        page_url = self.page.url
        attempts: list[HealingAttempt] = []

        # Stage 0: original locator
        ok, err = await _execute(self.page, locator, action, fill_value, self._timeout)
        attempts.append(HealingAttempt(
            locator=locator, stage="original", action=action, success=ok, error=err,
        ))

        if ok:
            result = self._make_result(
                success=True, stage="original", original=locator, repaired=None,
                action=action, fill_value=fill_value, description=description,
                attempts=attempts, page_url=page_url, t0=t0,
            )
            self._history.append(result)
            return result

        logger.warning("[Stage 0] FAILED %r on %r — %s", action, locator, err[:120])

        # Extract DOM once
        dom_elements = await self._extract_dom()
        original_dom_element = _find_original_element(locator, dom_elements)

        # Stage 1: heuristic repair
        for hc in heuristic_generator.generate(locator, dom_elements):
            ok, err = await _execute(self.page, hc.locator, action, fill_value, self._timeout)
            attempts.append(HealingAttempt(
                locator=hc.locator, stage="heuristic", action=action,
                success=ok, error=err, strategy=hc.strategy,
            ))
            if ok:
                logger.info("[Stage 1] HEALED %r → %r (%s)", locator, hc.locator, hc.strategy)
                result = self._make_result(
                    success=True, stage="heuristic", original=locator, repaired=hc.locator,
                    action=action, fill_value=fill_value, description=description,
                    attempts=attempts, dom_element=original_dom_element,
                    page_url=page_url, t0=t0,
                )
                self._history.append(result)
                return result

        logger.info("[Stage 1] Heuristics exhausted — escalating to LLM")

        # Stage 2: LLM + validation
        failure_error = next(
            (a.error for a in reversed(attempts) if a.error), "Unknown error"
        )
        llm_result = await self._repairer.repair(
            broken_locator=locator,
            action=action,
            error_message=failure_error,
            dom_elements=dom_elements,
            min_confidence=self._min_llm_conf,
        )

        if not llm_result.success or not llm_result.candidates:
            logger.error("[Stage 2] LLM returned no candidates: %s", llm_result.error)
            result = self._make_result(
                success=False, stage="failed", original=locator, repaired=None,
                action=action, fill_value=fill_value, description=description,
                attempts=attempts, dom_element=original_dom_element,
                llm_result=llm_result, page_url=page_url, t0=t0,
            )
            self._history.append(result)
            return result

        logger.info("[Stage 2] LLM returned %d candidates", len(llm_result.candidates))

        validation = self._validate(llm_result.candidates, dom_elements, original_dom_element)

        for vc in validation[:self._max_candidates]:
            ok, err = await _execute(
                self.page, vc["selector"], action, fill_value, self._timeout
            )
            attempts.append(HealingAttempt(
                locator=vc["selector"],
                stage="llm",
                action=action,
                success=ok,
                error=err,
                llm_confidence=vc.get("confidence", 0.0),
                dom_score=vc.get("final_score", 0.0),
                combined_score=vc.get("final_score", 0.0),
            ))
            if ok:
                logger.info(
                    "[Stage 2] HEALED %r → %r (score=%.3f)",
                    locator, vc["selector"], vc.get("final_score", 0.0),
                )
                result = self._make_result(
                    success=True, stage="llm",
                    original=locator, repaired=vc["selector"],
                    action=action, fill_value=fill_value, description=description,
                    attempts=attempts,
                    dom_element=vc.get("matched_element") or original_dom_element,
                    llm_result=llm_result,
                    validation=validation,
                    page_url=page_url, t0=t0,
                )
                self._history.append(result)
                return result

        logger.error("[FAILED] Could not heal %r after %d total attempts", locator, len(attempts))
        result = self._make_result(
            success=False, stage="failed", original=locator, repaired=None,
            action=action, fill_value=fill_value, description=description,
            attempts=attempts, dom_element=original_dom_element,
            llm_result=llm_result, validation=validation,
            page_url=page_url, t0=t0,
        )
        self._history.append(result)
        return result

    async def _extract_dom(self) -> list[dict[str, Any]]:
        try:
            return await extract_dom_from_page(self.page)
        except Exception as exc:
            logger.warning("[DOM] Extraction failed: %s", exc)
            return []

    def _validate(
        self,
        candidates: list[RepairCandidate],
        dom_elements: list[dict],
        original_element: Optional[dict],
    ) -> list[dict]:
        """Score and rank LLM candidates using simple locator_validator functions."""
        profile = original_element or {}
        scored: list[dict] = []

        for c in candidates:
            cand_dict = {
                "selector":     c.locator,
                "locator_type": c.locator_type,
                "source":       "llm",
                "confidence":   c.confidence,
                "reason":       c.reasoning,
                "resolved":     True,
                "matched_count": 1,
                "matched_element": None,
            }
            scored.append(lv.score_candidate(profile, None, cand_dict))

        return lv.rank_candidates(scored)

    @staticmethod
    def _make_result(
        *,
        success: bool,
        stage: str,
        original: str,
        repaired: Optional[str],
        action: str,
        fill_value: str,
        description: str,
        attempts: list[HealingAttempt],
        page_url: str,
        t0: float,
        dom_element: Optional[dict] = None,
        llm_result: Optional[RepairResult] = None,
        validation: Optional[list[dict]] = None,
    ) -> HealingResult:
        return HealingResult(
            success=success,
            stage=stage,
            original_locator=original,
            repaired_locator=repaired,
            action=action,
            fill_value=fill_value,
            description=description,
            attempts=attempts,
            dom_element=dom_element,
            llm_result=llm_result,
            validation=validation,
            total_ms=round((time.perf_counter() - t0) * 1000, 2),
            page_url=page_url,
        )


# ---------------------------------------------------------------------------
# DOM element lookup
# ---------------------------------------------------------------------------

def _find_original_element(
    broken_locator: str, dom_elements: list[dict]
) -> Optional[dict]:
    """Try to identify which DOM element the broken locator was meant to target."""
    if not dom_elements:
        return None

    # #id (strip mutation suffixes)
    m = re.search(r"#([\w-]+)", broken_locator)
    if m:
        target = re.sub(
            r"[-_](broken|old|new|v\d+|backup|test|copy|tmp|temp)$",
            "", m.group(1), flags=re.IGNORECASE,
        ).lower()
        found = next(
            (el for el in dom_elements if (el.get("id") or "").lower() == target), None
        )
        if found:
            return found

    # [name="…"]
    m = re.search(r'name=["\']([^"\']+)["\']', broken_locator)
    if m:
        target = m.group(1).lower()
        found = next(
            (el for el in dom_elements if (el.get("name") or "").lower() == target), None
        )
        if found:
            return found

    # [data-testid="…"]
    m = re.search(r'data-testid=["\']([^"\']+)["\']', broken_locator)
    if m:
        target = m.group(1).lower()
        found = next(
            (el for el in dom_elements
             if (el.get("data-testid") or "").lower() == target), None
        )
        if found:
            return found

    # [placeholder="…"]
    m = re.search(r'placeholder=["\']([^"\']+)["\']', broken_locator)
    if m:
        target = m.group(1).lower()
        found = next(
            (el for el in dom_elements
             if (el.get("placeholder") or "").lower() == target), None
        )
        if found:
            return found

    return None
