# tests/

## Automatic tests (run on every push)

```bat
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
| `smoke/mcp_bundle_smoke.py` | Every MCP server inside a packaged build. |
| `smoke/mcp_integrity_smoke.py` | Read-only MCP checks and isolated edits against a packaged core. |
| `smoke/provider_smoke.py`, `smoke/api_fixture.py` | The remote-API path (OpenAI and Claude formats) against a local fake server. |
