"""
llm/locator_repair.py

LLM-based locator repair: prompt construction, Pydantic models,
LocatorRepairer class, and candidate normalisation.

Supports OpenAI and Anthropic via config.LLM_PROVIDER.

Public API (original — preserved for backward compatibility)
------------------------------------------------------------
    LocatorRepairer               — class: repair(broken_locator, ...) -> RepairResult
    RepairCandidate               — Pydantic model
    RepairResponse                — Pydantic model
    RepairResult                  — Pydantic model
    _build_user_message(...)      — module-level helper
    _parse_response(raw_json)     — module-level helper

Public API (new additions)
--------------------------
    build_repair_prompt(...)      — prompt for LLMClient.suggest_selectors()
    normalize_locator_candidates(raw) -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY: str    = config.OPENAI_API_KEY
OPENAI_MODEL: str      = config.OPENAI_MODEL
ANTHROPIC_API_KEY: str = config.ANTHROPIC_API_KEY
ANTHROPIC_MODEL: str   = config.ANTHROPIC_MODEL
MAX_DOM_ELEMENTS: int  = 80

# ---------------------------------------------------------------------------
# System prompt (shared by LocatorRepairer and build_repair_prompt)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior Playwright test automation engineer specialising in \
self-healing test locators.

A Playwright locator has failed during a test run. Your task is to analyse \
the page DOM and suggest 3 to 5 alternative locators that target the same \
element, ranked by confidence (highest first).

LOCATOR PREFERENCE ORDER (most preferred first):
  1. page.get_by_role(...)          – semantic, WAI-ARIA based
  2. page.get_by_label(...)         – form labels
  3. page.get_by_placeholder(...)   – input placeholders
  4. page.get_by_text(...)          – visible text
  5. page.get_by_alt_text(...)      – image alt text
  6. page.get_by_title(...)         – title attribute
  7. page.locator('[data-testid="…"]')
  8. page.locator('[aria-label="…"]')
  9. page.locator('#id')
 10. CSS selector                   – last resort

RULES:
- Output ONLY a raw JSON object. No markdown, no code fences, no prose.
- Every candidate must include: locator, locator_type, confidence, reasoning.
- locator_type must be one of:
    get_by_role | get_by_label | get_by_placeholder | get_by_text |
    get_by_alt_text | get_by_title | css | xpath
- confidence is a float 0.0 – 1.0.
- reasoning is one short sentence (max 120 chars).
- Return between 3 and 5 candidates.

EXACT OUTPUT SCHEMA:
{
  "candidates": [
    {
      "locator": "page.get_by_role('button', name='Login')",
      "locator_type": "get_by_role",
      "confidence": 0.95,
      "reasoning": "Unique submit button with accessible name Login."
    }
  ]
}
"""

# ---------------------------------------------------------------------------
# Pydantic models (original — preserved)
# ---------------------------------------------------------------------------

LocatorType = Literal[
    "get_by_role",
    "get_by_label",
    "get_by_placeholder",
    "get_by_text",
    "get_by_alt_text",
    "get_by_title",
    "css",
    "xpath",
]


class RepairCandidate(BaseModel):
    """A single locator repair suggestion."""

    locator: str = Field(..., description="Full Playwright locator expression")
    locator_type: LocatorType = Field(..., description="Category of locator")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., max_length=200)

    @field_validator("locator")
    @classmethod
    def locator_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("locator must not be empty")
        return v

    @field_validator("reasoning")
    @classmethod
    def reasoning_not_empty(cls, v: str) -> str:
        return v.strip() or "No reasoning provided."


class RepairResponse(BaseModel):
    """Validated LLM response containing all repair candidates."""

    candidates: list[RepairCandidate] = Field(..., min_length=1, max_length=10)

    @field_validator("candidates")
    @classmethod
    def sort_by_confidence(cls, v: list[RepairCandidate]) -> list[RepairCandidate]:
        return sorted(v, key=lambda c: c.confidence, reverse=True)


