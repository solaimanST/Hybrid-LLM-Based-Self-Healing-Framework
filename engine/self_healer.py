"""
engine/self_healer.py

Orchestrates the three-stage self-healing pipeline:

  Stage 0 — Try the original selector.  If it still works, return immediately.
  Stage 1 — HeuristicEngine: DOM-based strategy generation + live validation.
  Stage 2 — LLM + RepairMemory: semantic suggestion + scored ranking.

False-repair detection
----------------------
After every successful Stage-1 or Stage-2 heal, _verify_repair() checks that
the action produced an observable page-state change:

    fill   → input_value() must equal the filled text
    click  → URL changed  OR  DOM element count changed by ≥ 3

If no observable change is detected the result is returned with
``false_repair=True`` so the experiment log captures it — without blocking
the test (the action may have had subtle, undetectable side-effects).

JSONL log fields (written by _log_result)
-----------------------------------------
    action, description, original_selector, success, healed_selector,
    source, stage, attempts, candidate_count, dom_element_count,
    winning_score, score_margin, rejection_reasons, false_repair,
    repair_time_sec, page_url, healing_mode, risk_flags, ambiguous,
    original_error, timestamp  (added by experiment_logger)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from playwright.async_api import Error as PWError
from playwright.async_api import Locator
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeout

import config
from dom.dom_analyzer import DOMAnalyzer
from engine import heuristic_generator as _hgen
from engine.action_wrapper import ActionWrapper
from engine.heuristic_engine import HeuristicEngine
from engine.repair_memory import RepairMemory
from llm.llm_client import LLMClient
from utils.experiment_logger import append_experiment_log
from validator import locator_validator as lv
from validator.locator_validator import _INTENT_TEXT_MAP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backward-compatibility wrapper (used by unit tests and Stage-2 pipeline)
# ---------------------------------------------------------------------------

def generate_heuristic_candidates(
    selector: str,
    dom_elements: list,
    action: str = "",
    max_candidates: Optional[int] = None,
    description: str = "",
) -> list:
    """
    Module-level wrapper around heuristic_generator.generate().

    Returns a list of plain dicts compatible with the healing pipeline:
        { selector, locator_type, source, confidence, reason }

    Exists so that:
      - unit tests can patch ``engine.self_healer.generate_heuristic_candidates``
      - Stage-2 can augment its candidate pool without re-running the full
        heuristic engine (which already ran in Stage-1).
    """
    try:
        raw = _hgen.generate(
            broken_locator=selector,
            dom_elements=dom_elements or [],
            description=description,
            action=action,
        )
        results = []
        for c in (raw or []):
            results.append({
                "selector":     c.locator,
                "locator_type": c.locator_type,
                "source":       "heuristic",
                "confidence":   round(c.confidence, 4),
                "reason":       c.reasoning,
            })
        if max_candidates is not None:
            results = results[:max_candidates]
        return results
    except Exception:
        logger.debug("[generate_heuristic_candidates] generation failed", exc_info=True)
        return []


ORIGINAL_ACTION_TIMEOUT_MS = getattr(config, "ORIGINAL_ACTION_TIMEOUT_MS", 1500)
HEAL_VALIDATION_TIMEOUT_MS = getattr(config, "HEAL_VALIDATION_TIMEOUT_MS", 2500)

LOW_MARGIN_THRESHOLD = getattr(config, "LOW_MARGIN_THRESHOLD", 0.03)
LOW_SCORE_THRESHOLD  = getattr(config, "LOW_SCORE_THRESHOLD", 0.85)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class HealingResult:
    original_selector: str
    success: bool
    healed_selector: Optional[str] = None
    source: str = ""
    attempts: int = 0
    candidates: list[dict] = field(default_factory=list)
    winning_score: float = 0.0
    top_score: float = 0.0
    second_score: float = 0.0
    score_margin: float = 0.0
    repair_time_sec: float = 0.0
    original_error: str = ""
    # Research-grade fields
    false_repair: bool = False
    dom_element_count: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    click_evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SelfHealer
# ---------------------------------------------------------------------------

class SelfHealer:
    def __init__(
        self,
        page: Page,
        llm_client: Optional[LLMClient] = None,
        memory: Optional[RepairMemory] = None,
        timeout: int = config.DEFAULT_TIMEOUT,
        healing_mode: Optional[str] = None,
    ) -> None:
        self.page     = page
        self._wrapper = ActionWrapper(page, timeout=timeout)
        self._dom     = DOMAnalyzer(page)
        self._memory  = memory or RepairMemory()
        self._timeout = timeout
        self._mode    = (healing_mode or config.HEALING_MODE).lower()

        self._llm: Optional[LLMClient] = None
        if self._mode in ("hybrid", "llm_only"):
            if llm_client is not None:
                self._llm = llm_client
            else:
                try:
                    self._llm = LLMClient()
                except Exception:
                    logger.exception("[SelfHealer] Failed to initialise LLM client")

        self._heuristic_engine = HeuristicEngine(
            memory_store=self._MemoryAdapter(self._memory),
            max_validate=getattr(config, "MAX_HEURISTIC_VALIDATE", 12),
            max_try=getattr(config, "MAX_HEURISTIC_TRY", 4),
            timeout_ms=min(
                HEAL_VALIDATION_TIMEOUT_MS,
                getattr(config, "HEURISTIC_VALIDATE_TIMEOUT", 1500),
            ),
        )

    # ------------------------------------------------------------------
    # Memory adapter
    # ------------------------------------------------------------------

    class _MemoryAdapter:
        def __init__(self, memory: RepairMemory) -> None:
            self.memory = memory

        def find_similar(self, ref) -> list[dict]:
            try:
                return self.memory.find_candidates(
                    ref.failed_selector,
                    action=ref.action,
                    max_candidates=getattr(config, "MAX_LLM_CANDIDATES", 5),
                ) or []
            except Exception:
                return []

        def save_success(self, ref, candidate: dict) -> None:
            try:
                self.memory.add_record({
                    "failed_selector": ref.failed_selector,
                    "healed_selector": candidate.get("healed_selector") or candidate.get("selector"),
                    "locator_type":    candidate.get("locator_type", "css"),
                    "action":          ref.action,
                    "url":             "",
                })
            except Exception:
                logger.exception("[SelfHealer] Failed to save repair memory")

    # ------------------------------------------------------------------
    # Public action methods
    # ------------------------------------------------------------------

    async def click(self, selector: str, description: str = "") -> HealingResult:
        return await self._heal("click", selector, "", description)

    async def fill(
        self, selector: str, value: str, description: str = ""
    ) -> HealingResult:
        return await self._heal("fill", selector, value, description)

    async def expect_visible(
        self, selector: str, description: str = ""
    ) -> HealingResult:
        return await self._heal("expect_visible", selector, "", description)

    async def select_option(
        self, selector: str, value: str, description: str = ""
    ) -> HealingResult:
        """Select an option with the same self-healing pipeline used by clicks/fills."""
        return await self._heal("select", selector, value, description)

    # ------------------------------------------------------------------
    # Core healing pipeline
    # ------------------------------------------------------------------

    async def _heal(
        self,
        action: str,
        selector: str,
        fill_value: str,
        description: str,
    ) -> HealingResult:
        t0 = time.perf_counter()
        self._last_click_evidence: dict = {}

        # --- Stage 0: try original selector ---
        ok, error = await self._try_action(
            action, selector, fill_value,
            timeout_ms=ORIGINAL_ACTION_TIMEOUT_MS,
            fast_precheck=True,
        )
        if ok:
            result = HealingResult(
                original_selector=selector,
                success=True,
                source="original",
                attempts=1,
                repair_time_sec=_elapsed(t0),
            )
            self._log_result(action, description, result)
            return result

        if self._mode == "none":
            result = HealingResult(
                original_selector=selector,
                success=False,
                source="failed",
                attempts=1,
                original_error=error,
                repair_time_sec=_elapsed(t0),
            )
            self._log_result(action, description, result)
            return result

        # --- Extract DOM once, reuse for all stages ---
        dom_elements = await self._extract_dom()
        dom_count    = len(dom_elements)
        expected_profile = _build_expected_profile(selector, dom_elements)

        # Capture pre-heal page state for false-repair detection
        pre_url       = self.page.url
        pre_dom_count = await self._get_dom_count()

        ranked:   list[dict] = []
        attempts: int        = 1
        rejection_reasons:   list[str] = []

        # --- Stage 1: heuristic engine ---
        if self._mode in ("heuristic", "hybrid"):
            heuristic_result = await self._run_heuristic_engine(
                action=action,
                selector=selector,
                fill_value=fill_value,
                description=description,
                dom_elements=dom_elements,
            )

            if heuristic_result.candidates:
                ranked.extend(heuristic_result.candidates)
                # Collect rejection reasons from validation details
                for c in heuristic_result.candidates:
                    reason = c.get("validation", {}).get("reason", "")
                    if reason and reason != "ok" and reason not in rejection_reasons:
                        rejection_reasons.append(reason)

            if heuristic_result.success:
                score_ok = heuristic_result.winning_score >= LOW_SCORE_THRESHOLD
                margin_ok = (
                    heuristic_result.score_margin >= LOW_MARGIN_THRESHOLD
                    or len(heuristic_result.candidates) <= 1
                    or heuristic_result.top_score >= 0.90
                )

                if not score_ok and "LOW_SCORE" not in rejection_reasons:
                    rejection_reasons.append("LOW_SCORE")
                if not margin_ok and "LOW_MARGIN" not in rejection_reasons:
                    rejection_reasons.append("LOW_MARGIN")

                if action == "click":
                    click_evidence = self._last_click_evidence or {}
                    allowed = self._pre_click_evidence_allowed(
                        click_evidence.get("before", {}),
                        description,
                    )
                else:
                    click_evidence = {}
                    allowed = await self._is_candidate_allowed_for_action(
                        action=action,
                        selector=heuristic_result.healed_selector,
                        description=description,
                        locator_type=heuristic_result.locator_type or "css",
                    )

                if allowed:
                    if action == "click":
                        false_repair = not self._click_evidence_changed(
                            click_evidence.get("before", {}),
                            click_evidence.get("after", {}),
                            description,
                        )
                    else:
                        click_evidence = {}
                        false_repair = await self._verify_repair(
                            action=action,
                            selector=heuristic_result.healed_selector,
                            fill_value=fill_value,
                            locator_type=heuristic_result.locator_type or "css",
                            pre_url=pre_url,
                            pre_dom_count=pre_dom_count,
                            description=description,
                        )

                    if false_repair:
                        if "FALSE_REPAIR" not in rejection_reasons:
                            rejection_reasons.append("FALSE_REPAIR")
                        if action == "click" and "NO_CLICK_STATE_CHANGE" not in rejection_reasons:
                            rejection_reasons.append("NO_CLICK_STATE_CHANGE")
                    else:
                        result = HealingResult(
                            original_selector=selector,
                            success=True,
                            healed_selector=heuristic_result.healed_selector,
                            source=heuristic_result.source,
                            attempts=attempts + heuristic_result.attempts,
                            candidates=heuristic_result.candidates,
                            winning_score=heuristic_result.winning_score,
                            top_score=heuristic_result.top_score,
                            second_score=heuristic_result.second_score,
                            score_margin=heuristic_result.score_margin,
                            repair_time_sec=_elapsed(t0),
                            original_error=error,
                            false_repair=False,
                            dom_element_count=dom_count,
                            rejection_reasons=rejection_reasons,
                            click_evidence=click_evidence,
                        )
                        self._log_result(action, description, result)
                        return result
                elif action == "click":
                    if "CLICK_TARGET_NOT_ACTIONABLE" not in rejection_reasons:
                        rejection_reasons.append("CLICK_TARGET_NOT_ACTIONABLE")

            attempts += heuristic_result.attempts

        # --- Stage 2: LLM + memory ---
        legacy_candidates: list[dict] = []

        if config.ENABLE_REPAIR_MEMORY:
            mem_cands = self._memory.find_candidates(
                selector,
                action=action,
                max_candidates=config.MAX_LLM_CANDIDATES,
            ) or []
            legacy_candidates.extend(mem_cands)

        # Augment with heuristic generator candidates (lightweight, no live validation).
        # This ensures Stage-2 can rank and try the right candidates even when
        # Stage-1's full engine timed out or navigated away.
        gen_cands = generate_heuristic_candidates(
            selector,
            dom_elements,
            action=action,
            description=description,
        )
        legacy_candidates.extend(gen_cands)

        if self._mode in ("llm_only", "hybrid") and self._llm is not None:
            try:
                # Reuse already-extracted dom_elements — avoids a second page fetch.
                dom_snapshot = DOMAnalyzer.elements_to_prompt_context(dom_elements[:80])
                llm_cands = await self._llm.suggest_selectors(
                    failed_selector=selector,
                    dom_snapshot=dom_snapshot,
                    action_description=description or action,
                    max_candidates=config.MAX_LLM_CANDIDATES,
                )
                legacy_candidates.extend(llm_cands)
            except Exception:
                logger.exception("[SelfHealer] LLM selector suggestion failed")

        legacy_candidates = _dedupe_candidates(legacy_candidates)

        if legacy_candidates:
            resolved = await self._resolve_candidates(legacy_candidates, dom_elements)
            scored   = self._score_candidates(
                resolved,
                expected_profile,
                action=action,
                description=description,
            )
            ranked_legacy = lv.rank_candidates(scored)

            # Collect rejection reasons from scored candidates
            for c in ranked_legacy:
                r = c.get("rejection_reason", "")
                if r and r not in rejection_reasons:
                    rejection_reasons.append(r)

            if ranked_legacy:
                ranked = _dedupe_candidates(ranked + ranked_legacy)

            top_score    = ranked_legacy[0].get("final_score", 0.0) if ranked_legacy else 0.0
            second_score = ranked_legacy[1].get("final_score", 0.0) if len(ranked_legacy) > 1 else 0.0
            score_margin = max(0.0, top_score - second_score)

            for cand in ranked_legacy:
                sel          = cand["selector"]
                locator_type = cand.get("locator_type", "css")
                score        = cand.get("final_score", cand.get("confidence", 0.0))

                if score <= 0:
                    continue

                allowed = await self._is_candidate_allowed_for_action(
                    action=action,
                    selector=sel,
                    description=description,
                    locator_type=locator_type,
                )
                if not allowed:
                    continue

                if action == "click":
                    ok, _err, click_evidence = await self._click_once_with_evidence(
                        selector=sel,
                        locator_type=locator_type,
                        description=description,
                        timeout_ms=HEAL_VALIDATION_TIMEOUT_MS,
                    )
                else:
                    ok, _err = await self._try_action_compat(
                        action=action,
                        selector=sel,
                        fill_value=fill_value,
                        locator_type=locator_type,
                        timeout_ms=HEAL_VALIDATION_TIMEOUT_MS,
                    )
                    click_evidence = {}
                attempts += 1

                if ok:
                    source = cand.get("source", "llm")

                    if config.ENABLE_REPAIR_MEMORY:
                        self._memory.add_record({
                            "failed_selector": selector,
                            "healed_selector": sel,
                            "locator_type":    locator_type,
                            "action":          action,
                            "url":             self.page.url,
                        })

                    if action == "click":
                        false_repair = False
                    else:
                        false_repair = await self._verify_repair(
                            action=action,
                            selector=sel,
                            fill_value=fill_value,
                            locator_type=locator_type,
                            pre_url=pre_url,
                            pre_dom_count=pre_dom_count,
                            description=description,
                        )

                    if false_repair:
                        if "FALSE_REPAIR" not in rejection_reasons:
                            rejection_reasons.append("FALSE_REPAIR")
                        continue

                    result = HealingResult(
                        original_selector=selector,
                        success=True,
                        healed_selector=sel,
                        source=source,
                        attempts=attempts,
                        candidates=ranked,
                        winning_score=score,
                        top_score=top_score,
                        second_score=second_score,
                        score_margin=score_margin,
                        repair_time_sec=_elapsed(t0),
                        original_error=error,
                        false_repair=False,
                        dom_element_count=dom_count,
                        rejection_reasons=rejection_reasons,
                        click_evidence=click_evidence,
                    )
                    self._log_result(action, description, result)
                    return result
                elif action == "click":
                    if _err and _err not in rejection_reasons:
                        rejection_reasons.append(_err)

        # --- All stages exhausted ---
        result = HealingResult(
            original_selector=selector,
            success=False,
            source="failed",
            attempts=attempts,
            candidates=ranked,
            original_error=error,
            repair_time_sec=_elapsed(t0),
            dom_element_count=dom_count,
            rejection_reasons=rejection_reasons,
        )
        self._log_result(action, description, result)
        return result

    # ------------------------------------------------------------------
    # Heuristic engine runner
    # ------------------------------------------------------------------

    async def _run_heuristic_engine(
        self,
        action: str,
        selector: str,
        fill_value: str,
        description: str,
        dom_elements: list[dict],
    ):
        async def action_fn(locator: Locator):
            first = locator.first
            if action == "click":
                before = await self._capture_click_evidence(locator=locator)
                try:
                    await first.click(timeout=HEAL_VALIDATION_TIMEOUT_MS)
                    after = await self._capture_click_evidence(locator=locator)
                    self._last_click_evidence = {
                        "before": before,
                        "after": after,
                        "changed": self._click_evidence_changed(before, after, description),
                    }
                except Exception:
                    after = await self._capture_click_evidence(locator=locator)
                    self._last_click_evidence = {
                        "before": before,
                        "after": after,
                        "changed": self._click_evidence_changed(before, after, description),
                    }
                    if self._last_click_evidence["changed"]:
                        return
                    raise
            elif action == "fill":
                await first.fill(fill_value, timeout=HEAL_VALIDATION_TIMEOUT_MS)
            elif action == "select":
                await first.select_option(fill_value, timeout=HEAL_VALIDATION_TIMEOUT_MS)
            elif action == "expect_visible":
                await first.wait_for(state="visible", timeout=HEAL_VALIDATION_TIMEOUT_MS)
            else:
                raise ValueError(f"Unsupported action: {action!r}")

        reference_context = _build_reference_context(selector, description, dom_elements)

        return await self._heuristic_engine.repair(
            page=self.page,
            failed_selector=selector,
            action=action,
            action_fn=action_fn,
            dom_snapshot=dom_elements,
            description=description,
            reference_context=reference_context,
        )

    # ------------------------------------------------------------------
    # False-repair detection
    # ------------------------------------------------------------------

    async def _get_dom_count(self) -> int:
        """Return total element count in the live DOM."""
        try:
            return await self.page.evaluate("document.querySelectorAll('*').length")
        except Exception:
            return 0

    async def _capture_click_evidence(
        self,
        selector: str = "",
        locator_type: str = "css",
        locator: Optional[Locator] = None,
    ) -> dict:
        """Capture generic before/after evidence for a single click candidate."""
        evidence = {
            "url": self.page.url,
            "dom_count": await self._get_dom_count(),
            "target_count": 0,
            "target_tag": "",
            "target_type": "",
            "target_text": "",
            "target_value": "",
            "target_checked": None,
            "generic_visible_state": await self._capture_generic_visible_state(),
        }

        try:
            loc = locator if locator is not None else self._make_locator(selector, locator_type)
            evidence["target_count"] = await loc.count()
            if evidence["target_count"] > 0:
                first = loc.first
                try:
                    evidence["target_tag"] = (
                        await first.evaluate("el => el.tagName.toLowerCase()")
                        or ""
                    ).strip().lower()
                except Exception:
                    evidence["target_tag"] = ""
                try:
                    evidence["target_type"] = (
                        await first.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
                        or ""
                    ).strip().lower()
                except Exception:
                    evidence["target_type"] = ""
                try:
                    evidence["target_text"] = (
                        await first.inner_text(timeout=800) or ""
                    ).strip()
                except Exception:
                    evidence["target_text"] = ""
                try:
                    evidence["target_value"] = (
                        await first.evaluate("el => el.getAttribute('value') || ''")
                        or ""
                    ).strip()
                except Exception:
                    evidence["target_value"] = ""
                try:
                    evidence["target_checked"] = await first.evaluate(
                        "el => typeof el.checked === 'boolean' ? el.checked : null"
                    )
                except Exception:
                    evidence["target_checked"] = None
        except Exception:
            pass

        return evidence

    def _pre_click_evidence_allowed(self, evidence: dict, description: str = "") -> bool:
        """Check uniqueness, action compatibility, and semantic intent before click."""
        if not evidence or evidence.get("target_count") != 1:
            return False

        tag = (evidence.get("target_tag") or "").lower()
        input_type = (evidence.get("target_type") or "").lower()
        if tag not in {"button", "a", "input", "label", "select"}:
            return False
        if tag == "input" and input_type in {"hidden", "radio"}:
            return False

        intent = _classify_intent(description, "click")
        if intent == "action_button":
            if tag == "a":
                return False
            if tag == "input" and input_type not in {"submit", "button"}:
                return False

        desc = re.sub(r"[-_]", " ", (description or "").lower())
        label = _norm_click_label(
            evidence.get("target_text", ""),
            evidence.get("target_value", ""),
        )
        if not label:
            return True

        for intent_phrase, required_word in _INTENT_TEXT_MAP:
            phrase_norm = re.sub(r"[-_]", " ", intent_phrase)
            if phrase_norm in desc:
                return required_word in label

        return True

    async def _capture_generic_visible_state(self) -> list[str]:
        """
        Capture generic short visible counters/badges without site-specific selectors.
        This intentionally favours small numeric UI state over large content text.
        """
        try:
            return await self.page.evaluate(
                """
                () => {
                  const out = [];
                  const seen = new Set();
                  for (const el of document.querySelectorAll('body *')) {
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none') continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!text || text.length > 12 || text.includes(' ')) continue;
                    const identity = [
                      el.id || '',
                      el.className || '',
                      el.getAttribute('role') || '',
                      el.getAttribute('aria-label') || '',
                      el.getAttribute('data-testid') || '',
                      el.getAttribute('data-test') || ''
                    ].join(' ').toLowerCase();
                    const counterLike = /^\\d{1,4}$/.test(text)
                      || /badge|count|counter|qty|quantity|total|cart/.test(identity);
                    if (!counterLike) continue;
                    const value = `${text}@${Math.round(rect.left)},${Math.round(rect.top)}`;
                    if (!seen.has(value)) {
                      seen.add(value);
                      out.push(value);
                    }
                    if (out.length >= 30) break;
                  }
                  return out;
                }
                """
            )
        except Exception:
            return []

    def _click_evidence_changed(
        self,
        before: dict,
        after: dict,
        description: str = "",
    ) -> bool:
        """Return True only when click evidence shows an observable state change."""
        if not before or not after:
            return False

        pre_url = before.get("url") or ""
        post_url = after.get("url") or ""
        if pre_url and post_url and pre_url != post_url:
            return True

        pre_count = int(before.get("target_count") or 0)
        post_count = int(after.get("target_count") or 0)
        if pre_count != post_count:
            return True

        if before.get("target_checked") != after.get("target_checked"):
            return True

        pre_dom = int(before.get("dom_count") or 0)
        post_dom = int(after.get("dom_count") or 0)
        if pre_dom and post_dom and abs(post_dom - pre_dom) >= 2:
            return True

        before_label = _norm_click_label(
            before.get("target_text", ""),
            before.get("target_value", ""),
        )
        after_label = _norm_click_label(
            after.get("target_text", ""),
            after.get("target_value", ""),
        )
        if before_label != after_label:
            desc = (description or "").lower()
            if "add" in desc and "add" in before_label and "remove" in after_label:
                return True
            if "remove" in desc and "remove" in before_label:
                return True
            if "continue" in desc or "checkout" in desc:
                return True
            if before_label and after_label:
                return True

        before_state = set(before.get("generic_visible_state") or [])
        after_state = set(after.get("generic_visible_state") or [])
        if before_state != after_state:
            return True

        return False

    async def _click_once_with_evidence(
        self,
        selector: str,
        locator_type: str,
        description: str,
        timeout_ms: int,
    ) -> tuple[bool, str, dict]:
        """Validate, click once, then accept only if before/after evidence changes."""
        before = await self._capture_click_evidence(selector, locator_type)
        if before.get("target_count") != 1:
            return False, "AMBIGUOUS_CLICK_TARGET", {"before": before, "after": {}}

        locator = self._make_locator(selector, locator_type)
        try:
            await locator.first.click(timeout=timeout_ms)
        except Exception as exc:
            after = await self._capture_click_evidence(selector, locator_type)
            evidence = {
                "before": before,
                "after": after,
                "changed": self._click_evidence_changed(before, after, description),
            }
            if evidence["changed"]:
                return True, "", evidence
            return False, f"CLICK_TARGET_NOT_ACTIONABLE:{exc}", evidence

        after = await self._capture_click_evidence(selector, locator_type)
        evidence = {
            "before": before,
            "after": after,
            "changed": self._click_evidence_changed(before, after, description),
        }
        if not evidence["changed"]:
            return False, "NO_CLICK_STATE_CHANGE", evidence
        return True, "", evidence

    async def _verify_repair(
        self,
        action: str,
        selector: str,
        fill_value: str = "",
        locator_type: str = "css",
        pre_url: str = "",
        pre_dom_count: int = 0,
        description: str = "",
    ) -> bool:
        """Return True when a healed action looks like a false repair."""
        desc = (description or "").lower()

        try:
            loc = self._make_locator(selector, locator_type).first

            if action == "fill" and fill_value:
                try:
                    actual = await loc.input_value(timeout=1500)
                    return actual.strip() != fill_value.strip()
                except Exception:
                    return False

            if action == "select" and fill_value:
                try:
                    actual = await loc.input_value(timeout=1500)
                    return actual.strip() != fill_value.strip()
                except Exception:
                    return False

            if action == "click":
                try:
                    if await self._make_locator(selector, locator_type).count() == 0:
                        return False
                except Exception:
                    return False

                try:
                    text = (await loc.inner_text(timeout=800) or "").strip().lower()
                except Exception:
                    text = ""

                try:
                    value = (
                        await loc.evaluate("el => (el.getAttribute('value') || '').toLowerCase()")
                        or ""
                    ).strip().lower()
                except Exception:
                    value = ""

                label = f"{text} {value}".strip()
                if label:
                    if "add to cart" in desc and "add" not in label:
                        return True
                    if "remove" in desc and "remove" not in label:
                        return True
                    if "continue" in desc and "continue" not in label:
                        return True
                    if "checkout" in desc and "checkout" not in label:
                        return True

                post_url = self.page.url
                if post_url and pre_url and post_url != pre_url:
                    return False

                if pre_dom_count > 0:
                    try:
                        post_count = await self.page.evaluate(
                            "document.querySelectorAll('*').length"
                        )
                        delta = abs(post_count - pre_dom_count)
                        if delta >= 3:
                            return False
                        if delta < 2:
                            return True
                    except Exception:
                        pass

                return False

        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # Action execution helpers
    # ------------------------------------------------------------------

    async def _run_action_with_timeout(
        self,
        locator: Locator,
        action: str,
        value: str = "",
        timeout_ms: Optional[int] = None,
    ) -> None:
        timeout_ms = timeout_ms or self._timeout

        if action == "click":
            await locator.click(timeout=timeout_ms)
        elif action == "fill":
            await locator.fill(value, timeout=timeout_ms)
        elif action == "select":
            await locator.select_option(value, timeout=timeout_ms)
        elif action == "expect_visible":
            await locator.wait_for(state="visible", timeout=timeout_ms)
        else:
            raise ValueError(f"Unsupported action: {action!r}")

    async def _try_action(
        self,
        action: str,
        selector: str,
        fill_value: str,
        locator_type: str = "css",
        timeout_ms: Optional[int] = None,
        fast_precheck: bool = False,
    ) -> tuple[bool, str]:
        try:
            if fast_precheck and locator_type == "css":
                count = await self._make_locator(selector, locator_type).count()
                if count == 0:
                    return False, f"Selector not found: {selector}"

            loc = self._make_locator(selector, locator_type).first
            before_url = self.page.url
            try:
                await self._run_action_with_timeout(
                    locator=loc,
                    action=action,
                    value=fill_value,
                    timeout_ms=timeout_ms or self._timeout,
                )
                return True, ""
            except Exception as inner_exc:
                if action == "click" and self.page.url != before_url:
                    return True, ""
                raise inner_exc
        except (PWTimeout, PWError, Exception) as exc:
            return False, str(exc)

    async def _try_action_compat(
        self,
        action: str,
        selector: str,
        fill_value: str,
        locator_type: str = "css",
        timeout_ms: Optional[int] = None,
    ) -> tuple[bool, str]:
        return await self._try_action(
            action=action,
            selector=selector,
            fill_value=fill_value,
            locator_type=locator_type,
            timeout_ms=timeout_ms,
            fast_precheck=False,
        )

    # ------------------------------------------------------------------
    # Action allowance check
    # ------------------------------------------------------------------

    async def _is_candidate_allowed_for_action(
        self,
        action: str,
        selector: str,
        description: str,
        locator_type: str = "css",
    ) -> bool:
        clean_sel = (selector or "").strip().lower()
        desc = (description or "").lower()
        intent = _classify_intent(description, action)

        if clean_sel in _EXCLUDED_SELECTORS:
            return False

        try:
            locator = self._make_locator(selector, locator_type).first
            tag = (await locator.evaluate("el => el.tagName.toLowerCase()")).lower()
        except Exception:
            return False if action == "click" else True

        try:
            text = (await locator.inner_text(timeout=800) or "").strip()
        except Exception:
            text = ""

        try:
            input_type = (
                await locator.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
                or ""
            ).lower()
        except Exception:
            input_type = ""

        try:
            value_attr = (
                await locator.evaluate("el => (el.getAttribute('value') || '').toLowerCase()")
                or ""
            ).strip().lower()
        except Exception:
            value_attr = ""

        text_lower = text.lower()
        label = f"{text_lower} {value_attr}".strip()

        if action == "select" or intent == "dropdown" or "sort" in desc:
            return tag == "select"

        if action == "fill":
            return tag in {"input", "textarea"} and input_type not in {
                "submit", "button", "checkbox", "radio", "hidden",
            }

        if action == "click":
            try:
                if await self._make_locator(selector, locator_type).count() != 1:
                    return False
            except Exception:
                return False

            clickable_tags = {"button", "a", "input", "label", "select"}
            if tag not in clickable_tags:
                try:
                    role = (
                        await locator.evaluate("el => el.getAttribute('role') || ''")
                    ).lower()
                    return role in {
                        "button", "link", "menuitem", "tab",
                        "checkbox", "radio", "switch",
                    }
                except Exception:
                    return False

            if tag == "input" and input_type in {"hidden", "radio"}:
                return False

            if "add to cart" in desc and label and "add" not in label:
                return False
            if "remove" in desc and label and "remove" not in label:
                return False
            if "continue" in desc and label and "continue" not in label:
                return False
            if "checkout" in desc and label and "checkout" not in label:
                return False

            if intent == "action_button":
                if tag == "a":
                    return False
                if tag == "input":
                    return input_type in {"submit", "button"}
                return tag in {"button", "label"}

            if intent == "navigation_link":
                return tag == "a"

            if intent == "checkbox":
                if tag == "input":
                    return input_type == "checkbox"
                return tag == "label"

            if label and desc:
                desc_norm = re.sub(r"[-_]", " ", desc)
                for intent_phrase, required_word in _INTENT_TEXT_MAP:
                    phrase_norm = re.sub(r"[-_]", " ", intent_phrase)
                    if phrase_norm in desc_norm:
                        return required_word in label

            return True

        if action == "expect_visible":
            if any(w in desc for w in {"continue", "checkout", "remove", "add to cart"}):
                if label:
                    if "continue" in desc and "continue" not in label:
                        return False
                    if "checkout" in desc and "checkout" not in label:
                        return False
                    if "remove" in desc and "remove" not in label:
                        return False
                    if "add to cart" in desc and "add" not in label:
                        return False

            small_label_words = {
                "quantity", "count", "badge", "price", "qty", "label",
                "cart count", "item count", "number", "total", "amount",
            }
            if any(w in desc for w in small_label_words):
                if "\n" in text or len(text) > 20:
                    return False
                if text and text.upper() == text and not text.strip().isdigit():
                    return False
                numeric_words = {"quantity", "count", "number", "qty"}
                if any(w in desc for w in numeric_words):
                    cleaned = text.strip().replace(",", "").replace(".", "")
                    if text and not cleaned.isdigit():
                        return False
            return len(text) <= 80

        return True

    # ------------------------------------------------------------------
    # DOM extraction and candidate resolution
    # ------------------------------------------------------------------

    async def _extract_dom(self) -> list[dict]:
        try:
            return await self._dom.extract_elements()
        except Exception:
            return []

    async def _resolve_candidates(
        self,
        candidates: list[dict],
        dom_elements: Optional[list[dict]] = None,
    ) -> list[dict]:
        if dom_elements is None:
            dom_elements = await self._extract_dom()

        resolved: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for cand in candidates:
            sel          = cand.get("selector", "")
            locator_type = cand.get("locator_type", "css")
            key          = (locator_type, sel)

            if not sel or key in seen:
                continue
            seen.add(key)

            try:
                count = await self._make_locator(sel, locator_type).count()
            except Exception:
                count = 0

            if count == 0:
                continue

            matched_el = _find_dom_match(sel, dom_elements)
            resolved.append({
                **cand,
                "resolved":       True,
                "matched_count":  count,
                "matched_element": matched_el,
            })

        return resolved

    def _score_candidates(
        self,
        resolved: list[dict],
        expected_profile: dict,
        action: str = "",
        description: str = "",
    ) -> list[dict]:
        return [
            lv.score_candidate(
                expected_profile=expected_profile,
                matched_element=cand.get("matched_element"),
                candidate=cand,
                action=action,
                description=description,
            )
            for cand in resolved
        ]

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_result(
        self,
        action: str,
        description: str,
        result: HealingResult,
    ) -> None:
        try:
            entry = asdict(result)
            entry["action"]           = action
            entry["description"]      = description
            entry["page_url"]         = self.page.url
            entry["healing_mode"]     = self._mode
            entry["stage"]            = _infer_heal_stage(result)
            entry["candidate_count"]  = len(result.candidates)
            entry["dom_element_count"] = result.dom_element_count
            entry["winning_score"]    = result.winning_score
            entry["score_margin"]     = result.score_margin
            entry["rejection_reasons"] = result.rejection_reasons
            entry["false_repair"]     = result.false_repair
            entry["risk_flags"]       = _build_risk_flags(result)
            entry["ambiguous"]        = (
                result.score_margin < LOW_MARGIN_THRESHOLD and result.success
            )
            append_experiment_log(entry)
            print(_format_result_brief(action, description, result))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Locator factory
    # ------------------------------------------------------------------

    def _make_locator(self, selector: str, locator_type: str = "css") -> Locator:
        if locator_type.startswith("role:"):
            role = locator_type.split(":", 1)[1]
            return self.page.get_by_role(role, name=selector)
        return self.page.locator(selector)


# ---------------------------------------------------------------------------
# Expected-profile builder
# ---------------------------------------------------------------------------

def _build_expected_profile(failed_selector: str, dom_elements: list[dict]) -> dict:
    """
    Attempt to recover the original element's profile from the DOM snapshot
    by matching known patterns in the failed selector string.
    """
    if not dom_elements:
        return {}

    m = re.search(r"#([\w-]+)", failed_selector)
    if m:
        raw_id   = m.group(1)
        clean_id = re.sub(
            r"[-_](broken|old|new|v\d+|backup|test|copy|tmp|temp)$",
            "", raw_id, flags=re.IGNORECASE,
        ).lower()
        el = next((e for e in dom_elements if (e.get("id") or "").lower() == clean_id), None)
        if el:
            return el

    m = re.search(r'name=["\']([^"\']+)["\']', failed_selector)
    if m:
        target = m.group(1).lower()
        el = next((e for e in dom_elements if (e.get("name") or "").lower() == target), None)
        if el:
            return el

    m = re.search(r'data-testid=["\']([^"\']+)["\']', failed_selector)
    if m:
        target = m.group(1).lower()
        el = next(
            (e for e in dom_elements if (e.get("data-testid") or "").lower() == target),
            None,
        )
        if el:
            return el

    m = re.search(r'placeholder=["\']([^"\']+)["\']', failed_selector)
    if m:
        target = m.group(1).lower()
        el = next(
            (e for e in dom_elements if (e.get("placeholder") or "").lower() == target),
            None,
        )
        if el:
            return el

    return {}


def _build_reference_context(
    failed_selector: str,
    description: str,
    dom_elements: list[dict],
) -> dict:
    """
    Build the reference_context dict consumed by HeuristicEngine._build_reference().
    All attribute keys use the hyphenated HTML form ("aria-label", "data-testid")
    so they can be looked up directly in DOM element dicts.
    """
    expected = _build_expected_profile(failed_selector, dom_elements)
    if expected:
        return {
            "tag":         expected.get("tag"),
            "id":          expected.get("id"),
            "name":        expected.get("name"),
            "classes":     expected.get("classes", []),
            "href":        expected.get("href"),
            "text":        expected.get("text") or description,
            "role":        expected.get("role"),
            "type":        expected.get("type"),
            "placeholder": expected.get("placeholder"),
            "aria-label":  expected.get("aria-label"),   # hyphenated — standard form
            "data-testid": expected.get("data-testid"),  # hyphenated — standard form
            "parent_tag":  expected.get("parent_tag"),
            "sibling_tags": expected.get("sibling_tags", []),
            "attrs":       expected,
        }
    return {"text": description}


def _find_dom_match(selector: str, dom_elements: list[dict]) -> Optional[dict]:
    """Reverse-lookup: find the DOM element a selector most likely targets."""
    m = re.match(r"^#([\w-]+)$", selector.strip())
    if m:
        target = m.group(1).lower()
        return next(
            (e for e in dom_elements if (e.get("id") or "").lower() == target), None
        )

    m = re.search(r'data-test=["\']([^"\']+)["\']', selector)
    if m:
        target = m.group(1).lower()
        return next(
            (e for e in dom_elements if (e.get("data-test") or "").lower() == target), None
        )

    m = re.search(r'data-testid=["\']([^"\']+)["\']', selector)
    if m:
        target = m.group(1).lower()
        return next(
            (e for e in dom_elements if (e.get("data-testid") or "").lower() == target), None
        )

    m = re.search(r'name=["\']([^"\']+)["\']', selector)
    if m:
        target = m.group(1).lower()
        return next(
            (e for e in dom_elements if (e.get("name") or "").lower() == target), None
        )

    m = re.search(r'placeholder=["\']([^"\']+)["\']', selector)
    if m:
        target = m.group(1).lower()
        return next(
            (e for e in dom_elements if (e.get("placeholder") or "").lower() == target), None
        )

    m = re.search(r'aria-label=["\']([^"\']+)["\']', selector)
    if m:
        target = m.group(1).lower()
        return next(
            (
                e for e in dom_elements
                if (e.get("aria-label") or (e.get("attrs") or {}).get("aria-label") or "").lower() == target
            ),
            None,
        )

    m = re.search(r'\[class\*=["\']([^"\']+)["\']', selector)
    if m:
        token = m.group(1).lower()
        for e in dom_elements:
            classes_raw = e.get("class") or (e.get("attrs") or {}).get("class") or ""
            classes_str = " ".join(classes_raw).lower() if isinstance(classes_raw, list) \
                          else str(classes_raw).lower()
            if token in classes_str:
                return e

    m = re.search(r':has-text\(["\']([^"\']+)["\']\)', selector)
    if m:
        target_text = m.group(1).lower()
        return next(
            (e for e in dom_elements if target_text in (e.get("text") or "").lower()),
            None,
        )

    return None


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def _classify_intent(description: str, action: str = "") -> str:
    """Classify target intent so valid but wrong elements are rejected early."""
    d = (description or "").lower()

    if action == "fill":
        return "text_input"
    if action == "select" or "sort" in d or "dropdown" in d:
        return "dropdown"
    if any(w in d for w in {"checkbox", "agree", "accept", "consent"}):
        return "checkbox"
    if any(w in d for w in {
        "add to cart", "add item", "remove item", "remove", "checkout",
        "continue", "submit", "register", "login", "sign in", "sign up",
        "place order", "finish", "confirm", "save", "cancel", "delete", "update",
    }):
        return "action_button"
    if any(w in d for w in {
        "link", "privacy", "terms", "policy", "details", "learn more",
        "read more", "product link", "open product",
    }):
        return "navigation_link"
    return "generic"


# ---------------------------------------------------------------------------
# Excluded selectors (generic only — no site-specific IDs)
# ---------------------------------------------------------------------------

# Page-root and browser-level selectors that are never valid heal targets.
# Intentionally minimal — no site-specific IDs.
_EXCLUDED_SELECTORS: frozenset[str] = frozenset({
    "#root",
    "body",
    "html",
})


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for cand in candidates:
        sel          = cand.get("selector", "")
        locator_type = cand.get("locator_type", "css")
        key          = (locator_type, sel)

        if not sel or key in seen:
            continue
        if sel.strip().lower() in _EXCLUDED_SELECTORS:
            continue

        seen.add(key)
        deduped.append(cand)

    return deduped


def _norm_click_label(text: object, value: object = "") -> str:
    return re.sub(r"\s+", " ", f"{text or ''} {value or ''}").strip().lower()


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _infer_heal_stage(result: HealingResult) -> str:
    if result.source == "original":
        return "stage_0"
    if result.source in {"heuristic", "memory"}:
        return "stage_1"
    if result.source == "llm":
        return "stage_2"
    return "failed"


def _build_risk_flags(result: HealingResult) -> list[str]:
    if result.source == "original":
        return []
    flags: list[str] = []
    if result.winning_score < LOW_SCORE_THRESHOLD:
        flags.append("LOW_SCORE")
    if result.score_margin < LOW_MARGIN_THRESHOLD:
        flags.append("LOW_MARGIN")
    if result.false_repair:
        flags.append("FALSE_REPAIR")
    return flags


def _format_result_brief(
    action: str,
    description: str,
    result: HealingResult,
) -> str:
    if result.source == "original":
        return (
            f"[OK] action={action} desc='{description}' "
            f"selector='{result.original_selector}' time={result.repair_time_sec:.3f}s"
        )

    if result.success:
        risk_flags = _build_risk_flags(result)
        risk_text  = f" [{' '.join(risk_flags)}]" if risk_flags else ""
        return (
            f"[HEALED] action={action} desc='{description}' "
            f"'{result.original_selector}' -> '{result.healed_selector}' "
            f"score={result.winning_score:.3f}{risk_text} "
            f"margin={result.score_margin:.3f} "
            f"dom_elements={result.dom_element_count} "
            f"time={result.repair_time_sec:.3f}s"
        )

    return (
        f"[FAIL] action={action} desc='{description}' "
        f"selector='{result.original_selector}' "
        f"attempts={result.attempts} "
        f"rejections={result.rejection_reasons} "
        f"time={result.repair_time_sec:.3f}s"
    )


def _elapsed(t0: float) -> float:
    return round(time.perf_counter() - t0, 4)
