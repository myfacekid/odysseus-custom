"""Relevance gating for Deep Research evidence collection."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "from", "with",
    "they", "this", "that", "will", "your", "what", "when", "where", "which",
    "how", "who", "why", "into", "about", "than", "then", "them", "these",
    "those", "their", "there", "would", "could", "should", "also", "more",
    "most", "some", "such", "only", "other", "each", "between", "through",
    "during", "before", "after", "above", "below", "being", "both", "same",
    "does", "doing", "done", "just", "like", "make", "made", "many", "much",
    "very", "were", "while", "using", "used", "use", "study", "studies",
    "research", "paper", "papers", "analysis", "review", "results", "methods",
    "data", "based", "report", "findings", "evidence", "sources", "source",
    "compare", "between", "related", "work", "recent", "current", "latest",
    # Conversational / instructional verbs and framing words. These describe
    # what the user wants DONE, not the topic, so they must never count as
    # distinctive relevance tokens (otherwise "please find the most cited
    # papers that use X" gates candidates on "please/find/cited").
    "please", "find", "finding", "identify", "list", "show", "give", "tell",
    "want", "need", "needed", "looking", "kindly", "provide", "gather",
    "cite", "cited", "citing", "citation", "citations", "reference",
    "referenced", "referencing", "help", "please", "get", "fetch",
})

# Over-broad terms shared across unrelated bioinformatics papers.
_GENERIC_SCIENCE_TERMS = frozenset({
    "protein", "structure", "prediction", "model", "models", "learning",
    "deep", "neural", "network", "networks", "sequence", "sequences",
    "genome", "genomic", "gene", "genes", "cell", "cells", "molecular",
    "atomic", "language", "scale", "accurate", "accuracy", "method",
    "methods", "approach", "approaches", "novel", "new", "design", "using",
    "highly", "high", "level", "atomic", "evolutionary", "folding", "fold",
    "rna", "dna", "alignment", "assembly", "phylogenetic", "taxonomic",
})

# Terms that appear in anchor extraction but are too broad for overlap gating.
_WEAK_ANCHOR_TERMS = frozenset({
    "function", "functions", "protein", "proteins", "trained", "search",
    "structure", "structural", "methods", "method", "compare", "comparison",
    "handle", "lab", "laboratory", "papers", "paper", "answer", "chosen",
    "generative", "evolution", "simulating", "million", "years", "fast",
    "accurate", "clearly", "understand", "newly", "designed", "alphabet",
    "architecture", "models", "model", "specifically", "questions", "other",
    "same", "there", "please", "transfers", "point", "cloud", "space",
    "language", "uses", "use", "more", "while", "does", "which", "how",
    "handle", "questions", "work", "life", "uncharacterized", "determining",
    "fundamental", "structured", "vocabularies", "classification", "multi",
    "label", "fusion", "pretrained", "compare", "contrasts", "contrast",
    "overview", "background", "related", "similar", "recent", "novel",
    "representation", "representations", "vocabulary", "vocabularies",
    "annotation", "annotations", "classification", "ontology",
})

RECENCY_REQUEST_MARKERS = (
    "latest",
    "recent",
    "last five years",
    "last 5 years",
    "past five years",
    "past 5 years",
    "past decade",
    "this year",
    "current literature",
    "state of the art",
    "state-of-the-art",
    "cutting edge",
    "new developments",
    "since 201",
    "since 202",
)

IRRELEVANCE_MARKERS = [
    "not relevant",
    "not related",
    "unrelated",
    "no relevant",
    "does not contain",
    "does not address",
    "does not discuss",
    "does not relate",
    "not pertinent",
    "not about",
    "completely unrelated",
    "off-topic",
    "off topic",
    "wrong topic",
    "different topic",
    "non-academic",
    "system message",
    "boilerplate",
    "no substantive",
    "insufficient to",
    "unable to extract relevant",
    "no information about",
    "nothing about",
    "cannot answer",
    "cannot contribute",
    "does not pertain",
    "not applicable",
    "outside the scope",
    "out of scope",
]


def user_requests_recency(text: str) -> bool:
    """True when the user explicitly asks for recent or time-bounded literature."""
    q = (text or "").lower()
    return any(marker in q for marker in RECENCY_REQUEST_MARKERS)


def tokenize_query(text: str) -> List[str]:
    tokens = [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3]
    return [t for t in tokens if t not in _STOPWORDS]


def specific_query_tokens(question: str) -> List[str]:
    """Distinctive tokens for gating — drops field-wide vocabulary shared by unrelated papers."""
    return [t for t in tokenize_query(question) if t not in _GENERIC_SCIENCE_TERMS]


def score_text_relevance(text: str, question: str) -> float:
    """Return 0–1-ish overlap score between question and text."""
    if not text or not question:
        return 0.0
    tokens = tokenize_query(question)
    if not tokens:
        return 0.0
    hay = (text or "").lower()
    phrase = (question or "").lower().strip()
    hits = sum(1 for t in tokens if t in hay)
    if hits == 0:
        return 0.0
    base = hits / len(tokens)
    if len(phrase) >= 12 and phrase in hay:
        base += 0.35
    min_hits = 2 if len(tokens) >= 4 else 1
    if hits < min_hits:
        return base * 0.35
    return min(base, 1.0)


def score_specific_text_relevance(text: str, question: str) -> float:
    """Overlap on distinctive terms only — rejects generic bioinformatics matches."""
    if not text or not question:
        return 0.0
    tokens = specific_query_tokens(question)
    if not tokens:
        return score_text_relevance(text, question)
    hay = (text or "").lower()
    hits = sum(1 for t in tokens if t in hay)
    if hits == 0:
        return 0.0
    base = hits / len(tokens)
    min_hits = 2 if len(tokens) >= 4 else 1
    if hits < min_hits:
        return base * 0.35
    return min(base, 1.0)


def finding_text(finding: dict, *, evidence_chars: int = 800) -> str:
    parts = [
        finding.get("title") or "",
        finding.get("summary") or "",
        (finding.get("rational") or "")[:500],
        (finding.get("evidence") or "")[:evidence_chars],
        finding.get("abstract") or "",
    ]
    return " ".join(p for p in parts if p)


def score_specific_finding_relevance(finding: dict, question: str) -> float:
    return score_specific_text_relevance(finding_text(finding), question)


def score_finding_relevance(finding: dict, question: str) -> float:
    return score_text_relevance(finding_text(finding), question)


def score_node_relevance(node: dict, question: str) -> float:
    title = node.get("title") or ""
    snippet = node.get("snippet") or ""
    meta = node.get("meta") or {}
    meta_bits = " ".join(
        str(meta.get(k) or "")
        for k in ("authors", "doi", "path", "abstract")
    )
    return score_text_relevance(f"{title} {snippet} {meta_bits}", question)


def score_search_result(result: dict, question: str) -> float:
    parts = [
        result.get("title") or "",
        result.get("content") or "",
        result.get("snippet") or "",
        result.get("description") or "",
    ]
    return score_text_relevance(" ".join(p for p in parts if p), question)


def is_extraction_irrelevant(parsed: dict) -> bool:
    if parsed.get("relevant") is False:
        return True
    combined = " ".join([
        str(parsed.get("rational") or ""),
        str(parsed.get("summary") or ""),
    ]).lower()
    return any(marker in combined for marker in IRRELEVANCE_MARKERS)


def matches_avoid_topics(
    finding: dict,
    avoid_topics: Optional[Iterable[str]],
) -> bool:
    """True when the finding text hits a planner-derived avoid-topic phrase."""
    if not avoid_topics:
        return False
    hay = finding_text(finding).lower()
    for topic in avoid_topics:
        t = (topic or "").strip().lower()
        if len(t) >= 4 and t in hay:
            return True
    return False


def is_finding_relevant(
    finding: dict,
    question: str,
    *,
    min_score: float = 0.2,
    avoid_topics: Optional[Iterable[str]] = None,
    plan_anchor_terms: Optional[Iterable[str]] = None,
) -> bool:
    if finding.get("is_seed"):
        return True
    if is_extraction_irrelevant(finding):
        return False
    if not (question or "").strip():
        return True
    if matches_avoid_topics(finding, avoid_topics):
        return False
    generic = score_finding_relevance(finding, question)
    specific = score_specific_finding_relevance(finding, question)
    if specific >= min_score:
        return True
    anchors = list(plan_anchor_terms or []) or strong_anchor_terms(question)
    if anchors and _finding_has_anchor_overlap(
        finding, anchors, plan_anchors=plan_anchor_terms,
    ):
        return specific >= 0.08
    if generic >= min_score and specific < 0.08:
        return False
    return False


def filter_relevant_findings(
    findings: Iterable[dict],
    question: str,
    *,
    min_score: float = 0.2,
    avoid_topics: Optional[Iterable[str]] = None,
    plan_anchor_terms: Optional[Iterable[str]] = None,
) -> List[dict]:
    out: List[dict] = []
    for finding in findings or []:
        if is_finding_relevant(
            finding,
            question,
            min_score=min_score,
            avoid_topics=avoid_topics,
            plan_anchor_terms=plan_anchor_terms,
        ):
            out.append(finding)
    return out


RELEVANCE_GATE_PROMPT = """You gate sources for an academic literature review.