class RepairResult(BaseModel):
    """Final result returned to callers of LocatorRepairer.repair()."""

    success: bool
    candidates: list[RepairCandidate] = Field(default_factory=list)
    best: Optional[RepairCandidate] = None
    broken_locator: str = ""
    action: str = ""
    model: str = ""
    tokens_used: int = 0
    latency_ms: float = 0.0
    error: str = ""

    def above_threshold(self, min_confidence: float = 0.5) -> list[RepairCandidate]:
        return [c for c in self.candidates if c.confidence >= min_confidence]


# ---------------------------------------------------------------------------
# LocatorRepairer (original class — preserved)
# ---------------------------------------------------------------------------

class LocatorRepairer:
    """
    Sends a broken locator + DOM context to an LLM and returns structured
    repair candidates.

    Provider is selected via ``config.LLM_PROVIDER``:
      - "openai"    → OpenAI GPT (default)
      - "anthropic" → Anthropic Claude
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        provider = config.LLM_PROVIDER.lower()

        if provider == "anthropic":
            from anthropic import AsyncAnthropic
            self._backend = "anthropic"
            self._client = AsyncAnthropic(api_key=api_key or ANTHROPIC_API_KEY)
            self.model = model or ANTHROPIC_MODEL
        else:
            from openai import AsyncOpenAI
            self._backend = "openai"
            self._client = AsyncOpenAI(api_key=api_key or OPENAI_API_KEY)
            self.model = model or OPENAI_MODEL

    async def repair(
        self,
        broken_locator: str,
        action: str,
        error_message: str,
        dom_elements: list[dict[str, Any]],
        *,
        min_confidence: float = 0.0,
    ) -> RepairResult:
        """
        Request locator repair from the configured LLM.

        Returns RepairResult — never raises; errors are in ``.error``.
        """
        t0 = time.perf_counter()

        user_message = _build_user_message(
            broken_locator=broken_locator,
            action=action,
            error_message=error_message,
            dom_elements=dom_elements,
        )

        try:
            raw_json, tokens = await self._call_llm(user_message)
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return RepairResult(
                success=False,
                broken_locator=broken_locator,
                action=action,
                model=self.model,
                latency_ms=_ms(t0),
                error=str(exc),
            )

        latency = _ms(t0)

        try:
            response = _parse_response(raw_json)
        except Exception as exc:
            logger.error("Response parsing failed: %s — raw: %r", exc, raw_json)
            return RepairResult(
                success=False,
                broken_locator=broken_locator,
                action=action,
                model=self.model,
                tokens_used=tokens,
                latency_ms=latency,
                error=f"Parse error: {exc}",
            )

        candidates = (
            [c for c in response.candidates if c.confidence >= min_confidence]
            if min_confidence > 0.0
            else response.candidates
        )

        logger.info(
            "Repair complete — %d candidates, best=%r (%.2f) in %.0f ms",
            len(candidates),
            candidates[0].locator if candidates else None,
            candidates[0].confidence if candidates else 0,
            latency,
        )

        return RepairResult(
            success=True,
            candidates=candidates,
            best=candidates[0] if candidates else None,
            broken_locator=broken_locator,
            action=action,
            model=self.model,
            tokens_used=tokens,
            latency_ms=latency,
        )

    async def _call_llm(self, user_message: str) -> tuple[str, int]:
        if self._backend == "anthropic":
            return await self._call_anthropic(user_message)
        return await self._call_openai(user_message)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_openai(self, user_message: str) -> tuple[str, int]:
        response = await self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        content = response.choices[0].message.content or "{}"
        tokens = response.usage.total_tokens if response.usage else 0
        return content, tokens

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_anthropic(self, user_message: str) -> tuple[str, int]:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        content = response.content[0].text if response.content else "{}"
        tokens = (
            response.usage.input_tokens + response.usage.output_tokens
            if response.usage else 0
        )
        return content, tokens


# ---------------------------------------------------------------------------
# Module-level helpers (original — preserved)
# ---------------------------------------------------------------------------

def _build_user_message(
    broken_locator: str,
    action: str,
    error_message: str,
    dom_elements: list[dict[str, Any]],
) -> str:
    trimmed = dom_elements[:MAX_DOM_ELEMENTS]
    dom_json = json.dumps(trimmed, indent=2, ensure_ascii=False)
    return (
        f"BROKEN LOCATOR : {broken_locator}\n"
        f"ACTION         : {action}\n"
        f"ERROR MESSAGE  : {error_message}\n\n"
        f"PAGE DOM ({len(trimmed)} of {len(dom_elements)} elements):\n"
        f"{dom_json}"
    )


def _parse_response(raw_json: str) -> RepairResponse:
    data = json.loads(raw_json)
    if isinstance(data, list):
        data = {"candidates": data}
    return RepairResponse.model_validate(data)


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


# ---------------------------------------------------------------------------
# New additions — used by LLMClient.suggest_selectors()
# ---------------------------------------------------------------------------

_VALID_LOCATOR_TYPES: frozenset[str] = frozenset(
    {"css", "text", "role", "label", "placeholder", "test_id", "xpath"}
)

_NEW_SYSTEM_INSTRUCTION = """\
You are a senior Playwright test automation engineer specialising in \
self-healing UI test locators.

