"""Map Nobody OpenAI-compatible endpoints to LangChain chat models for LDR."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from src.endpoint_resolver import normalize_base
from src.llm_core import _detect_provider

logger = logging.getLogger(__name__)


def openai_api_base_from_endpoint(chat_endpoint: str) -> str:
    """Derive LangChain ``base_url`` from an Nobody chat completions URL."""
    base = normalize_base((chat_endpoint or "").strip())
    if not base:
        raise ValueError("Empty LLM endpoint URL")

    provider = _detect_provider(base)
    parsed = urlparse(base)
    path = (parsed.path or "").rstrip("/")

    if provider == "ollama":
        # OpenAI-compatible Ollama listens on /v1
        if path.endswith("/v1"):
            return base
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
        return f"{root.rstrip('/')}/v1"

    if provider == "anthropic":
        return base

    if path.endswith("/v1"):
        return base
    root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
    return f"{root.rstrip('/')}/v1"


def api_key_from_headers(headers: Optional[Dict[str, str]]) -> str:
    """Extract bearer token for ChatOpenAI; local servers often need a placeholder."""
    for key, value in (headers or {}).items():
        if key.lower() != "authorization":
            continue
        text = (value or "").strip()
        if text.lower().startswith("bearer "):
            return text[7:].strip() or "none"
        if text:
            return text
    return "none"


def default_headers_for_langchain(
    headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Pass through non-Authorization headers (e.g. custom provider headers)."""
    out: Dict[str, str] = {}
    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            continue
        if value is not None:
            out[key] = str(value)
    return out


def build_langchain_chat_model(
    *,
    chat_endpoint: str,
    model: str,
    headers: Optional[Dict[str, str]] = None,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    **kwargs: Any,
):
    """Return a LangChain chat model wired to an Nobody research endpoint."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "LangChain stack not installed. "
            "Reinstall with: pip install -r requirements.txt "
            "(requires Python 3.12–3.13)."
        ) from exc

    model_name = (model or "").strip()
    if not model_name:
        raise ValueError("Model name is required for LDR research")

    base_url = openai_api_base_from_endpoint(chat_endpoint)
    api_key = api_key_from_headers(headers)
    extra_headers = default_headers_for_langchain(headers)

    params: Dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
    }
    if max_tokens is not None and max_tokens > 0:
        params["max_tokens"] = max_tokens
    if extra_headers:
        params["default_headers"] = extra_headers
    params.update(kwargs)

    logger.debug("LDR LangChain model base_url=%s model=%s", base_url, model_name)
    return ChatOpenAI(**params)
