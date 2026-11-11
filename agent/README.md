# agent/ — the core

Everything the packaged `strata-core.exe` runs: the agent loop and local API, engines, tools, updates
and the interface. The big picture is in [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md); this page is
a map of the files.

## Start here

| File | Role |
|---|---|
| `agent.py` | Agent loop and HTTP API (`/api/chat`, models, sessions, projects…). |
| `desktop_runtime.py` | Routes that do not depend on the engine: engine switching, updates, Hugging Face, LM Studio/Unsloth import, preferences, automatic updates at startup. |
| `runtime_paths.py` | Where program files and user data live; first-run setup. |
| `index.html` | The interface. Modules below are injected into it by `scripts/sync-ui.py`. |

## Interface modules (edit these, then run `python scripts/sync-ui.py`)

| File | Part of the interface |
|---|---|
| `ui-shell.js` | Settings layout, dialogs, window frame, segmented controls, menus. |
| `ui-models.js` | *Models* window: Hugging Face browser, downloads, import/export. |
| `ui-tour.js` | First-run tour, update and minor-update boxes in Settings → General. |
| `ui-palette.js` | Palettes, styles and app icon. |
| `ui-plugins.js`, `ui-tools.js`, `ui-load-settings.js`, `engine_controls.js`, `floating-windows.js` | Extensions, tool windows, load settings, engine panel, window tiling. |
| `ui-panels.css`, `ui-mcp.js`, `ui-motion.js`, `ui-i18n.js`, `locales.json` | Styles, MCP options, motion, translation runtime and texts (served as separate files). |

## Tools the model can use (MCP servers)

`pc_mcp.py` (files, shell, checks), `browser_mcp.py` (autonomous browser), `computer_mcp.py` (screen,
mouse and keyboard), `admin_mcp.py` + `admin_helper.py` (elevated commands, opt-in), `hf_mcp.py`
(Hugging Face). Web search and HTTP tools live in [`web_mcp/`](../web_mcp/).

## Rules of thumb

- Paths the model gives are confined by `access_policy.py`; never open files elsewhere directly.
- Text shown to people goes through `uiText()` and needs entries in `locales.json` for es/en/pt/fr/de.
- Colours come from palette tokens only (`--accent`, `--panel`, `--text`…).
- `model-profiles.json`, `creator-recommendations.json` and `template-provenance.json` are the clean
  starting data copied to a new user's data folder; real per-user data never goes in the repository.