Research question:
{question}

Candidate source:
Title: {title}
Type: {source_type}
Preview:
{preview}

Is this source materially relevant to answering the research question?
Reply with ONLY "YES" or "NO"."""


def parse_relevance_yes_no(response: str) -> Optional[bool]:
    """Parse a YES/NO relevance gate response."""
    if not response:
        return None
    clean = re.sub(r"^[\s*_`\"'<>#\-]+", "", (response or "").strip()).upper()
    if clean.startswith("YES"):
        return True
    if clean.startswith("NO"):
        return False
    return None


def heuristic_relevance_decision(title: str, preview: str, question: str) -> Optional[bool]:
    """Fast accept/reject before an LLM gate. None = needs LLM."""
    text = f"{title} {preview}"
    generic = score_text_relevance(text, question)
    specific = score_specific_text_relevance(text, question)
    if specific >= 0.18:
        return True
    if generic >= 0.42 and specific < 0.08:
        return False
    if generic < 0.1:
        return False
    return None


def min_node_score_for_graph_source(source: str, base: float = 0.22) -> float:
    """Indirect graph sources need stronger lexical overlap."""
    if source in ("graph_neighbor", "collection"):
        return max(base, 0.28)
    return base


def parse_author_name_terms(authors: str) -> set[str]:
    """Lowercase author name tokens to exclude from paper search queries."""
    terms: set[str] = set()
    for chunk in re.split(r"[;,]|\band\b", authors or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        for word in re.findall(r"[A-Za-z]+", chunk):
            w = word.lower()
            if len(w) >= 3 and w not in _STOPWORDS:
                terms.add(w)
    return terms


def author_terms_from_finding(finding: dict) -> set[str]:
    """Collect author-name tokens attached to a seed finding."""
    terms = parse_author_name_terms(finding.get("authors") or "")
    for key in ("title", "summary", "evidence", "abstract"):
        blob = (finding.get(key) or "")[:400]
        if not blob:
            continue
        first_line = blob.split("\n", 1)[0]
        if len(first_line) <= 120 and re.search(r"[A-Z][a-z]+\s+[A-Z]", first_line):
            terms.update(parse_author_name_terms(first_line))
    return terms


def extract_anchor_terms(*texts: str, exclude_terms: Optional[Iterable[str]] = None) -> List[str]:
    """Distinctive terms from titles/questions (model names, acronyms, digit tokens)."""
    seen: set[str] = set()
    anchors: List[str] = []
    blocked = {t.lower() for t in (exclude_terms or []) if t}

    def _add(raw: str) -> None:
        term = (raw or "").strip().lower()
        if (
            len(term) < 3
            or term in _STOPWORDS
            or term in _GENERIC_SCIENCE_TERMS
            or term in _WEAK_ANCHOR_TERMS
            or term in seen
            or term in blocked
        ):
            return
        seen.add(term)
        anchors.append(term)

    blob = " ".join(t for t in texts if t)
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9]*(?:[0-9]+|[A-Z][a-z]+)+\b", blob):
        _add(match.group(0))
    for match in re.finditer(r"\b[A-Z]{2,}[0-9]*\b", blob):
        _add(match.group(0))
    for tok in re.findall(r"[a-z0-9]+", blob.lower()):
        if any(ch.isdigit() for ch in tok):
            _add(tok)
    for tok in tokenize_query(blob):
        if tok not in _GENERIC_SCIENCE_TERMS:
            _add(tok)
    return anchors


def _looks_like_author_only(text: str) -> bool:
    """Heuristic: short blob that is mostly person names, not an abstract."""
    raw = (text or "").strip()
    if not raw or len(raw) > 240:
        return False
    words = re.findall(r"[A-Za-z]+", raw)
    if len(words) < 2:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps >= max(2, len(words) - 1)


def build_seed_fingerprint(seed_findings: Iterable[dict]) -> str:
    """Text fingerprint from seed titles and abstracts — not PDF body or author lists."""
    parts: List[str] = []
    for finding in seed_findings or []:
        if not finding:
            continue
        parts.append(finding.get("title") or "")
        abstract = (finding.get("abstract") or "").strip()
        if abstract:
            parts.append(abstract[:800])
        else:
            summary = (finding.get("summary") or "").strip()
            if summary and not _looks_like_author_only(summary):
                parts.append(summary[:600])
        doi = (finding.get("doi_or_id") or "").strip()
        if doi.startswith("10."):
            parts.append(doi)
    return " ".join(p for p in parts if p).strip()


def build_relevance_query(
    question: str,
    *,
    seed_findings: Optional[Iterable[dict]] = None,
) -> str:
    """Combine user question with seed paper context for gating/scoring."""
    parts = [(question or "").strip()]
    fingerprint = build_seed_fingerprint(seed_findings or [])
    if fingerprint:
        parts.append(fingerprint)
    author_block = set()
    for finding in seed_findings or []:
        author_block.update(author_terms_from_finding(finding))
    for term in extract_anchor_terms(question or "", fingerprint, exclude_terms=author_block):
        parts.append(term)
    return " ".join(p for p in parts if p).strip()


def seed_knowledge_queries(
    question: str,
    seed_findings: Iterable[dict],
    *,
    limit: int = 6,
) -> List[str]:
    """Explicit Links graph queries from seed titles and anchor terms."""
    seen: set[str] = set()
    queries: List[str] = []

    def _add(raw: str) -> None:
        text = (raw or "").strip()
        if len(text) < 3:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        queries.append(text)

    seeds = [
        f for f in (seed_findings or [])
        if f.get("is_seed") or f.get("paper_key") or f.get("zotero_key")
    ]
    author_block: set[str] = set()
    for finding in seeds:
        author_block.update(author_terms_from_finding(finding))
    for finding in seeds:
        title = (finding.get("title") or "").strip()
        if len(title) >= 10:
            _add(title)
        for term in extract_anchor_terms(
            title,
            finding.get("abstract") or "",
            exclude_terms=author_block,
        ):
            _add(term)

    for term in extract_anchor_terms(question or ""):
        _add(term)

    return queries[: max(limit, 1)]


def score_seed_overlap(finding: dict, seed_findings: Iterable[dict]) -> float:
    fingerprint = build_seed_fingerprint(seed_findings)
    if not fingerprint:
        return 0.0
    return score_finding_relevance(finding, fingerprint)


def strong_anchor_terms(*texts: str, exclude_terms: Optional[Iterable[str]] = None) -> List[str]:
    """Distinctive anchors suitable for topical overlap checks."""
    return [
        a for a in extract_anchor_terms(*texts, exclude_terms=exclude_terms)
        if a not in _WEAK_ANCHOR_TERMS
    ]


def _is_distinctive_anchor(
    term: str,
    *,
    plan_anchors: Optional[Iterable[str]] = None,
) -> bool:
    """Single-token anchor match is only meaningful for method names, not broad nouns."""
    t = (term or "").strip().lower()
    if not t or t in _WEAK_ANCHOR_TERMS or t in _GENERIC_SCIENCE_TERMS:
        return False
    if plan_anchors and t in {a.lower() for a in plan_anchors if a}:
        return True
    if any(ch.isdigit() for ch in t):
        return True
    if len(t) >= 7 and t not in _WEAK_ANCHOR_TERMS:
        return True
    return False


def _finding_has_anchor_overlap(
    finding: dict,
    anchor_terms: List[str],
    *,
    plan_anchors: Optional[Iterable[str]] = None,
) -> bool:
    if not anchor_terms:
        return False
    hay = " ".join([
        finding.get("title") or "",
        finding.get("summary") or "",
        (finding.get("evidence") or "")[:1200],
        finding.get("abstract") or "",
    ]).lower()
    specific = [t for t in anchor_terms if t not in _GENERIC_SCIENCE_TERMS]
    pool = specific or anchor_terms
    hits = [term for term in pool if term in hay]
    if not hits:
        return False
    strong_hits = [h for h in hits if h not in _WEAK_ANCHOR_TERMS]
    if len(strong_hits) >= 2:
        return True
    if len(strong_hits) == 1 and _is_distinctive_anchor(
        strong_hits[0], plan_anchors=plan_anchors,
    ):
        return True
    return False


def is_similar_paper_relevant(
    finding: dict,
    question: str,
    seed_findings: Iterable[dict],
    *,
    min_specific_score: float = 0.12,
    research_mode: str = "",
    avoid_topics: Optional[Iterable[str]] = None,
    plan_anchor_terms: Optional[Iterable[str]] = None,
) -> bool:
    """Similar-paper APIs often return broad co-citation noise — require topical focus."""
    if finding.get("is_seed"):
        return True
    seeds = list(seed_findings or [])
    combined = build_relevance_query(question, seed_findings=seeds) if seeds else (question or "")
    if matches_avoid_topics(finding, avoid_topics):
        return False
    if research_mode == "compare":
        min_specific_score = max(min_specific_score, 0.14)

    specific = score_specific_finding_relevance(finding, combined)
    if specific >= min_specific_score:
        return True

    anchors = list(plan_anchor_terms or []) or strong_anchor_terms(
        build_seed_fingerprint(seeds),
        question or "",
    )
    if anchors and _finding_has_anchor_overlap(
        finding, anchors, plan_anchors=plan_anchor_terms,
    ):
        return specific >= 0.08

    generic = score_finding_relevance(finding, combined)
    if generic >= 0.25 and specific < 0.08:
        return False
    return False


RELEVANCE_GATE_WITH_SEEDS_PROMPT = """You gate sources for an academic literature review.

