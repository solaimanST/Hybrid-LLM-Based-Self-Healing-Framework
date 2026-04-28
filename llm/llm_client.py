"""
llm/llm_client.py

Unified async LLM client supporting OpenAI and Anthropic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config
from llm.locator_repair import build_repair_prompt, normalize_locator_candidates

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Async LLM client for locator repair suggestions.
    """

    def __init__(self) -> None:
        self._provider = config.LLM_PROVIDER.lower()
        self._client: Any = None
        self._ready = False

        try:
            if self._provider == "openai":
                from openai import AsyncOpenAI

                api_key = config.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

                if not api_key:
                    logger.warning("LLMClient: OPENAI_API_KEY is missing.")
                    return

                self._client = AsyncOpenAI(api_key=api_key)
                self._ready = True

            elif self._provider == "anthropic":
                from anthropic import AsyncAnthropic

                api_key = config.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY")

                if not api_key:
                    logger.warning("LLMClient: ANTHROPIC_API_KEY is missing.")
                    return

                self._client = AsyncAnthropic(api_key=api_key)
                self._ready = True

            else:
                logger.warning(
                    "LLMClient: unknown LLM_PROVIDER %r. Returning no candidates.",
                    self._provider,
                )

        except Exception as exc:
            logger.warning(
                "LLMClient: could not initialise provider %r: %s",
                self._provider,
                exc,
            )

    async def suggest_selectors(
        self,
        failed_selector: str,
        dom_snapshot: str,
        action_description: str = "",
        max_candidates: int = 5,
    ) -> list[dict]:
        if not self._ready:
            logger.warning("LLMClient: provider not ready. Returning no candidates.")
            return []

        prompt = build_repair_prompt(
            failed_selector=failed_selector,
            action_description=action_description,
            dom_prompt_context=dom_snapshot,
            max_candidates=max_candidates,
        )

        try:
            raw_text = await self._call(prompt, max_candidates)
        except Exception as exc:
            logger.warning("LLMClient: API call failed: %s", exc)
            return []

        raw_candidates = self._parse_candidates(raw_text)
        normalised = normalize_locator_candidates(raw_candidates)

        logger.info(
            "LLMClient: %d candidate(s) returned for %r",
            len(normalised),
            failed_selector,
        )

        return normalised

    async def _call(self, prompt: str, max_candidates: int) -> str:
        if self._provider == "openai":
            return await self._call_openai(prompt, max_candidates)

        if self._provider == "anthropic":
            return await self._call_anthropic(prompt, max_candidates)

        return "{}"

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _call_openai(self, prompt: str, max_candidates: int) -> str:
        max_tokens = max(256, max_candidates * 140 + 100)

        response = await self._client.chat.completions.create(
            model=config.OPENAI_MODEL,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        return response.choices[0].message.content or "{}"

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _call_anthropic(self, prompt: str, max_candidates: int) -> str:
        max_tokens = max(256, max_candidates * 140 + 100)

        response = await self._client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        return response.content[0].text if response.content else "{}"

    @staticmethod
    def _parse_candidates(raw_text: str) -> list[dict]:
        try:
            text = raw_text.strip()

            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.I)
                text = text.rstrip("`").strip()

            data = json.loads(text)

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                candidates = data.get("candidates")
                if isinstance(candidates, list):
                    return candidates

                for val in data.values():
                    if isinstance(val, list):
                        return val

            return []

        except Exception as exc:
            logger.warning(
                "LLMClient: could not parse LLM response: %s. Raw: %r",
                exc,
                raw_text[:200],
            )
            return []