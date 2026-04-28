"""
engine/heuristic_engine.py

Stage-1 heuristic healing engine.

Scoring weights in _recompute_final_score (sum to 1.0 for base):
    attr_sim      0.30   — identity attributes (primary discriminator)
    tag_sim       0.15   — structural tag (also enforced as hard multiplier)
    structure_sim 0.15   — parent-tag + sibling-tag context
    text_sim      0.10   — visible text (intentionally low)
    stability     0.10   — selector-type robustness
    action_fit    0.10   — action / tag compatibility
    confidence    0.10   — self-reported
Small additive bonuses (bounded, do not shift rank order dramatically):
    uniqueness    up to +0.08
    source_prior  up to +0.04
    specificity_bonus, action_specific_boost, semantic_description_boost, etc.

Tag-action hard constraint:
    fill   → tag ∉ {input, textarea}  → multiplier = 0.0  (hard zero)
    select → tag ≠ select             → multiplier = 0.0
    click  → non-interactive tag      → multiplier = 0.2 (kept in list but low)
             tag ∉ clickable AND no interactive role → multiplier = 0.0
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


@dataclass
class ReferenceElement:
    failed_selector: str
    action: str
    description: str = ""
    tag: Optional[str] = None
    id_value: Optional[str] = None
    name: Optional[str] = None
    classes: List[str] = field(default_factory=list)
    href: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    type_attr: Optional[str] = None
    placeholder: Optional[str] = None
    aria_label: Optional[str] = None
    data_testid: Optional[str] = None
    parent_tag: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    selector: str
    locator_type: str = "css"
    source: str = "heuristic"
    confidence: float = 0.5
    reason: str = ""
    tag: Optional[str] = None
    text: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)

    attr_sim: float = 0.0
    text_sim: float = 0.0
    tag_sim: float = 0.0
    structure_sim: float = 0.0
    stability: float = 0.0
    action_fit: float = 0.0
    uniqueness: float = 0.0
    source_prior: float = 0.0
    brittleness_penalty: float = 0.0
    specificity_bonus: float = 0.0
    partial_class_sim: float = 0.0
    proximity: float = 0.0
    final_score: float = 0.0

    validation: Dict[str, Any] = field(default_factory=dict)
    signals: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "selector": self.selector,
            "locator_type": self.locator_type,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "tag": self.tag,
            "text": self.text,
            "attr_sim": round(self.attr_sim, 4),
            "text_sim": round(self.text_sim, 4),
            "tag_sim": round(self.tag_sim, 4),
            "structure_sim": round(self.structure_sim, 4),
            "stability": round(self.stability, 4),
            "action_fit": round(self.action_fit, 4),
            "uniqueness": round(self.uniqueness, 4),
            "source_prior": round(self.source_prior, 4),
            "brittleness_penalty": round(self.brittleness_penalty, 4),
            "specificity_bonus": round(self.specificity_bonus, 4),
            "partial_class_sim": round(self.partial_class_sim, 4),
            "proximity": round(self.proximity, 4),
            "final_score": round(self.final_score, 4),
            "validation": self.validation,
            "signals": self.signals,
        }


@dataclass
class HeuristicRepairResult:
    success: bool
    healed_selector: Optional[str]
    locator_type: Optional[str]
    source: str
    winning_score: float
    repair_time_sec: float
    attempts: int
    candidates: List[Dict[str, Any]]
    top_score: float = 0.0
    second_score: float = 0.0
    score_margin: float = 0.0
    error: Optional[str] = None


class HeuristicEngine:
    MIN_SCORE = 0.45

    _TRIVIAL_SELECTORS: frozenset[str] = frozenset({"#root", "body", "html"})
    _CLICKABLE_TAGS:    frozenset[str] = frozenset({"button", "a", "input", "label", "select"})
    _INTERACTIVE_ROLES: frozenset[str] = frozenset({
        "button", "link", "menuitem", "tab",
        "checkbox", "radio", "switch", "option",
    })

    def __init__(
        self,
        memory_store: Optional[Any] = None,
        max_validate: int = 12,
        max_try: int = 4,
        timeout_ms: int = 1500,
    ) -> None:
        self.memory_store = memory_store
        self.max_validate = max_validate
        self.max_try = max_try
        self.timeout_ms = timeout_ms

    async def repair(
        self,
        page: Page,
        failed_selector: str,
        action: str,
        action_fn: Callable[[Locator], Awaitable[None]],
        dom_snapshot: List[Dict[str, Any]],
        description: str = "",
        reference_context: Optional[Dict[str, Any]] = None,
    ) -> HeuristicRepairResult:
        start = time.perf_counter()

        try:
            ref = self._build_reference(
                failed_selector=failed_selector,
                action=action,
                description=description,
                reference_context=reference_context or {},
            )

            raw_candidates = self._collect_candidates(ref, dom_snapshot)
            ranked = self._rank_candidates(ref, raw_candidates)

            validated: List[Candidate] = []
            for cand in ranked[: self.max_validate]:
                cand.validation = await self._validate_candidate(
                    page, cand, action, ref=ref
                )
                if cand.validation.get("valid"):
                    cand.uniqueness = self._compute_uniqueness_score(
                        cand.validation.get("match_count", 0)
                    )
                    cand.action_fit = self._compute_action_fit_from_validation(
                        action, cand.validation
                    )
                    cand.final_score = self._recompute_final_score(cand, ref)

                    if cand.final_score >= self.MIN_SCORE:
                        validated.append(cand)

            validated.sort(
                key=lambda c: (
                    c.final_score,
                    c.specificity_bonus,
                    c.uniqueness,
                    c.validation.get("visible", False),
                    c.confidence,
                ),
                reverse=True,
            )

            top_score    = validated[0].final_score if validated else 0.0
            second_score = validated[1].final_score if len(validated) > 1 else 0.0
            score_margin = max(0.0, top_score - second_score)

            attempts = 0
            for cand in validated[: self.max_try]:
                attempts += 1
                locator = self._make_locator(page, cand)
                try:
                    await action_fn(locator)
                    elapsed = time.perf_counter() - start

                    if self.memory_store is not None:
                        self._save_memory(ref, cand)

                    return HeuristicRepairResult(
                        success=True,
                        healed_selector=cand.selector,
                        locator_type=cand.locator_type,
                        source=cand.source,
                        winning_score=cand.final_score,
                        repair_time_sec=round(elapsed, 4),
                        attempts=attempts,
                        candidates=[c.as_dict() for c in validated[: self.max_try]],
                        top_score=top_score,
                        second_score=second_score,
                        score_margin=score_margin,
                        error=None,
                    )
                except Exception:
                    continue

            elapsed = time.perf_counter() - start
            return HeuristicRepairResult(
                success=False,
                healed_selector=None,
                locator_type=None,
                source="failed",
                winning_score=0.0,
                repair_time_sec=round(elapsed, 4),
                attempts=attempts,
                candidates=[c.as_dict() for c in validated[: self.max_try]],
                top_score=top_score,
                second_score=second_score,
                score_margin=score_margin,
                error="No valid heuristic candidate succeeded",
            )

        except Exception as e:
            elapsed = time.perf_counter() - start
            return HeuristicRepairResult(
                success=False,
                healed_selector=None,
                locator_type=None,
                source="failed",
                winning_score=0.0,
                repair_time_sec=round(elapsed, 4),
                attempts=0,
                candidates=[],
                top_score=0.0,
                second_score=0.0,
                score_margin=0.0,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Reference builder
    # ------------------------------------------------------------------

    def _build_reference(
        self,
        failed_selector: str,
        action: str,
        description: str,
        reference_context: Dict[str, Any],
    ) -> ReferenceElement:
        parsed = self._parse_selector_hints(failed_selector)

        return ReferenceElement(
            failed_selector=failed_selector,
            action=action,
            description=description or "",
            tag=reference_context.get("tag") or parsed.get("tag"),
            id_value=reference_context.get("id") or parsed.get("id"),
            name=reference_context.get("name"),
            classes=reference_context.get("classes", []),
            href=reference_context.get("href"),
            text=reference_context.get("text") or description or parsed.get("text"),
            role=reference_context.get("role"),
            type_attr=reference_context.get("type"),
            placeholder=reference_context.get("placeholder"),
            # Always read "aria-label" (hyphenated) from context dict.
            # The reference_context builder normalises to this key.
            aria_label=reference_context.get("aria-label"),
            data_testid=reference_context.get("data-testid"),
            parent_tag=reference_context.get("parent_tag"),
            attrs=reference_context.get("attrs", {}),
        )

    def _parse_selector_hints(self, selector: str) -> Dict[str, Optional[str]]:
        result: Dict[str, Optional[str]] = {"tag": None, "id": None, "text": None}
        selector = selector.strip()

        m = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*)", selector)
        if m:
            result["tag"] = m.group(1).lower()

        m = re.search(r"#([a-zA-Z0-9_-]+)", selector)
        if m:
            result["id"] = m.group(1)

        m = re.search(r':has-text\("([^"]+)"\)', selector)
        if m:
            result["text"] = m.group(1)

        return result

    # ------------------------------------------------------------------
    # Candidate collection
    # ------------------------------------------------------------------

    def _collect_candidates(
        self,
        ref: ReferenceElement,
        dom_snapshot: List[Dict[str, Any]],
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        seen: set[Tuple[str, str]] = set()

        def add_candidate(c: Candidate) -> None:
            key = (c.locator_type, c.selector)
            if not c.selector or key in seen:
                return
            if c.selector.strip().lower() in self._TRIVIAL_SELECTORS:
                return
            seen.add(key)
            candidates.append(c)

        # Memory hits (highest prior)
        if self.memory_store is not None:
            try:
                for hit in self.memory_store.find_similar(ref) or []:
                    add_candidate(Candidate(
                        selector=hit.get("healed_selector", ""),
                        locator_type=hit.get("locator_type", "css"),
                        source="memory",
                        confidence=float(hit.get("confidence", 0.9)),
                        reason="memory match",
                        tag=hit.get("tag"),
                        text=hit.get("text"),
                        attrs=hit,
                    ))
            except Exception:
                pass

        # Primary: heuristic_generator (all 5 strategies, action-filtered)
        from engine.heuristic_generator import generate as _hg_generate
        for hc in _hg_generate(
            ref.failed_selector,
            dom_snapshot,
            description=ref.description,
            action=ref.action,          # NEW: pass action for early filtering
        ):
            add_candidate(self._map_heuristic_candidate(hc, dom_snapshot))

        # Fallback: if generator produced nothing (empty DOM or all strategies
        # returned nothing), run the per-element builder so the pipeline never
        # returns an empty candidate list.
        if not any(c.source == "heuristic" for c in candidates):
            for el in dom_snapshot:
                for cand in self._build_heuristic_candidates(ref, el):
                    add_candidate(cand)
            for cand in self._fuzzy_dom_scan(ref, dom_snapshot):
                add_candidate(cand)

        return candidates

    def _build_heuristic_candidates(
        self,
        ref: ReferenceElement,
        el: Dict[str, Any],
    ) -> List[Candidate]:
        """
        Fallback per-element candidate builder.  Only runs when heuristic_generator
        produces nothing.  Applies the same action-based tag filtering.
        """
        out: List[Candidate] = []
        attrs = el.get("attrs") or {}

        tag = (el.get("tag") or "").strip().lower()

        # Action-based early filtering — skip elements structurally incompatible
        # with the action before generating any candidates.
        if ref.action == "fill" and tag and tag not in {"input", "textarea"}:
            return []
        if ref.action == "select" and tag and tag != "select":
            return []
        if ref.action == "click" and tag and tag not in self._CLICKABLE_TAGS:
            role = (el.get("role") or attrs.get("role") or "").lower()
            if role not in self._INTERACTIVE_ROLES:
                return []

        text       = self._normalize_space(el.get("text") or "")
        href       = el.get("href") or attrs.get("href")
        id_value   = el.get("id") or attrs.get("id")
        name       = el.get("name") or attrs.get("name")
        data_testid = el.get("data-testid") or el.get("data_testid") or attrs.get("data-testid")
        data_test  = el.get("data-test") or ""
        data_cy    = el.get("data-cy") or ""
        role_attr  = el.get("role") or attrs.get("role") or ""
        aria_label = el.get("aria-label") or attrs.get("aria-label")
        placeholder = el.get("placeholder") or attrs.get("placeholder")
        type_attr  = el.get("type") or attrs.get("type")
        value_attr = el.get("value") or attrs.get("value") or ""
        parent_tag = el.get("parent_tag")
        classes    = self._stable_classes(
            self._parse_class_value(el.get("class") or attrs.get("class") or "")
        )

        def add(selector: str, confidence: float, reason: str,
                locator_type: str = "css") -> None:
            out.append(Candidate(
                selector=selector,
                locator_type=locator_type,
                source="heuristic",
                confidence=max(0.0, min(1.0, confidence)),
                reason=reason,
                tag=tag or None,
                text=text or None,
                attrs=el,
            ))

        if id_value and not self._looks_dynamic_token(id_value):
            add(f'#{self._css_escape(id_value)}', 0.96, "stable id")

        if data_testid:
            add(f'[data-testid="{self._css_escape(data_testid)}"]', 0.95, "data-testid")

        if data_test:
            add(f'[data-test="{self._css_escape(data_test)}"]', 0.95, "data-test")

        if data_cy:
            add(f'[data-cy="{self._css_escape(data_cy)}"]', 0.94, "data-cy")

        if role_attr:
            if tag:
                add(f'{tag}[role="{self._css_escape(role_attr)}"]', 0.88, "tag+role")
            add(f'[role="{self._css_escape(role_attr)}"]', 0.84, "role attr")

        if name:
            if tag:
                add(f'{tag}[name="{self._css_escape(name)}"]', 0.91, "tag+name")
            add(f'[name="{self._css_escape(name)}"]', 0.88, "name")

        if aria_label:
            if tag:
                add(f'{tag}[aria-label="{self._css_escape(aria_label)}"]', 0.90, "tag+aria-label")
            add(f'[aria-label="{self._css_escape(aria_label)}"]', 0.87, "aria-label")

        if placeholder and tag in {"input", "textarea"}:
            add(f'{tag}[placeholder="{self._css_escape(placeholder)}"]', 0.86, "placeholder")

        if tag == "a":
            if href:
                add(f'a[href="{self._css_escape(href)}"]', 0.92, "exact href")
            if text:
                add(f'a:has-text("{self._css_escape(text)}")', 0.89, "link text")
                add(text, 0.91, "role link + text", locator_type="role:link")

        if tag == "button":
            if text:
                add(f'button:has-text("{self._css_escape(text)}")', 0.89, "button text")
                add(text, 0.91, "role button + text", locator_type="role:button")

        if tag == "input":
            if type_attr:
                add(f'input[type="{self._css_escape(type_attr)}"]', 0.70, "input type")

                if type_attr in {"submit", "button"}:
                    effective_label = (el.get("value") or attrs.get("value") or text)
                    if effective_label:
                        add(
                            f'input[value="{self._css_escape(effective_label)}"]',
                            0.94, "submit by value",
                        )
                        add(
                            f'input[type="{self._css_escape(type_attr)}"][value="{self._css_escape(effective_label)}"]',
                            0.97, "submit by type+value",
                        )

                if type_attr == "checkbox":
                    if name:
                        add(f'input[type="checkbox"][name="{self._css_escape(name)}"]', 0.96, "checkbox name")
                    add('input[type="checkbox"]', 0.72, "checkbox type")

            if type_attr in {"", "text", "email", "password", "tel", "search"}:
                if aria_label:
                    add(aria_label, 0.88, "role textbox + label", locator_type="role:textbox")
                elif placeholder:
                    add(placeholder, 0.84, "role textbox + placeholder", locator_type="role:textbox")
                elif name:
                    add(name, 0.80, "role textbox + name", locator_type="role:textbox")

        # Interactive tags only — no :has-text() on layout containers
        if tag in {"a", "button", "label"} and text:
            add(f'{tag}:has-text("{self._css_escape(text)}")', 0.78, "tag+text")

        # Partial class token matching
        broken_cls_tokens = self._extract_class_tokens_from_selector(ref.failed_selector)
        if broken_cls_tokens:
            all_cls = self._parse_class_value(el.get("class") or attrs.get("class") or "")
            all_cls_str = " ".join(all_cls).lower()
            for token in broken_cls_tokens:
                if token in all_cls_str:
                    esc = self._css_escape(token)
                    add(f'[class*="{esc}"]', 0.62, f"partial class: {token!r}")
                    if tag:
                        add(f'{tag}[class*="{esc}"]', 0.66, f"tag+partial class: {token!r}")

        if tag and classes:
            add(f'{tag}.' + ".".join(self._css_escape(c) for c in classes), 0.58, "stable class combo")
            add(f'.{self._css_escape(classes[0])}', 0.50, "single stable class")

        if tag and parent_tag:
            add(f"{parent_tag} {tag}", 0.30, "parent+tag structural")

        if ref.action == "fill":
            desc = self._normalize_space(ref.description)
            if desc:
                for phrase in self._meaningful_phrases(desc):
                    add(f'input[placeholder*="{self._css_escape(phrase)}"]', 0.57, "description placeholder hint")
                    add(f'input[name*="{self._css_escape(phrase)}"]', 0.57, "description name hint")
                    add(phrase, 0.60, "role textbox + description hint", locator_type="role:textbox")

        if ref.action == "click":
            desc = self._normalize_space(ref.description).lower()
            if "continue" in desc or "submit" in desc or "register" in desc:
                if tag == "input" and type_attr == "submit":
                    add('input[type="submit"]', 0.97, "submit input")
                    if text:
                        add(f'input[value="{self._css_escape(text)}"]', 0.99, "submit by value")
                if tag == "button" and text:
                    add(f'button:has-text("{self._css_escape(text)}")', 0.80, "button submit text")
                    add(text, 0.82, "role button submit text", locator_type="role:button")

        return out

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_candidates(
        self,
        ref: ReferenceElement,
        candidates: List[Candidate],
    ) -> List[Candidate]:
        for cand in candidates:
            cand.attr_sim      = self._attribute_similarity(ref, cand.attrs)
            cand.text_sim      = self._text_similarity(
                ref.text or ref.description or "",
                cand.text or cand.attrs.get("text", ""),
            )
            cand.tag_sim       = self._tag_similarity(ref.tag, cand.tag)
            cand.structure_sim = self._structure_similarity(ref, cand.attrs)
            cand.stability     = self._compute_stability_score(cand.selector, cand.locator_type)
            cand.action_fit    = self._static_action_fit(ref.action, cand)
            cand.uniqueness    = 0.5
            cand.source_prior  = self._source_prior(cand.source)
            cand.brittleness_penalty = self._brittleness_penalty(cand.selector)
            cand.specificity_bonus   = self._specificity_bonus(cand)
            cand.partial_class_sim   = self._partial_class_similarity(ref, cand.attrs)
            cand.proximity           = self._proximity_score(ref, cand)
            cand.final_score         = self._recompute_final_score(cand, ref)
            cand.signals             = self._collect_match_signals(ref, cand)

        candidates.sort(
            key=lambda c: (
                c.final_score,
                c.specificity_bonus,
                c.stability,
                c.confidence,
                c.source_prior,
            ),
            reverse=True,
        )
        return candidates

    def _recompute_final_score(self, cand: Candidate, ref: ReferenceElement) -> float:
        """
        Precision-first weighted scoring.

        Base weights (sum = 1.0):
            attr_sim      0.30
            tag_sim       0.15  (also applied as hard multiplier below)
            structure_sim 0.15
            text_sim      0.10  (low — shared labels cause false positives)
            stability     0.10
            action_fit    0.10
            confidence    0.10

        Small additive bonuses (each bounded):
            uniqueness    up to +0.08
            source_prior  up to +0.04
        """
        base_score = (
            0.30 * cand.attr_sim
            + 0.15 * cand.tag_sim
            + 0.15 * cand.structure_sim
            + 0.10 * cand.text_sim
            + 0.10 * cand.stability
            + 0.10 * cand.action_fit
            + 0.10 * cand.confidence
        )

        # Small additive bonuses (bounded so they don't dominate)
        base_score += min(0.08, cand.uniqueness * 0.08)
        base_score += min(0.04, cand.source_prior * 0.04)
        base_score += cand.specificity_bonus
        base_score += self._action_specific_boost(ref, cand)
        base_score += self._semantic_description_boost(ref, cand)
        base_score += 0.06 * cand.partial_class_sim
        base_score += 0.03 * cand.proximity
        base_score -= self._wrong_click_penalty(ref, cand)
        base_score -= cand.brittleness_penalty
        base_score += self._dom_resolution_bonus(cand)

        # Hard tag-action constraint: multiplier zeroes out structurally wrong candidates.
        base_score *= self._tag_action_multiplier(ref.action, cand)

        return max(0.0, min(0.98, base_score))

    def _tag_action_multiplier(self, action: str, cand: Candidate) -> float:
        """
        Multiplier enforcing hard tag-action structural constraints.

        fill   → only input/textarea: 0.0 for everything else
        select → only <select>: 0.0 for everything else
        click  → non-interactive without role: 0.0
                 non-clickable with interactive role: 0.5
        """
        tag = (cand.tag or cand.attrs.get("tag") or "").lower()
        if not tag:
            return 1.0   # unknown — defer to live validation

        if action == "fill":
            return 1.0 if tag in {"input", "textarea"} else 0.0

        if action == "select":
            return 1.0 if tag == "select" else 0.0

        if action == "click":
            if tag in self._CLICKABLE_TAGS:
                return 1.0
            role = (
                cand.attrs.get("role")
                or (cand.attrs.get("attrs") or {}).get("role")
                or ""
            ).lower()
            if role in self._INTERACTIVE_ROLES:
                return 0.5   # interactive role but non-standard tag
            return 0.0       # bare non-interactive container

        return 1.0

    # ------------------------------------------------------------------
    # Scoring sub-components
    # ------------------------------------------------------------------

    def _attribute_similarity(self, ref: ReferenceElement, el: Dict[str, Any]) -> float:
        total  = 0.0
        weight = 0.0
        attrs  = el.get("attrs") or {}

        def get_val(key_hyphen: str) -> Optional[str]:
            """Get attribute value, always preferring the hyphenated key."""
            return el.get(key_hyphen) or attrs.get(key_hyphen)

        def compare(a: Optional[str], b: Optional[str], w: float) -> None:
            nonlocal total, weight
            if a is None and b is None:
                total += w * 0.5
                weight += w
                return
            if a is None or b is None:
                weight += w
                return
            total += w * self._soft_string_similarity(a, b)
            weight += w

        compare(ref.id_value,    get_val("id"),          0.24)
        compare(ref.name,        get_val("name"),         0.20)
        compare(ref.href,        get_val("href"),         0.18)
        compare(ref.aria_label,  get_val("aria-label"),   0.12)
        compare(ref.placeholder, get_val("placeholder"),  0.10)
        compare(ref.type_attr,   get_val("type"),         0.08)
        compare(ref.data_testid, get_val("data-testid"),  0.16)

        # Partial class similarity from broken selector tokens
        broken_cls_tokens = self._extract_class_tokens_from_selector(ref.failed_selector)
        if broken_cls_tokens:
            el_class_str = " ".join(self._get_all_classes_from_el(el)).lower()
            if el_class_str:
                hits = sum(1 for t in broken_cls_tokens if t in el_class_str)
                total  += 0.10 * (hits / len(broken_cls_tokens))
                weight += 0.10

        if weight == 0:
            return 0.4
        return max(0.0, min(1.0, total / weight))

    def _text_similarity(self, a: str, b: str) -> float:
        a = self._normalize_space(a).lower()
        b = self._normalize_space(b).lower()

        if not a and not b:
            return 0.8
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        a_tokens = set(a.split())
        b_tokens = set(b.split())
        if not a_tokens or not b_tokens:
            return 0.0

        jaccard     = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
        containment = 0.20 if (a in b or b in a) else 0.0
        partial     = min(
            0.25,
            sum(
                0.10
                for at in a_tokens
                for bt in b_tokens
                if len(at) >= 4 and len(bt) >= 4 and at != bt and (at in bt or bt in at)
            ),
        )
        return max(0.0, min(1.0, 0.70 * jaccard + containment + partial))

    def _tag_similarity(self, a: Optional[str], b: Optional[str]) -> float:
        a = (a or "").strip().lower()
        b = (b or "").strip().lower()

        if not a and not b:
            return 0.8
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        equivalent = {("button", "input"), ("input", "button"),
                      ("label", "input"),  ("input", "label")}
        if (a, b) in equivalent:
            return 0.45
        return 0.0

    def _structure_similarity(self, ref: ReferenceElement, el: Dict[str, Any]) -> float:
        """
        Combined parent-tag + sibling-tag context similarity.

        Parent (60% weight): 1.0 exact match, 0.7 both absent, 0.3 one absent, 0.0 mismatch.
        Sibling Jaccard (40% weight): overlap of sibling tag sets.
        """
        ref_parent = (ref.parent_tag or "").strip().lower()
        el_parent  = (el.get("parent_tag") or "").strip().lower()

        if not ref_parent and not el_parent:
            parent_sim = 0.7
        elif ref_parent == el_parent:
            parent_sim = 1.0
        elif ref_parent and el_parent:
            parent_sim = 0.0   # different parents — likely wrong location
        else:
            parent_sim = 0.3   # one side missing context

        # Sibling-tag Jaccard
        ref_sibs = set(
            (ref.attrs.get("sibling_tags") or el.get("sibling_tags") or [])
        )
        el_sibs  = set(el.get("sibling_tags") or [])

        if ref_sibs or el_sibs:
            union = ref_sibs | el_sibs
            sibling_sim = len(ref_sibs & el_sibs) / len(union) if union else 0.7
        else:
            sibling_sim = 0.7   # no sibling info → neutral

        return 0.60 * parent_sim + 0.40 * sibling_sim

    def _compute_stability_score(self, selector: str, locator_type: str) -> float:
        s = selector.lower()

        if locator_type.startswith("role:"):
            return 0.92
        if "data-testid" in s or "data-test" in s or "data-qa" in s:
            return 0.95
        if s.startswith("#"):
            return 0.93
        if "[name=" in s or "[aria-label=" in s:
            return 0.86
        if "[placeholder=" in s:
            return 0.82
        if "[type=" in s and "[value=" in s:
            return 0.80
        if "[type=" in s:
            return 0.72
        if "[value=" in s:
            return 0.68
        if ":has-text(" in s:
            return 0.74
        if "[href=" in s:
            return 0.72
        if "[href*=" in s:
            return 0.64
        if "." in s:
            return 0.42
        if "nth-child" in s or ">" in s:
            return 0.18
        return 0.28

    def _brittleness_penalty(self, selector: str) -> float:
        penalty = 0.0
        s = selector.lower()

        if "nth-child" in s:
            penalty += 0.25
        if s.count(">") >= 2:
            penalty += 0.20
        if s.count(" ") >= 4:
            penalty += 0.15
        if re.search(r"\.css-[a-z0-9]+", s):
            penalty += 0.25
        if re.search(r"#.+\d{4,}", s):
            penalty += 0.20
        if s.startswith(".") and "[" not in s:
            penalty += 0.06

        return min(0.6, penalty)

    def _static_action_fit(self, action: str, cand: Candidate) -> float:
        selector  = cand.selector.lower()
        tag       = (cand.tag or "").lower()
        attrs     = cand.attrs or {}
        type_attr = (attrs.get("type") or attrs.get("attrs", {}).get("type") or "").lower()

        if action == "fill":
            if cand.locator_type == "role:textbox":
                return 0.95
            if tag in {"input", "textarea"} and type_attr not in {"checkbox", "submit", "button"}:
                return 0.90
            if "placeholder" in selector or "[name=" in selector or "aria-label" in selector:
                return 0.78
            return 0.20

        if action == "click":
            if type_attr == "checkbox":
                return 0.95
            if type_attr == "submit":
                return 0.95
            if cand.locator_type in {"role:button", "role:link"}:
                return 0.82
            if tag in {"button", "a", "label"}:
                return 0.78
            if ":has-text(" in selector:
                return 0.60
            return 0.25

        if action in {"expect_visible", "wait_for_visible"}:
            if ":has-text(" in selector or cand.locator_type.startswith("role:"):
                return 0.84
            return 0.60

        return 0.5

    def _compute_action_fit_from_validation(
        self, action: str, validation: Dict[str, Any]
    ) -> float:
        if not validation.get("valid"):
            return 0.0

        visible    = bool(validation.get("visible"))
        enabled    = bool(validation.get("enabled", True))
        editable   = bool(validation.get("editable", False))
        tag        = (validation.get("tag") or "").lower()
        input_type = (validation.get("type") or "").lower()

        if action == "fill":
            return 1.0 if visible and editable and tag in {"input", "textarea"} else 0.0

        if action in {"click", "hover", "press"}:
            if not (visible and enabled):
                return 0.0
            if tag == "input" and input_type in {"checkbox", "submit", "button"}:
                return 1.0
            return 0.9 if tag in {"button", "a", "label"} else 0.45

        if action in {"expect_visible", "wait_for_visible"}:
            return 1.0 if visible else 0.0

        return 0.7

    def _compute_uniqueness_score(self, match_count: int) -> float:
        if match_count == 1:
            return 1.0
        if match_count == 2:
            return 0.65
        if match_count == 3:
            return 0.35
        return 0.08

    def _source_prior(self, source: str) -> float:
        return {"memory": 1.0, "heuristic": 0.8, "llm": 0.7}.get(source, 0.5)

    def _specificity_bonus(self, cand: Candidate) -> float:
        s     = cand.selector.lower()
        bonus = 0.0

        attr_count = s.count("[")
        if attr_count >= 2:
            bonus += 0.10
        elif attr_count == 1:
            bonus += 0.05

        if s.startswith("#"):
            bonus += 0.10
        if ":has-text(" in s:
            bonus += 0.03
        if s.startswith("[name="):
            bonus -= 0.01
        if s.startswith(".") and "[" not in s and ":has-text(" not in s:
            bonus -= 0.06
        if s in {"input", "button", "a", "label", "div", "span"}:
            bonus -= 0.12
        if s in {'input[type="submit"]', "input[type='submit']"}:
            bonus += 0.03
        if s in {'input[type="checkbox"]', "input[type='checkbox']"}:
            bonus -= 0.03

        return bonus

    def _dom_resolution_bonus(self, cand: Candidate) -> float:
        resolved        = bool(cand.attrs and cand.attrs.get("tag"))
        confirmed_valid = bool(cand.validation.get("valid"))

        if not resolved and not confirmed_valid:
            return -0.12
        if not resolved:
            return 0.0

        bonus = 0.08
        tag = (cand.tag or cand.attrs.get("tag") or "").lower()
        if tag in {"button", "input", "a", "label", "select", "textarea"}:
            bonus += 0.05

        role = (
            cand.attrs.get("role")
            or (cand.attrs.get("attrs") or {}).get("role")
            or ""
        ).lower()
        locator_interactive = cand.locator_type in {
            "role:button", "role:link", "role:textbox", "role:checkbox",
        }
        if role in self._INTERACTIVE_ROLES or locator_interactive:
            bonus += 0.03

        return bonus

    def _action_specific_boost(self, ref: ReferenceElement, cand: Candidate) -> float:
        """
        Generic action-specific boosts.  No site-specific rules.
        """
        desc      = self._normalize_space(ref.description).lower()
        selector  = cand.selector.lower()
        attrs     = cand.attrs or {}
        type_attr = (attrs.get("type") or attrs.get("attrs", {}).get("type") or "").lower()
        value_attr = self._normalize_space(
            attrs.get("value") or attrs.get("attrs", {}).get("value") or ""
        ).lower()

        boost = 0.0

        if ref.action == "fill":
            if cand.locator_type == "role:textbox":
                boost += 0.06
            if "first name" in desc and "firstname" in selector:
                boost += 0.02
            if "last name" in desc and "lastname" in selector:
                boost += 0.02
            if "email" in desc and ("email" in selector or type_attr == "email"):
                boost += 0.02

        if ref.action == "click":
            if "agree" in desc or "checkbox" in desc:
                if '[type=' in selector and 'checkbox' in selector:
                    boost += 0.18
                elif "checkbox" in selector:
                    boost += 0.08

            if "continue" in desc or "submit" in desc or "register" in desc:
                has_type_submit = '[type=' in selector and 'submit' in selector
                has_value       = '[value=' in selector and bool(value_attr)

                if has_type_submit and has_value:
                    boost += 0.25
                elif has_type_submit:
                    boost += 0.16
                elif type_attr == "submit":
                    boost += 0.12

                if value_attr and any(w in value_attr for w in desc.split() if len(w) > 3):
                    boost += 0.08

        return boost

    def _wrong_click_penalty(self, ref: ReferenceElement, cand: Candidate) -> float:
        """
        Generic penalty for obviously wrong click targets.
        No site-specific text or selector patterns.
        """
        if ref.action != "click":
            return 0.0

        selector  = cand.selector.lower()
        attrs     = cand.attrs or {}
        type_attr = (attrs.get("type") or attrs.get("attrs", {}).get("type") or "").lower()
        desc      = self._normalize_space(ref.description).lower()

        penalty = 0.0

        # Bare single-tag selectors with no qualifiers are almost always too broad
        if selector in {"button", "a", "div", "span", "div button"}:
            penalty += 0.35

        # Wrong input type for the described intent
        if ("continue" in desc or "submit" in desc or "register" in desc) and type_attr == "checkbox":
            penalty += 0.18
        if ("agree" in desc or "checkbox" in desc) and type_attr == "submit":
            penalty += 0.18

        return penalty

    # ------------------------------------------------------------------
    # Live validation
    # ------------------------------------------------------------------

    async def _validate_candidate(
        self,
        page: Page,
        cand: Candidate,
        action: str,
        ref: Optional[ReferenceElement] = None,
    ) -> Dict[str, Any]:
        try:
            locator = self._make_locator(page, cand)
            count   = await locator.count()
            if count == 0:
                return {"valid": False, "reason": "no match", "match_count": 0}

            first = locator.first
            await first.wait_for(state="attached", timeout=self.timeout_ms)

            visible    = False
            enabled    = True
            editable   = False
            tag        = ""
            text       = ""
            input_type = ""

            try: visible    = await first.is_visible()
            except Exception: visible = False

            try: enabled    = await first.is_enabled()
            except Exception: enabled = True

            try: editable   = await first.is_editable()
            except Exception: editable = False

            try: tag        = await first.evaluate("(el) => el.tagName.toLowerCase()")
            except Exception: tag = ""

            try: input_type = await first.evaluate("(el) => (el.getAttribute('type') || '').toLowerCase()")
            except Exception: input_type = ""

            try: text       = (await first.inner_text(timeout=800)).strip()
            except Exception: text = ""
            try: value_text = (await first.evaluate("(el) => el.getAttribute('value') || ''")).strip()
            except Exception: value_text = ""

            # --- Action-specific hard validation ---
            if action == "fill":
                if not visible:
                    return {"valid": False, "reason": "not visible", "match_count": count}
                if tag not in {"input", "textarea"}:
                    return {"valid": False, "reason": f"wrong tag for fill: {tag}", "match_count": count}
                if not editable:
                    return {"valid": False, "reason": "not editable", "match_count": count}

            elif action == "select":
                if not visible:
                    return {"valid": False, "reason": "not visible", "match_count": count}
                if tag != "select":
                    return {"valid": False, "reason": f"wrong tag for select: {tag}", "match_count": count}

            elif action in {"click", "hover", "press"}:
                if not visible:
                    return {"valid": False, "reason": "not visible", "match_count": count}
                if not enabled:
                    return {"valid": False, "reason": "not enabled", "match_count": count}
                if count != 1:
                    return {"valid": False, "reason": "ambiguous_click_multiple_matches", "match_count": count}
                if tag == "input" and input_type in {"hidden", "radio"}:
                    return {"valid": False, "reason": f"wrong input type: {input_type}", "match_count": count}

                # Non-interactive containers (div/span/p/…) without an ARIA role
                non_interactive = {"div", "span", "p", "ul", "ol", "li", "section",
                                   "article", "main", "aside", "header", "footer"}
                if tag in non_interactive:
                    role_val = ""
                    try:
                        role_val = await first.evaluate("(el) => el.getAttribute('role') || ''")
                    except Exception:
                        pass
                    if not role_val:
                        return {"valid": False, "reason": f"non_interactive_container:{tag}", "match_count": count}

                if ref is not None:
                    label_text = self._normalize_space(f"{text} {value_text}")
                    reject_reason = self._check_click_candidate(cand, ref, tag, input_type, label_text)
                    if reject_reason:
                        return {"valid": False, "reason": reject_reason, "match_count": count}

            elif action in {"expect_visible", "wait_for_visible"}:
                if not visible:
                    return {"valid": False, "reason": "not visible", "match_count": count}
                if len(text) > 60:
                    return {"valid": False, "reason": "container_large_text", "match_count": count}

            return {
                "valid": True,
                "reason": "ok",
                "match_count": count,
                "visible": visible,
                "enabled": enabled,
                "editable": editable,
                "tag": tag,
                "text": text,
                "type": input_type,
            }

        except Exception as e:
            return {"valid": False, "reason": f"validation exception: {e}", "match_count": 0}

    def _check_click_candidate(
        self,
        cand: "Candidate",
        ref: "ReferenceElement",
        live_tag: str,
        live_type: str,
        live_text: str,
    ) -> Optional[str]:
        """
        Pre-click semantic validation.  Returns a rejection reason string or None.

        Checks:
          1. Wrong input type for the described intent
          2. Description-token mismatch (when description is specific enough)
        """
        attrs = cand.attrs or {}
        desc  = self._normalize_space(ref.description).lower()

        if live_type == "hidden":
            return "hidden_input"

        if "submit" in desc or "login" in desc or "continue" in desc or "register" in desc:
            if live_type in {"radio", "checkbox"}:
                return f"wrong_type_for_submit:{live_type}"

        if "agree" in desc or "checkbox" in desc:
            if live_type and live_type not in {"checkbox", ""}:
                return f"wrong_type_for_checkbox:{live_type}"

        # For compound broken selectors (space/>/+/~ combinator), require that at
        # least one non-generic class token from the broken selector appears in the
        # candidate's class, id, or visible text.  This prevents, e.g., a product
        # item link (#item_4_title_link) from being chosen when the broken selector
        # clearly targets a cart-related element (.shopping_cart_container-SIBLING).
        broken_cls_tokens = self._extract_class_tokens_from_selector(ref.failed_selector)
        has_combinator = bool(re.search(r"[\s>+~]", ref.failed_selector.strip()))
        if broken_cls_tokens and has_combinator and cand.attrs:
            _GENERIC_TOKENS: frozenset[str] = frozenset({
                "link", "icon", "btn", "button", "wrap", "wrapper", "container", "card",
            })
            non_generic = [t for t in broken_cls_tokens if t not in _GENERIC_TOKENS]
            if non_generic:
                el_cls = " ".join(self._get_all_classes_from_el(cand.attrs)).lower()
                el_id  = (cand.attrs.get("id") or "").lower()
                searchable = f"{el_cls} {el_id} {live_text.lower()}"
                if not any(t in searchable for t in non_generic):
                    return "broken_class_token_mismatch"

        # Description-token mismatch: require at least one long description token
        # to appear in the candidate's identity when description is non-trivial.
        desc_tokens = [t for t in desc.split() if len(t) >= 5]
        if len(desc_tokens) >= 3 and live_tag and live_text:
            el_id   = (attrs.get("id") or "").lower()
            el_name = (attrs.get("name") or "").lower()
            el_aria = (
                attrs.get("aria-label")
                or (attrs.get("attrs") or {}).get("aria-label")
                or ""
            ).lower()
            searchable = f"{el_id} {el_name} {el_aria} {live_text} {cand.selector.lower()}"
            if not any(t in searchable for t in desc_tokens):
                return "description_mismatch"

        return None

    # ------------------------------------------------------------------
    # Semantic boosts and signal collection
    # ------------------------------------------------------------------

    def _semantic_description_boost(self, ref: ReferenceElement, cand: Candidate) -> float:
        desc        = self._normalize_space(ref.description).lower()
        desc_tokens = [t for t in self._tokenize_text(desc) if len(t) >= 4]
        if not desc_tokens:
            return 0.0

        attrs     = cand.attrs or {}
        el_id     = (attrs.get("id") or "").lower()
        el_name   = (attrs.get("name") or "").lower()
        selector  = cand.selector.lower()
        identity  = " ".join(filter(None, [el_id, el_name, selector]))
        if not identity:
            return 0.0

        matched = sum(
            1 for token in desc_tokens
            if any(
                token in seg or seg in token
                for seg in self._tokenize_text(identity) if len(seg) >= 4
            )
        )
        if matched == 0:
            return 0.0
        return min(0.06, (matched / len(desc_tokens)) * 0.08)

    def _collect_match_signals(
        self, ref: ReferenceElement, cand: Candidate
    ) -> List[str]:
        signals = []
        attrs   = cand.attrs or {}

        el_id          = (attrs.get("id") or "").lower()
        el_name        = (attrs.get("name") or "").lower()
        el_type        = (attrs.get("type") or "").lower()
        el_value       = self._normalize_space(attrs.get("value") or "").lower()
        el_aria        = (attrs.get("aria-label") or "").lower()
        el_placeholder = (attrs.get("placeholder") or "").lower()
        desc           = self._normalize_space(ref.description).lower()
        selector       = cand.selector.lower()

        if ref.id_value and el_id and self._soft_string_similarity(ref.id_value.lower(), el_id) > 0.70:
            signals.append("id_match")
        if ref.name and el_name and self._soft_string_similarity(ref.name.lower(), el_name) > 0.70:
            signals.append("name_match")
        if ref.aria_label and el_aria and self._soft_string_similarity(ref.aria_label.lower(), el_aria) > 0.70:
            signals.append("aria_match")
        if ref.placeholder and el_placeholder and self._soft_string_similarity(ref.placeholder.lower(), el_placeholder) > 0.70:
            signals.append("placeholder_match")

        if ref.action == "fill":
            if el_type not in {"checkbox", "submit", "button", "radio", "hidden"}:
                if cand.tag in {"input", "textarea"} or cand.locator_type == "role:textbox":
                    signals.append("fill_type_match")
        elif ref.action == "click":
            if el_type == "checkbox":
                signals.append("checkbox_match")
            elif el_type in {"submit", "button"} or cand.tag == "button":
                signals.append("submit_match")

        if el_value and desc and any(w in el_value for w in desc.split() if len(w) > 3):
            signals.append("value_match")

        desc_tokens = [t for t in self._tokenize_text(desc) if len(t) >= 4]
        cand_tokens = [t for t in self._tokenize_text(
            " ".join(filter(None, [el_id, el_name, selector]))
        ) if len(t) >= 4]
        if desc_tokens and cand_tokens:
            if any(dt in ct or ct in dt for dt in desc_tokens for ct in cand_tokens):
                signals.append("semantic_match")

        broken_cls_tokens = self._extract_class_tokens_from_selector(ref.failed_selector)
        if broken_cls_tokens:
            el_class_str = " ".join(self._get_all_classes_from_el(attrs)).lower()
            if any(t in el_class_str for t in broken_cls_tokens):
                signals.append("partial_class_match")

        desc_keywords = self._extract_meaningful_keywords(ref.description)
        el_text       = self._normalize_space(attrs.get("text") or "").lower()
        if desc_keywords and el_text and any(kw in el_text for kw in desc_keywords):
            signals.append("text_content_match")

        from engine.heuristic_generator import _extract_keywords, _token_overlap_score
        fuzzy_tokens = (
            _extract_keywords(ref.failed_selector)
            | _extract_keywords(ref.description or "")
        )
        if fuzzy_tokens and _token_overlap_score(attrs, fuzzy_tokens) >= 0.5:
            signals.append("token_overlap_match")

        if cand.source == "memory":
            signals.append("memory_hit")

        return signals

    # ------------------------------------------------------------------
    # Proximity / partial class
    # ------------------------------------------------------------------

    def _partial_class_similarity(
        self, ref: ReferenceElement, el: Dict[str, Any]
    ) -> float:
        tokens = self._extract_class_tokens_from_selector(ref.failed_selector)
        if not tokens:
            return 0.5

        all_classes = self._get_all_classes_from_el(el)
        if not all_classes:
            return 0.0

        class_str = " ".join(all_classes).lower()
        matched   = sum(1 for t in tokens if t in class_str)
        return matched / len(tokens)

    def _proximity_score(self, ref: ReferenceElement, cand: Candidate) -> float:
        attrs        = cand.attrs or {}
        parent_tag   = (attrs.get("parent_tag") or "").lower()
        sibling_tags: List[str] = attrs.get("sibling_tags") or []

        if not parent_tag and not sibling_tags:
            return 0.5

        score = 0.5

        if ref.action in {"fill", "click"}:
            if parent_tag in {"form", "fieldset"}:
                score += 0.25
            elif parent_tag in {"div", "section", "li", "td"}:
                interactive = {"input", "button", "select", "textarea", "label"}
                if any(t in interactive for t in sibling_tags):
                    score += 0.12

        if ref.action == "click":
            if parent_tag in {"nav", "ul", "li", "header", "menu"}:
                score += 0.08
            if cand.tag in {"button", "a"} and any(
                t in {"button", "a", "input"} for t in sibling_tags
            ):
                score += 0.05

        return min(1.0, score)

    # ------------------------------------------------------------------
    # Generator integration helpers
    # ------------------------------------------------------------------

    def _map_heuristic_candidate(
        self, hc: Any, dom_snapshot: List[Dict[str, Any]]
    ) -> "Candidate":
        el = self._resolve_dom_el_for_candidate(hc.locator, dom_snapshot)
        return Candidate(
            selector=hc.locator,
            locator_type=hc.locator_type,
            source="heuristic",
            confidence=hc.confidence,
            reason=f"{hc.strategy}: {hc.reasoning}",
            tag=el.get("tag") if el else None,
            text=self._normalize_space(el.get("text") or "") if el else None,
            attrs=el or {},
        )

    def _resolve_dom_el_for_candidate(
        self, selector: str, dom_snapshot: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        s = selector.strip()

        m = re.match(r"^#([\w-]+)$", s)
        if m:
            id_val = m.group(1)
            for el in dom_snapshot:
                if (el.get("id") or "").strip() == id_val:
                    return el

        m = re.match(r"^(\w+)?\[([a-z-]+)=[\"']([^\"']+)[\"']\]$", s)
        if m:
            tag_prefix, attr, val = m.group(1), m.group(2), m.group(3)
            for el in dom_snapshot:
                if tag_prefix and (el.get("tag") or "").lower() != tag_prefix:
                    continue
                attrs = el.get("attrs") or {}
                raw   = el.get(attr) or attrs.get(attr) or ""
                if str(raw).strip() == val:
                    return el

        m = re.search(r':has-text\("([^"]+)"\)', s)
        if m:
            text_val = m.group(1).lower()
            tag_m    = re.match(r"^(\w+):", s)
            for el in dom_snapshot:
                if tag_m and (el.get("tag") or "").lower() != tag_m.group(1):
                    continue
                el_text = self._normalize_space(el.get("text") or "").lower()
                if text_val in el_text or el_text in text_val:
                    return el

        m = re.match(r"^(\w+)?\.([a-zA-Z][a-zA-Z0-9_-]*)$", s)
        if m:
            tag_prefix, cls = m.group(1), m.group(2)
            for el in dom_snapshot:
                if tag_prefix and (el.get("tag") or "").lower() != tag_prefix:
                    continue
                if cls in self._get_all_classes_from_el(el):
                    return el

        m = re.match(r"^(\w+)?\[class\*=[\"']([^\"']+)[\"']\]$", s)
        if m:
            tag_prefix, token = m.group(1), m.group(2)
            for el in dom_snapshot:
                if tag_prefix and (el.get("tag") or "").lower() != tag_prefix:
                    continue
                cls_str = " ".join(self._get_all_classes_from_el(el)).lower()
                if token.lower() in cls_str:
                    return el

        return None

    # ------------------------------------------------------------------
    # Fuzzy fallback DOM scan (last resort)
    # ------------------------------------------------------------------

    def _fuzzy_dom_scan(
        self, ref: ReferenceElement, dom_snapshot: List[Dict[str, Any]]
    ) -> List[Candidate]:
        from engine.heuristic_generator import _extract_keywords

        tokens = (
            _extract_keywords(ref.failed_selector)
            | _extract_keywords(ref.description or "")
        )
        if not tokens:
            return []

        scored = [
            (self._token_overlap_score_el(el, tokens), el)
            for el in dom_snapshot
        ]
        scored = [(s, el) for s, el in scored if s > 0.0]
        scored.sort(key=lambda x: x[0], reverse=True)

        out: List[Candidate] = []
        seen_ids: set = set()

        for score, el in scored[:6]:
            # Apply action-based tag filtering in fallback scan too
            el_tag = (el.get("tag") or "").strip().lower()
            if ref.action == "fill" and el_tag and el_tag not in {"input", "textarea"}:
                continue
            if ref.action == "select" and el_tag and el_tag != "select":
                continue

            conf  = min(0.78, 0.38 + score * 0.40)
            attrs = el.get("attrs") or {}

            el_id     = el.get("id") or ""
            el_testid = el.get("data-testid") or attrs.get("data-testid") or ""
            el_datacy = el.get("data-cy") or ""
            el_name   = el.get("name") or attrs.get("name") or ""
            el_ph     = el.get("placeholder") or attrs.get("placeholder") or ""
            el_aria   = el.get("aria-label") or attrs.get("aria-label") or ""
            el_href   = el.get("href") or attrs.get("href") or ""

            def _pick() -> Optional[str]:
                if el_id and el_id not in seen_ids:
                    seen_ids.add(el_id)
                    return f"#{self._css_escape(el_id)}"
                if el_testid:
                    return f'[data-testid="{self._css_escape(el_testid)}"]'
                if el_datacy:
                    return f'[data-cy="{self._css_escape(el_datacy)}"]'
                if el_name and el_tag:
                    return f'{el_tag}[name="{self._css_escape(el_name)}"]'
                if el_ph and el_tag in {"input", "textarea"}:
                    return f'{el_tag}[placeholder="{self._css_escape(el_ph)}"]'
                if el_aria:
                    return f'[aria-label="{self._css_escape(el_aria)}"]'
                if el_href and el_tag == "a":
                    return f'a[href="{self._css_escape(el_href)}"]'
                return None

            sel = _pick()
            if sel:
                out.append(Candidate(
                    selector=sel,
                    locator_type="css",
                    source="heuristic",
                    confidence=conf,
                    reason=f"fuzzy_scan: token overlap={score:.2f}",
                    tag=el_tag or None,
                    text=el.get("text") or None,
                    attrs=el,
                ))

        return out

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _save_memory(self, ref: ReferenceElement, cand: Candidate) -> None:
        try:
            self.memory_store.save_success(ref, {
                "failed_selector": ref.failed_selector,
                "healed_selector": cand.selector,
                "locator_type":    cand.locator_type,
                "action":          ref.action,
                "tag":             cand.validation.get("tag") or cand.tag,
                "text":            cand.validation.get("text") or cand.text,
                "confidence":      cand.final_score,
                "source":          cand.source,
                "reason":          cand.reason,
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _make_locator(self, page: Page, cand: Candidate) -> Locator:
        if cand.locator_type.startswith("role:"):
            role = cand.locator_type.split(":", 1)[1]
            return page.get_by_role(role, name=cand.selector)
        return page.locator(cand.selector)

    def _normalize_space(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    def _css_escape(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _looks_dynamic_token(self, token: str) -> bool:
        if not token:
            return False
        if re.match(r"^[a-f0-9]{6,}$", token):
            return True
        if re.match(r"^\d+$", token):
            return True
        if re.match(r"^(?:css|jsx)-[a-zA-Z0-9]+$", token):
            return True
        m = re.match(r".*[_-]([a-zA-Z0-9]{6,})$", token)
        if m and re.search(r"\d", m.group(1)):
            return True
        return False

    def _stable_classes(self, classes: List[str]) -> List[str]:
        return [c for c in classes if not self._looks_dynamic_token(c) and len(c) >= 3][:2]

    def _tokenize_text(self, text: Optional[str]) -> List[str]:
        text = self._normalize_space(text).lower()
        return [t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 3]

    def _meaningful_phrases(self, text: str) -> List[str]:
        tokens = self._tokenize_text(text)
        return list(dict.fromkeys(tokens[:3]))

    def _parse_class_value(self, raw: Any) -> List[str]:
        if isinstance(raw, list):
            return [str(c) for c in raw if c]
        if isinstance(raw, str):
            return raw.split()
        return []

    def _get_all_classes_from_el(self, el: Dict[str, Any]) -> List[str]:
        raw = el.get("class") or (el.get("attrs") or {}).get("class") or ""
        return self._parse_class_value(raw)

    def _extract_class_tokens_from_selector(self, selector: str) -> List[str]:
        _sfx = re.compile(
            r"[-_](BROKEN|OLD|NEW|V\d+|BACKUP|TEST|COPY|TMP|TEMP|REMOVED|MOVED|EXTRA|SIBLING|NESTED)$",
            flags=re.IGNORECASE,
        )
        class_parts = re.findall(r"\.([a-zA-Z][a-zA-Z0-9_-]*)", selector)
        tokens: List[str] = []
        for part in class_parts:
            cleaned = _sfx.sub("", part).lower()
            sub     = re.split(r"[-_]", cleaned)
            tokens.extend(t for t in sub if len(t) >= 3)
        return list(dict.fromkeys(tokens))

    def _extract_meaningful_keywords(self, text: Optional[str]) -> List[str]:
        if not text:
            return []
        cleaned = re.sub(r'[#.\[\]=\'"()>~+,*|^$@!/\\]', " ", text)
        tokens  = re.split(r"[-_\s]+", cleaned.lower())
        return [t for t in tokens if len(t) >= 4 and not t.isdigit()]

    def _token_overlap_score_el(self, el: Dict[str, Any], tokens: set) -> float:
        if not tokens:
            return 0.0
        attrs = el.get("attrs") or {}
        parts = [
            el.get("id") or "",
            el.get("name") or attrs.get("name") or "",
            el.get("text") or "",
            el.get("placeholder") or attrs.get("placeholder") or "",
            el.get("aria-label") or attrs.get("aria-label") or "",
            el.get("data-testid") or attrs.get("data-testid") or "",
            el.get("data-cy") or "",
            el.get("data-test") or "",
            " ".join(self._get_all_classes_from_el(el)),
        ]
        searchable = " ".join(filter(None, parts)).lower()
        if not searchable:
            return 0.0
        matched = sum(1 for t in tokens if t in searchable)
        return matched / len(tokens)

    def _soft_string_similarity(self, a: str, b: str) -> float:
        a = self._normalize_space(a).lower()
        b = self._normalize_space(b).lower()

        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.75

        a_tokens = set(self._tokenize_text(a))
        b_tokens = set(self._tokenize_text(b))
        if not a_tokens or not b_tokens:
            return 0.0
        return len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