Research question:
{question}

Seed papers (sources must relate to these paper topics — not author biographies):
{seed_context}

Candidate source:
Title: {title}
Type: {source_type}
Preview:
{preview}

Is this source materially relevant to the research question and the seed papers' topics?
Reject author profile pages, citation dashboards, and papers unrelated to the seed topics.
Reject papers that only share broad field vocabulary (protein, machine learning, bioinformatics)
but address a different sub-problem than the question or seeds (e.g. GO function prediction when
the question compares structure representations).
Reply with ONLY "YES" or "NO"."""


def format_seed_context(seed_findings: Iterable[dict], *, limit: int = 6) -> str:
    lines: List[str] = []
    for finding in list(seed_findings or [])[:limit]:
        title = (finding.get("title") or finding.get("paper_key") or "Untitled").strip()
        preview = (finding.get("abstract") or finding.get("summary") or "").strip()
        if not preview:
            preview = (finding.get("evidence") or "")[:240].strip()
        doi = (finding.get("doi_or_id") or "").strip()
        bits = [f"- {title}"]
        if doi.startswith("10."):
            bits.append(f"  DOI: {doi}")
        if preview and not _looks_like_author_only(preview):
            bits.append(f"  {preview[:240]}")
        lines.append("\n".join(bits))
    return "\n".join(lines) if lines else "(none)"
