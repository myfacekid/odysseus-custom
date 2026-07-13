"""Soft claim-grounding verification for Deep Research reports.

After synthesis, check whether each inline ``[N]`` citation is actually
supported by the text of source N. This catches the "real citation, wrong
claim" failure mode. It is deliberately *soft*: it appends a "Citation
verification" section flagging unsupported claims but never rewrites the report.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_UNSUPPORTED = "UNSUPPORTED"
VERDICT_UNKNOWN = "UNKNOWN"
_VALID_VERDICTS = {VERDICT_SUPPORTED, VERDICT_PARTIAL, VERDICT_UNSUPPORTED, VERDICT_UNKNOWN}


def extract_claims(report: str, *, max_claims: int = 40) -> List[dict]:
    """Return sentence-level claims carrying inline [N] citations (body only)."""
    from src.research_evidence import extract_citation_nums, split_references_section

    body, _refs = split_references_section(report or "")
    claims: List[dict] = []
    for line in body.split("\n"):
        s = line.strip()
        if not s or s.startswith(("#", "|", ">", "```")):
            continue
        # Strip leading list markers so the sentence reads cleanly.
        s = re.sub(r"^[-*+]\s+", "", s)
        for sent in _SENTENCE_SPLIT.split(s):
            nums = extract_citation_nums(sent)
            if not nums:
                continue
            text = re.sub(r"\s+", " ", sent).strip()
            if len(text) < 18:
                continue
            claims.append({"text": text, "nums": sorted(nums)})
            if len(claims) >= max_claims:
                return claims
    return claims


def _source_text_map(registry, findings, *, max_chars: int = 1400) -> Dict[int, dict]:
    """citation_num -> {title, text} using the richest available source text."""
    out: Dict[int, dict] = {}
    for f in findings or []:
        num = f.get("citation_num")
        if not isinstance(num, int):
            continue
        text = (
            f.get("evidence")
            or f.get("abstract")
            or f.get("summary")
            or ""
        ).strip()
        title = (f.get("title") or "").strip()
        if text and (num not in out or len(text) > len(out[num].get("text", ""))):
            out[num] = {"title": title, "text": text[:max_chars]}
    try:
        sources = registry.sources() if registry else []
    except Exception:
        sources = []
    for src in sources:
        num = getattr(src, "citation_num", None)
        if not isinstance(num, int) or num in out:
            continue
        text = (getattr(src, "content_excerpt", "") or getattr(src, "title", "") or "").strip()
        if text:
            out[num] = {"title": getattr(src, "title", ""), "text": text[:max_chars]}
    return out


def _build_batch_prompt(batch: List[dict], text_map: Dict[int, dict]) -> str:
    lines = [
        "You are a meticulous scientific fact-checker. For each numbered CLAIM, decide "
        "whether the provided SOURCE excerpt(s) support it.",
        "",
        "Verdicts:",
        "- SUPPORTED: the excerpt clearly states or directly entails the claim.",
        "- PARTIAL: related but the excerpt does not fully establish the claim, or the "
        "claim overreaches what the excerpt says.",
        "- UNSUPPORTED: the excerpt does not support the claim or is insufficient to judge.",
        "",
        'Return ONLY a JSON array: [{"i": <claim index>, "verdict": "SUPPORTED|PARTIAL|UNSUPPORTED", "reason": "<=15 words"}].',
        "",
    ]
    for idx, claim in enumerate(batch):
        lines.append(f"CLAIM [{idx}]: {claim['text']}")
        for num in claim["nums"]:
            src = text_map.get(num)
            if not src:
                lines.append(f"  SOURCE [{num}]: (no source text available)")
                continue
            title = src.get("title") or ""
            excerpt = (src.get("text") or "").strip()
            head = f"  SOURCE [{num}]"
            if title:
                head += f" — {title}"
            lines.append(f"{head}:")
            lines.append(f"    {excerpt}")
        lines.append("")
    return "\n".join(lines)


def _parse_verdicts(response: str, batch_len: int) -> List[dict]:
    from src.research_utils import strip_thinking

    text = strip_thinking(response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    parsed = None
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            parsed = None
    verdicts = [{"verdict": VERDICT_UNKNOWN, "reason": ""} for _ in range(batch_len)]
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                i = int(item.get("i"))
            except (TypeError, ValueError):
                continue
            if not (0 <= i < batch_len):
                continue
            verdict = str(item.get("verdict") or "").strip().upper()
            if verdict not in _VALID_VERDICTS:
                verdict = VERDICT_UNKNOWN
            verdicts[i] = {"verdict": verdict, "reason": str(item.get("reason") or "").strip()[:160]}
    return verdicts


async def verify_claims(
    claims: List[dict],
    text_map: Dict[int, dict],
    *,
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    batch_size: int = 5,
    timeout: int = 90,
) -> List[dict]:
    """Return each claim annotated with a support verdict."""
    from src.llm_core import llm_call_async

    results: List[dict] = []
    for i in range(0, len(claims), batch_size):
        batch = claims[i : i + batch_size]
        prompt = _build_batch_prompt(batch, text_map)
        try:
            response = await llm_call_async(
                url=llm_endpoint,
                model=llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
                headers=llm_headers,
                timeout=timeout,
            )
            verdicts = _parse_verdicts(response, len(batch))
        except Exception as exc:
            logger.warning("Claim verification batch failed: %s", exc)
            verdicts = [{"verdict": VERDICT_UNKNOWN, "reason": ""} for _ in batch]
        for claim, verdict in zip(batch, verdicts):
            results.append({**claim, **verdict})
    return results


def build_verification_section(verdicts: List[dict]) -> str:
    """Render the '## Citation verification' section from verdicts."""
    if not verdicts:
        return ""
    checked = len(verdicts)
    supported = sum(1 for v in verdicts if v["verdict"] == VERDICT_SUPPORTED)
    partial = [v for v in verdicts if v["verdict"] == VERDICT_PARTIAL]
    unsupported = [v for v in verdicts if v["verdict"] == VERDICT_UNSUPPORTED]

    lines = ["## Citation verification", ""]
    lines.append(
        f"An automated grounding check compared {checked} cited claim"
        f"{'' if checked == 1 else 's'} against the corresponding source text: "
        f"**{supported} supported**, **{len(partial)} partial**, "
        f"**{len(unsupported)} unsupported**."
    )
    if not partial and not unsupported:
        lines.append("")
        lines.append("_No unsupported claims were detected._")
        return "\n".join(lines)

    def _fmt(v: dict) -> str:
        cites = ", ".join(f"[{n}]" for n in v["nums"])
        snippet = v["text"]
        if len(snippet) > 200:
            snippet = snippet[:199].rstrip() + "\u2026"
        reason = f" — {v['reason']}" if v.get("reason") else ""
        return f"- {cites} *{snippet}*{reason}"

    if unsupported:
        lines.append("")
        lines.append("**Claims not supported by their cited source(s):**")
        lines.extend(_fmt(v) for v in unsupported)
    if partial:
        lines.append("")
        lines.append("**Claims only partially supported (verify before relying on them):**")
        lines.extend(_fmt(v) for v in partial)
    lines.append("")
    lines.append(
        "_Automated check — flags possible citation/claim mismatches for human review; "
        "it does not itself prove a claim false._"
    )
    return "\n".join(lines)


def summarize_verdicts(verdicts: List[dict]) -> dict:
    """Compact, UI-friendly summary of verification verdicts."""
    checked = len(verdicts)
    supported = sum(1 for v in verdicts if v["verdict"] == VERDICT_SUPPORTED)
    partial = [v for v in verdicts if v["verdict"] == VERDICT_PARTIAL]
    unsupported = [v for v in verdicts if v["verdict"] == VERDICT_UNSUPPORTED]
    unknown = sum(1 for v in verdicts if v["verdict"] == VERDICT_UNKNOWN)

    def _flag(v: dict) -> dict:
        snippet = v.get("text", "")
        if len(snippet) > 240:
            snippet = snippet[:239].rstrip() + "\u2026"
        return {
            "claim": snippet,
            "citations": list(v.get("nums") or []),
            "verdict": v["verdict"],
            "reason": v.get("reason", ""),
        }

    if checked and (checked - unknown):
        confidence = round(100 * supported / (checked - unknown))
    else:
        confidence = None
    return {
        "checked": checked,
        "supported": supported,
        "partial": len(partial),
        "unsupported": len(unsupported),
        "unknown": unknown,
        "confidence": confidence,
        "flagged": [_flag(v) for v in unsupported] + [_flag(v) for v in partial],
    }


async def verify_and_annotate(
    report: str,
    *,
    registry,
    findings: List[dict],
    llm_endpoint: str,
    llm_model: str,
    llm_headers: Optional[dict] = None,
    max_claims: int = 40,
) -> tuple:
    """Run the verification pass; return (annotated_report, structured_summary).

    ``structured_summary`` is ``None`` when there were no citable claims to check.
    """
    from src.research_coverage import insert_section_before_references

    claims = extract_claims(report, max_claims=max_claims)
    if not claims:
        return report, None
    text_map = _source_text_map(registry, findings)
    verdicts = await verify_claims(
        claims,
        text_map,
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_headers=llm_headers,
    )
    summary = summarize_verdicts(verdicts)
    section = build_verification_section(verdicts)
    if section:
        report = insert_section_before_references(report, section)
    return report, summary
