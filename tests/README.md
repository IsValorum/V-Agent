# tests/

## Automatic tests (run on every push)

```bat
.venv\Scripts\python scripts\build-ui.py
.venv\Scripts\python -m unittest discover -s tests
for %f in (tests\*.cjs) do node %f
```

- `test_*.py` — the core: agent controls and approvals, sandbox, updates and their signatures, minor
  updates, Hugging Face and LM Studio/Unsloth import, engines, MCP reliability, storage…
- `test_*.cjs` — the interface in Node: translations, palettes, permissions dialog, streaming
  rendering, motion, response metrics.

None of them need a model, a GPU or the internet.

## Smoke tests (manual, `smoke/`)

Scripts that drive a running core with a real model or packaged build. Start a core with a
throw-away data folder first:

```bat
.venv\Scripts\python backend.py --port 19381 --data-dir %TEMP%\v-agent-smoke -- --background
```

| Script | Checks |
|---|---|
| `smoke/ling_tools_smoke.py` | A small local model using file and system tools end to end. Set `V_AGENT_TEST_MODEL` to a small GGUF. |
| `smoke/llama_smoke.py` | Loading, context change and a reply with a tiny GGUF in `.test-models/`. |
| `smoke/tool_battery.py` | A real model choosing file tools: write, edit, copy/paste lines, diagnose and fix, restore a version (5 cases, ~2 min; `SUITE_FULL=1` runs all 13, including search, move, HTML in the browser, interrupted drafts and writes outside the folder). Works with any engine. |
| `smoke/mcp_bundle_smoke.py` | Every MCP server inside a packaged build. |
| `smoke/mcp_integrity_smoke.py` | Read-only MCP checks and isolated edits against a packaged core. |
| `smoke/model_transfer_smoke.py` | Imports, lists and exports a real GGUF with each local engine without loading its weights; pass `--model` and `--engine-state`. |
| `smoke/provider_smoke.py`, `smoke/api_fixture.py` | The remote-API path (OpenAI and Claude formats) against a local fake server. |
| `smoke/ui_walkthrough.py` | Walks through the interface in the bundled headless browser and saves a full screenshot of every step (`smoke/ui_steps.json` opens every window and settings page). `--size 800x600 --scheme light` for the smallest window and the light theme. |
| `smoke/repaint_probe.py` | Counts visible repaints while windows sit idle; a window that repaints on its own (flicker) fails it. Needs Pillow. |
| `smoke/real_models.py` | A real model on llama.cpp, Strata and/or Strata Rust (`--llama`, `--strata`, `--rust`): files written and working, denied approval, leaving a reply half way, two chats at once, malformed requests, engine key and Host checks, unsupported architectures (`--unsupported`). Starts its own isolated core. |
| `smoke/ui_consistency.py` | Uses the interface by clicks and compares the screen with the core after each action and reload; watches for messages written where nobody can see them. Starts its own isolated core; `--model` a small GGUF. |
| `smoke/xss_model_card.py` | Feeds the real Models window a model card with 28 XSS vectors. No model needed. |
| `smoke/language_checks.py` | The code checker on a correct and a broken file per language, and the sandboxed-preview check for web pages. No core needed. |

The interface tools use `browser/chrome-headless-shell-win64` (or `V_AGENT_HEADLESS`) and write to
`build/`. `smoke/isolated_core.py` starts a core from source with a throw-away data folder, reusing
only the engines V-Agent has installed.

## Quality runs (`scripts/quality/`)

| Script | Does |
|---|---|
| `run_all.py` | Runs every level below plus the suites above and writes `docs/test-reports/<version>.md`. |
| `static_analysis.py` | ruff, bandit (against `bandit-reviewed.json`), ESLint on the assembled interface (rules proven on `eslint-seeded.js` first), control-character scan. |
| `verify_release.py` | The published release on GitHub, validated as the previous version would; minor updates applied through the real channel; tampering refused. |
| `screenshots.py` | Screenshots of the real interface with a model loaded and a real agent run, for the version's report. |

[docs/QUALITY.md](../docs/QUALITY.md) describes every level of testing.
