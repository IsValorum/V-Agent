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

Open http://127.0.0.1:19381 to use the interface in a browser while developing. Interface modules live
in `agent/ui-*.js` and `agent/ui-panels.css`; run `python scripts/sync-ui.py` after editing them.

## Tests

```bat
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
node tests\test_ui_i18n.cjs
```

Changes to the agent loop or tools should also be tried with a real local model: unit tests do not
show how a model actually uses a tool.

## Style

- User-facing text goes through `uiText(...)` with translations for es, en, pt, fr and de in
  `agent/locales.json`.
- Respect the palette tokens (`--accent`, `--panel`, `--text`…) so every theme and style keeps working.
- Explain *why* in comments when the reason is not obvious from the code.
