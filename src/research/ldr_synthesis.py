"""Nobody academic synthesis on EvidenceRegistry (LDR decision B)."""
from __future__ import annotations

import logging
import re
from typing import List, Optional

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
from src.text_helpers import strip_think

logger = logging.getLogger(__name__)

_DRAFT_LINE_RE = re.compile(r"^\[\d+\]\s+.+:\s*")
_HEADING_RE = re.compile(r"^#{1,3}\s+")
_REWRITE_DUMP_USER = (
    "The source notes are evidence, not the report. Write the full academic report now "
    "with a '# ' title and the required ## headings from the instructions. "
    "Write prose paragraphs and cite with [N] in sentences. "
    "Do not copy '[N] Title: excerpt' source-note lines. "
    "Do not include planning or thinking — begin with the '# ' title line."
)
_MAX_REWRITE_ATTEMPTS = 2
_JUNK_TITLE_RE = re.compile(
    r"(?:title specific|or similar|maybe [\"']|^title\b|"
    r"^report\b|^summary\b|^background\b)",
    re.I,
)


def _has_heading(raw: str, title: str) -> bool:
    return bool(re.search(rf"^##\s+{re.escape(title)}\s*$", raw, re.I | re.M))


def _has_top_title(raw: str) -> bool:
    return bool(re.search(r"^#\s+\S+", raw, re.M))


def _is_junk_report_title(title: str) -> bool:
    title = (title or "").strip()
    if not title:
        return True
    if _JUNK_TITLE_RE.search(title):
        return True
    if len(title) > 180:
        return True
    return False


def prepare_synthesis_markdown(text: str) -> str:
    """Strip thinking/prompt-echo and start at the first real report heading."""
    out = strip_think(text or "", prose=True, prompt_echo=True).strip()
    if not out:
        return ""
    match = re.search(r"^#{1,3}\s+\S", out, re.M)
    if match:
        out = out[match.start():].strip()
    lines = out.splitlines()
    while lines:
        first = lines[0].strip()
        if re.match(r"^#\s+", first) and not first.startswith("##"):
            title = first.lstrip("#").strip()
            if _is_junk_report_title(title):
                lines = lines[1:]
                while lines and not lines[0].strip():
                    lines = lines[1:]
                continue
        break
    return "\n".join(lines).strip()


def report_looks_like_gathering_dump(
    text: str,
    *,
    research_mode: str = "literature_review",
) -> bool:
    """True when markdown is a source-line dump or lacks required body headings.

    A missing top-level ``#`` title alone is not treated as a dump — those
    reports are still usable write-ups (retry separately for the title).
    """
    from src.research_templates import section_headings

    raw = prepare_synthesis_markdown(text) if text else ""
    if not raw:
        return True
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return True

    dump_lines = sum(1 for ln in lines if _DRAFT_LINE_RE.match(ln))
    content_lines = [ln for ln in lines if not _HEADING_RE.match(ln)]
    if content_lines and dump_lines / len(content_lines) >= 0.5:
        return True
    if dump_lines >= 2 and not re.search(r"^#{2,3}\s+\S+", raw, re.M):
        return True
    if dump_lines == 0 and len(lines) <= 3:
        cite_only = sum(1 for ln in lines if re.match(r"^\[\d+\]\s+\S+", ln))
        if cite_only >= max(2, len(lines) - 1):
            return True

    has_exec = _has_heading(raw, "Executive Summary")
    extra = [
        name
        for name in section_headings(research_mode)
        if name not in ("Executive Summary", "References")
    ]
    has_extra = any(_has_heading(raw, name) for name in extra)
    return not (has_exec and has_extra)


def report_needs_rewrite(
    text: str,
    *,
    research_mode: str = "literature_review",
) -> bool:
    """True when synthesis should retry: dump/incomplete structure or missing title."""
    raw = prepare_synthesis_markdown(text)
    if report_looks_like_gathering_dump(raw, research_mode=research_mode):
        return True
    return not _has_top_title(raw)


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
    return prepare_synthesis_markdown(response or "")


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
            timeout=180,
        )
        outline = format_thematic_outline(raw) or heuristic_thematic_outline(registry)
    except Exception as exc:
        logger.warning("Thematic outline failed: %s", exc)
        outline = heuristic_thematic_outline(registry)
    table = ""
    if should_include_evidence_table(registry):
        table = build_evidence_table(registry)
    return combine_final_context_blocks(outline, table)


