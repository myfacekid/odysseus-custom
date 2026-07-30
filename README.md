# Nobody



A self-hosted AI workspace — chat, agents, research, and local model serving on
your hardware, with your data. Built for people who want the polished assistant
experience without surrendering the keys. Local-first, privacy-first, and nobody
else's business.

[Quick Start](#quick-start) · Setup Guide · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [License](#license)

## Features

- **Chat** — talk to any local model or API provider; wiring one up takes minutes.  
　vLLM · llama.cpp · Ollama · OpenRouter · OpenAI · Anthropic · Gemini · more
- **Agent** — give it tools and let it finish the job.  
　built on [opencode](https://github.com/anomalyco/opencode) · MCP · web · files · shell · skills · memory
- **Cookbook** — hardware-aware model recommendations, downloads, and one-click serving.  
　built on [llmfit](https://github.com/AlexsJones/llmfit) · VRAM-aware · GGUF / FP8 / AWQ · fit scoring · vLLM / llama.cpp serving
- **Deep Research** — multi-step runs that gather sources and synthesize a readable report.  
　web · Zotero · Links · seed papers · LDR gather + Nobody synthesis
- **Library** — documents, reports, chats, and papers in one place — Obsidian-like notes without the vault app.  
　multi-tab editor · markdown · linked notes · AI edits · Zotero papers · promote from projects
- **Links** — a portable knowledge graph across todos, documents, memories, skills, papers, and projects.  
　typed edges · suggestions · backlinks · agent-aware
- **Projects** — an optional context layer: the active project scopes chat, research, and agent working directory.  
　project chip · scoped tools · file browser · promote into Library
- **Compare** — run the same prompt across models side by side, including blind tests.  
　multi-model · blind test · synthesis
- **Memory / Skills** — persistent memory and reusable skills that improve as you work.  
　ChromaDB · fastembed (ONNX) · vector + keyword · import/export · self-evolving skills
- **Todos, Tasks & Calendar** — checklists, scheduled agent work, and local-first calendaring.  
　board · cron-style tasks · ntfy / browser · CalDAV · .ics
- **Gallery & Theme** — image editing plus a full appearance editor that matches the app.  
　inpaint · uploads · vision · theme tokens · density
- **Extras** — the rest of the toolbox when you need it.  
　file uploads (vision + PDF) · web search · presets · sessions · 2FA · MCP browser

## Demo

Landing page tour: `[docs/index.html](docs/index.html)`.

## Quick Start

Docker is the recommended path. Clone, run, then configure models and search in
**Settings**. Use `.env` only for deployment overrides (`APP_BIND`, `APP_PORT`,
`AUTH_ENABLED`, `DATABASE_URL`, admin seed, and similar).

```bash
git clone https://github.com/myfacekid/Nobody.git
cd Nobody
cp .env.example .env       # optional, but recommended for explicit defaults
docker compose up -d --build
```

Open `http://localhost:7000` when the containers are healthy. Compose binds the
UI to `127.0.0.1` by default. Set `APP_PORT` if `7000` is taken; set
`APP_BIND=0.0.0.0` only for intentional LAN or reverse-proxy access.

On first boot, Nobody creates an admin account (`admin` unless
`NOBODY_ADMIN_USER` is set) and prints a temporary password in the terminal —
or in `docker compose logs nobody`. Log in, then change it in **Settings**.

Native Linux/macOS/Windows, Apple Silicon, GPU overlays, Ollama, HTTPS,
security hardening, and configuration live in the
[setup guide](docs/setup.md).

## License

MIT -- see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).                                  |  
     

