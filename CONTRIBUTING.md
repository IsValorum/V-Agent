# Contributing to V-Agent

Thank you for helping. V-Agent is licensed under Apache 2.0; by contributing you agree that your
contribution is licensed under the same terms.

## Before you start

- Open an issue to discuss larger changes first.
- Keep changes focused: one fix or feature per pull request.
- Never commit personal data: `data/`, models, API keys, `runtime/`, `seeds/` and build folders are
  ignored on purpose.

## Development

```bat
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python backend.py --port 19381 --data-dir %TEMP%\v-agent-dev -- --background
```

Run `python scripts/build-ui.py` once (and after every change in `agent/ui/`), then open
http://127.0.0.1:19381 to use the interface in a browser while developing. The interface source is in
[`agent/ui/`](agent/ui/) — see its README — and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains
where everything else is.

Set `V_AGENT_NO_AUTO_UPDATE=1` while developing so the core does not apply published minor updates
to your test data.

## Tests

```bat
.venv\Scripts\python scripts\build-ui.py
.venv\Scripts\python -m unittest discover -s tests
for %f in (tests\*.cjs) do node %f
```

Both run on every push and pull request (GitHub Actions, `.github/workflows/tests.yml`). Changes to
the agent loop or tools should also be tried with a real local model — unit tests do not show how a
model actually uses a tool. `tests/smoke/` has scripts for that (see [tests/README.md](tests/README.md)).

## Style

- User-facing text goes through `uiText(...)` with translations for es, en, pt, fr and de in
  `agent/ui/locales.json`.
- Respect the palette tokens (`--accent`, `--panel`, `--text`…) so every theme and style keeps working.
- Explain *why* in comments when the reason is not obvious from the code.