def _structured_fallback_report(
    *,
    question: str,
    registry: EvidenceRegistry,
    findings: Optional[List[dict]],
    research_mode: str,
) -> str:
    fallback = registry.build_structured_fallback(
        question,
        findings or [],
        research_mode=research_mode,
    )
    repaired, _warnings = registry.validate_and_repair_report(fallback)
    return repaired


def persistable_synthesis_report(
    text: str,
    *,
    question: str,
    registry: Optional[EvidenceRegistry],
    findings: Optional[List[dict]] = None,
    research_mode: str = "literature_review",
) -> str:
    """Return structured markdown safe to save; never a gathering-draft dump.

    Headed write-ups missing only a ``#`` title are kept (title injected) rather
    than replaced with the automatic-synthesis stub.
    """
    raw = prepare_synthesis_markdown(text)
    mode = research_mode or "literature_review"
    if raw and not report_looks_like_gathering_dump(raw, research_mode=mode):
        if not _has_top_title(raw):
            title = (question or "Literature synthesis").strip() or "Literature synthesis"
            raw = f"# {title}\n\n{raw}"
        if registry is not None:
            repaired, _warnings = registry.validate_and_repair_report(raw)
            return repaired
        return raw
    if registry is not None and registry.sources():
        return _structured_fallback_report(
            question=question,
            registry=registry,
            findings=findings,
            research_mode=mode,
        )
    return raw


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
    findings: Optional[List[dict]] = None,
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
    sourcing_block = registry.sourcing_limitations_block(findings)
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

    async def _generate(msgs: List[dict]) -> str:
        result = await _llm_call(
            llm_endpoint=llm_endpoint,
            llm_model=llm_model,
            llm_headers=llm_headers,
            messages=msgs,
            temperature=0.3,
            max_tokens=max_report_tokens,
            # Slow local models routinely need >3 min for long reports.
            timeout=600,
        )
        if (
            len(result.split()) < expand_threshold
            and not report_needs_rewrite(result, research_mode=research_mode)
        ):
            expanded = await _llm_call(
                llm_endpoint=llm_endpoint,
                llm_model=llm_model,
                llm_headers=llm_headers,
                messages=[
                    *msgs,
                    {"role": "assistant", "content": result},
                    {"role": "user", "content": expansion_user_message(min_words)},
                ],
                temperature=0.4,
                max_tokens=max_report_tokens,
                timeout=600,
            )
            if len(expanded.split()) > len(result.split()):
                result = expanded
        return result

    async def _compose(*, rewrite: bool) -> str:
        msgs: List[dict] = [{"role": "user", "content": prompt}]
        if rewrite:
            msgs.append({"role": "user", "content": _REWRITE_DUMP_USER})
        return await _generate(msgs)

    last_exc: Optional[BaseException] = None
    last_result = ""
    for attempt in range(1 + _MAX_REWRITE_ATTEMPTS):
        try:
            result = await _compose(rewrite=attempt > 0)
            last_exc = None
            last_result = result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "LDR synthesis attempt %s/%s failed: %s",
                attempt + 1,
                1 + _MAX_REWRITE_ATTEMPTS,
                exc,
            )
            continue
        if not report_needs_rewrite(result, research_mode=research_mode):
            repaired, _warnings = registry.validate_and_repair_report(result)
            return repaired
        logger.warning(
            "LDR synthesis attempt %s/%s needs rewrite (dump or missing title)",
            attempt + 1,
            1 + _MAX_REWRITE_ATTEMPTS,
        )

    if last_exc and not last_result:
        logger.error("LDR Nobody synthesis failed: %s", last_exc)
    else:
        logger.error("LDR synthesis still incomplete; using persistable fallback path")
    return persistable_synthesis_report(
        last_result,
        question=question,
        registry=registry,
        findings=findings,
        research_mode=research_mode,
    )
