"""Keep src.search and services.search content extraction behavior aligned."""

import httpx
import pytest

pytest.importorskip("bs4")

from services.search import content as service_content
from src.search import content as src_content


class _FakeResponse:
    status_code = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}
    content = b""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com/blocked")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"{self.status_code} error", request=request, response=response,
            )


@pytest.mark.parametrize("module", [src_content, service_content])
def test_content_fetcher_extracts_og_image_and_body_fallback(module, tmp_path, monkeypatch):
    html = """
    <html>
      <head>
        <title>Example</title>
        <meta property="og:image" content="https://example.com/cover.jpg">
      </head>
      <body>
        <nav>Navigation text should not win</nav>
        <div class="content">Tiny</div>
        <main>
          <p>This is the substantive body text that should be retained.</p>
          <p>It is much longer than the tiny class-matched wrapper.</p>
        </main>
        <script>window.secret = "not content";</script>
      </body>
    </html>
    """

    monkeypatch.setattr(module, "CONTENT_CACHE_DIR", tmp_path)
    module.content_cache_index.clear()
    monkeypatch.setattr(module, "_get_public_url", lambda url, headers, timeout: _FakeResponse(html))

    result = module.fetch_webpage_content("https://example.com/parity-test")

    assert result["og_image"] == "https://example.com/cover.jpg"
    assert "substantive body text" in result["content"]
    assert "much longer than the tiny" in result["content"]
    assert "window.secret" not in result["content"]


@pytest.mark.parametrize("module", [src_content, service_content])
def test_content_fetcher_skips_og_image_when_disabled(module, tmp_path, monkeypatch):
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://example.com/cover.jpg">
      </head>
      <body><main><p>Body text for the page.</p></main></body>
    </html>
    """

    monkeypatch.setattr(module, "CONTENT_CACHE_DIR", tmp_path)
    module.content_cache_index.clear()
    monkeypatch.setattr(module, "_get_public_url", lambda url, headers, timeout: _FakeResponse(html))

    result = module.fetch_webpage_content(
        "https://example.com/no-og", include_og_image=False,
    )

    assert result["og_image"] == ""
    assert "Body text" in result["content"]


@pytest.mark.parametrize("module", [src_content, service_content])
def test_content_fetcher_returns_empty_on_http_error(module, tmp_path, monkeypatch):
    """A 403/404 from the page must not raise — chat auto-fetch used to 500."""
    monkeypatch.setattr(module, "CONTENT_CACHE_DIR", tmp_path)
    module.content_cache_index.clear()
    monkeypatch.setattr(
        module, "_get_public_url",
        lambda url, headers, timeout: _FakeResponse("nope", status_code=403),
    )

    result = module.fetch_webpage_content("https://example.com/blocked")

    assert result["success"] is False
    assert "403" in result["error"]
    assert result["content"] == ""
