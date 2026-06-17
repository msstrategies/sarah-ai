# Sarah AI

A deterministic lead-ops pipeline: one command turns a niche + a city into a qualified, researched, ready-to-send outreach list.

Built to test a thesis - most repetitive "Virtual Assistant" work is a fixed pattern that a deterministic pipeline does faster and more reliably than a human, with an LLM only at the steps that genuinely need judgment.

## What it does

```
python3 sarah_ai.py "Coiffeur" "Bern"        # scrape + analyze + generate outreach
python3 sarah_ai.py "Restaurant" "Zürich" --max 10
python3 sarah_ai.py --research "https://example.com"  # analyze one site
python3 sarah_ai.py --demo                    # runs offline with mock data
```

1. **Scrape** local businesses for the niche/city (Apify)
2. **Extract** and clean each website's text (custom HTML parser, no heavy deps)
3. **Analyze** the business and its gap (Claude)
4. **Generate** a tailored outreach message (Claude)
5. **Export** a CSV + a readable markdown report

## Design principles

- **Deterministic over autonomous** - every step is gated, logged, reproducible. The LLM analyzes and writes; the structure stays fixed.
- **Tool boundaries** - each capability is a discrete, testable function: `scrape_leads`, `analyze_company`, `generate_outreach`, `research_website`.
- **Production hygiene** - secrets via `.env` (never hardcoded), `--demo` mode for offline testing, idempotent runs.
- **Minimal dependencies** - Python stdlib first.

## Setup

```bash
cp .env.example .env   # add your keys
python3 sarah_ai.py --demo   # verify it runs
```

## Status

Working prototype. Proof-of-concept behind a larger thesis: deterministic AI replacing repetitive VA tasks via deep integration (MCP) into a customer's own software.

## License

MIT