A Playwright locator has failed. Analyse the page DOM and suggest up to \
{max_candidates} alternative locators that target the same element.

LOCATOR PREFERENCE ORDER (most preferred first):
  1. [data-testid="…"]
  2. [aria-label="…"]
  3. #id
  4. input[name="…"] / select[name="…"]
  5. role + accessible name
  6. visible text match
  7. CSS selector

OUTPUT FORMAT — respond with ONLY this JSON, no markdown, no prose:
{{
  "candidates": [
    {{
      "selector":     "…",
      "locator_type": "css" | "text" | "role" | "label" | "placeholder" | "test_id" | "xpath",
      "confidence":   0.0–1.0,
      "reason":       "one short sentence"
    }}
  ]
}}
"""


def build_repair_prompt(
    failed_selector: str,
    action_description: str,
    dom_prompt_context: str,
    max_candidates: int = 5,
) -> str:
    """Build the user-turn prompt for LLMClient.suggest_selectors()."""
    system_block = _NEW_SYSTEM_INSTRUCTION.format(max_candidates=max_candidates)
    return (
        f"{system_block}\n"
        f"---\n"
        f"FAILED SELECTOR  : {failed_selector}\n"
        f"ACTION           : {action_description or 'unknown'}\n\n"
        f"PAGE DOM SNAPSHOT:\n"
        f"{dom_prompt_context}\n"
    )


def normalize_locator_candidates(raw_candidates: list[Any]) -> list[dict]:
    """
    Normalise raw LLM output into a clean candidate list.

    - Skip empty selectors and duplicates.
    - Clamp confidence to [0.0, 1.0]; default 0.5 if missing/invalid.
    - Map unknown locator_type to "css".
    - Force source="llm".
    """
    seen: set[str] = set()
    result: list[dict] = []

    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or "").strip()
        if not selector or selector in seen:
            continue
        seen.add(selector)

        raw_type = str(raw.get("locator_type") or "").lower().strip()
        cleaned_type = re.sub(r"[^a-z_]", "", raw_type)
        locator_type = cleaned_type if cleaned_type in _VALID_LOCATOR_TYPES else "css"

        try:
            confidence = float(raw.get("confidence", 0.5))
            confidence = round(max(0.0, min(1.0, confidence)), 4)
        except (TypeError, ValueError):
            confidence = 0.5

        reason = str(raw.get("reason") or "LLM-suggested locator.").strip() or "LLM-suggested locator."

        result.append({
            "selector":     selector,
            "locator_type": locator_type,
            "source":       "llm",
            "confidence":   confidence,
            "reason":       reason,
        })

    return result
