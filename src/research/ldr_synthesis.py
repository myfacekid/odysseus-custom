"""Nobody academic synthesis on EvidenceRegistry (LDR decision B)."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.research.research_prompts import REPORT_LENGTH_SPECS
from src.research_evidence import EvidenceRegistry
from src.research_synthesis import (
    build_evidence_table,
    build_thematic_outline_prompt,
    combine_final_context_blocks,
    format_thematic_outline,
    heuristic_thematic_outline,
    should_cluster_thematically,
    should_include_evidence_table,
)
from src.research_templates import (
    ACADEMIC_REPORT_OVERRIDE,
    build_final_report_prompt,
    expansion_user_message,
)
from src.research_utils import strip_thinking

logger = logging.getLogger(__name__)


async def _llm_call(
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict],
    messages: List[dict],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    from src.llm_core import llm_call_async

    response = await llm_call_async(
        url=llm_endpoint,
        model=llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        headers=llm_headers,
        timeout=timeout,
    )
    return strip_thinking(response)


async def _build_pre_final_context(
    question: str,
    registry: EvidenceRegistry,
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict],
) -> str:
    if not should_cluster_thematically(registry):
        return ""
    try:
        prompt = build_thematic_outline_prompt(question=question, registry=registry)
        raw = await _llm_call(
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            llm_headers=llm_headers,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
            timeout=90,
        )
        outline = format_thematic_outline(raw) or heuristic_thematic_outline(registry)
    except Exception as exc:
        logger.warning("Thematic outline failed: %s", exc)
        outline = heuristic_thematic_outline(registry)
    table = ""
    if should_include_evidence_table(registry):
        table = build_evidence_table(registry)
    return combine_final_context_blocks(outline, table)


async def synthesize_academic_report(
    *,
    question: str,
    draft_report: str,
    registry: EvidenceRegistry,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    research_mode: str = "literature_review",
    report_length: str = "standard",
    max_report_tokens: int = 16384,
    deep_read_context: str = "",
) -> str:
    """Produce the final Nobody academic report from gathered evidence."""
    length_spec = REPORT_LENGTH_SPECS.get(
        report_length if report_length in REPORT_LENGTH_SPECS else "standard",
        REPORT_LENGTH_SPECS["standard"],
    )
    min_words = length_spec["min_words"]
    expand_threshold = length_spec["expand_threshold"]

    prompt = build_final_report_prompt(
        question=question,
        report=draft_report,
        min_words=min_words,
        mode=research_mode,
    )
    prompt += "\n\n" + ACADEMIC_REPORT_OVERRIDE
    registry_block = registry.registry_prompt_block()
    if registry_block:
        prompt += f"\n\n{registry_block}\n"
    quant_block = registry.quantitative_evidence_block()
    if quant_block:
        prompt += f"\n\n{quant_block}\n"
    sourcing_block = registry.sourcing_limitations_block()
    if sourcing_block:
        prompt += f"\n\n{sourcing_block}\n"
    synthesis_block = await _build_pre_final_context(
        question,
        registry,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
    )
    if synthesis_block:
        prompt += f"\n\n{synthesis_block}\n"
    if deep_read_context:
        prompt += f"\n\n{deep_read_context}\n"

    try:
        result = await _llm_call(
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            llm_headers=llm_headers,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_report_tokens,
            timeout=180,
        )
        if len(result.split()) < expand_threshold:
            expanded = await _llm_call(
                llm_endpoint=llm_endpoint,
                llm_model=llm_model,
                llm_headers=llm_headers,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": result},
                    {"role": "user", "content": expansion_user_message(min_words)},
                ],
                temperature=0.4,
                max_tokens=max_report_tokens,
                timeout=180,
            )
            if len(expanded.split()) > len(result.split()):
                result = expanded
        repaired, _warnings = registry.validate_and_repair_report(result)
        return repaired
    except Exception as exc:
        logger.error("LDR Nobody synthesis failed: %s", exc)
        repaired, _warnings = registry.validate_and_repair_report(draft_report)
        return repaired
