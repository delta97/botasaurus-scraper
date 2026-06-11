# Botasaurus Automation Studio

A web app that puts a visual, AI-driven control panel on top of the
[Botasaurus](https://github.com/omkarcloud/botasaurus) browser-automation
library (vendored in `vendor/botasaurus`).

Describe what you want in plain English — *"go to modernize.com and fill out
the lead form"* — and an autonomous agent drives a real Chrome browser to do
it: it snapshots the page, decides the next action with an LLM (via
[OpenRouter](https://openrouter.ai)), executes it, and repeats. Every run is
recorded as a deterministic **recipe** that can be replayed forever **without
AI**, exported as JSON/YAML, and scheduled with cron.

## Features

- **Settings UI** — OpenRouter API key + model picker (live model list),
  persisted in a local SQLite database.
- **Natural-language tasks** — goal + URL in, autonomous browser agent out.
- **Recipes** — successful runs become replayable step files with
  `{{variables}}` (typed values are auto-parametrized), editable in the UI,
  exportable as JSON or YAML.
- **Visual Botasaurus config** — headless, wait-for-full-page-load, block
  images/CSS, proxy, user agent, window size, Chrome profile, Cloudflare
  bypass, markdown output… per run or as defaults.
- **Deep logging** — every step (action, selector, value, duration, error,
  screenshot) and every LLM call (full prompt, response, token counts,
  latency) is stored in SQLite and shown in a run timeline, so failures can
  be reverse-engineered.
- **Frugal AI usage** — the LLM is only consulted for decisions:
  - HTML → markdown/text conversion is pure Python (markdownify), never AI
  - one `fill_form` decision executes all fields as a batch, no per-field calls
  - failed selectors retry recorded fallbacks before re-asking the LLM
  - the LLM sees a compressed ~6 KB page snapshot, never raw HTML
  - recipe replays use **zero** AI

## Setup

```bash
./setup.sh        # vendors botasaurus, installs python+npm deps, installs Chrome
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000, go to **Settings**, paste your OpenRouter API key
and pick a model. Check http://localhost:8000/api/health to confirm Chrome
was found.

Requirements: Python ≥ 3.9, Node ≥ 18 (frontend build only), Google Chrome or
Chromium on PATH (setup.sh installs it on Debian/Ubuntu). In containers,
keep **headless** enabled (the default).

For frontend development: `cd frontend && npm run dev` (proxies `/api` to :8000).

## Using it

1. **New Task** — e.g. goal *"Fill out the contact form with name John Smith,
   email john@example.com and submit it"*, URL `https://example.com`.
   Optionally tweak the Botasaurus config (headless, markdown output, …).
2. Watch the **run timeline**: every browser action, screenshot, and LLM
   decision streams in live. Cancel anytime.
3. On success, click **Save as recipe**. Typed values become `{{variables}}`.
4. Open the recipe to **replay** it with different variable values (no AI,
   no API key needed), **export** it as YAML/JSON, or edit the step JSON.

### Recipe format

```yaml
version: 1
name: example-lead-form
variables:
  - {name: first_name, default: John}
  - {name: email, default: john@example.com}
botasaurus:          # subset of @browser options, applied at replay
  headless: true
  block_images: true
steps:
  - {type: navigate, url: "https://example.com/quote"}
  - {type: type, selector: "input[name='first_name']", value: "{{first_name}}"}
  - {type: type, selector: "input[name='email']", value: "{{email}}"}
  - {type: select_option, selector: "select[name='project_type']", value: windows}
  - {type: click, selector: "button[type='submit']"}
  - {type: assert, selector: "#thanks", message: confirmation missing}
  - {type: extract_markdown, into: confirmation}
```

Step types: `navigate, click, type, select_option, wait_for, scroll,
extract_markdown, extract_text, screenshot, run_js, assert`. All accept
`optional: true` (continue on failure) and `selector_fallbacks` (tried in
order when the primary selector breaks). See `examples/lead_form_recipe.yaml`.

### CLI / cron scheduling

Recipes replay headlessly from the command line — no LLM, no API key:

```bash
python -m backend.runner examples/lead_form_recipe.yaml --var first_name=Jane
python -m backend.runner --recipe-id 3 --var zip=10001 --out result.json
python -m backend.runner recipe.yaml --no-log   # don't record in the app DB
```

Exit code 0/1 = success/failure; result JSON on stdout. Cron example:

```cron
*/30 * * * * cd /path/to/botasaurus-scraper && python3 -m backend.runner --recipe-id 1 >> cron.log 2>&1
```

Without `--no-log`, cron runs appear in the web UI's run history.

## Architecture

```
backend/
  main.py            FastAPI app (serves API + built frontend)
  agent/             the autonomous loop
    loop.py          runs INSIDE one @browser function (one driver per run)
    snapshot.py      compressed DOM snapshot the LLM sees (~6 KB budget)
    selectors.py     replay-robust CSS selector generation (+fallbacks)
    actions.py       LLM/recipe actions -> Botasaurus Driver calls
    recorder.py      executed actions -> recipe steps, auto-variablization
    markdown.py      deterministic HTML->markdown/text
  llm/               OpenRouter client (tool calling), prompts, mock for tests
  recipes/           recipe schema (pydantic), validation, YAML/JSON, replayer
  runs/              worker-thread manager (one Chrome at a time), DB step logger
  runner.py          CLI replay entry point
frontend/            React + Vite SPA (no state library, REST polling)
vendor/botasaurus/   vendored botasaurus source (pip install -e)
data/                SQLite DB + screenshots (gitignored)
```

- Runs execute on daemon worker threads; a semaphore serializes Chrome
  (extra runs queue). The DB is the single source of truth — the UI polls.
- SQLite tables: `settings`, `runs`, `run_steps`, `llm_calls`, `recipes`,
  `recipe_runs`.

## Security notes

- The OpenRouter key is stored **obfuscated, not encrypted** (`backend/secrets.py`)
  — it protects against casual DB-dump exposure only. The API never returns
  the key, only a preview.
- The agent can execute `run_js` in pages and the recipe editor accepts
  arbitrary steps; the app has **no authentication** — don't expose it to
  untrusted networks.
- Only automate sites you are authorized to interact with.

## Tests

```bash
python -m pytest tests/            # 22 tests
```

Unit tests (snapshot compression, selector generation, recipe schema,
variable substitution) need no browser or network. Browser-marked tests
(deterministic replay, full agent loop with a scripted mock LLM against a
locally served form page) auto-skip when Chrome isn't installed. A live
agent run requires your OpenRouter key.
